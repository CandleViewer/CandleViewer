import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CSRF_COOKIE,
  CSRF_HEADER,
  apiFetch,
  isSameOrigin,
  readCsrfCookie,
} from "../../src/lib/http/csrfFetch";

let cookieValue: string | null = null;

function setCookie(value: string | null): void {
  cookieValue = value;
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
    setCookie(null);
    vi.spyOn(document, "cookie", "get").mockImplementation(() =>
      cookieValue === null ? "other=1" : `other=1; ${CSRF_COOKIE}=${cookieValue}`,
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks(); // restores the real document.cookie accessor
  });

  it("readCsrfCookie returns the value or null", () => {
    expect(readCsrfCookie(`a=1; ${CSRF_COOKIE}=n.m; b=2`)).toBe("n.m");
    expect(readCsrfCookie("a=1")).toBeNull();
    expect(readCsrfCookie(`${CSRF_COOKIE}=`)).toBeNull();
  });

  it.each(["POST", "PUT", "PATCH", "DELETE", "post", "PURGE"])(
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

  it("never sends the token to another origin", async () => {
    setCookie("tok.mac");
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await apiFetch("https://evil.example/api/v1/x", { method: "POST" });
    expect(sentToken(fetchMock, 0)).toBeNull();
    expect(isSameOrigin("/api/v1/x")).toBe(true);
    expect(isSameOrigin(new URL("/x", window.location.href))).toBe(true);
    expect(isSameOrigin("https://evil.example/x")).toBe(false);
    expect(isSameOrigin("http://[bad")).toBe(false);
  });

  it("accepts a Request input and uses its method", async () => {
    setCookie("tok.mac");
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await apiFetch(new Request(new URL("/api/v1/x", window.location.href), { method: "DELETE" }));
    expect(sentToken(fetchMock, 0)).toBe("tok.mac");
  });

  it("refuses non-replayable stream bodies", async () => {
    setCookie("tok.mac");
    const body = new ReadableStream();
    await expect(apiFetch("/api/v1/x", { method: "POST", body })).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("multi-tab: re-reads the rotated cookie and retries once", async () => {
    setCookie("old.mac");
    fetchMock.mockImplementationOnce(async () => {
      setCookie("new.mac"); // another tab rotated it
      return problem("csrf_token_invalid");
    });
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const res = await apiFetch("/api/v1/x", { method: "POST", body: "{}" });
    expect(res.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sentToken(fetchMock, 0)).toBe("old.mac");
    expect(sentToken(fetchMock, 1)).toBe("new.mac");
  });

  it("does not repeat the request when the cookie did not change", async () => {
    setCookie("same.mac");
    fetchMock.mockResolvedValueOnce(problem("csrf_token_invalid"));
    const res = await apiFetch("/api/v1/x", { method: "POST", body: "{}" });
    expect(res.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("missing cookie: bootstraps via GET /auth/session, then retries once", async () => {
    setCookie(null);
    fetchMock.mockResolvedValueOnce(problem("csrf_token_invalid"));
    fetchMock.mockImplementationOnce(async () => {
      setCookie("reissued.mac"); // GET /auth/session re-issues it
      return new Response("{}", { status: 200 });
    });
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const res = await apiFetch("/api/v1/x", { method: "PUT", body: "{}" });
    expect(res.status).toBe(204);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/session");
    expect(sentToken(fetchMock, 0)).toBeNull();
    expect(sentToken(fetchMock, 2)).toBe("reissued.mac");
  });

  it("missing cookie that the bootstrap cannot restore surfaces the first refusal", async () => {
    setCookie(null);
    fetchMock.mockResolvedValueOnce(problem("csrf_token_invalid"));
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    const res = await apiFetch("/api/v1/x", { method: "POST" });
    expect(res.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fetchMock.mockResolvedValueOnce(problem("csrf_token_invalid"));
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    expect((await apiFetch("/api/v1/x", { method: "POST" })).status).toBe(403);
  });

  it("surfaces a second csrf refusal without a third attempt", async () => {
    setCookie("tok.mac");
    fetchMock.mockImplementationOnce(async () => {
      setCookie("tok2.mac");
      return problem("csrf_token_invalid");
    });
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
