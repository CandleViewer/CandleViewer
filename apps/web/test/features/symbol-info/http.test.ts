/** E08-D06 §6, D-12: the 10 s deadline of every SCR-103 GET and the bounds on `Retry-After`. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { DEADLINE_MS, getAnswer } from "../../../src/features/symbol-info/http";
import { SYSTEM_CLOCK } from "../../../src/features/symbol-search/instrumentIndex";

const reply = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(JSON.stringify(body), { status, headers });
const ask = () => getAnswer("/x", new AbortController().signal, SYSTEM_CLOCK);

beforeEach(() => {
  vi.useFakeTimers();
  apiFetch.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("the deadline", () => {
  it("is 10 s and aborts a call that has not answered, resolving null", async () => {
    let aborted = false;
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            aborted = true;
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    );
    expect(DEADLINE_MS).toBe(10_000);
    const pending = ask();
    await vi.advanceTimersByTimeAsync(DEADLINE_MS - 1);
    expect(aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(aborted).toBe(true);
    expect(await pending).toBeNull();
  });

  it("clears its timer once answered", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, {}));
    expect((await ask())?.status).toBe(200);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("Retry-After", () => {
  it.each([
    ["7", 7],
    ["0", 1],
    ["1", 1],
    ["60", 60],
    ["61", 60],
    ["99999", 60],
    [" 5 ", 5],
    ["-3", null],
    ["1.5", null],
    ["soon", null],
    ["Wed, 21 Oct 2026 07:28:00 GMT", null],
  ])("reads the header %j as %j whole seconds, clamped to 1..60", async (sent, expected) => {
    apiFetch.mockResolvedValueOnce(reply(503, {}, { "Retry-After": sent }));
    expect((await ask())?.retryAfterS).toBe(expected);
  });

  it("falls back to the body's retry_after_seconds and clamps it too", async () => {
    apiFetch.mockResolvedValueOnce(reply(503, { retry_after_seconds: 500 }));
    expect((await ask())?.retryAfterS).toBe(60);
    apiFetch.mockResolvedValueOnce(reply(503, {}));
    expect((await ask())?.retryAfterS).toBeNull();
  });
});
