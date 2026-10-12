import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CSRF_COOKIE, CSRF_HEADER, apiFetch, readCsrfCookie } from "../../src/lib/http/csrfFetch";

function setCookie(value: string | null): void {
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get: () => (value === null ? "other=1" : `other=1; ${CSRF_COOKIE}=${value}`),
  });
}

function problem(code: string): Response {
  return new Response(JSON.stringify({ status: 403, code }), {
    status: 403,
    headers: { "content-type": "application/problem+json" },
  });
}

function sentToken(fetchMock: ReturnType<typeof vi.fn>, call: number): string | null {
  const init = fetchMock.mock.calls[call]?.[1] as RequestInit | undefined;
  return new Headers(init?.headers).get(CSRF_HEADER);
}

describe("csrfFetch (SR-041)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setCookie(null);
  });

  it("readCsrfCookie returns the value or null", () => {
    expect(readCsrfCookie(`a=1; ${CSRF_COOKIE}=n.m; b=2`)).toBe("n.m");
    expect(readCsrfCookie("a=1")).toBeNull();
    expect(readCsrfCookie(`${CSRF_COOKIE}=`)).toBeNull();
  });

  it.each(["POST", "PUT", "PATCH", "DELETE", "post"])(
    "sends the cookie as X-CSRF-Token on %s",
    async (method) => {
      setCookie("tok.mac");
      fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
      await apiFetch("/api/v1/x", { method, headers: { "Content-Type": "application/json" } });
      expect(sentToken(fetchMock, 0)).toBe("tok.mac");
      const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
      expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    },
  );

  it("never adds the header to safe methods", async () => {
    setCookie("tok.mac");
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 200 }));
    await apiFetch("/api/v1/x");
    expect(sentToken(fetchMock, 0)).toBeNull();
  });

  it("omits the header when the cookie is absent", async () => {
    setCookie(null);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await apiFetch("/api/v1/x", { method: "POST" });
    expect(sentToken(fetchMock, 0)).toBeNull();
  });

  it("multi-tab: re-reads the rotated cookie and retries once", async () => {
    let cookie = "old.mac";
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => `${CSRF_COOKIE}=${cookie}`,
    });
    fetchMock.mockImplementationOnce(async () => {
      cookie = "new.mac"; // another tab rotated it
      return problem("csrf_token_invalid");
    });
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const res = await apiFetch("/api/v1/x", { method: "POST", body: "{}" });
    expect(res.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sentToken(fetchMock, 0)).toBe("old.mac");
    expect(sentToken(fetchMock, 1)).toBe("new.mac");
  });

  it("surfaces a second csrf refusal without a third attempt", async () => {
    setCookie("tok.mac");
    fetchMock.mockResolvedValueOnce(problem("csrf_token_invalid"));
    fetchMock.mockResolvedValueOnce(problem("csrf_token_invalid"));
    const res = await apiFetch("/api/v1/x", { method: "DELETE" });
    expect(res.status).toBe(403);
    expect(((await res.json()) as { code: string }).code).toBe("csrf_token_invalid");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry other 403s or non-JSON 403s", async () => {
    setCookie("tok.mac");
    fetchMock.mockResolvedValueOnce(problem("forbidden"));
    expect((await apiFetch("/api/v1/x", { method: "POST" })).status).toBe(403);
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 403 }));
    expect((await apiFetch("/api/v1/x", { method: "POST" })).status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
