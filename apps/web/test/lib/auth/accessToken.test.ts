// #2712 (ADR-0020 decisions 1, 3, 5; 23 §4.3): the tab's in-memory access token, its refresh, its bearer
// rule and the WS client's `TokenSource`. Fake timers and a stubbed `fetch`: no network, no wall clock.
import { inspect } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  REFRESH_LOCK,
  REFRESH_PATH,
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
/** A Web Locks stand-in shared by the tabs of a test: one holder of a name at a time. */
function serialLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  return {
    request: vi.fn((_name: string, task: () => Promise<unknown>) => {
      const run = tail.then(task);
      tail = run.catch(() => undefined);
      return run;
    }),
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
let toSignIn: Mock<() => void>;
let holder: AccessTokenHolder;
let transport: Mock<(init: RequestInit) => Promise<Response>>;

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
  ])("apiFetch to %s: bearer sent %s", async (_name, carries, input) => {
    accessToken.set(bundle(1));
    fetchMock.mockResolvedValueOnce(noContent());
    await apiFetch(input);
    const [sent, init] = fetchMock.mock.calls[0] ?? [];
    const own = sent instanceof Request ? sent.headers.get("Authorization") : null;
    expect(authOf(init) ?? own).toBe(carries ? bearer(1) : null);
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

  it("makes a second tab wait for the first under the cv.auth.refresh lock", async () => {
    const locks = serialLocks();
    vi.stubGlobal("navigator", { locks });
    const answer: ((res: Response) => void)[] = [];
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => answer.push(resolve)));
    const first = holder.getToken();
    const second = createAccessTokenHolder(vi.fn()).getToken();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1); // the single-use cookie is never presented twice at once
    answer[0]?.(refreshed(1));
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2); // the second tab presents the cookie the first one rotated
    answer[1]?.(refreshed(2));
    await expect(first).resolves.toMatchObject({ accessToken: tokenOf(1) });
    await expect(second).resolves.toMatchObject({ accessToken: tokenOf(2) });
    expect(locks.request).toHaveBeenCalledWith(REFRESH_LOCK, expect.any(Function));
    await expect(holder.refresh()).resolves.toBe("ok"); // a token that is still fresh presents nothing
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["answers 503", async () => json(503, {})],
    ["answers 200 without a bundle", async () => json(200, { status: "authenticated" })],
    ["cannot be reached", () => Promise.reject(new TypeError("offline"))],
    [
      "does not answer in 10 s",
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) =>
          init.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError"))),
        ),
    ],
  ])("a refresh that %s answers unavailable and clears nothing", async (_name, answer) => {
    holder.set(bundle(1));
    holder.invalidate();
    fetchMock.mockImplementationOnce(answer);
    const result = holder.getToken();
    await vi.advanceTimersByTimeAsync(10_000);
    await expect(result).resolves.toEqual({ kind: "unavailable" });
    await holder.send("/api/v1/x", {}, transport);
    expect(authOf(transport.mock.calls[0]?.[0])).toBe(bearer(1));
    expect(toSignIn).not.toHaveBeenCalled();
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

  it("answers locked on 401 session_idle_locked and clears nothing", async () => {
    holder.set(bundle(1));
    holder.invalidate();
    fetchMock.mockResolvedValueOnce(refused("session_idle_locked"));
    await expect(holder.getToken()).resolves.toEqual({ kind: "locked" });
    await holder.send("/api/v1/x", {}, transport);
    expect(authOf(transport.mock.calls[0]?.[0])).toBe(bearer(1));
    expect(toSignIn).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(refreshed(2)); // after the unlock, the same cookie refreshes
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

  it("is never repeated on an auth route, where a 401 judges a password or a code", async () => {
    holder.set(bundle(1));
    transport.mockResolvedValue(refused("unlock_invalid"));
    await holder.send("/api/v1/auth/unlock", { method: "POST" }, transport);
    expect(transport).toHaveBeenCalledTimes(1);
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
