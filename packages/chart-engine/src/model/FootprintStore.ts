// FootprintStore (26 §3.3, E11-T03): cells as parallel arrays sorted by (barIndex, priceLevel), with
// `offsets` prefix sums so the cells of bar b are [offsets[b], offsets[b + 1]) in O(1), handed out as
// subarray views (no copy). Declared here; footprint semantics and `upsertFootprintCells` are E18's.
import { DEFAULT_MAX_BARS } from "./BarStore.js";
import { ModelCounters, type MutationRange, RangeSlot } from "./counters.js";

/** 1 << 22 cells × 18 B ≈ 75 MB: the per-store byte ceiling (a larger declared count is refused). */
export const DEFAULT_MAX_CELLS = 1 << 22;
const CELL_BYTES = 4 + 4 + 4 + 4 + 2;

/** §8 `FootprintData`, structurally. */
export interface FootprintBatch {
  readonly barIndexOffsets: Uint32Array; // bars + 1 prefix sums
  readonly cellPriceLevel: Int32Array; // ticks from priceOrigin, increasing within a bar
  readonly cellBidVol: Float32Array;
  readonly cellAskVol: Float32Array;
  readonly cellTradeCount: Uint16Array;
  readonly priceOrigin: number;
  readonly tickSize: number;
}

/** The cells of one bar: views into the store's columns (writable memory: read only), valid until
 * its next mutation. */
export class FootprintCells {
  priceLevel: Int32Array = new Int32Array(0);
  bidVol: Float32Array = new Float32Array(0);
  askVol: Float32Array = new Float32Array(0);
  tradeCount: Uint16Array = new Uint16Array(0);
}

export class FootprintStore {
  readonly counters: ModelCounters;
  readonly maxCells: number;
  readonly maxBars: number;
  barIndex: Uint32Array = new Uint32Array(0);
  priceLevel: Int32Array = new Int32Array(0);
  bidVol: Float32Array = new Float32Array(0);
  askVol: Float32Array = new Float32Array(0);
  tradeCount: Uint16Array = new Uint16Array(0);
  offsets: Uint32Array = new Uint32Array(1);
  priceOrigin = 0;
  tickSize = 0;
  private readonly range = new RangeSlot();
  private readonly cells = new FootprintCells();

  constructor(
    opts: {
      readonly maxCells?: number;
      readonly maxBars?: number;
      readonly counters?: ModelCounters;
    } = {},
  ) {
    this.maxCells = opts.maxCells ?? DEFAULT_MAX_CELLS;
    this.maxBars = opts.maxBars ?? DEFAULT_MAX_BARS;
    this.counters = opts.counters ?? new ModelCounters();
  }

  get bars(): number {
    return this.offsets.length - 1;
  }
  get cellCount(): number {
    return this.priceLevel.length;
  }
  /** `engine.model.bytes{store="footprint"}`. */
  get bytes(): number {
    return this.cellCount * CELL_BYTES + this.offsets.byteLength;
  }

  /** Replaces every cell; built in full before the swap, so a rejected batch changes nothing. */
  replace(d: FootprintBatch): MutationRange {
    const cs = this.counters;
    const [off, price] = [d.barIndexOffsets, d.cellPriceLevel];
    const typed =
      off instanceof Uint32Array &&
      price instanceof Int32Array &&
      d.cellBidVol instanceof Float32Array &&
      d.cellAskVol instanceof Float32Array &&
      d.cellTradeCount instanceof Uint16Array;
    if (!typed) cs.reject("type", "footprint columns must be the declared typed arrays");
    const n = price.length;
    const bars = off.length - 1;
    if (n > this.maxCells)
      cs.reject("ceiling", `${n} cells declared, maxCells is ${this.maxCells}`);
    if (bars > this.maxBars)
      cs.reject("ceiling", `${bars} bars declared, maxBars is ${this.maxBars}`);
    const sized = [d.cellBidVol, d.cellAskVol, d.cellTradeCount].every((c) => c.length === n);
    if (!sized || bars < 0) cs.reject("length", "footprint columns differ in length");
    if (off[0] !== 0 || off[bars] !== n) cs.reject("offsets", "offsets must run from 0 to cells");
    if (!Number.isFinite(d.priceOrigin) || !(d.tickSize > 0 && d.tickSize < Infinity)) {
      cs.reject("non_finite", "priceOrigin / tickSize must be finite, tickSize > 0");
    }
    for (let b = 0; b < bars; b += 1) {
      const [from, to] = [off[b] as number, off[b + 1] as number];
      if (to < from || to > n) cs.reject("offsets", `offsets decrease or overrun at bar ${b}`);
      for (let i = from; i < to; i += 1) {
        const p = price[i] as number;
        if (i > from && p <= (price[i - 1] as number)) cs.reject("order", `cell ${i}: unsorted`);
        if (!Number.isFinite(d.cellBidVol[i]) || !Number.isFinite(d.cellAskVol[i])) {
          cs.reject("non_finite", `cell ${i}: non-finite volume`);
        }
      }
    }
    const barIndex = new Uint32Array(n);
    for (let b = 0; b < bars; b += 1) barIndex.fill(b, off[b], off[b + 1]);
    this.barIndex = barIndex;
    this.priceLevel = new Int32Array(price);
    this.bidVol = new Float32Array(d.cellBidVol);
    this.askVol = new Float32Array(d.cellAskVol);
    this.tradeCount = new Uint16Array(d.cellTradeCount);
    this.offsets = new Uint32Array(off);
    this.priceOrigin = d.priceOrigin;
    this.tickSize = d.tickSize;
    this.counters.reallocations += 1;
    return this.range.set("replace", 0, n, 0);
  }

  /** The cells of `bar` as views over [offsets[bar], offsets[bar + 1]) (empty when it has none;
   * four subarrays per call); null when `bar` is outside [0, bars). */
  cellsFor(bar: number): FootprintCells | null {
    if (!Number.isInteger(bar) || bar < 0 || bar >= this.bars) return null;
    const from = this.offsets[bar] as number;
    const to = this.offsets[bar + 1] as number;
    const c = this.cells;
    c.priceLevel = this.priceLevel.subarray(from, to);
    c.bidVol = this.bidVol.subarray(from, to);
    c.askVol = this.askVol.subarray(from, to);
    c.tradeCount = this.tradeCount.subarray(from, to);
    return c;
  }
}
