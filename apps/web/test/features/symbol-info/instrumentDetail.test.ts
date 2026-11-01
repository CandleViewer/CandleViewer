/** E08-D06 §11.1, D-12: `GET /instruments/{symbol}` by status, and the 2/4/8/16/30 s ladder bounded at 60 s. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  attemptDetail,
  ladderWaitS,
  loadInstrumentDetail,
} from "../../../src/features/symbol-info/instrumentDetail";

const BODY = { symbol: "BTCUSDT", category: "linear", tick_size: "0.10", qty_step: "0.001" };
const json = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
const signal = (): AbortSignal => new AbortController().signal;

beforeEach(() => {
  vi.useFakeTimers();
  apiFetch.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("attemptDetail", () => {
  it("returns the detail on 200 and asks the symbol's own path", async () => {
    apiFetch.mockResolvedValueOnce(json(200, BODY));
    const out = await attemptDetail("BTCUSDT", signal());
    expect(out).toEqual({ kind: "ok", detail: BODY });
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/instruments/BTCUSDT");
  });

  it("sends nothing for a string that is not a symbol", async () => {
    expect(await attemptDetail("btc/../x", signal())).toEqual({
      kind: "failed",
      failure: { cause: "network" },
    });
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("maps 403, 404 (retry after 60 s), 503 and other statuses", async () => {
    vi.setSystemTime(1_000_000);
    apiFetch
      .mockResolvedValueOnce(json(403, { code: "forbidden" }))
      .mockResolvedValueOnce(json(404, {}))
      .mockResolvedValueOnce(json(503, { instance: "urn:cv:req:abc" }, { "Retry-After": "7" }))
      .mockResolvedValueOnce(json(500, { detail: "internal wording", instance: "urn:cv:req:def" }));
    expect(await attemptDetail("BTCUSDT", signal())).toEqual({ kind: "forbidden" });
    expect(await attemptDetail("BTCUSDT", signal())).toEqual({
      kind: "not_listed",
      retryAtMs: 1_060_000,
    });
    expect(await attemptDetail("BTCUSDT", signal())).toEqual({
      kind: "loading",
      retryAfterS: 7,
      instance: "urn:cv:req:abc",
    });
    expect(await attemptDetail("BTCUSDT", signal())).toEqual({
      kind: "failed",
      failure: { cause: "http", status: 500, instance: "urn:cv:req:def" },
    });
  });

  it("keeps an instance only when it is a request reference, and never Problem.detail", async () => {
    apiFetch.mockResolvedValueOnce(json(502, { instance: "http://internal/host", detail: "boom" }));
    const out = await attemptDetail("BTCUSDT", signal());
    expect(out).toEqual({
      kind: "failed",
      failure: { cause: "http", status: 502, instance: null },
    });
    expect(JSON.stringify(out)).not.toContain("boom");
  });

  it("is a failure for a network error, a 200 with another symbol, or a broken body", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await attemptDetail("BTCUSDT", signal())).toEqual({
      kind: "failed",
      failure: { cause: "network" },
    });
    apiFetch.mockResolvedValueOnce(json(200, { ...BODY, symbol: "ETHUSDT" }));
    expect(await attemptDetail("BTCUSDT", signal())).toMatchObject({
      kind: "failed",
      failure: { status: 200 },
    });
    apiFetch.mockResolvedValueOnce(new Response("<html>", { status: 200 }));
    expect(await attemptDetail("BTCUSDT", signal())).toEqual({
      kind: "failed",
      failure: { cause: "network" },
    });
  });

  it("drops the answer of an aborted read", async () => {
    const ctl = new AbortController();
    apiFetch.mockImplementationOnce(async () => {
      ctl.abort();
      return json(200, BODY);
    });
    expect(await attemptDetail("BTCUSDT", ctl.signal)).toBeNull();
  });
});

describe("ladderWaitS", () => {
  it("waits 2, 4, 8, 16, 30, 30 s, or what the server asked", () => {
    expect([0, 1, 2, 3, 4, 5].map((n) => ladderWaitS(n, null))).toEqual([2, 4, 8, 16, 30, 30]);
    expect(ladderWaitS(0, 9)).toBe(9);
  });
});

describe("loadInstrumentDetail", () => {
  it("retries a 503 on the ladder, reports each wait, then returns the detail", async () => {
    apiFetch
      .mockResolvedValueOnce(json(503, {}))
      .mockResolvedValueOnce(json(503, {}))
      .mockResolvedValueOnce(json(200, BODY));
    const waits: number[] = [];
    const pending = loadInstrumentDetail("BTCUSDT", signal(), {
      onLoading: (w) => waits.push(w.waitS),
    });
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(await pending).toEqual({ kind: "ok", detail: BODY });
    expect(waits).toEqual([2, 4]);
    expect(apiFetch).toHaveBeenCalledTimes(3);
  });

  it("fails as unavailable once the 503s pass 60 s, with the last instance", async () => {
    apiFetch.mockImplementation(async () => json(503, { instance: "urn:cv:req:z" }));
    const pending = loadInstrumentDetail("BTCUSDT", signal());
    await vi.advanceTimersByTimeAsync(120_000);
    expect(await pending).toEqual({
      kind: "failed",
      failure: { cause: "unavailable", instance: "urn:cv:req:z" },
    });
    // 2 + 4 + 8 + 16 + 30 = 60 s: no try is made past the mark.
    expect(apiFetch.mock.calls.length).toBeLessThanOrEqual(6);
  });

  it("never loops on a 500: one try, then the failure", async () => {
    apiFetch.mockImplementation(async () => json(500, {}));
    expect(await loadInstrumentDetail("BTCUSDT", signal())).toMatchObject({ kind: "failed" });
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("stops waiting on abort and resolves null", async () => {
    apiFetch.mockImplementation(async () => json(503, {}));
    const ctl = new AbortController();
    const pending = loadInstrumentDetail("BTCUSDT", ctl.signal);
    await vi.advanceTimersByTimeAsync(100);
    ctl.abort();
    expect(await pending).toBeNull();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });
});
