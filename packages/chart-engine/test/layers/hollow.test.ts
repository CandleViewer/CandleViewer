// E12-S07 hollow candles (E12-D06 §3.2, §4.2): the four marks (fill by close vs open, colour and
// wick weight by close vs the previous close) and the first bar's fallback in the geometry twin;
// the ring's two meta bits (8 hollow, 9 colour-up; nothing else) and the one-bar extension of a
// write for the next bar's colour bit, as a seeded property; below 3 CSS px the candle's mark.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANDLE_DIR,
  CANDLE_META,
  CANDLE_PART,
  CandleRing,
  CandleSeries,
  candleGeometry,
  candleRect,
  GEOM,
  hollowFill,
  MARK,
  PALETTE,
  partColor,
  SERIES_PARTS,
} from "../../src/layers/index.js";
import { type BarBatch, BarStore } from "../../src/model/index.js";
import { ringBar, storeBar } from "./fixtures.js";

function batch(rows: readonly (readonly number[])[], t0 = 0): BarBatch {
  const col = (k: number): Int32Array => Int32Array.from(rows, (r) => r[k] ?? 0);
  return {
    time: Float64Array.from(rows, (_, i) => t0 + i * 60e6),
    open: col(0),
    high: col(1),
    low: col(2),
    close: col(3),
    volume: new Float32Array(rows.length).fill(1),
    priceOrigin: 0,
    tickSize: 1,
  };
}

const geom = (s: number, dpr: number): Float32Array => {
  const g = new Float32Array(8);
  candleGeometry(s, dpr, g);
  return g;
};
const K = Float64Array.of(10, -2, 500, 0, 0, 600, 0, 0);
const mark = (ring: CandleRing, i: number): number => (ringBar(ring, i)[4] ?? 0) >> 4;

/** The expected bits of bar i of `rows` (the first held bar: close vs open for both). */
const bits = (rows: readonly (readonly number[])[], i: number): number => {
  const [o = 0, , , c = 0] = rows[i] ?? [];
  const prev = i > 0 ? (rows[i - 1]?.[3] ?? 0) : o;
  return (c >= o ? CANDLE_META.hollow : 0) | (c >= prev ? CANDLE_META.colourUp : 0);
};

function hollowRing(rows: readonly (readonly number[])[]) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const series = new CandleSeries(ring, "hollow");
  ring.sync(store, store.append(batch(rows)));
  return { store, ring, series };
}

// The first bar is the fallback; then one bar per cell of D06 §4.2's table.
const FOUR = [
  [10, 16, 8, 14], // first: close ≥ open → hollow, up colour, 1 px wick (both channels)
  [16, 18, 9, 12], // close < open, 12 < 14 → solid, down colour, 2 px wick
  [8, 13, 7, 10], // close ≥ open, 10 < 12 → hollow, down colour, 2 px wick
  [15, 16, 9, 11], // close < open, 11 ≥ 10 → solid, up colour, 1 px wick
  [9, 14, 8, 13], // close ≥ open, 13 ≥ 11 → hollow, up colour, 1 px wick
];

describe("hollow candle: the four marks (D06 §4.2)", () => {
  it("fill × colour × wick weight per cell, and the first bar's fallback", () => {
    const { ring } = hollowRing(FOUR);
    const g = geom(12, 1);
    const out = new Float64Array(4);
    const seen = FOUR.map((r, i) => {
      const m = mark(ring, i);
      const [o = 0, h = 0, l = 0, c = 0] = r;
      candleRect(CANDLE_PART.hollowWick, i, o, h, l, c, m, K, 0, 0, g, out);
      const wick = out[2];
      const colour = partColor(CANDLE_PART.hollowBody, m) === PALETTE.up ? "up" : "down";
      const fill = hollowFill(CANDLE_PART.hollowBody, m) ? "hollow" : "solid";
      return `${fill} ${colour} ${wick}`;
    });
    expect(seen).toEqual([
      "hollow up 1",
      "solid down 2",
      "hollow down 2",
      "solid up 1",
      "hollow up 1",
    ]);
  });

  it("the four marks stay distinct with colour ignored (fill × weight)", () => {
    const { ring } = hollowRing(FOUR);
    const marks = new Set(FOUR.map((_, i) => mark(ring, i) & (MARK.hollow | MARK.colourUp)));
    expect(marks.size).toBe(4);
  });

  it("the wick is neutral and the body places exactly as the candle's", () => {
    const { ring } = hollowRing(FOUR);
    const g = geom(12, 2);
    const [a, b] = [new Float64Array(4), new Float64Array(4)];
    for (let i = 0; i < FOUR.length; i += 1) {
      const m = mark(ring, i);
      const [o = 0, h = 0, l = 0, c = 0] = FOUR[i] ?? [];
      candleRect(CANDLE_PART.hollowBody, i, o, h, l, c, m, K, 0, 0, g, a);
      candleRect(CANDLE_PART.body, i, o, h, l, c, m, K, 0, 0, g, b);
      expect(Array.from(a)).toEqual(Array.from(b));
      expect(partColor(CANDLE_PART.hollowWick, m)).toBe(PALETTE.wick);
    }
  });

  it("a doji keeps §4.2's previous-close colour and wick weight; zero-range stays neutral", () => {
    // D06 §9, doji row: "Hollow: the body keeps §4.2's previous-close colour and wick weight".
    const rows = [
      [10, 12, 8, 11],
      [11, 13, 9, 11], // doji, 11 ≥ 11: up colour, 1 hairline wick
      [10, 12, 8, 10], // doji, 10 < 11: down colour, 2 hairline wick
      [10, 10, 10, 10], // zero-range: neutral, 1 hairline
    ];
    const { ring } = hollowRing(rows);
    const g = geom(12, 1);
    const [out, ref] = [new Float64Array(4), new Float64Array(4)];
    const seen = [1, 2, 3].map((i) => {
      const m = mark(ring, i);
      const [o = 0, h = 0, l = 0, c = 0] = rows[i] ?? [];
      candleRect(CANDLE_PART.hollowWick, i, o, h, l, c, m, K, 0, 0, g, out);
      const wick = out[2];
      // The body keeps the candle's §9 doji / zero-range geometry, painted whole.
      candleRect(CANDLE_PART.hollowBody, i, o, h, l, c, m, K, 0, 0, g, out);
      candleRect(CANDLE_PART.body, i, o, h, l, c, m & MARK.dir, K, 0, 0, g, ref);
      expect(Array.from(out)).toEqual(Array.from(ref));
      expect(hollowFill(CANDLE_PART.hollowBody, m)).toBe(false);
      expect(partColor(CANDLE_PART.hollowWick, m)).toBe(PALETTE.wick);
      return [m & MARK.dir, partColor(CANDLE_PART.hollowBody, m), wick];
    });
    const { doji, zeroRange } = CANDLE_DIR;
    expect(seen).toEqual([
      [doji, PALETTE.up, 1],
      [doji, PALETTE.down, 2],
      [zeroRange, PALETTE.wick, 1],
    ]);
  });

  it("a doji wick at dpr 2 is h and 2h device px: 2 (up) and 4 (down), E12-D06 §9", () => {
    const rows = [
      [10, 12, 8, 11],
      [11, 13, 9, 11], // up doji
      [10, 12, 8, 10], // down doji
    ];
    const { ring } = hollowRing(rows);
    const g = geom(12, 2);
    const h = g[GEOM.hair] ?? 0;
    expect(h).toBe(2);
    const out = new Float64Array(4);
    const wicks = [1, 2].map((i) => {
      const [o = 0, hi = 0, l = 0, c = 0] = rows[i] ?? [];
      candleRect(CANDLE_PART.hollowWick, i, o, hi, l, c, mark(ring, i), K, 0, 0, g, out);
      return out[2];
    });
    expect(wicks).toEqual([h, 2 * h]);
    expect(wicks).toEqual([2, 4]);
  });

  it("below 3 CSS px the hosts draw the candle's wick and body (D06 §5.5)", () => {
    const { series } = hollowRing(FOUR);
    series.frame(12, 1);
    expect(series.blocks.map((b) => b.ints[0])).toEqual([
      CANDLE_PART.hollowWick,
      CANDLE_PART.hollowBody,
      CANDLE_PART.seam,
    ]);
    series.frame(2.9, 1);
    expect(series.blocks.map((b) => b.ints[0])).toEqual([0, 1, CANDLE_PART.seam]);
    expect(SERIES_PARTS.hollow.map(([n]) => n)).toEqual(["wick", "body", "seam"]);
  });
});

describe("hollow bits in the ring", () => {
  it("uses bits 8 and 9 only; a candle ring never writes them", () => {
    const { ring } = hollowRing(FOUR);
    const plain = new CandleRing();
    const store = new BarStore({ initialCapacity: 8 });
    plain.sync(store, store.append(batch(FOUR)));
    for (let i = 0; i < FOUR.length; i += 1) {
      const meta = ringBar(ring, i)[4] ?? 0;
      expect(meta & ~(0x3f | CANDLE_META.hollow | CANDLE_META.colourUp)).toBe(0);
      expect(meta & 0x3f).toBe((storeBar(store, i)[4] ?? 0) & 0x3f);
      expect(ringBar(plain, i)).toEqual(storeBar(store, i));
    }
  });

  it("a patch extends its write by the next bar (its colour reads the patched close)", () => {
    const { store, ring } = hollowRing(FOUR);
    expect(mark(ring, 2) & MARK.colourUp).toBe(0);
    ring.sync(store, store.patch(1, batch([[16, 18, 7, 8]], 60e6)));
    expect([ring.lastFrom, ring.lastTo]).toEqual([1, 3]);
    expect(mark(ring, 2) & MARK.colourUp).toBe(MARK.colourUp); // 10 ≥ 8 now
  });

  it("an append at the end and a write of the last bar extend nothing", () => {
    const { store, ring } = hollowRing(FOUR);
    ring.sync(store, store.append(batch([[13, 15, 12, 14]], 5 * 60e6)));
    expect([ring.lastFrom, ring.lastTo]).toEqual([5, 6]);
    ring.sync(store, store.append(batch([[13, 15, 11, 12]], 5 * 60e6), true));
    expect([ring.lastFrom, ring.lastTo]).toEqual([5, 6]);
  });

  it("setKind to hollow and back rewrites the bits in place", () => {
    const store = new BarStore({ initialCapacity: 8 });
    const ring = new CandleRing();
    const series = new CandleSeries(ring);
    ring.sync(store, store.append(batch(FOUR)));
    const data = ring.data;
    series.setKind("hollow", false, store);
    expect([ring.data, ring.hollow, series.shape, series.blocks[1]?.label]).toEqual([
      data,
      true,
      "hollow",
      "series.hollow.body",
    ]);
    expect(FOUR.map((_, i) => mark(ring, i) & 0x30)).toEqual(
      FOUR.map((_, i) => bits(FOUR, i) >> 4),
    );
    series.setKind("candles", false, store);
    expect(FOUR.map((_, i) => ringBar(ring, i))).toEqual(FOUR.map((_, i) => storeBar(store, i)));
  });

  it("property: seeded appends, merges, patches and prepends keep every bar's bits exact", () => {
    for (let seed = 1; seed <= 40; seed += 1) {
      const rnd = mulberry32(seed);
      const bar = (): number[] => {
        const o = Math.floor(rnd() * 40);
        const c = o + Math.floor(rnd() * 9) - 4;
        return [o, Math.max(o, c) + 2, Math.min(o, c) - 2, c];
      };
      const rows = Array.from({ length: 2 + Math.floor(rnd() * 6) }, bar);
      let t0 = 0;
      const { store, ring } = hollowRing(rows);
      for (let step = 0; step < 30; step += 1) {
        const op = Math.floor(rnd() * 4);
        if (op === 0) {
          const add = Array.from({ length: 1 + Math.floor(rnd() * 3) }, bar);
          ring.sync(store, store.append(batch(add, (t0 + rows.length) * 60e6)));
          rows.push(...add);
        } else if (op === 1) {
          const last = bar();
          ring.sync(store, store.append(batch([last], (t0 + rows.length - 1) * 60e6), true));
          rows[rows.length - 1] = last;
        } else if (op === 2) {
          const at = Math.floor(rnd() * rows.length);
          const fix = bar();
          ring.sync(store, store.patch(at, batch([fix], (t0 + at) * 60e6)));
          rows[at] = fix;
        } else {
          const older = Array.from({ length: 1 + Math.floor(rnd() * 3) }, bar);
          t0 -= older.length;
          ring.sync(store, store.prepend(batch(older, t0 * 60e6)));
          rows.unshift(...older);
        }
        const got = rows.map((_, i) => ((ringBar(ring, i)[4] ?? 0) >> 8) << 8);
        expect(got, `seed ${seed} step ${step} op ${op}`).toEqual(
          rows.map((_, i) => bits(rows, i)),
        );
      }
    }
  });
});
