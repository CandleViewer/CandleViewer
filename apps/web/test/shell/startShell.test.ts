// E17-T04 S5g (C11, C12; WS-E06; D9): the shell starts the web WS client and feeds the shell store from it. The `system` updates
// and the connection state reach the store as they arrive; the client is the one the app reads through `useWsState`; and
// The last test is the real path: the shell, the client, the worker's host and a gateway, which says `hello`, then `auth`,
// before any `sub`.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getActiveClient } from "../../src/lib/ws/client/activeClient.js";
import type { WsState } from "../../src/lib/ws/state/types.js";
import { INITIAL_WS_STATE } from "../../src/lib/ws/state/reducer.js";
import { getShellState, resetShellState, setShellState } from "../../src/shell/bootstrap/store.js";
import { accessToken, REFRESH_PATH } from "../../src/lib/auth/accessToken.js";
import { startShell, toConnectionState } from "../../src/shell/startShell.js";
import { tokenOf, URL } from "../lib/ws/support/connectionHarness";
import { BOOK } from "../lib/ws/support/engineHarness";
import { FakePort } from "../lib/ws/support/fakePort";
import { shim, WAIT } from "../lib/ws/support/portShim";

const WS_URL = "wss://localhost/api/v1/ws";
const jsonResponse = (body: unknown): Response =>
  new Response(JSON.stringify(body), { status: 200 });
const withLink = (link: WsState["link"]): WsState => ({ ...INITIAL_WS_STATE, link });
const started = () => {
  const port = new FakePort();
  const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
  const handle = startShell({ wsUrl: WS_URL, fetchImpl, port });
  return { port, fetchImpl, handle };
};
/** `SharedWorker` or `Worker` (the other one absent): what it made and has not had let go of, and what happened to it, in order. */
function stubWorkers(kind: "SharedWorker" | "Worker") {
  const live = new Set<object>();
  const events: string[] = [];
  const post = (message: { t: string }): void => void events.push(`post ${message.t}`);
  const release = (worker: object): void => void (live.delete(worker), events.push("close"));
  class Fake {
    readonly port = { postMessage: post, onmessage: null as unknown, close: () => release(this) };
    postMessage = post;
    onmessage: unknown = null;
    terminate = (): void => release(this);
    constructor() {
      live.add(this);
    }
  }
  vi.stubGlobal("SharedWorker", kind === "SharedWorker" ? Fake : undefined);
  vi.stubGlobal("Worker", kind === "Worker" ? Fake : undefined);
  return { live, events };
}

// #2712: the page-load refresh finds no session unless a test says otherwise
let refreshMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  resetShellState();
  refreshMock = vi.fn(async () => new Response(null, { status: 401 }));
  vi.stubGlobal("fetch", refreshMock);
});
afterEach(() => {
  accessToken.clear();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "cv");
});

describe("startShell", () => {
  it("starts the WS client and the REST bootstrap concurrently", async () => {
    const { port, fetchImpl, handle } = started();
    expect(port.of("connect")).toEqual([
      expect.objectContaining({ t: "connect", wsUrl: WS_URL, shell: "browser" }),
    ]);
    await handle.ready;
    expect(fetchImpl).toHaveBeenCalled();
    handle.stop();
  });

  it("routes system updates into the shell store's systemByKind, the moment they arrive", () => {
    const { port, handle } = started();
    port.say({ t: "system", update: { kind: "health", health: "healthy" } });
    expect(getShellState().systemByKind.health).toEqual({ kind: "health", health: "healthy" });
    handle.stop();
  });

  it("maps the client's connection onto the shell's, and says it again on each transition", () => {
    setShellState({ connection: { kind: "live" } }); // what an earlier shell left
    const { port, handle } = started();
    expect(getShellState().connection).toEqual({ kind: "connecting" }); // the new client's, at once
    port.say({ t: "state", state: withLink({ kind: "up" }) });
    expect(getShellState().connection).toEqual({ kind: "live" });
    port.say({
      t: "state",
      state: withLink({ kind: "reconnecting", attempt: 2, nextAttemptAtMs: 9_000 }),
    });
    expect(getShellState().connection).toEqual({
      kind: "reconnecting",
      attempt: 2,
      nextAttemptAtMs: 9_000,
    });
    port.say({ t: "state", state: withLink({ kind: "offline", cause: "tailnet_unreachable" }) });
    expect(getShellState().connection).toEqual({ kind: "offline", cause: "tailnet_unreachable" });
    handle.stop();
  });

  it("holds every link the client can be in to one the shell knows", () => {
    expect(toConnectionState(withLink({ kind: "connecting" }))).toEqual({ kind: "connecting" });
    for (const cause of ["offline", "tailnet_unreachable", "backend_unreachable"] as const) {
      expect(toConnectionState(withLink({ kind: "offline", cause }))).toEqual({
        kind: "offline",
        cause,
      });
    }
    // a close that forbids a reconnect (1002, 1009, 4400, 4403): the backend cannot be reached as it is
    expect(
      toConnectionState(withLink({ kind: "offline", cause: "fatal", closeCode: 4403 })),
    ).toEqual({
      kind: "offline",
      cause: "backend_unreachable",
    });
  });

  it("is the client the app reads: set while the shell runs, and gone when it stops", () => {
    expect(getActiveClient()).toBeNull();
    const { handle } = started();
    expect(getActiveClient()).not.toBeNull();
    expect(getActiveClient()?.diagnostics()).toBeUndefined(); // the worker's counters are reachable from the app's client
    handle.stop();
    expect(getActiveClient()).toBeNull();
  });

  it("stopping the shell stops the client: stop is posted once, and nothing it hears after changes the store", () => {
    const { port, handle } = started();
    handle.stop();
    handle.stop();
    expect(port.of("stop")).toHaveLength(1);
    expect(getShellState().connection).toEqual({ kind: "offline", cause: "backend_unreachable" }); // where the stop left it
    port.say({ t: "system", update: { kind: "health", health: "healthy" } });
    expect(getShellState().systemByKind.health).toBeUndefined();
  });

  it("starting a second shell stops the first client before it takes its place", () => {
    const first = started();
    const second = started();
    expect(first.port.of("stop")).toHaveLength(1);
    expect(second.port.of("stop")).toHaveLength(0);
    first.handle.stop(); // a stale handle does not take the live client with it
    expect(getActiveClient()).not.toBeNull();
    second.handle.stop();
    expect(getActiveClient()).toBeNull();
  });

  it.each(["SharedWorker", "Worker"] as const)(
    "lets go of the worker of the shell it replaces, and of the last one when it stops: one live %s",
    (kind) => {
      const { live, events } = stubWorkers(kind);
      const options = { wsUrl: WS_URL, fetchImpl: vi.fn().mockResolvedValue(jsonResponse({})) };
      startShell(options);
      const second = startShell(options);
      expect(live.size).toBe(1);
      second.stop();
      expect(live.size).toBe(0);
      // each shell stops its client, which posts `stop`, and only then lets go of its port
      expect(events.filter((e) => e === "post stop" || e === "close")).toEqual([
        "post stop",
        "close",
        "post stop",
        "close",
      ]);
    },
  );

  it("lets go only of the port it opened: one a caller gives is the caller's", () => {
    const { port, handle } = started();
    const close = vi.fn();
    Object.assign(port, { close });
    handle.stop();
    expect(close).not.toHaveBeenCalled();
  });

  it("reads the backend unreachable and still runs the REST bootstrap when no worker can be started (a CSP SecurityError)", async () => {
    vi.stubGlobal(
      "SharedWorker",
      class {
        constructor() {
          throw new DOMException("blocked by the page's CSP", "SecurityError");
        }
      },
    );
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    const handle = startShell({ wsUrl: WS_URL, fetchImpl }); // no port given: the browser's
    expect(getShellState().connection).toEqual({ kind: "offline", cause: "backend_unreachable" });
    expect(getActiveClient()).toBeNull();
    expect(logged).toHaveBeenCalledOnce();
    await expect(handle.ready).resolves.toBeUndefined();
    expect(fetchImpl).toHaveBeenCalled();
    expect(() => handle.stop()).not.toThrow();
    logged.mockRestore();
  });

  it("answers the worker from the tab's access token: unavailable without a session", async () => {
    const { port, handle } = started();
    port.say({ t: "tokenRequest", req: 3, invalidate: false });
    await vi.waitFor(() => expect(port.of("token")).toHaveLength(1));
    expect(port.of("token")).toEqual([{ t: "token", req: 3, result: { kind: "unavailable" } }]);
    handle.stop();
  });

  it("re-derives the token from the refresh cookie once, before the bootstrap's first call (a reload)", async () => {
    const order: string[] = [];
    const token = ["probe", "7", "x".repeat(20)].join("-");
    refreshMock.mockImplementation(async (path: string) => {
      order.push(path);
      const tokens = { access_token: token, token_type: "Bearer", expires_in: 600 };
      return jsonResponse({ status: "authenticated", tokens, user: {} });
    });
    const sent: (string | null)[] = [];
    const fetchImpl = vi.fn(async (path: RequestInfo | URL, init?: RequestInit) => {
      order.push(String(path));
      sent.push(new Headers(init?.headers).get("Authorization"));
      return jsonResponse({});
    });
    const port = new FakePort();
    const handle = startShell({ wsUrl: WS_URL, fetchImpl, port });
    await handle.ready;
    port.say({ t: "tokenRequest", req: 1, invalidate: false });
    await vi.waitFor(() => expect(port.of("token")).toHaveLength(1));
    expect(order[0]).toBe(REFRESH_PATH);
    expect(order.filter((path) => path === REFRESH_PATH)).toHaveLength(1);
    expect(sent).toEqual([`Bearer ${token}`, `Bearer ${token}`, `Bearer ${token}`]);
    expect(port.of("token")[0]).toMatchObject({ result: { kind: "ok", accessToken: token } });
    handle.stop();
  });

  it("gives the worker the token it is given", async () => {
    const port = new FakePort();
    const tokens = {
      getToken: vi.fn(async () => ({
        kind: "ok" as const,
        accessToken: tokenOf(1),
        expiresAtMs: 9e12,
      })),
      invalidate: vi.fn(),
    };
    const handle = startShell({
      wsUrl: WS_URL,
      fetchImpl: vi.fn().mockResolvedValue(jsonResponse({})),
      tokens,
      port,
    });
    port.say({ t: "tokenRequest", req: 1, invalidate: true });
    await vi.waitFor(() => expect(port.of("token")).toHaveLength(1));
    expect(tokens.invalidate).toHaveBeenCalledTimes(1);
    expect(port.of("token")[0]).toMatchObject({ result: { kind: "ok", accessToken: tokenOf(1) } });
    handle.stop();
  });

  it("is the Electron shell where the preload bridge is, and speaks the language of the page", () => {
    Object.defineProperty(window, "cv", { configurable: true, value: {} });
    vi.stubGlobal("navigator", { language: "de-CH" });
    const { port, handle } = started();
    expect(port.of("connect")[0]).toMatchObject({ shell: "electron", locale: "de-CH" });
    handle.stop();
    vi.stubGlobal("navigator", { language: "" });
    const { port: other, handle: again } = started();
    expect(other.of("connect")[0]).toMatchObject({ locale: "en" }); // `hello` takes a language, and a page may have none
    again.stop();
    vi.stubGlobal("navigator", { language: "x".repeat(40) });
    const { port: long, handle: cut } = started();
    expect(long.of("connect")[0]).toMatchObject({ locale: "x".repeat(16) }); // and takes at most 16 characters of it
    cut.stop();
  });
});

describe("startShell on the real path", () => {
  it("says hello, then auth, before any sub: the shell reads live, and a system update reaches the store", async () => {
    const { gateway, attach } = shim();
    const handle = startShell({
      wsUrl: URL,
      fetchImpl: vi.fn().mockResolvedValue(jsonResponse({})),
      tokens: {
        getToken: async () => ({
          kind: "ok",
          accessToken: tokenOf(1),
          expiresAtMs: Date.now() + 600_000,
        }),
        invalidate: () => undefined,
      },
      port: attach().port,
    });
    await handle.ready;
    await vi.waitFor(() => expect(getShellState().connection).toEqual({ kind: "live" }), WAIT);
    getActiveClient()?.consume({ ch: BOOK, paneId: "p1", priority: "focused" });
    await vi.waitFor(() => expect(gateway.latest.subs().map((s) => s.ch)).toContain(BOOK), WAIT);
    const sent = gateway.latest.received.map((frame) => frame["t"]);
    expect(sent.filter((t) => t === "hello" || t === "auth" || t === "sub")).toEqual([
      "hello",
      "auth",
      "sub",
    ]);
    gateway.latest.delta("system", { kind: "health", health: "degraded" });
    await vi.waitFor(
      () => expect(getShellState().systemByKind.health).toMatchObject({ health: "degraded" }),
      WAIT,
    );
    handle.stop();
  });
});
