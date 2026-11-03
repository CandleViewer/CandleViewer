// SeriesPriceSource (E12-S11 PR A1, 26 §3.5 and :390): one runtime-owned series as autoscale's
// `PriceExtentSource`. The extent and the log guard's minimum read the DRAWN instance words, the
// series' `CandleRing` (real bars, or the Heikin-Ashi candles while HA is on, whose high or low
// can lie outside the real range), so autoscale never clips what is on screen; the percent anchor
// reads the store's real close (E12-D06 R-4: the axis and its labels are real prices). A series
// that is not the viewport's time map is read by time (its own bars spanning the visible ones),
// and every value is converted into the pane's price frame (rounded outward) when its origin or
// tick differ. A line-family series (line, area, baseline: E12-S07 PR B) draws only its closes,
// so in `closes` mode the extent and the minimum read the close word alone. The runtime sets the
// mode and bumps `version` after every applied batch and kind switch; nothing is allocated per
// call. No DOM, no GL.
import type { BarStore } from "../../model/BarStore.js";
import type { PriceExtentSource } from "../../viewport/autoscale.js";
import type { ViewportState } from "../../viewport/types.js";
import { CANDLE_STRIDE, type CandleRing } from "./ring.js";

/** The ring words a scan reads: high, low and close (`[open, high, low, close, meta]`). */
const HIGH = 1;
const LOW = 2;
const CLOSE = 3;

export class SeriesPriceSource implements PriceExtentSource {
  readonly kind = "series" as const;
  version = 0;
  private minAt = -1;
  private min = Number.NaN;
  /** The exclusive end of the last `first` call's slice, in this series' bars. */
  private end = 0;
  /** Closes only (a line-family kind): the high and low words are not drawn. */
  private closesOnly = false;

  constructor(
    private readonly store: BarStore,
    private readonly ring: CandleRing,
    /** The chart's viewport: re-pointed by the runtime when a re-init replaces it. */
    public viewport: ViewportState,
    private readonly pane: number,
  ) {}

  /** The series' data or drawn shape changed: autoscale refits and the guard re-runs. */
  bump(): void {
    this.version += 1;
  }

  /**
   * Price from the closes alone (line, area, baseline) or from the high and low (candles, OHLC).
   * The caller bumps `version` afterwards (the runtime does on every kind switch).
   */
  setClosesOnly(on: boolean): void {
    if (on === this.closesOnly) return;
    this.closesOnly = on;
    this.minAt = -1;
  }

  get closes(): boolean {
    return this.closesOnly;
  }

  extent(i0: number, i1: number, out: Float64Array): boolean {
    const a = this.first(i0, i1);
    const b = this.end;
    if (a < 0 || a >= b) return false;
    const r = this.ring;
    const c = this.closesOnly;
    scan(r.ints, r.head, r.capacity - 1, a, b, c ? CLOSE : HIGH, c ? CLOSE : LOW, out);
    out[0] = Math.floor(this.toPane(out[0] as number));
    out[1] = Math.ceil(this.toPane(out[1] as number));
    return true;
  }

  minLow(): number {
    if (this.minAt !== this.version) {
      const r = this.ring;
      this.min = lowest(r.ints, r.head, r.capacity - 1, r.length, this.closesOnly ? CLOSE : LOW);
      this.minAt = this.version;
    }
    return Number.isNaN(this.min) ? this.min : Math.floor(this.toPane(this.min));
  }

  close(i: number): number {
    const j = this.own(i);
    if (j < 0) return Number.NaN;
    const s = this.store;
    const c = s.columns.close[(s.ringHead + j) & (s.capacity - 1)] as number;
    return this.same() ? c : Math.round(this.toPane(c));
  }

  /** This series' bars spanning the time map's bars [i0, i1): the first, `end` set; -1 if none. */
  private first(i0: number, i1: number): number {
    const map = this.viewport.map;
    const n = Math.min(this.ring.length, this.store.length);
    if (this.viewport.panes[this.pane] === undefined || n === 0) return -1;
    if (map === this.store) {
      this.end = Math.min(n, i1);
      return Math.max(0, i0);
    }
    const lo = Math.max(0, i0);
    const hi = Math.min(map.length, i1);
    if (lo >= hi) return -1;
    this.end = this.store.timeToIndex(map.indexToTime(hi - 1)) + 1;
    return Math.max(0, this.store.timeToIndex(map.indexToTime(lo)));
  }

  /**
   * Bar i of the time map as this series' bar index: its bar at that time, else its last bar
   * before it (`timeToIndex`, at or before); -1 when i is off the map or precedes its first bar.
   */
  private own(i: number): number {
    const map = this.viewport.map;
    const n = this.store.length;
    if (this.viewport.panes[this.pane] === undefined || !(i >= 0 && i < map.length)) return -1;
    if (map === this.store) return i < n ? i : -1;
    return this.store.timeToIndex(map.indexToTime(i));
  }

  /** The pane already draws in this series' frame, or has none yet (the raw ticks stand). */
  private same(): boolean {
    const p = this.viewport.panes[this.pane];
    const s = this.store;
    return (
      p === undefined ||
      !(p.tickSize > 0) ||
      !(s.tickSize > 0) ||
      (p.priceOrigin === s.priceOrigin && p.tickSize === s.tickSize)
    );
  }

  /** A tick of this series as a (fractional) tick of the pane's frame. */
  private toPane(t: number): number {
    if (this.same()) return t;
    const p = this.viewport.panes[this.pane] as ViewportState["panes"][number];
    return (this.store.priceOrigin + this.store.tickSize * t - p.priceOrigin) / p.tickSize;
  }
}

/**
 * [min of word `lw`, max of word `hw`] of the drawn words over logical bars [a, b) into `out`
 * (a < b): high and low, or the close twice. Plain locals, int32 compares: the ring's `fill`
 * pattern, so the loop stays optimised after warm-up.
 */
function scan(
  ints: Int32Array,
  head: number,
  mask: number,
  a: number,
  b: number,
  hw: number,
  lw: number,
  out: Float64Array,
): void {
  const stride = CANDLE_STRIDE; // a local: an imported binding can be a getter per read
  let lo = 0x7fffffff;
  let hi = -0x80000000;
  for (let i = a; i < b; i += 1) {
    const w = ((head + i) & mask) * stride;
    const h = (ints[w + hw] as number) | 0;
    const l = (ints[w + lw] as number) | 0;
    if (h > hi) hi = h;
    if (l < lo) lo = l;
  }
  out[0] = lo;
  out[1] = hi;
}

/** The lowest drawn word `lw` (the low, or the close) over the `n` bars held; NaN when none. */
function lowest(ints: Int32Array, head: number, mask: number, n: number, lw: number): number {
  if (n === 0) return Number.NaN;
  const stride = CANDLE_STRIDE;
  let lo = 0x7fffffff;
  for (let i = 0; i < n; i += 1) {
    const l = (ints[((head + i) & mask) * stride + lw] as number) | 0;
    if (l < lo) lo = l;
  }
  return lo;
}
