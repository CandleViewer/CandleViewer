// E24-S05 (#780): the 250 ms coalescer — bucket boundaries, the flush on the frame after a bucket closes, and
// the burst rate per 500 ms push window (D02 §6: one 500 ms push of 620 prints reads 1,240 prints/s).
import { describe, expect, it } from "vitest";
import {
  BUCKET_MS,
  bucketOf,
  LiquidationCoalescer,
} from "../../../../src/features/derivatives/liquidations/coalescer";
import type { LiquidationPrint } from "../../../../src/features/derivatives/liquidations/prints";

const prints = (n: number): LiquidationPrint[] =>
  Array.from({ length: n }, (_, k) => ({
    tsMs: 1 + k,
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

  it("reads one 620-print push as 1,240 prints/s for one push window, then 0", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(620), 1_000, true); // bucket 4
    expect(c.rateLowerBound(1_100)).toBe(0); // the bucket is still open
    expect(c.rateLowerBound(1_250)).toBe(1_240);
    expect(c.rateLowerBound(1_500)).toBe(1_240);
    expect(c.rateLowerBound(1_750)).toBe(0);
  });

  it("never counts a snapshot's replay toward the rate", () => {
    const c = new LiquidationCoalescer();
    c.add(prints(100), 0, false);
    expect(c.rateLowerBound(250)).toBe(0);
    expect(c.drain(250)).toHaveLength(100);
  });

  it("ignores an empty batch and clears everything", () => {
    const c = new LiquidationCoalescer();
    c.add([], 0, true);
    expect(c.drain(1_000)).toBeNull();
    c.add(prints(2), 0, true);
    c.clear();
    expect(c.drain(1_000)).toBeNull();
    expect(c.rateLowerBound(250)).toBe(0);
  });
});
