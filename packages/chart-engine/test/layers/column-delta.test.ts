// E12-S09 BQ-06 (#421, ruling 6577189670; E12-D06 §5.4 / §12): `foldDeltaRange` is the per-column
// delta min / max beside `foldVolumeMax`: same grid, zeroed outputs, columns outside skipped, no
// allocation; an all-negative column keeps its true (negative) max; the forming bar is never folded.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { BAR_FLAG, BarStore } from "../../src/model/index.js";
import { foldDeltaRange, foldEnd, foldVolumeMax } from "../../src/layers/index.js";
import { rowsBatch } from "./column-oracle.js";

function make(deltas: number[], forming = false, capacity?: number): BarStore {
  const rows = deltas.map((_, i) => [100 + i, 101 + i, 100 + i, 101 + i, 1]);
  const flags = Uint8Array.from(deltas, (_, i) =>
    forming && i === deltas.length - 1 ? BAR_FLAG.forming : 0,
  );
  const s = new BarStore(capacity === undefined ? {} : { initialCapacity: capacity });
  s.append({ ...rowsBatch(rows, flags), delta: Float32Array.from(deltas) });
  return s;
}

const run = (s: BarStore, px: number, width: number, first = 0, left = 0) => {
  const lo = new Float32Array(width).fill(9);
  const hi = new Float32Array(width).fill(9);
  const n = foldDeltaRange(s, left, px, 0, foldEnd(s), first, lo, hi);
  return { n, lo: Array.from(lo), hi: Array.from(hi) };
};

describe("foldDeltaRange (BQ-06): the per-column delta min / max", () => {
  it("empty store: both outputs zeroed, nothing written", () => {
    expect(run(new BarStore(), 1, 3)).toEqual({ n: 0, lo: [0, 0, 0], hi: [0, 0, 0] });
  });

  it("single bar: min = max = its delta", () => {
    expect(run(make([-3]), 1, 2)).toEqual({ n: 1, lo: [-3, 0], hi: [-3, 0] });
  });

  it("all-negative column: the max is the largest negative, not zero", () => {
    const r = run(make([-5, -2, -9, -1]), 0.5, 3);
    expect(r).toEqual({ n: 2, lo: [-5, -9, 0], hi: [-2, -1, 0] });
  });

  it("mixed signs and an empty column between: gaps stay 0 / 0", () => {
    const r = run(make([4, -6, 2]), 2, 6); // bars land in columns 1, 3, 5
    expect(r).toEqual({ n: 6, lo: [0, 4, 0, -6, 0, 2], hi: [0, 4, 0, -6, 0, 2] });
    expect(run(make([4, -6, 7, 1]), 0.5, 2)).toEqual({ n: 2, lo: [-6, 1], hi: [4, 7] });
  });

  it("the forming bar is its own entry: foldEnd excludes it from the fold", () => {
    const s = make([1, 2, -50], true);
    expect(foldEnd(s)).toBe(2);
    expect(run(s, 0.5, 2)).toEqual({ n: 1, lo: [1, 0], hi: [2, 0] });
  });

  it("skips columns outside the buffers; a pan offset and firstColumn shift the buckets", () => {
    const s = make([1, 2, 3, 4, 5, 6]);
    expect(run(s, 1, 2, 2).lo).toEqual([3, 4]);
    expect(run(s, 1, 2, 0, 2).lo).toEqual([3, 4]);
  });

  it("clamps like the volume fold: bad grid writes nothing, from / to clamp", () => {
    const s = make([1, 2, 3, 4]);
    const lo = new Float32Array(4);
    const hi = new Float32Array(4);
    for (const px of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(foldDeltaRange(s, 0, px, 0, 4, 0, lo, hi)).toBe(0);
    }
    expect(foldDeltaRange(s, Number.NaN, 1, 0, 4, 0, lo, hi)).toBe(0);
    expect(foldDeltaRange(s, 0, 1, Number.NaN, Number.NaN, 0, lo, hi)).toBe(0);
    expect(foldDeltaRange(s, 0, 1, -5, 1e9, 0, lo, hi)).toBe(4);
    expect(Array.from(hi)).toEqual([1, 2, 3, 4]);
    // different buffer lengths: the shorter bounds the fold
    expect(foldDeltaRange(s, 0, 1, 0, 4, 0, new Float32Array(2), hi)).toBe(2);
  });

  it("property: matches a brute-force scan on a wrapped ring, same columns as foldVolumeMax", () => {
    for (let seed = 1; seed <= 60; seed += 1) {
      const rng = mulberry32(seed);
      const n = 1 + Math.floor(rng() * 40);
      const deltas = Array.from({ length: n }, () => Math.round((rng() - 0.6) * 100));
      const s = make(deltas, rng() < 0.3, 4);
      const px = 0.1 + rng() * 3;
      const left = Math.floor(rng() * 5) - 2;
      const first = Math.floor(rng() * 4) - 1;
      const width = 1 + Math.floor(rng() * 20);
      const end = foldEnd(s);
      const lo = new Float32Array(width);
      const hi = new Float32Array(width);
      const vol = new Float32Array(width);
      const cols = foldDeltaRange(s, left, px, 0, end, first, lo, hi);
      expect(foldVolumeMax(s, left, px, 0, end, first, vol), `seed ${seed}`).toBe(cols);
      for (let c = 0; c < width; c += 1) {
        const ds = deltas.filter(
          (_, i) => i < end && Math.floor((i + 0.5 - left) * px) - first === c,
        );
        const want = ds.length === 0 ? [0, 0] : [Math.min(...ds), Math.max(...ds)];
        expect([lo[c], hi[c]], `seed ${seed} col ${c}`).toEqual(want);
      }
    }
  });
});
