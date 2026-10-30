// HeatmapRing (26 §3.3 / §3.8, E11-T03): the descriptor of the DOM-heatmap texture ring, 2048 columns
// × 512 price rows with a `writeCol` cursor that overwrites the oldest column. Descriptor only: the
// texture and its uploads are E21's.
import { ModelCounters, type MutationRange, RangeSlot } from "./counters.js";

export const HEATMAP_COLUMNS = 2048;
export const HEATMAP_ROWS = 512;

export class HeatmapRing {
  readonly counters: ModelCounters;
  readonly columns = HEATMAP_COLUMNS;
  readonly rows = HEATMAP_ROWS;
  /** Time (µs) of each column; NaN until written. */
  readonly colTime = new Float64Array(HEATMAP_COLUMNS).fill(Number.NaN);
  writeCol = 0;
  filled = 0;
  priceOrigin = 0;
  priceStep = 0;
  private last = -Infinity;
  private readonly range = new RangeSlot();

  constructor(counters: ModelCounters = new ModelCounters()) {
    this.counters = counters;
  }

  /** `engine.model.bytes{store="heatmap"}`: an RG16F texture plus the column times. */
  get bytes(): number {
    return this.columns * this.rows * 4 + this.colTime.byteLength;
  }

  /** Row 0's price and the row step; both finite, the step > 0. */
  setPriceAxis(priceOrigin: number, priceStep: number): void {
    if (!Number.isFinite(priceOrigin) || !(priceStep > 0 && priceStep < Infinity)) {
      this.counters.reject("non_finite", "heatmap price axis must be finite, step > 0");
    }
    this.priceOrigin = priceOrigin;
    this.priceStep = priceStep;
  }

  /** Claims the next column for `time` (non-decreasing); returns the one column written. */
  push(time: number): MutationRange {
    if (!Number.isFinite(time)) this.counters.reject("non_finite", "heatmap column time");
    if (time < this.last) this.counters.reject("order", "heatmap column older than the last");
    const col = this.writeCol;
    this.colTime[col] = time;
    this.last = time;
    this.writeCol = (col + 1) & (HEATMAP_COLUMNS - 1);
    this.filled = Math.min(this.filled + 1, HEATMAP_COLUMNS);
    return this.range.set("append", col, col + 1, 0);
  }
}
