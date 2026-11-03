// E12-S09 test helpers: the brute-force column oracle (BQ-02). It stands in for E11-S12's
// decimator (#418), which this PR must not take code from: for every device column it scans
// every bar, by logical index through the ring's mask, and keeps the 26 §3.6 survivors.
import type { ColumnSource } from "../../src/layers/index.js";
import type { BarBatch, BarStore } from "../../src/model/index.js";

export const ORACLE_STRIDE = 6; // 26 §3.6: the stride reserves room past the four survivors

/** Device column of bar i on the §3.6 grid. */
export const columnOf = (i: number, leftIndex: number, pxPerBar: number): number =>
  Math.floor((i + 0.5 - leftIndex) * pxPerBar);

/** Columns [0, width) over bars [0, end): an empty column has minLow > maxHigh. */
export function foldOracle(
  store: BarStore,
  leftIndex: number,
  pxPerBar: number,
  end: number,
  width: number,
): ColumnSource {
  const ints = new Int32Array(width * ORACLE_STRIDE);
  const { open, high, low, close } = store.columns;
  const mask = store.capacity - 1;
  for (let col = 0; col < width; col += 1) {
    let lo = 2 ** 31 - 1;
    let hi = -(2 ** 31);
    let first = -1;
    let last = -1;
    for (let i = 0; i < end; i += 1) {
      if (columnOf(i, leftIndex, pxPerBar) !== col) continue;
      const p = (store.ringHead + i) & mask;
      lo = Math.min(lo, low[p] ?? 0);
      hi = Math.max(hi, high[p] ?? 0);
      if (first < 0) first = p;
      last = p;
    }
    const at = col * ORACLE_STRIDE;
    ints[at] = lo;
    ints[at + 1] = hi;
    ints[at + 2] = first < 0 ? 0 : (open[first] ?? 0);
    ints[at + 3] = last < 0 ? 0 : (close[last] ?? 0);
  }
  return { ints, stride: ORACLE_STRIDE, count: width, firstColumn: 0 };
}

/** OHLC rows as a batch, one minute apart from `t0` (or at `times`), flags optional. */
export function rowsBatch(
  rows: readonly (readonly number[])[],
  flags?: Uint8Array,
  times?: Float64Array,
): BarBatch {
  const col = (k: number): Int32Array => Int32Array.from(rows, (r) => r[k] ?? 0);
  return {
    time: times ?? Float64Array.from(rows, (_, i) => i * 60e6),
    open: col(0),
    high: col(1),
    low: col(2),
    close: col(3),
    volume: Float32Array.from(rows, (r) => r[4] ?? 1),
    flags,
    priceOrigin: 0,
    tickSize: 1,
  };
}
