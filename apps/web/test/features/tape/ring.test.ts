// E22-S01 (#714) PR-A: the struct-of-arrays ring (scout §4.3, S01-u-07, S22).
import { describe, expect, it } from "vitest";
import {
  FLAG_BIG,
  FLAG_SEAM,
  SIDE_SELL,
  TAPE_RING_CAPACITY,
  TAPE_RING_MAX_CAPACITY,
  TapeRing,
  type PrintInput,
} from "../../../src/features/tape/model/ring";

const print = (n: number, over: Partial<PrintInput> = {}): PrintInput => ({
  id: `t${n}`,
  tsMs: 1_000 + n,
  price: "65000.5",
  size: "0.25",
  side: SIDE_SELL,
  flags: 0,
  clusterSize: 1,
  ...over,
});

const fill = (ring: TapeRing, from: number, to: number): void => {
  for (let n = from; n <= to; n += 1) ring.push(print(n));
};

describe("tape ring", () => {
  it("holds 10 000 prints by default and refuses a capacity outside 1 to 50 000", () => {
    expect(new TapeRing().capacity).toBe(TAPE_RING_CAPACITY);
    expect(TAPE_RING_CAPACITY).toBe(10_000);
    expect(() => new TapeRing(0)).toThrow(RangeError);
    expect(() => new TapeRing(TAPE_RING_MAX_CAPACITY + 1)).toThrow(RangeError);
    expect(() => new TapeRing(2.5)).toThrow(RangeError);
  });

  it("stores each field in its typed array under a monotonic seq", () => {
    const ring = new TapeRing(4);
    const seq = ring.push(print(7, { flags: FLAG_BIG, clusterSize: 3 }));
    expect(seq).toBe(0);
    const i = ring.slot(0);
    expect([ring.tsMs[i], ring.price[i], ring.size[i], ring.side[i]]).toEqual([
      1007, 65000.5, 0.25, 1,
    ]);
    expect([ring.flags[i], ring.clusterSize[i]]).toEqual([FLAG_BIG, 3]);
    expect([ring.id(0), ring.priceText(0), ring.sizeText(0)]).toEqual(["t7", "65000.5", "0.25"]);
    expect([ring.length, ring.oldestSeq, ring.nextSeq]).toEqual([1, 0, 1]);
  });

  it("evicts the oldest by an index move when full, and forgets its id", () => {
    const ring = new TapeRing(3);
    fill(ring, 1, 5);
    expect([ring.length, ring.oldestSeq, ring.nextSeq]).toEqual([3, 2, 5]);
    expect(ring.hasId("t2")).toBe(false);
    expect(ring.hasId("t3")).toBe(true);
    expect(ring.has(1)).toBe(false);
    expect([ring.id(1), ring.priceText(1), ring.sizeText(1)]).toEqual([undefined, "", ""]);
    expect(ring.id(4)).toBe("t5");
  });

  it("never evicts a pinned print: a full ring refuses and counts the new one (S01-u-07, S22)", () => {
    const ring = new TapeRing(3);
    fill(ring, 1, 3);
    ring.pin(1); // the focused print, seq 1
    expect(ring.push(print(4))).toBe(3); // seq 0 is older than the pin: evicted
    expect(ring.push(print(5))).toBeNull(); // seq 1 is now the oldest and pinned
    expect(ring.push(print(6))).toBeNull();
    expect([ring.notKept, ring.has(1), ring.id(1)]).toEqual([2, true, "t2"]);
    ring.unpin(1);
    expect(ring.push(print(7))).toBe(4);
    expect(ring.has(1)).toBe(false);
  });

  it("ignores a pin on an evicted or unheld seq, so the ring keeps accepting prints", () => {
    const ring = new TapeRing(2);
    fill(ring, 1, 3); // seq 0 is evicted
    ring.pin(0);
    ring.pin(99);
    expect(ring.push(print(4))).toBe(3);
    expect(ring.notKept).toBe(0);
  });

  it("nests pins and keeps the lowest one as the floor", () => {
    const ring = new TapeRing(2);
    fill(ring, 1, 2);
    ring.pin(1);
    ring.pin(1);
    ring.pin(0);
    ring.unpin(0);
    ring.unpin(1);
    expect(ring.push(print(3))).toBe(2); // seq 0 unpinned: evicted
    expect(ring.push(print(4))).toBeNull(); // seq 1 still holds one pin
    ring.unpin(1);
    ring.unpin(9); // never pinned: ignored
    expect(ring.push(print(5))).toBe(3);
  });

  it("marks a seam on a held print only", () => {
    const ring = new TapeRing(2);
    fill(ring, 1, 2);
    ring.markSeam(1);
    ring.markSeam(9);
    expect(ring.flags[ring.slot(1)]).toBe(FLAG_SEAM);
  });

  it("keeps the id of a print a later duplicate replaced when the older copy is evicted", () => {
    const ring = new TapeRing(2);
    ring.push(print(1));
    ring.push(print(1)); // the ring does not dedupe: the ingest does
    ring.push(print(2)); // evicts seq 0, whose id now maps to seq 1
    expect(ring.hasId("t1")).toBe(true);
  });

  it("clamps a cluster size into its 16-bit slot", () => {
    const ring = new TapeRing(2);
    ring.push(print(1, { clusterSize: 70_000 }));
    ring.push(print(2, { clusterSize: 0 }));
    expect([ring.clusterSize[0], ring.clusterSize[1]]).toEqual([0xffff, 1]);
  });
});
