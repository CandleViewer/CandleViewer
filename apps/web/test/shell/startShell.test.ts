// E17-T04 S5g (C11, C12; WS-E06; D9): the shell starts the web WS client and feeds the shell store from it. The `system` updates
// and the connection state reach the store as they arrive; the client is the one the app reads through `useWsState`; and
// The last test is the real path: the shell, the client, the worker's host and a gateway, which says `hello`, then `auth`,
// before any `sub`.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startTelemetry } from "../../src/lib/telemetry/aggregator.js";
import { getActiveClient } from "../../src/lib/ws/client/activeClient.js";
import { onWsError } from "../../src/lib/ws/errorHandler.js";
import type { ErrorUiClass } from "../../src/lib/ws/errorMapping.js";
import type { WsState } from "../../src/lib/ws/state/types.js";
import { INITIAL_WS_STATE } from "../../src/lib/ws/state/reducer.js";
import {
  PRIVATE_HANDOVER_MS,
  degradedIssues,
} from "../../src/features/system-states/degradedIssues.js";
import {
  getShellState,
  resetShellState,
  setShellState,
  type Me,
} from "../../src/shell/bootstrap/store.js";
import { accessToken, REFRESH_PATH, REFRESH_WAIT_MS } from "../../src/lib/auth/accessToken.js";
import { startShell, toConnectionState } from "../../src/shell/startShell.js";
import { REVISION_QUIET_MS } from "../../src/features/symbol-search/revisionReread.js";
import {
  getSymbolSearchState,
  resetSymbolSearch,
  setSymbolOpener,
} from "../../src/features/symbol-search/searchSession.js";
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

  it("gives SCR-102 its instrument index with the shell and takes it back on stop() (E08-S09)", () => {
    const { handle } = started();
    expect(getSymbolSearchState().index).not.toBeNull();
    handle.stop();
    expect(getSymbolSearchState().index).toBeNull();
  });

  it("routes system updates into the shell store's systemByKind, the moment they arrive", () => {
    const { port, handle } = started();
    port.say({ t: "system", update: { kind: "health", health: "healthy" } });
    expect(getShellState().systemByKind.health).toEqual({ kind: "health", health: "healthy" });
    handle.stop();
  });

  it("folds system frames into the SCR-153 degraded rows, row 9 handing over to R5 at 10 s (E10-S04)", () => {
    vi.useFakeTimers();
    try {
      const { port, handle } = started();
      const rows = (): string[] => degradedIssues(getShellState().degraded).map((i) => i.id);
      const exchange = (p: object) => ({ t: "system", update: { kind: "exchange_state", ...p } });
      port.say(exchange({ public_ws: "disconnected", private_ws: "connecting" }));
      expect(rows()).toEqual(["exchangeFeedDown", "privateReconnect"]);
      vi.advanceTimersByTime(PRIVATE_HANDOVER_MS - 1);
      port.say(exchange({ private_ws: "resyncing" })); // a re-assertion keeps the episode's clock
      expect(rows()).toEqual(["exchangeFeedDown", "privateReconnect"]);
      vi.advanceTimersByTime(1);
      expect(rows()).toEqual(["exchangeFeedDown"]); // R5's from here, one surface at a time
      port.say(exchange({ private_ws: "resyncing" }));
      expect(rows()).toEqual(["exchangeFeedDown"]);
      port.say(exchange({ public_ws: "connected", private_ws: "connected" }));
      port.say(exchange({ private_ws: "connecting" })); // a new episode shows the row again
      expect(rows()).toEqual(["privateReconnect"]);
      vi.advanceTimersByTime(5_000);
      port.say(exchange({ private_ws: "connected" })); // ended before 10 s: its timer is dropped
      port.say(exchange({ private_ws: "connecting" }));
      vi.advanceTimersByTime(5_000); // the dropped timer would have fired here
      expect(rows()).toEqual(["privateReconnect"]);
      vi.advanceTimersByTime(5_000);
      expect(rows()).toEqual([]);
      handle.stop();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stop() drops the degraded facts and row 9's hand-over timer (E10-S04, #4723 review)", () => {
    vi.useFakeTimers();
    try {
      const { port, handle } = started();
      port.say({ t: "system", update: { kind: "exchange_state", private_ws: "connecting" } });
      expect(getShellState().degraded.asserted).toEqual({ privateReconnect: 1 });
      handle.stop();
      expect(getShellState().degraded.asserted).toEqual({});
      const before = getShellState();
      vi.advanceTimersByTime(PRIVATE_HANDOVER_MS);
      expect(getShellState()).toBe(before); // the dropped timer wrote nothing
    } finally {
      vi.useRealTimers();
    }
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

  it("hands the store the last welcome's build label: undefined until the first, then each one's (SCR-157)", () => {
    setShellState({ serverProtocol: "cv.v1", serverVersion: "0.0.9" }); // what an earlier shell left
    const { port, handle } = started();
    const label = () => [getShellState().serverProtocol, getShellState().serverVersion];
    expect(label()).toEqual([undefined, undefined]); // never welcomed
    const build = (protocol: string | null, version: string | null): WsState => ({
      ...INITIAL_WS_STATE,
      server: { protocol, version },
    });
    port.say({ t: "state", state: build("cv.v1", "1.4.3") });
    expect(label()).toEqual(["cv.v1", "1.4.3"]);
    port.say({ t: "state", state: build("cv.v1", "v".repeat(33)) }); // refused at the port
    expect(label()).toEqual(["cv.v1", "1.4.3"]);
    port.say({ t: "state", state: build(null, "1.4.3") }); // welcomed, protocol label refused
    expect(label()).toEqual([null, "1.4.3"]); // null, never undefined: 10b fails closed on it
    port.say({ t: "state", state: build("cv.v1", null) }); // a server_version the worker refused
    expect(label()).toEqual(["cv.v1", undefined]);
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

  it("a stale stop() leaves the live shell's degraded facts alone (E10-S04)", () => {
    const first = started();
    first.port.say({ t: "system", update: { kind: "exchange_state", public_ws: "disconnected" } });
    const second = started(); // stops the first: its facts go with it
    expect(getShellState().degraded.asserted).toEqual({});
    second.port.say({ t: "system", update: { kind: "notice", reason: "maintenance.enabled" } });
    first.handle.stop();
    expect(getShellState().degraded.asserted).toEqual({ maintenance: 1 });
    second.handle.stop();
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

  it("a reload into an idle-locked session: the refresh's lock marks the bootstrap locked and skips /me (#1640)", async () => {
    refreshMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ status: 401, code: "session_idle_locked" }), { status: 401 }),
    );
    const fetchImpl = vi.fn(async () => jsonResponse({}));
    const handle = startShell({ wsUrl: WS_URL, fetchImpl, port: new FakePort() });
    await handle.ready;
    expect(getShellState().bootstrap).toEqual({ kind: "locked" });
    expect(fetchImpl).not.toHaveBeenCalled(); // a cookie-only /me would answer unauthenticated
    handle.stop();
  });

  it("a refresh that finds no session still runs the bootstrap (the route guard's turn)", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}));
    const handle = startShell({ wsUrl: WS_URL, fetchImpl, port: new FakePort() });
    await handle.ready;
    expect(fetchImpl).toHaveBeenCalled();
    expect(getShellState().bootstrap.kind).not.toBe("locked");
    handle.stop();
  });

  it("holds the first paint for REFRESH_WAIT_MS at most when another tab keeps the refresh lock", async () => {
    vi.useFakeTimers();
    const grants: (() => void)[] = [];
    const request = (_name: string, task: () => Promise<unknown>) =>
      new Promise((resolve) => grants.push(() => resolve(task())));
    vi.stubGlobal("navigator", { language: "en", locks: { request } });
    try {
      const { fetchImpl, handle } = started();
      let painted = false;
      void handle.ready.then(() => (painted = true));
      await vi.advanceTimersByTimeAsync(REFRESH_WAIT_MS - 1);
      expect(painted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await handle.ready;
      expect(fetchImpl).toHaveBeenCalled(); // the bootstrap ran, without a token
      handle.stop();
    } finally {
      grants.forEach((grant) => grant()); // the other tab lets go: the refresh ends with this test
      await vi.advanceTimersByTimeAsync(0);
      vi.useRealTimers();
    }
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

describe("an instrument_revision snapshot and SCR-102's instrument list (E08-S09, #4703)", () => {
  const LIST = "/api/v1/instruments?status=Trading&limit=500";
  // Cast: only the presence of `/me`'s answer is read; the index starts once it has one and an opener is bound.
  const ME = { role: "owner", permissions: [], user: { username: "robin" } } as unknown as Me;
  const instrument = (symbol: string) => ({
    symbol,
    category: "linear",
    status: "Trading",
    tick_size: "0.1",
    qty_step: "1",
  });
  const listed = (): Response =>
    jsonResponse({
      items: ["BTCUSDT", "ETHUSDT"].map(instrument),
      meta: { next_cursor: null, has_more: false, count: 2, cache_age_s: 0, stale_since: null },
    });
  /** The list GETs so far: the index's reads. */
  const reads = (): number => refreshMock.mock.calls.filter(([url]) => url === LIST).length;
  /** What the worker posts a tab when a consumer's snapshot says its symbol's instrument was revised (23 7.4). */
  const revised = (id: string) => ({
    t: "data",
    id,
    status: "live",
    effective: {},
    source: "live",
    frames: [
      {
        kind: "snap",
        seq: 1,
        ts: 1_000,
        sp: undefined,
        decodeMs: 0.5,
        size: 20,
        meta: { reason: "instrument_revision" },
        bodies: [{ e: "j", p: {} }],
      },
    ],
  });

  /** The shell with the index running (it has read the list once) and three consumers: c1 BTCUSDT, c2 ETHUSDT, c3 DOGEUSDT. */
  async function running() {
    vi.useFakeTimers();
    refreshMock.mockImplementation(async (url: RequestInfo | URL) =>
      String(url) === LIST ? listed() : new Response(null, { status: 401 }),
    );
    const shell = started();
    setShellState({ me: ME });
    setSymbolOpener({ target: null, open: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads()).toBe(1);
    const client = getActiveClient();
    client?.consume({ ch: "book.BTCUSDT.50", paneId: "p1", priority: "focused" });
    client?.consume({ ch: "bars.ETHUSDT.time.1", paneId: "p1", priority: "other" });
    client?.consume({ ch: "book.DOGEUSDT.50", paneId: "p2", priority: "other" });
    return shell;
  }
  afterEach(() => {
    resetSymbolSearch();
    vi.useRealTimers();
  });

  it("a burst re-reads the list once, a quiet after its last frame", async () => {
    const { port, handle } = await running();
    port.say(revised("c1"));
    await vi.advanceTimersByTimeAsync(400);
    port.say(revised("c2"));
    port.say(revised("c1"));
    await vi.advanceTimersByTimeAsync(REVISION_QUIET_MS - 1);
    expect(reads()).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(reads()).toBe(2);
    await vi.advanceTimersByTimeAsync(10 * REVISION_QUIET_MS);
    expect(reads()).toBe(2);
    handle.stop();
  });

  it("a frame after that quiet re-reads the list again", async () => {
    const { port, handle } = await running();
    port.say(revised("c1"));
    await vi.advanceTimersByTimeAsync(REVISION_QUIET_MS);
    expect(reads()).toBe(2);
    port.say(revised("c2"));
    await vi.advanceTimersByTimeAsync(REVISION_QUIET_MS);
    expect(reads()).toBe(3);
    handle.stop();
  });

  it("reads nothing for a symbol the list does not hold", async () => {
    const { port, handle } = await running();
    port.say(revised("c3")); // book.DOGEUSDT.50
    await vi.advanceTimersByTimeAsync(10 * REVISION_QUIET_MS);
    expect(reads()).toBe(1);
    handle.stop();
  });
});

/** The shell over the worker's host and the fake gateway, through a real message port, once it reads live. */
async function liveShell() {
  const { gateway, attach, posted } = shim();
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
  return { gateway, posted, handle };
}

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

  it("carries welcome's protocol and server_version from the worker to the store (SCR-157)", async () => {
    const { handle } = await liveShell();
    expect([getShellState().serverProtocol, getShellState().serverVersion]).toEqual([
      "cv.v1",
      "test", // the fake gateway's server_version
    ]);
    handle.stop();
  });

  it("a fatal, a transient and a client-bug err reach the listeners of WsErrorHost, with the code and the message only (23 10.3)", async () => {
    const { gateway, posted, handle } = await liveShell();
    const heard: [string, ErrorUiClass][] = [];
    const off = onWsError((code, treatment) => heard.push([code, treatment.uiClass]));
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const extra = { retryable: false, field: "min_stack", request_id: "urn:cv:req:1" };
    for (const code of ["forbidden", "degraded_data", "invalid_options"])
      gateway.latest.send({
        t: "err",
        id: "c-9999",
        ch: BOOK,
        p: { code, message: "no", ...extra },
      });
    await vi.waitFor(() => expect(heard).toHaveLength(3), WAIT);
    off();
    expect(heard).toEqual([
      ["forbidden", "fatal"], // the modal
      ["degraded_data", "transient"], // the staleness badge
      ["invalid_options", "clientBug"], // the console and the toast, in the page
    ]);
    expect(logged).toHaveBeenCalledWith("[ws] client-bug error", "invalid_options", "no");
    const relayed = posted.filter((p) => p.message.t === "err").map((p) => p.message);
    expect(relayed).toEqual([
      { t: "err", code: "forbidden", message: "no" },
      { t: "err", code: "degraded_data", message: "no" },
      { t: "err", code: "invalid_options", message: "no" },
    ]); // no id, topic, field or request id leaves the worker
    logged.mockRestore();
    handle.stop();
  });

  it("feeds fe_ws_decode_ms to the app's aggregator and the latency indicator to the store (D8, budget #3)", async () => {
    const telemetry = startTelemetry(async () => undefined);
    const { handle } = await liveShell();
    expect(getShellState().latency.state).toBe("unavailable");
    const book = getActiveClient()?.consume({ ch: BOOK, paneId: "p1", priority: "focused" });
    await vi.waitFor(() => expect(getShellState().latency.valueMs).not.toBeNull(), WAIT); // the snapshot was rendered
    expect(getShellState().latency).toMatchObject({
      unit: "ms",
      label: expect.stringMatching(/^WS latency: /),
    });
    const decoded = telemetry.aggregator.drain()?.fe_ws_decode_ms.counts ?? [];
    expect(decoded.reduce((a, b) => a + b, 0)).toBeGreaterThan(0);
    telemetry.stop();
    book?.release();
    handle.stop();
  });
});
