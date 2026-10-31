// Autoscale, the log guard and the percent anchor (E11-S05, 26 §3.5, README BQ-116 to BQ-120).
// Data reaches it through the internal `PriceExtentSource` seam (BarStore-shaped) until E12
// attaches the store; `SeriesPlugin.priceRange` is the later adapter. `update` runs once per
// frame before the uniforms are written: it compares a few keys per pane and refits only when
// one changed (the integer visible range, a source's version, a flag or margin), with no
// allocation. The guard covers the whole loaded range on every data change (C-31), not the
// visible one, and falls back to linear before the frame is drawn (E11-D03 D5).
import { fitPriceRange, priceAt } from "./transform.js";
import type { LogReason, PaneTransform } from "./types.js";
import type { ChartViewport } from "./Viewport.js";

/** One series, overlay or drawing whose prices a pane's autoscale and log guard read. */
export interface PriceExtentSource {
  /** `overlay` is left out under "Scale price only"; `drawing` counts only when included. */
  readonly kind: "series" | "overlay" | "drawing";
  /** Bumped on every mutation (append, patch, prepend, replace). */
  readonly version: number;
  /** Writes [min low, max high] in ticks over bars [i0, i1) into `out`; false when none. */
  extent(i0: number, i1: number, out: Float64Array): boolean;
  /** The lowest low over everything loaded, in ticks; NaN when empty (the log guard). */
  minLow(): number;
  /** Bar i's close in ticks, NaN outside: the percent anchor (series only). */
  close?(i: number): number;
}

/** The engine's internal scale counters (BQ-125; `FrameStats` is frozen, G-15). */
export interface ScaleCounters {
  autoscale_recomputes: number;
  log_guard_trips: number;
}

/** Key slots per pane: floor left, ceil right, ceil left, version, origin, tick, flags, margins. */
const KEYS = 9;

/** BQ-120: the reason log cannot be drawn over `minLow`, or null. */
export function logReasonFor(p: Readonly<PaneTransform>, minLow: number): LogReason | null {
  if (!(p.tickSize > 0)) return "no-price-origin";
  return priceAt(p, minLow) <= 0 ? "non-positive" : null;
}

const flagsOf = (p: Readonly<PaneTransform>): number =>
  (p.autoScale ? 1 : 0) |
  (p.includeDrawings ? 2 : 0) |
  (p.priceOnly ? 4 : 0) |
  (p.scaleMode === "log" ? 8 : 0) |
  (p.inverted ? 16 : 0);

export class AutoScaler {
  readonly counters: ScaleCounters = { autoscale_recomputes: 0, log_guard_trips: 0 };
  private readonly out = new Float64Array(2);
  private readonly keys: Float64Array;
  private readonly next = new Float64Array(KEYS);

  constructor(
    private readonly vp: ChartViewport,
    /** Each pane's sources; the runtime injects pane 0's (`RuntimeDeps.priceSources`). */
    private readonly sources: (pane: number) => readonly PriceExtentSource[],
  ) {
    this.keys = new Float64Array(vp.panes.length * KEYS).fill(Number.NaN);
  }

  /** Once per frame: true when a window, mode, anchor or log reason changed. */
  update(): boolean {
    let changed = false;
    for (let i = 0; i < this.vp.panes.length && i * KEYS < this.keys.length; i += 1) {
      changed = this.pane(i) || changed;
    }
    return changed;
  }

  private pane(i: number): boolean {
    const p = this.vp.panes[i] as PaneTransform;
    const list = this.sources(i);
    const vp = this.vp;
    const k = this.next;
    let version = 0;
    for (let s = 0; s < list.length; s += 1) version += (list[s] as PriceExtentSource).version;
    k[0] = Math.floor(vp.leftIndex);
    k[1] = Math.ceil(vp.leftIndex + vp.visibleBars);
    k[2] = Math.ceil(vp.leftIndex); // the left-most fully visible bar: the anchor
    k[3] = version;
    k[4] = p.priceOrigin;
    k[5] = p.tickSize;
    k[6] = flagsOf(p);
    k[7] = p.marginTop;
    k[8] = p.marginBottom;
    const at = i * KEYS;
    // A mode flip alone never re-runs the guard: `logReason` is kept current on every data change
    // (keys 3 to 5, NaN at first, so the first update always evaluates it), and `setScale` reads it.
    const dataChanged = !this.same(at, 3, 6);
    const refit = dataChanged || !this.same(at, 0, 2) || !this.same(at, 6, KEYS);
    const anchorMoved = !this.same(at, 2, 3);
    if (!refit && !anchorMoved) return false;
    this.keys.set(k, at);
    let changed = false;
    if (dataChanged) changed = this.guard(p, list) || changed;
    if (dataChanged || anchorMoved) changed = this.anchor(p, list, k[2] as number) || changed;
    if (refit && p.autoScale) {
      changed = this.fit(p, list, k[0] as number, k[1] as number) || changed;
    }
    this.keys[at + 6] = flagsOf(p); // after a fallback, so the next frame does not refit again
    return changed;
  }

  private same(at: number, from: number, to: number): boolean {
    for (let j = from; j < to; j += 1)
      if (!Object.is(this.keys[at + j], this.next[j])) return false;
    return true;
  }

  /** BQ-120 / C-31: the loaded range on every data change; a trip falls back to linear. */
  private guard(p: PaneTransform, list: readonly PriceExtentSource[]): boolean {
    let min = Number.NaN;
    for (let s = 0; s < list.length; s += 1) {
      const src = list[s] as PriceExtentSource;
      if (src.kind === "drawing") continue; // the guard reads every series and overlay
      const m = src.minLow();
      if (!Number.isNaN(m) && !(m >= min)) min = m;
    }
    const reason = logReasonFor(p, min);
    const first = p.logReason === "no-price-origin"; // the first evaluation over real prices
    const changed = reason !== p.logReason;
    p.logReason = reason;
    if (reason === null && first && p.requestedMode === "log" && p.scaleMode !== "log") {
      p.scaleMode = "log"; // a persisted log held until the price origin arrived (BQ-120)
      return true;
    }
    if (reason === null || p.scaleMode !== "log") return changed;
    p.scaleMode = "linear"; // never restores itself; `requestedMode` keeps "log" (D5)
    this.counters.log_guard_trips += 1;
    return true;
  }

  /** BQ-118: the close of the left-most fully visible bar. */
  private anchor(p: PaneTransform, list: readonly PriceExtentSource[], bar: number): boolean {
    let tick = Number.NaN;
    for (let s = 0; s < list.length && Number.isNaN(tick); s += 1) {
      const src = list[s] as PriceExtentSource;
      if (src.kind === "series" && src.close !== undefined) tick = src.close(bar);
    }
    const changed = !Object.is(tick, p.anchorTick);
    p.anchorTick = tick;
    return changed;
  }

  /** BQ-116 / BQ-117: one pass over the visible slice; an empty extent leaves the range. */
  private fit(
    p: PaneTransform,
    list: readonly PriceExtentSource[],
    i0: number,
    i1: number,
  ): boolean {
    let lo = Number.POSITIVE_INFINITY;
    let hi = Number.NEGATIVE_INFINITY;
    const out = this.out;
    for (let s = 0; s < list.length; s += 1) {
      const src = list[s] as PriceExtentSource;
      if (src.kind === "drawing" && !p.includeDrawings) continue;
      if (src.kind === "overlay" && p.priceOnly) continue;
      if (!src.extent(i0, i1, out)) continue;
      lo = Math.min(lo, out[0] as number);
      hi = Math.max(hi, out[1] as number);
    }
    if (!(lo <= hi)) return false;
    this.counters.autoscale_recomputes += 1;
    return fitPriceRange(p, lo, hi);
  }
}

/** The OHLC columns a source reads (a `BarStore` slice, or a test's arrays). */
export interface ExtentColumns {
  readonly low: ArrayLike<number>;
  readonly high: ArrayLike<number>;
  readonly close?: ArrayLike<number>;
  readonly length: number;
}

/** A `PriceExtentSource` over columns: E12's store fits the same shape (BQ-116). */
export function columnSource(
  cols: () => ExtentColumns,
  kind: PriceExtentSource["kind"] = "series",
): PriceExtentSource & { version: number } {
  return {
    kind,
    version: 0,
    extent(i0, i1, out): boolean {
      const c = cols();
      const a = Math.max(0, i0);
      const b = Math.min(c.length, i1);
      if (a >= b) return false;
      let lo = Number.POSITIVE_INFINITY;
      let hi = Number.NEGATIVE_INFINITY;
      for (let i = a; i < b; i += 1) {
        lo = Math.min(lo, c.low[i] as number);
        hi = Math.max(hi, c.high[i] as number);
      }
      out[0] = lo;
      out[1] = hi;
      return true;
    },
    minLow(): number {
      const c = cols();
      let lo = Number.NaN;
      for (let i = 0; i < c.length; i += 1) {
        const v = c.low[i] as number;
        if (!(v >= lo)) lo = v;
      }
      return lo;
    },
    close(i: number): number {
      const c = cols();
      return c.close !== undefined && i >= 0 && i < c.length ? (c.close[i] as number) : Number.NaN;
    },
  };
}
