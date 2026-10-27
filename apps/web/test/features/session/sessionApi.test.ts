/** #1640 review: `sessionApi` outcomes against a stubbed `apiFetch` (no network). */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch, refresh, endSession } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
  refresh: vi.fn(),
  endSession: vi.fn(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));
vi.mock("../../../src/lib/auth/accessToken", () => ({ accessToken: { refresh, endSession } }));

import { UNLOCK_TIMEOUT_MS, sessionApi } from "../../../src/features/session/sessionApi";

const CLOCK = {
  server_time: "2026-10-27T10:00:00Z",
  session: { idle_deadline: "2026-10-27T10:15:00Z", idle_timeout_s: 900, locked: false },
};
const reply = (status: number, body: unknown): Response =>
  new Response(typeof body === "string" ? body : JSON.stringify(body), { status });

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("sessionApi.unlock", () => {
  it.each([
    ["401 unlock_invalid", reply(401, { code: "unlock_invalid" }), "invalid"],
    ["401 session_revoked", reply(401, { code: "session_revoked" }), "revoked"],
    ["401 with a body that is not JSON (fail safe)", reply(401, "<html>"), "revoked"],
    ["409 conflict", reply(409, { code: "conflict" }), "not_locked"],
    ["429", reply(429, { code: "rate_limited" }), "throttled"],
    [
      "200 with a malformed body",
      reply(200, { session: { idle_deadline: "soon" } }),
      "unreachable",
    ],
    ["503", reply(503, { code: "audit_unavailable" }), "unreachable"],
  ])("%s -> %s", async (_name, res, kind) => {
    apiFetch.mockResolvedValueOnce(res);
    expect((await sessionApi.unlock("pw")).kind).toBe(kind);
  });

  it("a network failure is unreachable", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await sessionApi.unlock("pw")).toEqual({ kind: "unreachable" });
  });

  it("an unlock with no answer is aborted after the timeout as unreachable", async () => {
    vi.useFakeTimers();
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
        }),
    );
    const outcome = sessionApi.unlock("pw");
    await vi.advanceTimersByTimeAsync(UNLOCK_TIMEOUT_MS);
    expect(await outcome).toEqual({ kind: "unreachable" });
  });

  it("a 401 whose body is cut off by the timeout is unreachable, not a sign-out", async () => {
    vi.useFakeTimers();
    apiFetch.mockImplementationOnce(async (_url, init) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          init?.signal?.addEventListener("abort", () =>
            controller.error(new DOMException("", "AbortError")),
          );
        },
      });
      return new Response(body, { status: 401 });
    });
    const outcome = sessionApi.unlock("pw");
    await vi.advanceTimersByTimeAsync(UNLOCK_TIMEOUT_MS);
    expect(await outcome).toEqual({ kind: "unreachable" });
  });

  it("a 200 unlocks, sends the password only, then refreshes the token", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, CLOCK));
    expect(await sessionApi.unlock("pw")).toEqual({ kind: "unlocked", clock: CLOCK });
    expect(apiFetch.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ password: "pw" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe("sessionApi.read / extend", () => {
  it("returns a usable clock; extend is a POST", async () => {
    apiFetch.mockResolvedValue(reply(200, CLOCK));
    expect(await sessionApi.read()).toEqual(CLOCK);
    apiFetch.mockResolvedValue(reply(200, CLOCK));
    expect(await sessionApi.extend()).toEqual(CLOCK);
    expect(apiFetch).toHaveBeenLastCalledWith("/api/v1/auth/session/extend", { method: "POST" });
  });

  it.each([
    ["a NaN deadline", { ...CLOCK, session: { ...CLOCK.session, idle_deadline: "x" } }],
    ["a NaN server time", { ...CLOCK, server_time: "x" }],
    ["no locked flag", { ...CLOCK, session: { ...CLOCK.session, locked: "no" } }],
    ["no timeout", { ...CLOCK, session: { ...CLOCK.session, idle_timeout_s: null } }],
    ["not an object", "null"],
  ])("rejects %s (never a 0 ms schedule)", async (_name, body) => {
    apiFetch.mockResolvedValueOnce(reply(200, body));
    expect(await sessionApi.read()).toBeNull();
  });

  it("a refusal or a network failure reads as null", async () => {
    apiFetch.mockResolvedValueOnce(reply(401, { code: "session_idle_locked" }));
    expect(await sessionApi.extend()).toBeNull();
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await sessionApi.read()).toBeNull();
  });

  it("endSession hands over to the token holder", () => {
    sessionApi.endSession();
    expect(endSession).toHaveBeenCalledTimes(1);
  });
});
