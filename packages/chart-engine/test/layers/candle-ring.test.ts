// E12-S06 CandleRing: the interleaved int32 mirror of a BarStore. Each op (append, patch, prepend,
// replace, an evicting append) writes only its range [from, to), slot for slot with the store's
// ring; a reallocation rewrites into a new array; every attached node's batch is patched.
import { describe, expect, it } from "vitest";
import { CANDLE_DIR, CANDLE_STRIDE, CandleRing, candleDir } from "../../src/layers/index.js";
import { BAR_FLAG, BarStore, type MutationRange } from "../../src/model/index.js";
import { bars } from "../model/fixtures.js";
import { ringBar, storeBar } from "./fixtures.js";

const equal = (ring: CandleRing, store: BarStore): void => {
  expect(ring.length).toBe(store.length);
  for (let i = 0; i < store.length; i += 1)
    expect(ringBar(ring, i), `bar ${i}`).toEqual(storeBar(store, i));
};

/** A ring with a recording sink and two nodes, over a fresh store. */
function setup(maxBars = 64, initialCapacity = 16) {
  const patched: [string, string, number, number][] = [];
  const ring = new CandleRing({ patch: (id, r) => void patched.push([id, r.op, r.from, r.to]) });
  ring.nodes.push("series.candle.wick", "series.candle.body");
  const store = new BarStore({ maxBars, initialCapacity });
  const apply = (r: MutationRange): MutationRange => (ring.sync(store, r), r);
  return { ring, store, patched, apply };
}

describe("candleDir classifies once, at write", () => {
  it.each([
    [[1, 5, 0, 4], CANDLE_DIR.up],
    [[4, 5, 0, 1], CANDLE_DIR.down],
    [[3, 5, 0, 3], CANDLE_DIR.doji],
    [[3, 3, 3, 3], CANDLE_DIR.zeroRange],
  ])("%j → %i", (ohlc, dir) => {
    expect(candleDir(...(ohlc as [number, number, number, number]))).toBe(dir);
  });
});

describe("CandleRing per op", () => {
  it("replace: a full write into a new array, the store's head and capacity", () => {
    const { ring, store, apply } = setup();
    apply(store.replace({ ...bars(0, 6), flags: Uint8Array.of(1, 0, 2, 0, 4, 8) }));
    expect([ring.head, ring.capacity, ring.rewrites]).toEqual([store.ringHead, store.capacity, 1]);
    expect(ring.data.buffer).toBe(ring.ints.buffer);
    expect(ring.data.length).toBe(store.capacity * CANDLE_STRIDE);
    equal(ring, store);
    expect(ringBar(ring, 0)[4]).toBe(BAR_FLAG.gapBefore | (CANDLE_DIR.up << 4));
  });

  it("append, patch and prepend write only their range, in place", () => {
    const { ring, store, apply } = setup(64, 64);
    apply(store.replace(bars(0, 10)));
    const data = ring.data;
    const before = Array.from(ring.ints);
    apply(store.append(bars(10, 3)));
    expect([ring.lastFrom, ring.lastTo, ring.data === data]).toEqual([10, 13, true]);
    apply(store.patch(4, { ...bars(4, 1), high: Int32Array.of(40), close: Int32Array.of(40) }));
    expect([ring.lastFrom, ring.lastTo]).toEqual([4, 5]);
    apply(store.prepend(bars(-2, 2)));
    expect([ring.lastFrom, ring.lastTo, ring.data === data, ring.rewrites]).toEqual([
      0,
      2,
      true,
      1,
    ]);
    equal(ring, store);
    // Every slot outside the written ones is untouched.
    const touched = new Set<number>();
    for (const i of [0, 1, 6, 12, 13, 14]) touched.add((ring.head + i) & (ring.capacity - 1));
    for (let p = 0; p < ring.capacity; p += 1) {
      if (touched.has(p)) continue;
      const slot = before.slice(p * CANDLE_STRIDE, (p + 1) * CANDLE_STRIDE);
      expect(Array.from(ring.ints.subarray(p * CANDLE_STRIDE, (p + 1) * CANDLE_STRIDE))).toEqual(
        slot,
      );
    }
  });

  it("an evicting append moves the head and writes only the new bars", () => {
    const { ring, store, apply } = setup(8, 8);
    apply(store.append(bars(0, 8)));
    const rewrites = ring.rewrites;
    const r = apply(store.append(bars(8, 3)));
    expect([r.indexShift, ring.lastFrom, ring.lastTo, ring.rewrites]).toEqual([3, 5, 8, rewrites]);
    expect(ring.head).toBe(store.ringHead);
    equal(ring, store);
  });

  it("a store reallocation rewrites the whole ring into a new array (a full upload)", () => {
    const { ring, store, apply } = setup(64, 4);
    apply(store.append(bars(0, 4)));
    const data = ring.data;
    apply(store.append(bars(4, 1))); // 5 > 4 slots: the store grows
    expect([ring.data === data, ring.rewrites, ring.lastFrom, ring.lastTo]).toEqual([
      false,
      2,
      0,
      5,
    ]);
    equal(ring, store);
  });

  it("a merged append rewrites the last bar's instance", () => {
    const { ring, store, apply } = setup();
    apply(store.append(bars(0, 3)));
    apply(store.append({ ...bars(2, 1), close: Int32Array.of(-2), low: Int32Array.of(-5) }, true));
    expect([ring.lastFrom, ring.lastTo]).toEqual([2, 3]);
    expect(ringBar(ring, 2)[4]).toBe(CANDLE_DIR.down << 4);
    equal(ring, store);
  });

  it("patches every node's batch with the mutation's range", () => {
    const { store, patched, apply } = setup();
    apply(store.append(bars(0, 3)));
    apply(store.patch(1, bars(1, 1)));
    apply(store.append(bars(3, 0))); // an empty range patches nothing
    expect(patched).toEqual([
      ["series.candle.wick", "replace", 0, 3], // the first sync allocates: the whole ring
      ["series.candle.body", "replace", 0, 3],
      ["series.candle.wick", "patch", 1, 2],
      ["series.candle.body", "patch", 1, 2],
    ]);
  });

  it("works with no sink, and an empty mutation writes nothing", () => {
    const ring = new CandleRing();
    const store = new BarStore();
    ring.sync(store, store.append(bars(0, 2)));
    const written = ring.written;
    ring.sync(store, store.append(bars(2, 0)));
    expect([ring.written, ring.lastFrom, ring.lastTo]).toEqual([written, 2, 2]);
  });
});

describe("CandleRing after a view() re-linearisation", () => {
  it("rewrites in full at the next sync: the store's columns changed with no mutation", () => {
    const { ring, store, apply } = setup(8, 8);
    apply(store.append(bars(0, 8)));
    for (const m of [8, 11, 14]) apply(store.append(bars(m, 3))); // head 13: wrapped
    expect(store.ringHead).toBe(13);
    store.view(); // re-linearises: new columns, new head
    const rewrites = ring.rewrites;
    apply(store.patch(2, bars(11, 1))); // minutes 9..16 held
    expect([ring.rewrites, ring.lastFrom, ring.lastTo]).toEqual([rewrites + 1, 0, 8]);
    equal(ring, store);
  });
});
