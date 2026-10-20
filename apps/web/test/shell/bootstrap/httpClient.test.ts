import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken } from "../../../src/lib/auth/accessToken.js";
import { fetchJson, HttpError, HttpTimeoutError } from "../../../src/shell/bootstrap/httpClient.js";

const token = ["probe", "1", "x".repeat(20)].join("-");
const bundle = { access_token: token, token_type: "Bearer" as const, expires_in: 600 };
const authOf = (init: unknown): string | null =>
  new Headers((init as RequestInit | undefined)?.headers).get("Authorization");

// #2712: no session unless a test holds a token, and nothing (its refresh timer) outlives a test
beforeEach(() => accessToken.clear());
afterEach(() => {
  accessToken.clear();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("fetchJson", () => {
  it("resolves with the parsed JSON body on a 2xx response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const result = await fetchJson<{ ok: boolean }>("/api/v1/me", {
      timeoutMs: 1_000,
      fetchImpl,
    });
    expect(result).toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/me",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("sends the tab's access token to the same-origin API, and none to another origin (#2712)", async () => {
    accessToken.set(bundle);
    const fetchImpl = vi.fn().mockImplementation(async () => jsonResponse({}));
    await fetchJson("/api/v1/me", { timeoutMs: 1_000, fetchImpl });
    await fetchJson("https://other.example/api/v1/me", { timeoutMs: 1_000, fetchImpl });
    const [same, other] = fetchImpl.mock.calls.map((call) => authOf(call[1])); // what the client handed to fetch
    expect(same).toBe(`Bearer ${token}`);
    expect(other).toBeNull();
  });

  it("times out while it waits for the refresh a 401 started (#2712)", async () => {
    let answer: (res: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (answer = resolve))),
    );
    accessToken.set(bundle);
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 401));
    try {
      await expect(fetchJson("/api/v1/me", { timeoutMs: 5, fetchImpl })).rejects.toBeInstanceOf(
        HttpTimeoutError,
      );
    } finally {
      answer(new Response(null, { status: 503 })); // the refresh ends: nothing of it outlives the test
    }
  });

  it("throws HttpError with the status on a non-2xx response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 500));
    await expect(fetchJson("/api/v1/me", { timeoutMs: 1_000, fetchImpl })).rejects.toMatchObject({
      status: 500,
    });
  });

  it("throws HttpError as an instance", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 401));
    try {
      await fetchJson("/api/v1/me", { timeoutMs: 1_000, fetchImpl });
      expect.fail("expected rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(HttpError);
    }
  });

  it("throws HttpTimeoutError when the request exceeds timeoutMs", async () => {
    const fetchImpl = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    await expect(fetchJson("/api/v1/me", { timeoutMs: 5, fetchImpl })).rejects.toBeInstanceOf(
      HttpTimeoutError,
    );
  });
});
