/** #1640 S3: `sessionsApi` against a stubbed `apiFetch` (no network); bodies as the server answers. */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch, endSession } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
  endSession: vi.fn(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));
vi.mock("../../../src/lib/auth/accessToken", () => ({ accessToken: { endSession } }));

import { sessionsApi } from "../../../src/features/session/sessionsApi";

const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
/** `_problem` of services/api/candleviewer/api/sessions.py. */
const problem = (status: number, title: string, detail: string): Response =>
  reply(status, { type: "about:blank", title, status, detail });
const page = (ids: string[], next: string | null) => ({
  items: ids.map((id) => ({ id, current: false })),
  meta: { next_cursor: next, has_more: next !== null, count: ids.length },
});

afterEach(() => vi.clearAllMocks());

describe("sessionsApi.list", () => {
  it("follows next_cursor across pages", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, page(["a"], "100")));
    apiFetch.mockResolvedValueOnce(reply(200, page(["b"], null)));
    const out = await sessionsApi.list();
    expect(out).toEqual({
      kind: "ok",
      items: [
        { id: "a", current: false },
        { id: "b", current: false },
      ],
    });
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/auth/sessions?limit=100",
      "/api/v1/auth/sessions?limit=100&cursor=100",
    ]);
  });

  it.each([
    [403, "forbidden"],
    [503, "unavailable"],
    [422, "unavailable"],
  ])("%s -> %s", async (status, kind) => {
    apiFetch.mockResolvedValueOnce(problem(status, "x", "server detail never shown"));
    expect(await sessionsApi.list()).toEqual({ kind });
  });

  it("a body without items, or no answer, is unavailable", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, { meta: {} }));
    expect(await sessionsApi.list()).toEqual({ kind: "unavailable" });
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await sessionsApi.list()).toEqual({ kind: "unavailable" });
  });
});

describe("sessionsApi actions", () => {
  it("revoke: DELETE /me/sessions/{id}; 404 is not_found", async () => {
    apiFetch.mockResolvedValueOnce(reply(204));
    expect(await sessionsApi.revoke("s-1")).toEqual({ kind: "done" });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/me/sessions/s-1", { method: "DELETE" });
    apiFetch.mockResolvedValueOnce(problem(404, "Not found", "no such session"));
    expect(await sessionsApi.revoke("s-2")).toEqual({ kind: "not_found" });
  });

  it("sign out everywhere: POST /auth/logout {all_sessions: true}; 401 is refused", async () => {
    apiFetch.mockResolvedValueOnce(problem(401, "Unauthorized", "authentication required"));
    expect(await sessionsApi.signOutEverywhere()).toEqual({ kind: "refused" });
    const [url, init] = apiFetch.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/auth/logout");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ all_sessions: true });
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await sessionsApi.signOutEverywhere()).toEqual({ kind: "unavailable" });
  });

  it("endSession goes through the token holder", () => {
    sessionsApi.endSession();
    expect(endSession).toHaveBeenCalledTimes(1);
  });
});
