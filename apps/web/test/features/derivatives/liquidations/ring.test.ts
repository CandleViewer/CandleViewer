// E24-S05 (#780): the bounded ring — eviction by index, newest-first views, monotonic seq.
import { describe, expect, it } from "vitest";
import {
  LIQ_RING_CAPACITY,
  LiquidationRing,
} from "../../../../src/features/derivatives/liquidations/ring";
import type { LiquidationPrint } from "../../../../src/features/derivatives/liquidations/prints";

const print = (tsMs: number): LiquidationPrint => ({
  tsMs,
  side: "long",
  price: "62880.00",
  size: "3.220",
  notionalUsd: "202473.60",
  clusterSize: 1,
});

describe("LiquidationRing", () => {
  it("holds 1,000 prints by default (BQ 7, ruled 6612481277)", () => {
    expect(new LiquidationRing().capacity).toBe(LIQ_RING_CAPACITY);
    expect(LIQ_RING_CAPACITY).toBe(1_000);
  });

  it("evicts the oldest once full and keeps seq monotonic", () => {
    const ring = new LiquidationRing(3);
    for (let i = 1; i <= 5; i += 1) ring.push(print(i));
    expect(ring.length).toBe(3);
    expect(ring.nextSeq).toBe(5);
    expect(ring.all().map((p) => p.tsMs)).toEqual([3, 4, 5]);
    expect(ring.newest(2).map((p) => p.seq)).toEqual([4, 3]);
    expect(ring.newestTsMs).toBe(5);
  });

  it("returns fewer than asked when it holds fewer, and empties on clear", () => {
    const ring = new LiquidationRing(4);
    ring.push(print(1));
    expect(ring.newest(40)).toHaveLength(1);
    ring.clear();
    expect(ring.length).toBe(0);
    expect(ring.newestTsMs).toBeNull();
    expect(ring.push(print(2)).seq).toBe(1);
  });

  it("refuses a capacity that is not a positive integer", () => {
    expect(() => new LiquidationRing(0)).toThrow(RangeError);
    expect(() => new LiquidationRing(1.5)).toThrow(RangeError);
  });
});
