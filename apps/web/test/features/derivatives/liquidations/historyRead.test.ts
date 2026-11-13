// E24-S05 (#780) slice 2: the backfill read against `22` `getLiquidations` — the query, the coverage parse, the
// cursor to a bound keeping the newest prints, and every failure as a status, never a throw.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import type { LiqHistoryClock } from "../../../../src/features/derivatives/liquidations/history";
import {
  DEADLINE_MS,
  fetchLiquidationHistory,
  historyPath,
  parseCoverage,
} from "../../../../src/features/derivatives/liquidations/historyRead";
import { burst, DESIGN, EXAMPLE, EXAMPLE_COVERAGE_WIRE, restItem, restPage } from "./liqFrames";

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const FROM = Date.parse("2026-09-14T10:00:00Z");
const TO = Date.parse("2026-09-14T11:00:00Z");
const req = (over: Partial<Parameters<typeof fetchLiquidationHistory>[0]> = {}) => ({
  symbol: "BTCUSDT",
  fromMs: FROM,
  toMs: TO,
  minNotionalUsd: null,
  keep: 1_000,
  signal: new AbortController().signal,
  ...over,
});

describe("liquidation history read", () => {
  beforeEach(() => apiFetch.mockReset());

  it("builds the query 22 names: cluster_window_ms 0, the filter and the cursor only when set", () => {
    const url = new URL(historyPath(req(), null), "http://x");
    expect(url.pathname).toBe("/api/v1/market/liquidations");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: "BTCUSDT",
      from: "2026-09-14T10:00:00.000Z",
      to: "2026-09-14T11:00:00.000Z",
      limit: "500",
      cluster_window_ms: "0",
    });
    const filtered = new URL(historyPath(req({ minNotionalUsd: "50000" }), "c1"), "http://x");
    expect(filtered.searchParams.get("min_notional_usd")).toBe("50000");
    expect(filtered.searchParams.get("cursor")).toBe("c1");
  });

  it("parses the 22 example's coverage and refuses a malformed one", () => {
    expect(parseCoverage({ coverage: EXAMPLE_COVERAGE_WIRE })).toEqual({
      firstAvailableMs: Date.parse("2026-09-01T00:00:00.250Z"),
      coveredFromMs: FROM,
      coveredToMs: TO,
      noCoverage: false,
    });
    const never = {
      first_available_ts: null,
      covered_from: null,
      covered_to: null,
      no_coverage: true,
    };
    expect(parseCoverage({ coverage: never })?.firstAvailableMs).toBeNull();
    expect(parseCoverage({ coverage: { ...never, no_coverage: "yes" } })).toBeNull();
    expect(parseCoverage({ coverage: { ...never, covered_from: "soon" } })).toBeNull();
    expect(parseCoverage({})).toBeNull();
  });

  it("reads one page into ascending prints with the coverage, counting malformed items", async () => {
    apiFetch.mockResolvedValueOnce(
      json(200, restPage([restItem(DESIGN), restItem(EXAMPLE), { ...restItem(EXAMPLE), size: 3 }])),
    );
    const out = await fetchLiquidationHistory(req());
    expect(apiFetch).toHaveBeenCalledTimes(1);
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.prints.map((p) => p.price)).toEqual(["62880.00", "82751.20"]);
    expect(out.prints[0]?.side).toBe("long");
    expect(out.coverage.noCoverage).toBe(false);
    expect(out.malformed).toBe(1);
    expect(out.truncated).toBeNull();
  });

  it("follows next_cursor within an attempt and keeps the newest `keep` prints, ascending", async () => {
    apiFetch
      .mockResolvedValueOnce(
        json(200, restPage([restItem(DESIGN)], { has_more: true, next_cursor: "c1" })),
      )
      .mockResolvedValueOnce(json(200, restPage([restItem(EXAMPLE)])));
    const out = await fetchLiquidationHistory(req({ keep: 4 }));
    expect(new URL(apiFetch.mock.calls[1]?.[0] ?? "", "http://x").searchParams.get("cursor")).toBe(
      "c1",
    );
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.prints.map((p) => p.price)).toEqual(["62880.00", "82751.20"]);
    expect(out.truncated).toBeNull();
  });

  it("relies on the ascending order: a read stopped by its bound is narrowed from `to`, older end disclosed", async () => {
    const full = (n: number) =>
      restPage(burst(n).map(restItem), { has_more: true, next_cursor: "c" });
    apiFetch
      .mockResolvedValueOnce(json(200, full(3))) // attempt 1: the oldest prints, still more
      .mockResolvedValueOnce(
        // the narrowed attempt reports its own, narrower coverage; the full window's is the one kept (#5764 U1)
        json(
          200,
          restPage(burst(2, EXAMPLE, TO - 10).map(restItem), {
            coverage: { ...EXAMPLE_COVERAGE_WIRE, covered_from: "2026-09-14T10:45:00Z" },
          }),
        ),
      );
    const out = await fetchLiquidationHistory(req({ maxPages: 1 }));
    const second = new URL(apiFetch.mock.calls[1]?.[0] ?? "", "http://x").searchParams;
    expect(second.get("from")).toBe(new Date(TO - (TO - FROM) / 4).toISOString());
    expect(second.get("cursor")).toBeNull();
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.prints.map((p) => p.tsMs)).toEqual([TO - 10, TO - 9]); // the newest end, next to live
    expect(out.truncated).toEqual({ side: "older", atMs: TO - (TO - FROM) / 4 });
    expect(out.coverage.coveredFromMs).toBe(FROM); // the full window's coverage
  });

  it("says the newer end is missing when the last attempt is still bounded", async () => {
    // a fresh Response per call: a body reads once
    apiFetch.mockImplementation(async () =>
      json(200, restPage([restItem(EXAMPLE)], { has_more: true, next_cursor: "c" })),
    );
    const out = await fetchLiquidationHistory(req({ maxPages: 1, maxAttempts: 2 }));
    expect(apiFetch).toHaveBeenCalledTimes(2);
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.truncated).toEqual({ side: "newer", atMs: EXAMPLE.ts_ms });
  });

  it("fails without a status when its deadline fires, and lets go of the caller's signal", async () => {
    let fire: () => void = () => undefined;
    const clock: LiqHistoryClock = {
      setTimeout: (run) => {
        fire = run;
        return 1;
      },
      clearTimeout: () => undefined,
    };
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_ok, fail) => {
          init?.signal?.addEventListener("abort", () =>
            fail(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const caller = new AbortController();
    const removed = vi.spyOn(caller.signal, "removeEventListener");
    const pending = fetchLiquidationHistory(req({ clock, signal: caller.signal }));
    await Promise.resolve();
    fire();
    expect(await pending).toEqual({ kind: "failed", status: null, code: null });
    expect(removed).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("returns the status and code of a refusal", async () => {
    apiFetch.mockResolvedValueOnce(json(503, { code: "store_unavailable" }));
    expect(await fetchLiquidationHistory(req())).toEqual({
      kind: "failed",
      status: 503,
      code: "store_unavailable", // the contract's code (`22`); T03's `service_unavailable` is #5273's drift
    });
  });

  it("fails as malformed when the page lacks items or coverage", async () => {
    apiFetch.mockResolvedValueOnce(json(200, { items: [], meta: { has_more: false } }));
    expect(await fetchLiquidationHistory(req())).toEqual({
      kind: "failed",
      status: 200,
      code: "malformed",
    });
  });

  it("says the older end at the oldest kept print when `keep` drops read prints (#5764 U2)", async () => {
    apiFetch.mockResolvedValueOnce(json(200, restPage(burst(3).map(restItem))));
    const out = await fetchLiquidationHistory(req({ keep: 2 }));
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.prints.map((p) => p.tsMs)).toEqual([EXAMPLE.ts_ms + 1, EXAMPLE.ts_ms + 2]);
    expect(out.truncated).toEqual({ side: "older", atMs: EXAMPLE.ts_ms + 1 });
  });

  it("stops on has_more false even with a cursor, and on a missing cursor even with has_more (#5764 U4)", async () => {
    apiFetch.mockResolvedValueOnce(
      json(200, restPage([restItem(EXAMPLE)], { has_more: false, next_cursor: "c1" })),
    );
    expect((await fetchLiquidationHistory(req())).kind).toBe("ok");
    expect(apiFetch).toHaveBeenCalledTimes(1);
    apiFetch.mockResolvedValueOnce(
      json(200, restPage([restItem(EXAMPLE)], { has_more: true, next_cursor: null })),
    );
    const out = await fetchLiquidationHistory(req());
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(out.kind === "ok" && out.truncated).toBeNull();
  });

  it("makes at most 12 GETs: 2 pages × 6 narrowing attempts (#5764 U4)", async () => {
    apiFetch.mockImplementation(async () =>
      json(200, restPage([restItem(EXAMPLE)], { has_more: true, next_cursor: "c" })),
    );
    await fetchLiquidationHistory(req());
    expect(apiFetch).toHaveBeenCalledTimes(12);
  });

  it("fails without a status when the caller aborts mid-read, and sends nothing more (#5764 U4)", async () => {
    const caller = new AbortController();
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_ok, fail) => {
          init?.signal?.addEventListener("abort", () =>
            fail(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const pending = fetchLiquidationHistory(req({ signal: caller.signal }));
    await Promise.resolve();
    caller.abort();
    expect(await pending).toEqual({ kind: "failed", status: null, code: null });
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("fails with no status on a network error, and reads nothing once aborted", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("network"));
    expect(await fetchLiquidationHistory(req())).toEqual({
      kind: "failed",
      status: null,
      code: null,
    });
    const call = new AbortController();
    call.abort();
    expect((await fetchLiquidationHistory(req({ signal: call.signal }))).kind).toBe("failed");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("arms a deadline and clears it", async () => {
    const armed: number[] = [];
    const cleared: unknown[] = [];
    const clock: LiqHistoryClock = {
      setTimeout: (_run, ms) => (armed.push(ms), 7),
      clearTimeout: (id) => void cleared.push(id),
    };
    apiFetch.mockResolvedValueOnce(json(200, restPage([])));
    await fetchLiquidationHistory(req({ clock }));
    expect(armed).toEqual([DEADLINE_MS]);
    expect(cleared).toEqual([7]);
  });
});
