// E24-S05 (#780): the 250 ms coalescer — bucket boundaries, the flush on the frame after a bucket closes, and
// the burst rate per 500 ms push window on the prints' own times (D02 §6: one 500 ms push of 620 prints reads
// 1,240 prints/s), held through frame jitter and never inflated by a backlog read at once.
import { describe, expect, it } from "vitest";
import {
  BUCKET_MS,
  RATE_HOLD_MS,
  bucketOf,
  LiquidationCoalescer,
} from "../../../../src/features/derivatives/liquidations/coalescer";
import type { LiquidationPrint } from "../../../../src/features/derivatives/liquidations/prints";

/** `n` prints spread over one 500 ms push window starting at `fromTs`. */
const prints = (n: number, fromTs = 1): LiquidationPrint[] =>
  Array.from({ length: n }, (_, k) => ({
    tsMs: fromTs + Math.floor((k * 499) / Math.max(1, n)),
    side: "long",
    price: "82500.00",
    size: "0.080",
    notionalUsd: "6600.00",
    clusterSize: 1,
  }));

describe("bucketOf", () => {
  it("cuts [k·250, (k+1)·250)", () => {
    expect(bucketOf(0)).toBe(0);
    expect(bucketOf(BUCKET_MS - 1)).toBe(0);
    expect(bucketOf(BUCKET_MS)).toBe(1);
  });
});

describe("LiquidationCoalescer", () => {
  it("holds prints until the frame after their bucket closes", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(3), 10, true);
    c.add(prints(2), 240, true);
    expect(c.drain(249)).toBeNull();
    expect(c.drain(250)).toHaveLength(5);
    expect(c.drain(260)).toBeNull();
    expect(c.flushed).toBe(1);
  });

  it("flushes a late frame's whole backlog at once (render work follows the bucket clock)", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(1), 100, true);
    c.add(prints(1), 400, true); // the frame that should have flushed bucket 0 never ran
    expect(c.drain(900)).toHaveLength(2);
  });

  it("reads one 620-print push as 1,240 prints/s, holds it one window plus a bucket, then 0", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(620, 10_000), 1_000, true);
    expect(c.rateLowerBound(1_000)).toBe(1_240);
    expect(c.rateLowerBound(1_000 + RATE_HOLD_MS)).toBe(1_240);
    expect(c.rateLowerBound(1_001 + RATE_HOLD_MS)).toBe(0);
  });

  it("holds the rate through frame jitter between pushes", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(250, 10_000), 1_000, true);
    c.add(prints(250, 10_500), 1_700, true); // the frame carrying the next push came 700 ms later
    expect(c.rateLowerBound(1_650)).toBe(500);
    expect(c.rateLowerBound(1_700)).toBe(500);
  });

  it("does not count a hidden tab's backlog as one burst: the newest push window only", () => {
    const c = new LiquidationCoalescer();
    const backlog = Array.from({ length: 10 }, (_, k) => prints(620, 10_000 + k * 500)).flat();
    c.add(backlog, 60_000, true); // ten pushes, read in one frame
    expect(c.rateLowerBound(60_000)).toBe(1_240);
  });

  it("never counts a snapshot's replay toward the rate", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(100), 0, false);
    expect(c.rateLowerBound(0)).toBe(0);
    expect(c.drain(250)).toHaveLength(100);
  });

  it("ignores an empty batch and clears everything", () => {
    const c = new LiquidationCoalescer();
    c.add([], 0, true);
    expect(c.drain(1_000)).toBeNull();
    c.add(prints(2), 0, true);
    c.clear();
    expect(c.drain(1_000)).toBeNull();
    expect(c.rateLowerBound(0)).toBe(0);
  });
});
