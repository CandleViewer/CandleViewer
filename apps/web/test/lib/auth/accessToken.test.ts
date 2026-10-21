// #2712 (ADR-0020 decisions 1, 3, 5; 23 §4.3): the tab's in-memory access token, its refresh, its bearer
// rule and the WS client's `TokenSource`. Fake timers and a stubbed `fetch`: no network, no wall clock.
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { inspect } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  ORPHAN_WAIT_MS,
  REFRESH_LOCK,
  REFRESH_PATH,
  REFRESH_SENT_KEY,
  REFRESH_WAIT_MS,
  SIBLING_WAIT_MS,
  TOKEN_CHANNEL,
  accessToken,
  createAccessTokenHolder,
  type AccessTokenHolder,
  type TokenBundle,
} from "../../../src/lib/auth/accessToken";
import { apiFetch } from "../../../src/lib/http/csrfFetch";

/** Probe values made at run time, so no literal in this file looks like a credential. */
const tokenOf = (n: number): string => ["probe", String(n), "x".repeat(20)].join("-");
const bundle = (n: number, expiresIn = 600): TokenBundle => ({
  access_token: tokenOf(n),
  token_type: "Bearer",
  expires_in: expiresIn,
});
const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const refreshed = (n: number): Response =>
  json(200, { status: "authenticated", tokens: bundle(n), user: {} });
const refused = (code: string): Response => json(401, { status: 401, code });
const noContent = (): Response => new Response(null, { status: 204 });
const bearer = (n: number): string => `Bearer ${tokenOf(n)}`;
/** The `Authorization` a recorded `fetch`/transport call was given (a mock's argument is untyped). */
const authOf = (init: unknown): string | null =>
  new Headers((init as RequestInit | undefined)?.headers).get("Authorization");
/** Lets every promise chain that is ready run (a real macrotask turn; no fake time passes). */
const flush = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};
/** A Web Locks stand-in shared by the tabs of a test: one holder of a name at a time (its task is the last argument). */
function serialLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  return {
    request: vi.fn((_name: string, ...args: unknown[]) => {
      const run = tail.then(args.at(-1) as () => Promise<unknown>);
      tail = run.catch(() => undefined);
      return run;
    }),
  };
}
/** A lock another tab holds and never lets go of: a request waits until its signal, if it has one, aborts. */
const heldElsewhere = () => ({
  request: (_name: string, ...args: unknown[]) =>
    new Promise<never>((_resolve, reject) => {
      const { signal } = (args.length > 1 ? args[0] : {}) as LockOptions;
      signal?.addEventListener("abort", () => reject(signal.reason));
      if (signal?.aborted === true) reject(signal.reason);
    }),
});
/** Web Locks where the first holder's tab closes: `close()` lets its lock go, its request still on the wire. */
function closingTabLocks() {
  const queued: (() => void)[] = [];
  let held = false;
  return {
    close: () => queued.shift()?.(),
    request: (_name: string, task: () => Promise<unknown>) => {
      if (held) return new Promise((resolve) => queued.push(() => resolve(task())));
      held = true;
      return task();
    },
  };
}
/** A same-origin BroadcastChannel stand-in: a post reaches every other open channel of its name, as a task (a 1 ms timer under fake time). */
function siblingChannels() {
  const open: Channel[] = [];
  class Channel {
    static readonly opened: string[] = [];
    onmessage: ((event: MessageEvent) => void) | null = null;
    constructor(readonly name: string) {
      open.push(this);
      Channel.opened.push(name);
    }
    postMessage(data: unknown): void {
      for (const other of open.filter((c) => c !== this && c.name === this.name)) {
        setTimeout(() => other.onmessage?.(new MessageEvent("message", { data })), 0);
      }
    }
  }
  return Channel;
}
/**
 * The server's side of one session, as the API runs it: a refresh answers in 50 ms, rotating the CSRF
 * cookie and minting the next token, and the token before stops working. A REST call with another token
 * is refused: a write by the CSRF check first (`403 csrf_token_invalid`), a read with a 401.
 */
function rotatingSession() {
  const state = { live: 0 };
  vi.spyOn(document, "cookie", "get").mockImplementation(() => `__Host-cv_csrf=csrf-${state.live}`);
  fetchMock.mockImplementation(() => later(50, () => refreshed((state.live += 1))));
  const api = vi.fn(async (init: RequestInit) => {
    if (authOf(init) === bearer(state.live)) return noContent();
    return init.method === "POST"
      ? json(403, { code: "csrf_token_invalid" })
      : refused("unauthenticated");
  });
  return { state, api };
}
const later = <T>(ms: number, value: () => T | PromiseLike<T>): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value()), ms));
/** A `fetch` that never answers: as a browser's, it is rejected once its signal, if it has one, aborts. */
const stalled = (_url: string, init?: RequestInit): Promise<Response> =>
  new Promise((_resolve, reject) => {
    const signal = init?.signal;
    signal?.addEventListener("abort", () => reject(signal.reason));
  });

let fetchMock: ReturnType<typeof vi.fn>;
let toSignIn: Mock<() => void>;
let holder: AccessTokenHolder;
type Transport = (init: RequestInit) => Promise<Response>;
let transport: Mock<Transport>;

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  toSignIn = vi.fn();
  holder = createAccessTokenHolder(toSignIn);
  transport = vi.fn(async () => noContent());
});
afterEach(() => {
  holder.clear();
  accessToken.clear();
  localStorage.removeItem(REFRESH_SENT_KEY); // the mark of a refresh no test answered
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the access token lives in memory only", () => {
  it("is in no storage, cookie, URL or log after a sign-in and a refresh", async () => {
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m),
    );
    fetchMock.mockResolvedValueOnce(refreshed(1));
    await apiFetch("/api/v1/auth/login", { method: "POST", body: "{}" }); // the sign-in hands its bundle over
    fetchMock.mockResolvedValueOnce(refreshed(2));
    await vi.advanceTimersByTimeAsync(540_000);
    await expect(accessToken.getToken()).resolves.toMatchObject({ accessToken: tokenOf(2) });
    const dump = (s: Storage): string =>
      Array.from({ length: s.length }, (_, i) => `${s.key(i)}=${s.getItem(s.key(i) ?? "")}`).join();
    const places = [
      dump(localStorage),
      dump(sessionStorage),
      document.cookie,
      window.location.href,
      inspect(fetchMock.mock.calls.map((call) => String(call[0]))),
      inspect(logs.map((spy) => spy.mock.calls)),
    ].join("\n");
    expect(places).not.toContain(tokenOf(1));
    expect(places).not.toContain(tokenOf(2));
  });

  it("never holds a bundle that breaks the contract", async () => {
    // what a server that breaks `TokenBundle` could send
    const bad = [
      { ...bundle(1), token_type: "MAC" },
      { ...bundle(1), expires_in: 0 },
      { ...bundle(1), access_token: "not a b64token" },
    ] as unknown as TokenBundle[];
    for (const value of bad) holder.set(value);
    await holder.send("/api/v1/x", {}, transport);
    expect(authOf(transport.mock.calls[0]?.[0])).toBeNull();
  });
});

describe("the bearer goes to same-origin /api/v1 calls only", () => {
  const origin = window.location.origin;
  it.each([
    ["a relative /api/v1 path", true, "/api/v1/me"],
    ["an absolute same-origin URL", true, `${origin}/api/v1/me`],
    ["a same-origin Request", true, new Request(`${origin}/api/v1/me`)],
    ["a same-origin path outside /api/v1", false, "/assets/app.js"],
    ["another origin", false, "https://evil.example/api/v1/me"],
    ["a protocol-relative URL", false, "//evil.example/api/v1/me"],
    ["a URL object of another origin", false, new URL("https://evil.example/api/v1/me")],
    ["a Request to another origin", false, new Request("https://evil.example/api/v1/me")],
    ["a URL that does not parse", false, "http://[bad/api/v1/me"],
    ["userinfo before another host", false, "https://x@evil.example/api/v1/me"],
    ["a backslash path to another host", false, "/\\evil.example/api/v1/me"],
    ["a path that only begins like /api/v1", false, "/api/v1evil"],
    ["a dot segment out of /api/v1", false, "/api/v1/../../assets/x"],
    ["an encoded dot segment out of /api/v1", false, "/api/v1/%2e%2e/x"],
  ])("apiFetch to %s: bearer sent %s", async (_name, carries, input) => {
    accessToken.set(bundle(1));
    fetchMock.mockResolvedValueOnce(noContent());
    await apiFetch(input);
    const [sent, init] = fetchMock.mock.calls[0] ?? [];
    const own = sent instanceof Request ? sent.headers.get("Authorization") : null;
    expect(authOf(init) ?? own).toBe(carries ? bearer(1) : null);
    // a redirect of a bearer call to another origin is a network error, whatever the browser does
    expect((init as RequestInit | undefined)?.mode).toBe(carries ? "same-origin" : undefined);
  });

  it("refuses a Request that carries a body: a call may be repeated, and a body is read once", async () => {
    const input = new Request(`${origin}/api/v1/x`, { method: "POST", body: "{}" });
    await expect(apiFetch(input)).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("refresh ahead of expiry, one refresh at a time", () => {
  it("posts /auth/refresh at expires_at - 60 s with the CSRF header, and re-arms on the new bundle", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue("__Host-cv_csrf=csrf.mac");
    fetchMock.mockImplementation(async () => refreshed(2));
    holder.set(bundle(1));
    await vi.advanceTimersByTimeAsync(539_999);
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]; // the refresh's own call
    expect(url).toBe(REFRESH_PATH);
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf.mac");
    expect(authOf(init)).toBeNull(); // the cookie identifies the session, never the bearer
    await expect(holder.getToken()).resolves.toMatchObject({ accessToken: tokenOf(2) });
    await vi.advanceTimersByTimeAsync(540_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shares one refresh between concurrent token requests (no Web Locks here: in-tab only)", async () => {
    expect(navigator.locks).toBeUndefined();
    fetchMock.mockImplementation(async () => refreshed(1));
    const answers = await Promise.all([holder.getToken(), holder.getToken(), holder.getToken()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const ok = { kind: "ok", accessToken: tokenOf(1), expiresAtMs: Date.now() + 600_000 };
    expect(answers).toEqual([ok, ok, ok]);
  });

  it("makes a second tab wait for the first under the cv.auth.refresh lock, then take its bundle", async () => {
    const locks = serialLocks();
    vi.stubGlobal("navigator", { locks });
    vi.stubGlobal("BroadcastChannel", siblingChannels());
    rotatingSession();
    const first = createAccessTokenHolder(vi.fn()).getToken();
    const second = createAccessTokenHolder(vi.fn()).getToken();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1); // the single-use cookie is never presented twice at once
    await vi.advanceTimersByTimeAsync(60); // the answer at 50 ms, the first tab's post a moment later
    await expect(first).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(1) });
    await expect(second).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(1) });
    expect(fetchMock).toHaveBeenCalledTimes(1); // the second tab rotated nothing, so revoked nothing
    expect(locks.request).toHaveBeenCalledWith(REFRESH_LOCK, expect.any(Function));
  });

  it("presents nothing for a token that is still fresh", async () => {
    holder.set(bundle(1));
    await expect(holder.refresh()).resolves.toBe("ok");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["answers 503", async () => json(503, {})],
    ["answers 200 without a bundle", async () => json(200, { status: "authenticated" })],
    ["cannot be reached", () => Promise.reject(new TypeError("offline"))],
  ])("a refresh that %s answers unavailable and clears nothing", async (_name, answer) => {
    holder.set(bundle(1));
    holder.invalidate();
    fetchMock.mockImplementationOnce(answer);
    await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
    await holder.send("/api/v1/x", {}, transport);
    expect(authOf(transport.mock.calls[0]?.[0])).toBe(bearer(1));
    expect(toSignIn).not.toHaveBeenCalled();
  });

  it("never aborts a sent refresh: the caller stops waiting at 10 s, nothing is sent again, and the late bundle is held", async () => {
    holder.set(bundle(1));
    holder.invalidate();
    let answer: (res: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)));
    const first = holder.getToken();
    await vi.advanceTimersByTimeAsync(REFRESH_WAIT_MS);
    await expect(first).resolves.toEqual({ kind: "unavailable" });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit; // the refresh's own call
    expect(init.signal).toBeUndefined(); // this tab waits for the answer: it never presents the cookie again
    expect(init.keepalive).toBe(true); // a reload or a closed tab still stores the rotated cookie
    const second = holder.getToken(); // the WS client asks again
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    answer(refreshed(2));
    await expect(second).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(2) });
  });

  it("does not hold a refresh that answers after the session ended (a logout racing it)", async () => {
    holder.set(bundle(1));
    holder.invalidate();
    let answer: (res: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)));
    const pending = holder.refresh();
    await flush();
    holder.endSession();
    answer(refreshed(2));
    await expect(pending).resolves.toBe("lost");
    await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
    await vi.advanceTimersByTimeAsync(600_000);
    expect(fetchMock).toHaveBeenCalledTimes(1); // and no timer was armed for it
  });

  it("re-issues the CSRF cookie through GET /auth/session (cookie only) after a 403, then presents once more", async () => {
    let csrf = "stale.mac";
    vi.spyOn(document, "cookie", "get").mockImplementation(() => `__Host-cv_csrf=${csrf}`);
    fetchMock
      .mockResolvedValueOnce(json(403, { code: "csrf_token_invalid" }))
      .mockImplementationOnce(async () => {
        csrf = "reissued.mac"; // SR-041: refused before the cookie was spent
        return json(200, {});
      })
      .mockResolvedValueOnce(refreshed(1));
    await expect(holder.getToken()).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(1) });
    const calls = fetchMock.mock.calls as [string, RequestInit][];
    expect(calls.map(([url]) => url)).toEqual([REFRESH_PATH, "/api/v1/auth/session", REFRESH_PATH]);
    expect(authOf(calls[1]?.[1])).toBeNull(); // the cv_refresh cookie identifies the session
    expect(new Headers(calls[2]?.[1].headers).get("X-CSRF-Token")).toBe("reissued.mac");
  });

  it.each([
    ["is refused again", true, 2],
    ["is not re-issued", false, 1],
  ])("a refresh whose CSRF cookie %s answers failed", async (_name, reissued, posts) => {
    let csrf = "stale.mac";
    vi.spyOn(document, "cookie", "get").mockImplementation(() => `__Host-cv_csrf=${csrf}`);
    fetchMock.mockImplementation(async (url: string) => {
      if (url === REFRESH_PATH) return json(403, { code: "csrf_token_invalid" });
      if (reissued) csrf = "reissued.mac";
      return json(200, {});
    });
    await expect(holder.refresh()).resolves.toBe("failed");
    expect(fetchMock.mock.calls.filter(([url]) => url === REFRESH_PATH)).toHaveLength(posts);
    expect(toSignIn).not.toHaveBeenCalled();
  });

  it("a CSRF re-issue that never answers is given up by 10 s: the lock goes to the next tab", async () => {
    const locks = serialLocks();
    vi.stubGlobal("navigator", { locks });
    fetchMock
      .mockResolvedValueOnce(json(403, { code: "csrf_token_invalid" }))
      .mockImplementation(stalled); // the GET /auth/session that re-issues the CSRF cookie
    const pending = holder.refresh();
    await vi.advanceTimersByTimeAsync(REFRESH_WAIT_MS);
    await expect(pending).resolves.toBe("failed");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      REFRESH_PATH,
      "/api/v1/auth/session",
    ]);
    const next = vi.fn(async () => undefined); // another tab's refresh
    void locks.request(REFRESH_LOCK, next);
    await flush();
    expect(next).toHaveBeenCalledTimes(1);
  });

  it("stops waiting for a lock another tab never lets go of: 10 s for a token, or the caller's abort", async () => {
    vi.stubGlobal("navigator", { locks: heldElsewhere() });
    holder.set(bundle(1));
    holder.invalidate();
    const token = holder.getToken();
    await vi.advanceTimersByTimeAsync(REFRESH_WAIT_MS);
    await expect(token).resolves.toEqual({ kind: "unavailable" });
    transport.mockResolvedValue(refused("unauthenticated"));
    const abort = new AbortController();
    const call = holder.send("/api/v1/x", { signal: abort.signal }, transport);
    await flush();
    abort.abort(); // e.g. the bootstrap's own timeout
    await expect(call).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled(); // nothing was presented without the lock
  });

  it("a call that mints a session stops waiting for that lock too, and is never sent: 10 s, or the caller's abort", async () => {
    vi.stubGlobal("navigator", { locks: heldElsewhere() });
    const login = holder.send("/api/v1/auth/login", { method: "POST" }, transport);
    const timedOut = expect(login).rejects.toMatchObject({ name: "TimeoutError" });
    await vi.advanceTimersByTimeAsync(REFRESH_WAIT_MS);
    await timedOut;
    const abort = new AbortController();
    const init = { method: "POST", signal: abort.signal };
    const stepUp = holder.send("/api/v1/auth/step-up", init, transport);
    abort.abort();
    await expect(stepUp).rejects.toMatchObject({ name: "AbortError" });
    expect(transport).not.toHaveBeenCalled();
  });
});

describe("the WS TokenSource", () => {
  it("never hands out a rejected token, nor one inside its last minute: it refreshes", async () => {
    holder.set(bundle(1));
    await expect(holder.getToken()).resolves.toMatchObject({ accessToken: tokenOf(1) });
    holder.invalidate(); // the WS client was refused with it (4401)
    fetchMock.mockResolvedValueOnce(refreshed(2));
    await expect(holder.getToken()).resolves.toMatchObject({ accessToken: tokenOf(2) });
    vi.setSystemTime(Date.now() + 540_001); // past T - 60 s, its timer not run yet
    fetchMock.mockResolvedValueOnce(refreshed(3));
    await expect(holder.getToken()).resolves.toMatchObject({ accessToken: tokenOf(3) });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("hands out no token inside its last 65 s: the WS client re-auths by the server's earlier expiry", async () => {
    holder.set(bundle(1));
    vi.setSystemTime(Date.now() + 536_000); // T - 64 s: the holder's own timer is not due yet
    fetchMock.mockResolvedValueOnce(refreshed(2));
    await expect(holder.getToken()).resolves.toMatchObject({ accessToken: tokenOf(2) });
  });

  it("answers locked on 401 session_idle_locked, clears nothing, and presents the cookie again only after 5 s or the unlock", async () => {
    holder.set(bundle(1));
    holder.invalidate();
    fetchMock.mockImplementation(async () => refused("session_idle_locked"));
    await expect(holder.getToken()).resolves.toEqual({ kind: "locked" });
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(holder.getToken()).resolves.toEqual({ kind: "locked" }); // the WS client asks again
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(4_000);
    await expect(holder.getToken()).resolves.toEqual({ kind: "locked" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await holder.send("/api/v1/x", {}, transport);
    expect(authOf(transport.mock.calls[0]?.[0])).toBe(bearer(1));
    expect(toSignIn).not.toHaveBeenCalled();
    transport.mockResolvedValueOnce(json(200, {})); // SCR-005 lifts the lock
    await holder.send("/api/v1/auth/unlock", { method: "POST" }, transport);
    fetchMock.mockImplementation(async () => refreshed(2)); // and the same cookie refreshes
    await expect(holder.getToken()).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(2) });
  });
});

describe("a lost session goes back to sign-in", () => {
  it.each(["refresh_token_invalid", "unauthenticated", "no code"])(
    "a refresh refused with 401 (%s) clears the token, answers unavailable and routes to sign-in",
    async (code) => {
      holder.set(bundle(1));
      holder.invalidate();
      fetchMock.mockResolvedValueOnce(
        code === "no code" ? new Response("", { status: 401 }) : refused(code),
      );
      await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
      expect(toSignIn).toHaveBeenCalledTimes(1);
      await holder.send("/api/v1/x", {}, transport);
      expect(authOf(transport.mock.calls[0]?.[0])).toBeNull();
      await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
      expect(fetchMock).toHaveBeenCalledTimes(1); // no session: nothing is asked again
    },
  );

  it("logout does the same, and its refresh timer is gone", async () => {
    holder.set(bundle(1));
    holder.endSession();
    expect(toSignIn).toHaveBeenCalledTimes(1);
    await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
    await vi.advanceTimersByTimeAsync(600_000);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a page load that finds no session leaves the route guard to send the user to sign-in", async () => {
    fetchMock.mockResolvedValueOnce(refused("refresh_token_invalid"));
    await expect(holder.refresh()).resolves.toBe("lost");
    expect(toSignIn).not.toHaveBeenCalled();
    await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
    transport.mockResolvedValue(refused("unauthenticated"));
    expect((await holder.send("/api/v1/me", {}, transport)).status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1); // no session: a refused call asks nothing again
  });

  it("an unlock's 2xx after a refresh that called a locked session lost lets the next ask refresh", async () => {
    fetchMock.mockResolvedValueOnce(refused("refresh_token_invalid")); // the server's idle-lock gap
    await expect(holder.refresh()).resolves.toBe("lost");
    transport.mockResolvedValueOnce(json(200, {})); // SCR-005 unlocks with the cookie
    await holder.send("/api/v1/auth/unlock", { method: "POST" }, transport);
    fetchMock.mockResolvedValueOnce(refreshed(2)); // and the same cookie refreshes
    await expect(holder.getToken()).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(2) });
  });

  it("the tab's holder goes to SCR-001 with where the user was, as the route guard does", async () => {
    const assign = vi.fn();
    const { origin } = window.location;
    vi.stubGlobal("location", { origin, pathname: "/terminal/abc", search: "?tf=15", assign });
    fetchMock.mockImplementation(async () => refused("refresh_token_invalid"));
    await accessToken.refresh(); // a page load that finds no session: the route guard's turn
    expect(assign).not.toHaveBeenCalled();
    accessToken.set(bundle(1));
    accessToken.invalidate();
    await accessToken.getToken(); // a session the tab held is lost
    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fterminal%2Fabc%3Ftf%3D15");
  });
});

describe("a 401 on an API call", () => {
  it("refreshes once and repeats the call once with the new token", async () => {
    accessToken.set(bundle(1));
    fetchMock
      .mockResolvedValueOnce(refused("unauthenticated"))
      .mockResolvedValueOnce(refreshed(2))
      .mockResolvedValueOnce(noContent());
    const res = await apiFetch("/api/v1/me/preferences", { method: "PUT", body: "{}" });
    expect(res.status).toBe(204);
    const calls = fetchMock.mock.calls;
    expect(calls.map((call) => call[0])).toEqual([
      "/api/v1/me/preferences",
      REFRESH_PATH,
      "/api/v1/me/preferences",
    ]);
    expect([authOf(calls[0]?.[1]), authOf(calls[2]?.[1])]).toEqual([bearer(1), bearer(2)]);
  });

  it("ends the session when the refresh is refused too, and returns the 401 unrepeated", async () => {
    holder.set(bundle(1));
    transport.mockResolvedValue(refused("unauthenticated"));
    fetchMock.mockResolvedValueOnce(refused("refresh_token_invalid"));
    expect((await holder.send("/api/v1/x", { method: "POST" }, transport)).status).toBe(401);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(toSignIn).toHaveBeenCalledTimes(1);
  });

  it("repeats a call refused with a token already renewed by another, without a second refresh", async () => {
    holder.set(bundle(1));
    fetchMock.mockResolvedValueOnce(refreshed(2));
    const late: ((res: Response) => void)[] = [];
    transport.mockImplementation((init: RequestInit) =>
      authOf(init) === bearer(2)
        ? Promise.resolve(noContent())
        : new Promise<Response>((resolve) => late.push(resolve)),
    );
    const first = holder.send("/api/v1/a", {}, transport);
    const second = holder.send("/api/v1/b", {}, transport);
    await flush();
    late[0]?.(refused("unauthenticated"));
    await expect(first).resolves.toMatchObject({ status: 204 });
    late[1]?.(refused("unauthenticated"));
    await expect(second).resolves.toMatchObject({ status: 204 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["/api/v1/auth/unlock", "/api/v1/auth/password", "/api/v1/auth/mfa/methods/m1"])(
    "is never repeated on %s, where a 401 judges a password or a code",
    async (path) => {
      holder.set(bundle(1));
      transport.mockResolvedValue(refused("unlock_invalid"));
      await holder.send(path, { method: "POST" }, transport);
      expect(transport).toHaveBeenCalledTimes(1);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it.each(["/api/v1/auth/session", "/api/v1/auth/session/extend", "/api/v1/auth/logout"])(
    "is repeated on %s, which judges no credential",
    async (path) => {
      holder.set(bundle(1));
      fetchMock.mockResolvedValueOnce(refreshed(2));
      transport.mockImplementation(async (init: RequestInit) =>
        authOf(init) === bearer(2) ? noContent() : refused("unauthenticated"),
      );
      expect((await holder.send(path, { method: "POST" }, transport)).status).toBe(204);
      expect(transport).toHaveBeenCalledTimes(2);
    },
  );

  it("returns a 401 session_idle_locked as it is: locked, so nothing is refreshed or repeated", async () => {
    holder.set(bundle(1));
    transport.mockResolvedValue(refused("session_idle_locked"));
    expect((await holder.send("/api/v1/x", {}, transport)).status).toBe(401);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renews a call refused 401 with a body that is no JSON (a proxy's page), and repeats it once", async () => {
    holder.set(bundle(1));
    fetchMock.mockResolvedValueOnce(refreshed(2));
    transport.mockImplementation(async (init: RequestInit) =>
      authOf(init) === bearer(2) ? noContent() : new Response("<html>401</html>", { status: 401 }),
    );
    expect((await holder.send("/api/v1/x", {}, transport)).status).toBe(204);
    expect(transport.mock.calls.map(([init]) => authOf(init))).toEqual([bearer(1), bearer(2)]);
  });

  it("refreshes once for a call made before any token (the page-load refresh failed), and repeats it", async () => {
    fetchMock.mockResolvedValueOnce(refreshed(1));
    transport.mockImplementation(async (init: RequestInit) =>
      authOf(init) === bearer(1) ? noContent() : refused("unauthenticated"),
    );
    expect((await holder.send("/api/v1/me", {}, transport)).status).toBe(204);
    expect(transport.mock.calls.map(([init]) => authOf(init))).toEqual([null, bearer(1)]);
  });

  it("forgets the token when a logout succeeds: no bearer after it, and no refresh timer", async () => {
    holder.set(bundle(1));
    await holder.send("/api/v1/auth/logout", { method: "POST" }, transport);
    await expect(holder.getToken()).resolves.toEqual({ kind: "unavailable" });
    await holder.send("/api/v1/x", {}, transport);
    expect(authOf(transport.mock.calls[1]?.[0])).toBeNull();
    await vi.advanceTimersByTimeAsync(600_000);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("every response that carries a token bundle hands it to the holder", () => {
  it.each([
    "/api/v1/auth/login",
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/mfa/recovery",
    "/api/v1/auth/mfa/enroll/confirm",
  ])("%s", async (path) => {
    fetchMock.mockResolvedValueOnce(refreshed(3));
    await apiFetch(path, { method: "POST", body: "{}" });
    await expect(accessToken.getToken()).resolves.toMatchObject({ accessToken: tokenOf(3) });
  });

  it.each([
    ["/api/v1/auth/login", false],
    ["/api/v1/auth/mfa/verify", false],
    ["/api/v1/auth/mfa/recovery", false],
    ["/api/v1/auth/mfa/enroll/confirm", true],
    ["/api/v1/auth/step-up", true],
  ])("%s carries the bearer: %s (pre-session calls get none)", async (path, carries) => {
    holder.set(bundle(1));
    await holder.send(path, { method: "POST" }, transport);
    expect(authOf(transport.mock.calls[0]?.[0])).toBe(carries ? bearer(1) : null);
  });

  it("a step-up waits for a refresh under the lock, sends the token of that moment, and its bundle replaces it", async () => {
    vi.stubGlobal("navigator", { locks: serialLocks() });
    accessToken.set(bundle(1));
    await vi.advanceTimersByTimeAsync(100_000);
    let answer: (res: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)));
    accessToken.invalidate();
    void accessToken.refresh(); // it holds the lock
    const elevated = { elevated_until: "", action_class: "keys", single_use: false };
    fetchMock.mockResolvedValueOnce(json(200, { ...elevated, tokens: bundle(3) }));
    const stepUp = apiFetch("/api/v1/auth/step-up", { method: "POST", body: "{}" });
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1); // the rotation never races the refresh
    answer(refreshed(2));
    await stepUp;
    expect(authOf(fetchMock.mock.calls[1]?.[1])).toBe(bearer(2));
    fetchMock.mockResolvedValueOnce(noContent());
    await apiFetch("/api/v1/me");
    expect(authOf(fetchMock.mock.calls[2]?.[1])).toBe(bearer(3));
    fetchMock.mockImplementation(async () => refreshed(4));
    await vi.advanceTimersByTimeAsync(440_000); // the first token's T - 60 s: its timer is gone
    expect(fetchMock).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(100_000); // the step-up token's
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

describe("one token per origin: a bundle one tab receives, its sibling tabs hold", () => {
  const tab = (): AccessTokenHolder => createAccessTokenHolder(vi.fn());
  /** Two tabs after a page load: the first refreshed once, and the second holds its token. */
  async function twoTabs() {
    const Channel = siblingChannels();
    vi.stubGlobal("navigator", { locks: serialLocks() });
    vi.stubGlobal("BroadcastChannel", Channel);
    const session = rotatingSession();
    const signIns = [vi.fn(), vi.fn()] as const; // how each tab goes to sign-in
    const tabs = [
      createAccessTokenHolder(signIns[0]),
      createAccessTokenHolder(signIns[1]),
    ] as const;
    const loaded = tabs[0].refresh();
    await vi.advanceTimersByTimeAsync(60); // the answer at 50 ms, the post to the sibling a moment later
    await expect(loaded).resolves.toBe("ok");
    await expect(tabs[1].getToken()).resolves.toMatchObject({ accessToken: tokenOf(1) });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(Channel.opened).toEqual([TOKEN_CHANNEL, TOKEN_CHANNEL]);
    return { ...session, tabs, signIns };
  }

  it("after one tab refreshes, the other tab's reads and writes carry the new token", async () => {
    const { api, tabs } = await twoTabs();
    await vi.advanceTimersByTimeAsync(540_100); // T - 60 s in both tabs: one refreshes, the other takes its bundle
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await tabs[1].send("/api/v1/x", {}, api);
    await tabs[1].send("/api/v1/x", { method: "POST" }, api);
    expect(api.mock.calls.map(([init]) => authOf(init))).toEqual([bearer(2), bearer(2)]); // no 401, 403 or repeat
    await expect(tabs[1].getToken()).resolves.toMatchObject({
      kind: "ok",
      accessToken: tokenOf(2),
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("repeats a write refused 403 csrf_token_invalid, its bearer revoked by a sibling's refresh, with that tab's token", async () => {
    const { api, tabs } = await twoTabs();
    let sent = 0;
    const slowFirst = vi.fn((init: RequestInit) =>
      (sent += 1) === 1 ? later(100, () => api(init)) : api(init),
    );
    const write = tabs[1].send("/api/v1/x", { method: "POST" }, slowFirst);
    tabs[0].invalidate(); // the WS client in the other tab was refused: it refreshes while the write is on the wire
    void tabs[0].getToken();
    await vi.advanceTimersByTimeAsync(100);
    await expect(write).resolves.toMatchObject({ status: 204 });
    expect(slowFirst.mock.calls.map(([init]) => authOf(init))).toEqual([bearer(1), bearer(2)]);
    expect(fetchMock).toHaveBeenCalledTimes(2); // the writing tab refreshed nothing
  });

  it("renews two calls refused at once with one refresh, so neither repeat is rotated away", async () => {
    const { state, api, tabs } = await twoTabs();
    state.live += 1; // a rotation whose bundle these tabs never got (its tab has closed): token 1 is dead
    const calls = tabs.map((t) => t.send("/api/v1/x", {}, api));
    await vi.advanceTimersByTimeAsync(60);
    const answers = await Promise.all(calls);
    expect(answers.map((res) => res.status)).toEqual([204, 204]);
    expect(fetchMock).toHaveBeenCalledTimes(2); // the page load's, and one renewal
  });

  it.each<[string, (tab: AccessTokenHolder, api: Transport) => Promise<unknown>, number, number]>([
    ["logs out", (tab, api) => tab.send("/api/v1/auth/logout", { method: "POST" }, api), 0, 1],
    [
      "finds the session lost",
      (tab) => {
        fetchMock.mockImplementationOnce(async () => refused("refresh_token_invalid"));
        tab.invalidate(); // its WS client was refused
        return tab.getToken();
      },
      1,
      2,
    ],
  ])(
    "a tab that %s sends each sibling that held the token to sign-in, which sends no bearer and refreshes nothing",
    async (_name, act, own, refreshes) => {
      const { api, tabs, signIns } = await twoTabs();
      const tokenless = vi.fn();
      createAccessTokenHolder(tokenless); // a tab that holds none (the sign-in page) stays where it is
      await act(tabs[0], api);
      await flush(); // the post reaches the siblings
      // a logout's own tab is routed by the sign-out UI, a lost session's by its holder
      expect(signIns.map((signIn) => signIn.mock.calls.length)).toEqual([own, 1]);
      expect(tokenless).not.toHaveBeenCalled();
      await expect(tabs[1].getToken()).resolves.toEqual({ kind: "unavailable" });
      await tabs[1].send("/api/v1/x", {}, api);
      expect(authOf(api.mock.calls.at(-1)?.[0])).toBeNull();
      expect(fetchMock).toHaveBeenCalledTimes(refreshes); // the page load's, and the lost one's
    },
  );

  it.each<[string, (now: number) => unknown]>([
    ["no object", () => null],
    ["a token that is no b64token", (now) => ({ accessToken: "a b", expiresAtMs: now + 1e6 })],
    ["an expiry that is no number", () => ({ accessToken: tokenOf(9), expiresAtMs: Number.NaN })],
    ["an expiry already past", (now) => ({ accessToken: tokenOf(9), expiresAtMs: now })],
    ["the held token, due sooner", (now) => ({ accessToken: tokenOf(1), expiresAtMs: now + 61e3 })],
    [
      "an older bundle, due before the held one",
      (now) => ({ accessToken: tokenOf(9), expiresAtMs: now + 599e3 }),
    ],
  ])(
    "holds nothing another same-origin context posts that is not a newer bundle: %s",
    async (_name, message) => {
      const Channel = siblingChannels();
      vi.stubGlobal("BroadcastChannel", Channel);
      const own = tab();
      own.set(bundle(1));
      new Channel(TOKEN_CHANNEL).postMessage(message(Date.now()));
      await flush();
      await expect(own.getToken()).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(1) });
      await vi.advanceTimersByTimeAsync(539_999); // its timer stands: nothing before its T - 60 s
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("waits 1 s for the bundle of a sibling that rotated and closed, then refreshes once and lets the lock go", async () => {
    const locks = serialLocks();
    vi.stubGlobal("navigator", { locks });
    vi.stubGlobal("BroadcastChannel", siblingChannels());
    let csrf = "csrf-0";
    vi.spyOn(document, "cookie", "get").mockImplementation(() => `__Host-cv_csrf=${csrf}`);
    fetchMock.mockImplementation(async () => refreshed(2));
    void locks.request(REFRESH_LOCK, () => later(100, () => (csrf = "csrf-1"))); // it posts nothing
    const token = tab().getToken();
    await vi.advanceTimersByTimeAsync(100 + SIBLING_WAIT_MS - 1);
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(token).resolves.toMatchObject({ kind: "ok", accessToken: tokenOf(2) });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const third = vi.fn(async () => undefined);
    await locks.request(REFRESH_LOCK, third);
    expect(third).toHaveBeenCalledTimes(1);
  });
});

describe("a refresh no tab saw answered: its keepalive request outlives the lock of a closed or reloaded tab", () => {
  let csrf: string;
  beforeEach(() => {
    csrf = "csrf-0";
    vi.spyOn(document, "cookie", "get").mockImplementation(() => `__Host-cv_csrf=${csrf}`);
  });
  /** The CSRF header each `POST /auth/refresh` carried: which session cookie it presented. */
  const presented = (): (string | null)[] =>
    (fetchMock.mock.calls as [string, RequestInit][])
      .filter(([url]) => url === REFRESH_PATH)
      .map(([, init]) => new Headers(init.headers).get("X-CSRF-Token"));
  /** Every other call: the cookie-only `GET /auth/session` probes, and the `Authorization` each carried. */
  const probes = (): [string, string | null][] =>
    (fetchMock.mock.calls as [string, RequestInit][])
      .filter(([url]) => url !== REFRESH_PATH)
      .map(([url, init]) => [url, authOf(init)]);
  /** A tab sends a refresh and goes: it never sees the answer, whose rotated cookie lands `landsInMs` later. */
  async function sentThenGone(landsInMs?: number): Promise<void> {
    fetchMock.mockImplementationOnce(() => new Promise<Response>(() => undefined));
    void createAccessTokenHolder(vi.fn()).refresh();
    await flush();
    if (landsInMs !== undefined) setTimeout(() => (csrf = "csrf-1"), landsInMs);
    fetchMock.mockImplementation(async () => refreshed(2));
  }

  it("a reload waits for the cookie that refresh stores, then presents that one, once", async () => {
    await sentThenGone(300);
    expect(localStorage.getItem(REFRESH_SENT_KEY)).toBe(String(Date.now())); // a time, never the token
    const reloaded = holder.refresh(); // the new page's
    await vi.advanceTimersByTimeAsync(300);
    await expect(reloaded).resolves.toBe("ok");
    expect(presented()).toEqual(["csrf-0", "csrf-1"]); // the spent csrf-0 cookie is not presented again
  });

  it("a tab that waited on the lock for one that closed mid-refresh presents the cookie that refresh stores", async () => {
    const locks = closingTabLocks();
    vi.stubGlobal("navigator", { locks });
    await sentThenGone(50);
    const waited = holder.refresh();
    await flush();
    locks.close(); // the lock goes with the tab; its request does not
    await vi.advanceTimersByTimeAsync(100);
    await expect(waited).resolves.toBe("ok");
    expect(presented()).toEqual(["csrf-0", "csrf-1"]);
  });

  it.each([
    ["live, it is presented", 200, "ok", ["csrf-0", "csrf-0"]],
    ["spent, it is not: no session, and the family lives", 401, "lost", ["csrf-0"]],
  ])(
    "a cookie that never changes is first checked with GET /auth/session: %s",
    async (_name, status, outcome, sent) => {
      await sentThenGone();
      fetchMock.mockImplementation(async (url: string) =>
        url === REFRESH_PATH ? refreshed(2) : json(status, {}),
      );
      const reloaded = holder.refresh();
      await vi.advanceTimersByTimeAsync(ORPHAN_WAIT_MS);
      await expect(reloaded).resolves.toBe(outcome);
      expect(presented()).toEqual(sent);
      expect(probes()).toEqual([["/api/v1/auth/session", null]]);
    },
  );

  it("this tab's own refresh whose answer was lost is checked the same way before the cookie goes again", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("the answer was lost"));
    await expect(holder.refresh()).resolves.toBe("failed");
    fetchMock.mockImplementation(async (url: string) =>
      url === REFRESH_PATH ? refreshed(2) : json(401, {}),
    );
    const again = holder.refresh();
    await vi.advanceTimersByTimeAsync(ORPHAN_WAIT_MS);
    await expect(again).resolves.toBe("lost");
    expect(presented()).toEqual(["csrf-0"]);
  });

  it("a spent cookie the probe found stays marked: the page load after the sign-out probes again, and presents nothing", async () => {
    await sentThenGone();
    fetchMock.mockImplementation(async (url: string) =>
      url === REFRESH_PATH ? refreshed(2) : json(401, {}),
    );
    const first = holder.refresh();
    await vi.advanceTimersByTimeAsync(ORPHAN_WAIT_MS);
    await expect(first).resolves.toBe("lost");
    const signInPage = createAccessTokenHolder(vi.fn()); // /login loads, and its shell refreshes
    const second = signInPage.refresh();
    await vi.advanceTimersByTimeAsync(ORPHAN_WAIT_MS);
    await expect(second).resolves.toBe("lost");
    expect(presented()).toEqual(["csrf-0"]); // only the dead tab's
    expect(probes()).toHaveLength(2);
  });

  it.each([
    ["live, it is presented", 200, "ok", ["csrf-0", "csrf-0"]],
    ["spent, it is not", 401, "lost", ["csrf-0"]],
  ])(
    "this tab's own refresh that the browser fails 30 s after it went is checked too, at once: %s",
    async (_name, status, outcome, sent) => {
      let drop: (reason: unknown) => void = () => undefined;
      fetchMock.mockImplementationOnce(
        () => new Promise<Response>((_resolve, reject) => (drop = reject)),
      );
      const first = holder.refresh();
      await vi.advanceTimersByTimeAsync(30_000); // the caller stops waiting at 10 s, the browser later
      await expect(first).resolves.toBe("failed");
      drop(new TypeError("the answer was lost"));
      await flush();
      fetchMock.mockImplementation(async (url: string) =>
        url === REFRESH_PATH ? refreshed(2) : json(status, {}),
      );
      const again = holder.refresh();
      await flush(); // no wait for the cookie of a refresh sent that long ago
      expect(probes()).toEqual([["/api/v1/auth/session", null]]);
      await expect(again).resolves.toBe(outcome);
      expect(presented()).toEqual(sent);
    },
  );

  it("a refresh answered 500, which may come after the rotation, is checked the same way before the cookie goes again", async () => {
    fetchMock.mockResolvedValueOnce(json(500, {}));
    await expect(holder.refresh()).resolves.toBe("failed");
    fetchMock.mockImplementation(async (url: string) =>
      url === REFRESH_PATH ? refreshed(2) : json(401, {}),
    );
    const again = holder.refresh();
    await vi.advanceTimersByTimeAsync(ORPHAN_WAIT_MS);
    await expect(again).resolves.toBe("lost");
    expect(presented()).toEqual(["csrf-0"]);
  });

  it.each([
    [200, false],
    [401, false],
    [403, false],
    [429, false],
    [500, true],
    [503, true],
  ])(
    "a refresh answered %i keeps the mark: %s (a 2xx, or a refusal before any rotation, settles the cookie)",
    async (status, kept) => {
      fetchMock.mockResolvedValueOnce(status === 200 ? refreshed(2) : json(status, {}));
      await holder.refresh();
      expect(localStorage.getItem(REFRESH_SENT_KEY) !== null).toBe(kept);
    },
  );

  it("waits for that cookie by the clock, not by a count of looks: a hidden tab's late timers keep the lock no longer", async () => {
    await sentThenGone();
    fetchMock.mockImplementation(async (url: string) =>
      url === REFRESH_PATH ? refreshed(2) : json(200, {}),
    );
    const reloaded = holder.refresh();
    await vi.advanceTimersByTimeAsync(100); // one look at the cookie
    vi.setSystemTime(Date.now() + ORPHAN_WAIT_MS); // hidden, the tab's 100 ms timers run seconds late
    await vi.advanceTimersByTimeAsync(100); // so the next look is past the wait
    expect(probes()).toEqual([["/api/v1/auth/session", null]]);
    await expect(reloaded).resolves.toBe("ok");
  });

  it("a probe that never answers is given up by 10 s: the lock goes to the next tab, nothing more is presented, and the next ask probes again", async () => {
    await sentThenGone();
    const locks = serialLocks();
    vi.stubGlobal("navigator", { locks });
    fetchMock.mockImplementation(stalled); // the GET /auth/session probe
    const reloaded = holder.refresh();
    await vi.advanceTimersByTimeAsync(ORPHAN_WAIT_MS + REFRESH_WAIT_MS);
    await expect(reloaded).resolves.toBe("failed");
    expect(probes()).toEqual([["/api/v1/auth/session", null]]);
    const next = vi.fn(async () => undefined); // another tab's refresh
    void locks.request(REFRESH_LOCK, next);
    await flush();
    expect(next).toHaveBeenCalledTimes(1);
    expect(presented()).toEqual(["csrf-0"]); // the cookie that refresh may have spent is not presented
    void holder.getToken(); // a stalled probe is no 401: the session is not lost, so the next ask probes again
    await flush();
    expect(probes()).toHaveLength(2);
  });

  it("a document without storage refreshes all the same: the cookie goes once, and nothing escapes", async () => {
    const blocked = (): never => {
      throw new DOMException("storage is blocked", "SecurityError");
    };
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked);
    fetchMock.mockResolvedValueOnce(refreshed(1));
    await expect(holder.refresh()).resolves.toBe("ok");
    expect(presented()).toEqual(["csrf-0"]);
  });
});

describe("the test setup takes BroadcastChannel away for the token holder alone", () => {
  it("no other src module uses one, so none runs channel-less in its tests unnoticed (it would stub its own)", () => {
    const src = resolve(import.meta.dirname, "../../../src");
    const users = readdirSync(src, { recursive: true, encoding: "utf8" }).filter(
      (file) =>
        /\.tsx?$/.test(file) && readFileSync(join(src, file), "utf8").includes("BroadcastChannel"),
    );
    expect(users.map((file) => file.split(sep).join("/"))).toEqual(["lib/auth/accessToken.ts"]);
  });
});
