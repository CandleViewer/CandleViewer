// E12-S09 AC1 "spikes survive" (#421; 26 §3.6, E12-D06 §5.4), as a seeded property (README
// BQ-30: mulberry32 loops, a failure prints its seed). Random series on a small wrapping ring
// (eviction moves the head), random L2 spacing, DPR and pan: the brute-force oracle fills a
// `ColumnSource`, `ColumnEntries` turns it into instances, and for every device column the
// rendered wick (the geometry twin's `columnRect`, the shader's arithmetic) spans exactly the
// true max high to min low of the bars in it, the span runs from the first bar's open to the
// last bar's close, and no non-empty column is dropped. Plus the single-spike fixture at
// 20 bars a column (the 0.05 px clamp, D06 §5.1).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANDLE_PART,
  CANDLE_STRIDE,
  candleGeometry,
  ColumnEntries,
  columnRect,
  GEOM,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import { projectRel } from "../../src/viewport/transform.js";
import { columnOf, foldOracle, rowsBatch } from "./column-oracle.js";

const CASES = 10_000;
const K = Float64Array.of(10, -2, 500, 0, 0, 600, 0, 0);

/** Every entry's rendered wick and span against the true survivors of its column. */
function check(store: BarStore, left: number, px: number, dpr: number, width: number): string {
  const entries = new ColumnEntries(width);
  entries.write(foldOracle(store, left, px, store.length, width));
  const geom = new Float32Array(8);
  candleGeometry(px / dpr, dpr, geom, 2);
  const hair = geom[GEOM.hair] ?? 1;
  // The truth, one pass over the bars (not the oracle's per-column scan).
  const hi = new Map<number, number>();
  const lo = new Map<number, number>();
  const first = new Map<number, number>();
  const last = new Map<number, number>();
  const { open, high, low, close } = store.columns;
  for (let i = 0; i < store.length; i += 1) {
    const col = columnOf(i, left, px);
    if (col < 0 || col >= width) continue;
    const p = (store.ringHead + i) & (store.capacity - 1);
    hi.set(col, Math.max(hi.get(col) ?? -Infinity, high[p] ?? 0));
    lo.set(col, Math.min(lo.get(col) ?? Infinity, low[p] ?? 0));
    if (!first.has(col)) first.set(col, open[p] ?? 0);
    last.set(col, close[p] ?? 0);
  }
  if (entries.count !== hi.size) return `${entries.count} entries for ${hi.size} columns`;
  const out = new Float64Array(4);
  for (let e = 0; e < entries.count; e += 1) {
    const v = (k: number): number => entries.ints[e * CANDLE_STRIDE + k] ?? 0;
    const col = v(4) >> 4;
    const [h, l] = [hi.get(col) ?? NaN, lo.get(col) ?? NaN];
    columnRect(CANDLE_PART.columnWick, col, v(0), v(1), v(2), v(3), K, 0, geom, out);
    const top = projectRel(K, h);
    const bottom = Math.max(projectRel(K, l), top + hair);
    if (out[0] !== col || out[1] !== top || (out[1] ?? 0) + (out[3] ?? 0) !== bottom) {
      return `column ${col}: wick ${Array.from(out)} vs high ${h} low ${l}`;
    }
    if (v(0) !== first.get(col) || v(3) !== last.get(col)) return `column ${col}: span`;
  }
  return "";
}

describe("property (AC1): every rendered L2 column reaches its true high and low", () => {
  it(`holds for ${CASES} seeded random series`, { timeout: 120_000 }, () => {
    const failures: string[] = [];
    let wrapped = 0;
    for (let c = 0; c < CASES && failures.length === 0; c += 1) {
      const seed = 20261102 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const maxBars = 8 + int(56);
      const store = new BarStore({ maxBars, initialCapacity: 4 });
      let t0 = 0;
      for (let a = 0; a < 2; a += 1) {
        const rows = Array.from({ length: Math.ceil(maxBars / 2) + int(maxBars / 2) }, () => {
          const l = int(400) - 200;
          const h = l + (rng() < 0.05 ? 200 + int(500) : int(6)); // a spike now and then
          return [l + int(h - l + 1), h, l, l + int(h - l + 1)];
        });
        const b = rowsBatch(rows);
        store.append({ ...b, time: b.time.map((t) => t + t0) });
        t0 += rows.length * 60e6;
      }
      if (store.ringHead !== 0) wrapped += 1;
      const dpr = [1, 1.5, 2][int(3)] as number;
      const px = (0.05 + rng() * 1.44) * dpr; // L2: barSpacing < 1.5 CSS px
      const left = rng() * 4 - 2;
      const width = Math.ceil((store.length + 2) * px) + 1;
      const why = check(store, left, px, dpr, width);
      if (why !== "") failures.push(`seed=${seed}: ${why}`);
    }
    expect(failures).toEqual([]);
    expect(wrapped).toBeGreaterThan(CASES / 4); // the ring's head moved: reads go through the mask
  });

  it("a single spike at 20 bars a column (the 0.05 px clamp) is the column's wick", () => {
    const rows = Array.from({ length: 200 }, () => [100, 101, 99, 100]);
    rows[137] = [100, 900, 99, 100];
    rows[61] = [100, 101, -700, 100];
    const store = new BarStore();
    store.append(rowsBatch(rows));
    expect(check(store, 0, 0.05, 1, 10)).toBe("");
    const entries = new ColumnEntries(10);
    entries.write(foldOracle(store, 0, 0.05, 200, 10));
    const at = (col: number): number[] =>
      Array.from(entries.ints.subarray(col * CANDLE_STRIDE, col * CANDLE_STRIDE + 3));
    expect([at(6), at(3)]).toEqual([
      [100, 900, 99],
      [100, 101, -700],
    ]);
  });
});
