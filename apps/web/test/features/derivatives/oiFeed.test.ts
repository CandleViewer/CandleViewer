// E24-S01 (#776) slice 1: the OI feed loop — backfill then live without a refetch, rAF coalescing, the
// ≤ 1 Hz value publish, stale T1 / T2 (BQ 3), the failed-backfill gap and retry, and teardown.
import { describe, expect, it, vi } from "vitest";
import type { HistoryRequest, HistoryResult } from "../../../src/features/derivatives/oi/history";
import {
  parseCoverage,
  parsePoint,
  type HistoryPoint,
} from "../../../src/features/derivatives/oi/history";
import {
  startOiFeed,
  type OiClock,
  type OiFeedOptions,
} from "../../../src/features/derivatives/oi/oiFeed";
import { fakeClient } from "../tape/fakeFeed";
import {
  coverageOf,
  recordedRestPoints,
  recordedTickerItems,
  tickerDelta,
  tickerReset,
  tickerSnap,
  type TickerItem,
} from "./support/oiFixtures";

const MIN = 60_000;
const WALL = Date.parse("2026-10-20T09:14:02Z");
const REST = recordedRestPoints();
const POINTS = REST.map(parsePoint).filter((p): p is HistoryPoint => p !== null);
const COVERAGE = parseCoverage({ coverage: coverageOf(REST) });
if (COVERAGE === null) throw new Error("coverage fixture");
const ITEMS = recordedTickerItems();
const item = (i: number, over: Partial<TickerItem> = {}): TickerItem => {
  const it = ITEMS[i % ITEMS.length];
  if (it === undefined) throw new Error("ticker fixture");
  return { ...it, ...over };
};

function display() {
  const requested = new Map<number, () => void>();
  let id = 0;
  let nowMs = 0;
  const clock: OiClock = {
    raf: (cb) => (requested.set(++id, () => cb(nowMs)), id),
    caf: (h) => void requested.delete(h),
    now: () => nowMs,
    wallNow: () => WALL + nowMs,
  };
  return {
    clock,
    pending: () => requested.size,
    frame: (advanceMs = 16) => {
      nowMs += advanceMs;
      const due = [...requested.values()];
      requested.clear();
      for (const cb of due) cb();
    },
  };
}

const ok: HistoryResult = {
  kind: "ok",
  points: POINTS,
  coverage: COVERAGE,
  truncated: null,
  malformed: 0,
};

function start(results: HistoryResult[] = [ok], over: Partial<OiFeedOptions> = {}) {
  const fake = fakeClient();
  const d = display();
  const requests: HistoryRequest[] = [];
  const loadHistory = vi.fn(async (req: HistoryRequest) => {
    requests.push(req);
    return results.shift() ?? ok;
  });
  const analytics = {
    metricToggled: vi.fn(),
    intervalChanged: vi.fn(),
    backfillFailed: vi.fn(),
    backfillAnomaly: vi.fn(),
  };
  const feed = startOiFeed(fake.client, {
    symbol: "BTCUSDT",
    paneId: "oi-1",
    barMs: 5 * MIN,
    window: { fromMs: POINTS[0]?.tMs ?? 0, toMs: (ITEMS[0]?.ts_ms ?? 0) + MIN },
    loadHistory,
    clock: d.clock,
    analytics,
    ...over,
  });
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no handle");
  return { ...fake, d, feed, handle, loadHistory, requests, analytics };
}

const settle = async (): Promise<void> => {
  await Promise.resolve();
  await Promise.resolve();
};

describe("OI feed", () => {
  it("subscribes once to ticker.{symbol} and refuses a symbol or bar it cannot serve", () => {
    const { specs } = start();
    expect(specs).toEqual([{ ch: "ticker.BTCUSDT", paneId: "oi-1", priority: "other" }]);
    const fake = fakeClient();
    const base = { paneId: "p", window: { fromMs: 0, toMs: 1 }, loadHistory: vi.fn() };
    expect(() => startOiFeed(fake.client, { ...base, symbol: "BTCUSD", barMs: MIN })).toThrow(
      RangeError,
    );
    expect(() => startOiFeed(fake.client, { ...base, symbol: "BTCUSDT", barMs: 0 })).toThrow(
      RangeError,
    );
    expect(fake.client.consume).not.toHaveBeenCalled();
  });

  it("backfills once, then extends live from the ticker without a refetch", async () => {
    const { d, feed, handle, loadHistory, requests } = start();
    expect(requests[0]).toMatchObject({ symbol: "BTCUSDT", interval: "5min" });
    await settle();
    d.frame();
    expect(feed.getSnapshot().history).toEqual({ phase: "ready", empty: false, truncated: null });
    expect(feed.getSnapshot().rows).toHaveLength(POINTS.length);
    handle.queue.push(tickerSnap([item(0)]));
    expect(feed.getSnapshot().latest?.source).toBe("rest"); // nothing applied on arrival
    d.frame(MIN);
    expect(feed.getSnapshot().latest).toMatchObject({ source: "ws_ticker", base: "57911.602" });
    handle.queue.push(tickerDelta([item(19)]));
    d.frame(MIN);
    expect(loadHistory).toHaveBeenCalledTimes(1);
  });

  it("publishes a value change at most once a second, a state change at once", async () => {
    const { d, feed, handle } = start();
    await settle();
    d.frame();
    const listener = vi.fn();
    feed.subscribe(listener);
    handle.queue.push(tickerSnap([item(0)]));
    d.frame(1000);
    expect(listener).toHaveBeenCalledTimes(1);
    handle.queue.push(
      tickerDelta([item(0, { open_interest: "57912.000", ts_ms: item(0).ts_ms + 300 })]),
    );
    d.frame(300);
    expect(listener).toHaveBeenCalledTimes(1); // held
    d.frame(700);
    expect(listener).toHaveBeenCalledTimes(2);
    expect(feed.getSnapshot().latest?.base).toBe("57912.000");
    handle.status = "resyncing";
    d.frame();
    expect(listener).toHaveBeenCalledTimes(3);
    expect(feed.getSnapshot().feed).toBe("resyncing");
  });

  it("goes stale at 5 s (T1), escalates at 15 s (T2) and clears on the next update", async () => {
    const { d, feed, handle } = start();
    await settle();
    handle.queue.push(tickerSnap([item(0)]));
    d.frame();
    expect(feed.getSnapshot().stale.tier).toBe("fresh");
    d.frame(4_999);
    expect(feed.getSnapshot().stale.tier).toBe("fresh");
    d.frame(1);
    expect(feed.getSnapshot().stale).toEqual({ tier: "t1", ageMs: 5_000, lastTsMs: item(0).ts_ms });
    d.frame(2_000);
    expect(feed.getSnapshot().stale.ageMs).toBe(7_000);
    d.frame(8_000);
    expect(feed.getSnapshot().stale.tier).toBe("t2");
    handle.queue.push(tickerDelta([item(1)]));
    d.frame();
    expect(feed.getSnapshot().stale.tier).toBe("fresh");
  });

  it("routes a rejected or throwing read to the failed state, never stuck loading", async () => {
    for (const loadHistory of [
      vi.fn(async (): Promise<HistoryResult> => {
        throw new Error("boom");
      }),
      vi.fn((): Promise<HistoryResult> => {
        throw new Error("sync boom");
      }),
    ]) {
      const fake = fakeClient();
      const d = display();
      const analytics = {
        metricToggled: vi.fn(),
        intervalChanged: vi.fn(),
        backfillFailed: vi.fn(),
        backfillAnomaly: vi.fn(),
      };
      const feed = startOiFeed(fake.client, {
        symbol: "BTCUSDT",
        paneId: "oi",
        barMs: MIN,
        window: { fromMs: 0, toMs: 1 },
        loadHistory,
        clock: d.clock,
        analytics,
      });
      await settle();
      d.frame();
      expect(feed.getSnapshot().history).toEqual({
        phase: "failed",
        status: null,
        lastSuccessAtMs: null,
      });
      expect(feed.getSnapshot().gaps.map((g) => g.kind)).toEqual(["failed"]);
      expect(analytics.backfillFailed).toHaveBeenCalledWith("BTCUSDT", null, "exception");
      feed.stop();
    }
  });

  it("goes stale on a stream that never delivers, counting from the start", async () => {
    const { d, feed } = start();
    await settle();
    d.frame(4_000);
    expect(feed.getSnapshot().stale.tier).toBe("fresh");
    d.frame(1_000);
    expect(feed.getSnapshot().stale).toEqual({ tier: "t1", ageMs: 5_000, lastTsMs: null });
    d.frame(10_000);
    expect(feed.getSnapshot().stale.tier).toBe("t2");
  });

  it("reads a served stale flag as T2", async () => {
    const { d, feed, handle } = start();
    await settle();
    handle.queue.push(tickerSnap([item(0, { stale: true })]));
    d.frame();
    expect(feed.getSnapshot().stale.tier).toBe("t2");
  });

  it("reports a server contract breach the read survived once per read, through the analytics seam", async () => {
    const loadHistory = vi.fn(async (req: HistoryRequest): Promise<HistoryResult> => {
      req.onAnomaly?.("cursor_missing");
      return { ...ok, truncated: "newer" };
    });
    const { feed, analytics } = start([], { loadHistory });
    await settle();
    expect(analytics.backfillAnomaly).toHaveBeenCalledTimes(1);
    expect(analytics.backfillAnomaly).toHaveBeenCalledWith("BTCUSDT", "cursor_missing");
    expect(analytics.backfillFailed).not.toHaveBeenCalled();
    feed.retry();
    await settle();
    expect(analytics.backfillAnomaly).toHaveBeenCalledTimes(2); // a new read, a new count
    feed.stop();
  });

  it("does not report an anomaly from a read that was stopped or superseded", async () => {
    let seen: HistoryRequest | undefined;
    const loadHistory = vi.fn(async (req: HistoryRequest): Promise<HistoryResult> => {
      seen = req;
      await Promise.resolve();
      return ok;
    });
    const { feed, analytics } = start([], { loadHistory });
    feed.stop();
    seen?.onAnomaly?.("cursor_missing");
    expect(analytics.backfillAnomaly).not.toHaveBeenCalled();
  });

  it("survives a throwing analytics sink and still publishes the failed state", async () => {
    const failed: HistoryResult = { kind: "failed", status: 503, code: "x" };
    const { d, feed, analytics } = start([failed]);
    analytics.backfillFailed.mockImplementation(() => {
      throw new Error("sink");
    });
    await settle();
    d.frame();
    expect(feed.getSnapshot().history.phase).toBe("failed");
    feed.stop();
  });

  it("keeps live streaming through a failed backfill, gaps the history and retries", async () => {
    const failed: HistoryResult = { kind: "failed", status: 503, code: "service_unavailable" };
    const { d, feed, handle, analytics, loadHistory } = start([failed, ok, failed]);
    await settle();
    handle.queue.push(tickerSnap([item(0)]));
    d.frame();
    const snap = feed.getSnapshot();
    expect(snap.history).toEqual({ phase: "failed", status: 503, lastSuccessAtMs: null });
    expect(snap.latest?.source).toBe("ws_ticker");
    expect(snap.gaps.map((g) => g.kind)).toEqual(["failed"]);
    expect(analytics.backfillFailed).toHaveBeenCalledWith("BTCUSDT", 503, "service_unavailable");

    feed.retry();
    d.frame();
    expect(feed.getSnapshot().history).toEqual({ phase: "loading" });
    await settle();
    d.frame();
    expect(feed.getSnapshot().history.phase).toBe("ready");
    expect(feed.getSnapshot().gaps).toEqual([]);
    const succeededAt = WALL + 2 * 16; // the read resolved before the third frame

    feed.retry();
    await settle();
    d.frame();
    expect(feed.getSnapshot().history).toEqual({
      phase: "failed",
      status: 503,
      lastSuccessAtMs: succeededAt,
    });
    expect(loadHistory).toHaveBeenCalledTimes(3);
    expect(analytics.backfillFailed).toHaveBeenCalledTimes(2); // a retry counts again
  });

  it("draws a seam after a reset", async () => {
    const { d, feed, handle } = start();
    await settle();
    handle.queue.push(tickerSnap([item(0)]), tickerReset, tickerSnap([item(1)]));
    d.frame();
    expect(feed.getSnapshot().gaps).toEqual([
      { fromMs: item(0).ts_ms, toMs: item(1).ts_ms, kind: "live" },
    ]);
  });

  it("shows the native-granularity note on a bar finer than the history", async () => {
    const fine = start([ok], { barMs: MIN });
    await settle();
    fine.d.frame();
    expect(fine.feed.getSnapshot().note).toBe("Native granularity 5 min");
    const coarse = start();
    await settle();
    coarse.d.frame();
    expect(coarse.feed.getSnapshot().note).toBeNull();
  });

  it("tears down: releases the topic once, stops the loop, ignores a late read", async () => {
    let resolve: ((r: HistoryResult) => void) | undefined;
    const fake = fakeClient();
    const d = display();
    const feed = startOiFeed(fake.client, {
      symbol: "BTCUSDT",
      paneId: "oi-1",
      barMs: MIN,
      window: { fromMs: 0, toMs: 1 },
      loadHistory: (req) =>
        new Promise((res) => {
          resolve = res;
          req.signal.addEventListener("abort", () => undefined);
        }),
      clock: d.clock,
    });
    const listener = vi.fn();
    feed.subscribe(listener);
    feed.stop();
    feed.stop();
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(d.pending()).toBe(0);
    resolve?.(ok);
    await settle();
    d.frame();
    expect(listener).not.toHaveBeenCalled();
    expect(feed.getSnapshot().history).toEqual({ phase: "loading" });
    feed.retry();
    expect(feed.getSnapshot().history).toEqual({ phase: "loading" });
  });
});
