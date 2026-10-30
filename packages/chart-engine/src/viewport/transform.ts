// The single projection (E11-S03, US-CHART-007 NFR): every renderer, hit-test and the DOM mirror
// map time, bar index and price to screen through these functions and no second implementation.
// ESLint fails any arithmetic on `priceLow` / `priceHigh` outside this module. CPU maths is
// float64 in CSS px (BQ-74); `writePaneUniforms` is the one per-pane, per-frame hand-off to the
// GPU, as relative values only: no float32 ever holds an absolute price or µs epoch (BQ-75).
import type { IndexTimeMap, PaneTransform, ViewportState } from "./types.js";

const DEFAULT_BAR_US = 60e6;
/** Ticks and bar indices stay inside ±2^30 so their Int32 uniform bases never wrap (BQ-75). */
export const INT32_TICKS = 2 ** 30;
const NO_PANE: PaneTransform = {
  priceLow: 0,
  priceHigh: 1,
  scaleMode: "linear",
  plotTop: 0,
  plotHeight: 0,
};

const paneOf = (vp: ViewportState, pane: number): Readonly<PaneTransform> =>
  vp.panes[pane] ?? NO_PANE;

function barUs(map: IndexTimeMap): number {
  const n = map.length;
  const d = map.barDurationUs ?? (n >= 2 ? map.indexToTime(n - 1) - map.indexToTime(n - 2) : 0);
  return d > 0 ? d : DEFAULT_BAR_US;
}

/** The µs time at fractional index `f`: interpolated inside the map, extrapolated outside (BQ-66). */
export function timeAt(map: IndexTimeMap, f: number): number {
  const n = map.length;
  if (n === 0) return f * barUs(map);
  if (f <= 0) return map.indexToTime(0) + f * barUs(map);
  if (f >= n - 1) return map.indexToTime(n - 1) + (f - n + 1) * barUs(map);
  const i = Math.floor(f);
  const t0 = map.indexToTime(i);
  return t0 + (f - i) * (map.indexToTime(i + 1) - t0);
}

/** The fractional index at µs time `t`, O(log n): the inverse of `timeAt`. */
export function indexAt(map: IndexTimeMap, t: number): number {
  const n = map.length;
  if (n === 0) return t / barUs(map);
  const first = map.indexToTime(0);
  if (t <= first) return (t - first) / barUs(map);
  const last = map.indexToTime(n - 1);
  if (t >= last) return n - 1 + (t - last) / barUs(map);
  const i = map.timeToIndex(t);
  const t0 = map.indexToTime(i);
  return i + (t - t0) / (map.indexToTime(i + 1) - t0);
}

/** The x of bar i's centre (BQ-68). */
export function indexToScreen(vp: ViewportState, i: number): number {
  return (i + 0.5 - vp.leftIndex) * vp.barSpacing;
}

/** The bar under x, O(1) (BQ-68: floor, so x inside bar i gives i). */
export function screenToIndex(vp: ViewportState, x: number): number {
  return Math.floor(x / vp.barSpacing + vp.leftIndex);
}

/** A bar's open time lands on its centre, as `indexToScreen` places the bar. */
export function timeToScreen(vp: ViewportState, t: number): number {
  return indexToScreen(vp, indexAt(vp.map, t));
}

export function screenToTime(vp: ViewportState, x: number): number {
  return timeAt(vp.map, x / vp.barSpacing + vp.leftIndex - 0.5);
}

/** 26 §3.5's `ky`: px per tick, negative (screen y grows down). */
function ky(p: Readonly<PaneTransform>): number {
  return -p.plotHeight / (p.priceHigh - p.priceLow);
}

/** `sy = (p - priceLow) * ky + by`, `by` the plot's bottom edge; `tick` from `priceOrigin`. */
export function priceToScreen(vp: ViewportState, pane: number, tick: number): number {
  const p = paneOf(vp, pane);
  return (tick - p.priceLow) * ky(p) + p.plotTop + p.plotHeight;
}

/** The inverse of `priceToScreen`; a zero-height plot answers `priceLow`. */
export function screenToPrice(vp: ViewportState, pane: number, y: number): number {
  const p = paneOf(vp, pane);
  const k = ky(p);
  return k < 0 ? p.priceLow + (y - p.plotTop - p.plotHeight) / k : p.priceLow;
}

/** The setter's clamp: finite, `high >= low`; a window under one tick widens to one around it. */
export function setPriceRange(p: PaneTransform, low: number, high: number): boolean {
  // The int32 tick domain (BarStore's ticks): `u_tickBase` is an Int32 and must never wrap.
  if (!(low > -INT32_TICKS && high < INT32_TICKS) || high < low) return false;
  const pad = high - low < 1 ? (1 - (high - low)) / 2 : 0; // so `ky` stays finite in float32
  const changed = p.priceLow !== low - pad || p.priceHigh !== high + pad;
  p.priceLow = low - pad;
  p.priceHigh = high + pad;
  return changed;
}

/** One pane's GPU uniforms; preallocated per pane, rewritten in place each frame. */
export interface PaneUniforms {
  /** [`u_indexBase`, `u_tickBase`]: exact ints the shader subtracts before any float. */
  readonly ints: Int32Array;
  /** `u_k` = [barSpacing, ky, by, index fraction] in device px, then `u_viewport` [w, h]. */
  readonly floats: Float32Array;
}

export const createPaneUniforms = (): PaneUniforms => ({
  ints: new Int32Array(2),
  floats: new Float32Array(6),
});

/**
 * The uniform block (BQ-75): `x = (float(index - u_indexBase) + 0.5 - frac) * k.x` and
 * `y = float(tick - u_tickBase) * k.y + k.z`, so every float the GPU sees is a small relative value.
 */
export function writePaneUniforms(vp: ViewportState, pane: number, out: PaneUniforms): void {
  const p = paneOf(vp, pane);
  const base = Math.floor(vp.leftIndex);
  const tickBase = Math.floor(p.priceLow);
  const k = ky(p);
  const d = vp.dpr;
  out.ints[0] = base;
  out.ints[1] = tickBase;
  const f = out.floats;
  f[0] = vp.barSpacing * d;
  f[1] = k * d;
  f[2] = ((tickBase - p.priceLow) * k + p.plotTop + p.plotHeight) * d;
  f[3] = vp.leftIndex - base;
  f[4] = vp.plotWidth * d;
  f[5] = vp.height * d;
}
