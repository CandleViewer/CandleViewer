// E24-S05 (#780): the feed core's edges carried from #5763's review (6625587347 (a)–(e)) — the zero and over-long
// filter, the same-millisecond dedupe in its four shapes, the coalescer's literal 750 ms hold and 620-print push,
// the external store's identity and unsubscribe, and a rejected read.
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  LiquidationCoalescer,
  RATE_HOLD_MS,
} from "../../../../src/features/derivatives/liquidations/coalescer";
import type { LiqHistoryResult } from "../../../../src/features/derivatives/liquidations/history";
import {
  feedFilter,
  INITIAL_LIQ_SNAPSHOT,
  startLiquidationFeed,
  useLiqSnapshot,
  type LiqFeedOptions,
} from "../../../../src/features/derivatives/liquidations/liquidationFeed";
import type { LiquidationPrint } from "../../../../src/features/derivatives/liquidations/prints";
import { fakeClient, fakeDisplay } from "../../tape/fakeFeed";
import { delta, DESIGN, EXAMPLE, snap } from "./liqFrames";

const never = (): Promise<LiqHistoryResult> => new Promise(() => undefined);
const settle = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};
const frames = (d: { frame: () => void }, n = 6): void => {
  for (let f = 0; f < n; f += 1) d.frame();
};

function start(over: Partial<LiqFeedOptions> = {}) {
  const fake = fakeClient();
  const d = fakeDisplay(50);
  const feed = startLiquidationFeed(fake.client, {
    symbol: "BTCUSDT",
    paneId: "liq",
    window: { fromMs: 0, toMs: Date.parse("2026-10-22T00:00:00Z") },
    loadHistory: never,
    clock: { ...d.clock, wallNow: () => 0 },
    ...over,
  });
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no handle");
  handle.status = "live";
  return { ...fake, d, feed, handle };
}

/** The prints the ring holds. */
const held = (feed: { metrics: () => { held: number } }): number => feed.metrics().held;

describe("the filter (#5763 (a))", () => {
  it("treats a zero floor as no filter: not sent, not stated", () => {
    expect(feedFilter("0")).toBeNull();
    expect(feedFilter("0.00")).toBeNull();
    expect(feedFilter("50000")).toBe("50000");
    const { specs, feed } = start({ minNotionalUsd: "0" });
    expect(specs[0]?.opts).toEqual({ cluster_window_ms: 0 });
    expect(feed.getSnapshot().minNotionalUsd).toBeNull();
  });

  it("refuses a value over 32 characters, which the server would refuse as invalid_options", () => {
    expect(() => start({ minNotionalUsd: "1".repeat(30) + ".1" })).not.toThrow(); // 32
    expect(() => start({ minNotionalUsd: "1".repeat(30) + ".12" })).toThrow(RangeError); // 33
  });
});

describe("same-millisecond dedupe (#5763 (b))", () => {
  const Y = { ...DESIGN, price: "82751.30" }; // another print in X's millisecond

  it("a replay [Y, X] with X held keeps Y and drops X", () => {
    const { d, handle, feed } = start();
    handle.queue.push(snap([DESIGN]));
    frames(d);
    handle.queue.push(snap([Y, DESIGN]));
    frames(d);
    expect(held(feed)).toBe(2);
  });

  it("a replay [X, X] with one X held keeps the second X", () => {
    const { d, handle, feed } = start();
    handle.queue.push(snap([DESIGN]));
    frames(d);
    handle.queue.push(snap([DESIGN, DESIGN]));
    frames(d);
    expect(held(feed)).toBe(2);
  });

  it("a recorded X with live [X, X] keeps one live X", async () => {
    let resolve: (r: LiqHistoryResult) => void = () => undefined;
    const loadHistory = () =>
      new Promise<LiqHistoryResult>((ok) => {
        resolve = ok;
      });
    const { d, handle, feed } = start({ loadHistory });
    handle.queue.push(delta([DESIGN, DESIGN]));
    d.frame();
    resolve(recorded([DESIGN]));
    await settle();
    frames(d);
    expect(held(feed)).toBe(2);
  });

  it("live prints already in the ring when the read returns are merged once, after the recorded ones", async () => {
    let resolve: (r: LiqHistoryResult) => void = () => undefined;
    const loadHistory = () =>
      new Promise<LiqHistoryResult>((ok) => {
        resolve = ok;
      });
    const { d, handle, feed } = start({ loadHistory });
    const newer = { ...DESIGN, ts_ms: DESIGN.ts_ms + 1_000 };
    handle.queue.push(delta([DESIGN, newer]));
    frames(d); // flushed into the ring before the read answers
    resolve(recorded([EXAMPLE, DESIGN]));
    await settle();
    frames(d);
    expect(held(feed)).toBe(3);
    expect(feed.getSnapshot().rows.map((r) => r.tsMs)).toEqual([
      newer.ts_ms,
      DESIGN.ts_ms,
      EXAMPLE.ts_ms,
    ]);
  });
});

/** A recorded read of these wire items (all `sell`: long liquidated). */
function recorded(items: readonly (typeof DESIGN)[]): LiqHistoryResult {
  return {
    kind: "ok",
    prints: items.map((w): LiquidationPrint => ({
      tsMs: w.ts_ms,
      side: "long",
      price: w.price,
      size: w.size,
      notionalUsd: w.notional_usd ?? null,
      clusterSize: w.cluster_size ?? 1,
    })),
    coverage: { firstAvailableMs: 1, coveredFromMs: 2, coveredToMs: 3, noCoverage: false },
    truncated: null,
    malformed: 0,
  };
}

describe("the coalescer's literal figures (#5763 (c))", () => {
  it("holds 750 ms, and reads 620 prints in 100 ms as 1,240 prints/s", () => {
    expect(RATE_HOLD_MS).toBe(750);
    const c = new LiquidationCoalescer();
    const prints: LiquidationPrint[] = Array.from({ length: 620 }, (_, k) => ({
      tsMs: 50_000 + Math.floor((k * 100) / 620),
      side: "long",
      price: "82500.00",
      size: "0.080",
      notionalUsd: "6600.00",
      clusterSize: 1,
    }));
    c.add(prints, 1_000, true);
    expect(c.rateLowerBound(1_000)).toBe(1_240);
    expect(c.rateLowerBound(1_750)).toBe(1_240);
    expect(c.rateLowerBound(1_751)).toBe(0);
  });
});

describe("the external store (#5763 (d))", () => {
  it("keeps the snapshot's identity until a publish, and an unsubscribed listener hears nothing", () => {
    const { d, handle, feed } = start();
    d.frame(); // the first frame publishes the read's loading state
    const before = feed.getSnapshot();
    d.frame();
    expect(feed.getSnapshot()).toBe(before); // nothing changed: the same object
    const heard = vi.fn();
    const off = feed.subscribe(heard);
    off();
    handle.queue.push(delta([EXAMPLE]));
    frames(d);
    expect(feed.getSnapshot()).not.toBe(before);
    expect(heard).not.toHaveBeenCalled();
  });

  it("useLiqSnapshot reads the feed and re-renders on a publish; without a feed it is the initial snapshot", () => {
    const { d, handle, feed } = start();
    const { result } = renderHook(() => useLiqSnapshot(feed));
    handle.queue.push(delta([EXAMPLE]));
    act(() => frames(d));
    expect(result.current.rows).toHaveLength(1);
    expect(renderHook(() => useLiqSnapshot(null)).result.current).toBe(INITIAL_LIQ_SNAPSHOT);
  });
});

describe("a rejected read (#5763 (e))", () => {
  it("is a failed read, never an unhandled rejection or a stuck loading", async () => {
    const { d, feed } = start({ loadHistory: () => Promise.reject(new Error("boom")) });
    await settle();
    d.frame();
    expect(feed.getSnapshot().history).toEqual({
      phase: "failed",
      status: null,
      lastSuccessAtMs: null,
    });
  });
});
