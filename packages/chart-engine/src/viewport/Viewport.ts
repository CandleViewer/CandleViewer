// The chart viewport (E11-S03, 26 §3.5): one retained object per chart holding the state every
// renderer projects through `transform.ts`, the only module that maps it to pixels. Bar space is
// authoritative (BQ-66): pan and zoom move `leftIndex` and `barSpacing`, and times are derived
// through the injected `IndexTimeMap`. Every setter clamps, so no renderer observes an
// out-of-range value. DOM-free and internal (BQ-65): not §8's `Viewport` type.
import { INT32_TICKS, indexAt, screenToTime, setPriceRange } from "./transform.js";
import type { IndexTimeMap, PaneTransform, ViewportState } from "./types.js";

/** No bars loaded: a uniform 60 s grid from t = 0 µs, until E12 attaches the series store. */
export const EMPTY_TIME_MAP: IndexTimeMap = {
  length: 0,
  indexToTime: () => Number.NaN,
  timeToIndex: () => -1,
};

/** BQ-73: CSS px per bar. */
export const BAR_SPACING_MIN = 0.05;
export const BAR_SPACING_MAX = 200;
export const DEFAULT_BAR_SPACING = 6;

/** BQ-73: NaN or non-finite is rejected by the callers; the bounds are applied here. */
export const clampSpacing = (s: number): number =>
  Math.min(BAR_SPACING_MAX, Math.max(BAR_SPACING_MIN, s));

/**
 * BQ-69: `rightOffset` in [-(n - 1), visibleBars - 1], i.e. `leftIndex` in [1 - visibleBars,
 * n - 1]: the last bar never leaves through the left edge and bar 0 stays reachable. No bars, no
 * limit. Both bounds also stay inside ±2^30 (BQ-75), however wide the plot.
 */
export function clampLeft(left: number, n: number, visibleBars: number): number {
  const hi = Math.min(INT32_TICKS, n === 0 ? INT32_TICKS : n - 1);
  const lo = Math.max(-INT32_TICKS, n === 0 ? -INT32_TICKS : 1 - visibleBars);
  return Math.min(hi, Math.max(lo, left));
}

export class ChartViewport implements ViewportState {
  leftIndex = 0;
  barSpacing = DEFAULT_BAR_SPACING;
  plotWidth = 0;
  height = 0;
  dpr = 1;
  readonly panes: PaneTransform[] = [];

  constructor(
    public map: IndexTimeMap = EMPTY_TIME_MAP,
    panes = 1,
  ) {
    for (let i = 0; i < panes; i += 1) {
      this.panes.push({
        priceLow: 0,
        priceHigh: 1,
        scaleMode: "linear",
        plotTop: 0,
        plotHeight: 0,
      });
    }
  }

  get visibleBars(): number {
    return this.plotWidth / this.barSpacing;
  }

  /** Empty bars right of the last one (negative when it is past the right edge). */
  get rightOffset(): number {
    return this.leftIndex + this.visibleBars - this.map.length;
  }

  get timeStart(): number {
    return screenToTime(this, 0);
  }

  get timeEnd(): number {
    return screenToTime(this, this.plotWidth);
  }

  setMap(map: IndexTimeMap): void {
    this.map = map;
    this.place(this.leftIndex, this.barSpacing);
  }

  /** The plot size in CSS px and the device pixel ratio; false when nothing changed. */
  setSize(width: number, height: number, dpr: number): boolean {
    if (!(width >= 0 && height >= 0 && dpr > 0) || !Number.isFinite(width + height + dpr)) {
      return false;
    }
    const same = this.plotWidth === width && this.height === height && this.dpr === dpr;
    this.plotWidth = width;
    this.height = height;
    this.dpr = dpr;
    return this.place(this.leftIndex, this.barSpacing) || !same;
  }

  setPanePlot(pane: number, top: number, height: number): void {
    const p = this.panes[pane];
    if (p === undefined || !(height >= 0) || !Number.isFinite(top + height)) return;
    p.plotTop = top;
    p.plotHeight = height;
  }

  /** A price window in ticks; one under a tick widens to one tick. False when rejected. */
  setPriceRange(pane: number, low: number, high: number): boolean {
    const p = this.panes[pane];
    return p !== undefined && setPriceRange(p, low, high);
  }

  /** Moves the chart `dxPx` CSS px right (content follows the pointer). */
  pan(dxPx: number): boolean {
    if (!(this.plotWidth > 0) || !Number.isFinite(dxPx)) return false;
    return this.place(this.leftIndex - dxPx / this.barSpacing, this.barSpacing);
  }

  /**
   * BQ-70: `factor` > 1 zooms in (`barSpacing *= factor`). The index under `anchorPx` stays put,
   * also when `barSpacing` is clamped; when the `leftIndex` clamp wins, the anchor yields.
   */
  zoomAt(anchorPx: number, factor: number): boolean {
    const w = this.plotWidth;
    if (!(w > 0) || !(factor > 0) || !Number.isFinite(anchorPx) || !Number.isFinite(factor)) {
      return false;
    }
    const x = Math.min(w, Math.max(0, anchorPx)); // an off-plot anchor zooms at the nearer edge
    const at = x / this.barSpacing + this.leftIndex;
    const s = clampSpacing(this.barSpacing * factor);
    return this.place(at - x / s, s);
  }

  /** A cut (E11-S04 BQ-107): bar-space `left` at the plot's left edge, at `spacing` px a bar. */
  scrollTo(left: number, spacing = this.barSpacing): boolean {
    if (!(spacing > 0) || !Number.isFinite(spacing)) return false;
    return this.place(left, clampSpacing(spacing));
  }

  /** §8 `TimeScale.setVisibleRange`: through the map into bar space, then clamped. */
  setTimeRange(from: number, to: number): boolean {
    if (!(to > from) || !Number.isFinite(from) || !Number.isFinite(to)) return false;
    const a = indexAt(this.map, from);
    const s = this.plotWidth > 0 ? clampSpacing(this.plotWidth / (indexAt(this.map, to) - a)) : 0;
    return this.place(a + 0.5, s > 0 ? s : this.barSpacing);
  }

  /** The one write path of the bar-space state: clamped here, never in a getter. */
  private place(left: number, spacing: number): boolean {
    if (!Number.isFinite(left)) return false; // BQ-73: no NaN ever reaches state or a uniform
    const next = clampLeft(left, this.map.length, this.plotWidth / spacing);
    const changed = this.leftIndex !== next || this.barSpacing !== spacing;
    this.barSpacing = spacing;
    this.leftIndex = next;
    return changed;
  }
}
