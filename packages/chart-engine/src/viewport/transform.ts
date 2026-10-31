// The single projection (E11-S03, US-CHART-007 NFR): every renderer, hit-test and the DOM mirror
// map time, bar index and price to screen through these functions and no second implementation.
// ESLint fails any arithmetic on `priceLow` / `priceHigh` outside this module. CPU maths is
// float64 in CSS px (BQ-74); `writePaneUniforms` is the one per-pane, per-frame hand-off to the
// GPU, as relative values only: no float32 ever holds an absolute price or µs epoch (BQ-75).
// E11-S05: every price-scale mode is here too. Percent and indexed draw as linear (BQ-118),
// invert flips the coefficients, and log is `log1p` of the exact int tick difference times
// `tickSize / p(base)` (BQ-113); `projectRel` is the one float64 twin of the shader (BQ-114).
import type { IndexTimeMap, PaneTransform, ScaleMode, ViewportState } from "./types.js";

const DEFAULT_BAR_US = 60e6;
/** Ticks and bar indices stay inside ±2^30 so their Int32 uniform bases never wrap (BQ-75). */
export const INT32_TICKS = 2 ** 30;
/** The autoscale margin, top and bottom, as a fraction of the window (E11-D02 §5.5, BQ-117). */
export const DEFAULT_MARGIN = 0.05;
export const MAX_MARGIN = 0.45;
export const SCALE_MODES: readonly ScaleMode[] = ["linear", "log", "percent", "indexed"];

export const createPaneTransform = (): PaneTransform => ({
  priceLow: 0,
  priceHigh: 1,
  scaleMode: "linear",
  requestedMode: "linear",
  inverted: false,
  autoScale: true,
  includeDrawings: false,
  priceOnly: false,
  marginTop: DEFAULT_MARGIN,
  marginBottom: DEFAULT_MARGIN,
  priceOrigin: 0,
  tickSize: 0,
  anchorTick: Number.NaN,
  logReason: "no-price-origin",
  plotTop: 0,
  plotHeight: 0,
});
const NO_PANE = createPaneTransform();

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

/** The absolute price of `tick` (BQ-115); NaN until the pane knows its tick size. */
export const priceAt = (p: Readonly<PaneTransform>, tick: number): number =>
  p.tickSize > 0 ? p.priceOrigin + tick * p.tickSize : Number.NaN;

/** The shader clamps `log1p`'s argument here too, so a corrupt cell never yields NaN. */
export const LOG_FLOOR = -0.999999;

/** Log is drawn when asked and the window's int base is a positive price (BQ-113, BQ-120). */
const logOn = (p: Readonly<PaneTransform>): boolean =>
  p.scaleMode === "log" && priceAt(p, Math.floor(p.priceLow)) > 0;

type Coefficients = { [i: number]: number };
/** The CPU's float64 block (indices as `PaneUniforms.floats`), reused by every call. */
const CPU = new Float64Array(8);

/**
 * The y coefficients for ticks relative to `base`, in CSS px, at the block's indices: [1] `k`,
 * [2] `b`, [6] `lx` = `tickSize / p(base)`, [7] `on` (1 under log). The linear sums keep the
 * pre-S05 evaluation order in the uniform block, so linear stays bit-identical there (BQ-113).
 */
function coefficients(p: Readonly<PaneTransform>, base: number, out: Coefficients): void {
  const flip = p.inverted ? 1 : -1; // inverted: the low price at the top
  const edge = p.inverted ? 0 : p.plotHeight;
  if (logOn(p)) {
    const s0 = priceAt(p, p.priceLow);
    const k = (flip * p.plotHeight) / Math.log1p(((p.priceHigh - p.priceLow) * p.tickSize) / s0);
    out[1] = k;
    out[2] = Math.log1p(((base - p.priceLow) * p.tickSize) / s0) * k + p.plotTop + edge;
    out[6] = p.tickSize / priceAt(p, base);
    out[7] = 1;
    return;
  }
  const k = (flip * p.plotHeight) / (p.priceHigh - p.priceLow);
  out[1] = k;
  out[2] = (base - p.priceLow) * k + p.plotTop + edge;
  out[6] = 0;
  out[7] = 0;
}

/**
 * BQ-114: the shader's y in float64, `mix(rel, log1p(rel · lx), on) · k + b` with `rel` the tick
 * difference from the block's base. The 2D painter calls it on the uniform block; `priceToScreen`
 * (drawings, hit-testing, hover, the axis) on the CPU block: one mapping for every path.
 */
export function projectRel(c: ArrayLike<number>, rel: number): number {
  const on = c[7] ?? 0;
  const x = Math.max(rel * (c[6] ?? 0), LOG_FLOOR);
  return (rel * (1 - on) + Math.log1p(x) * on) * (c[1] ?? 0) + (c[2] ?? 0);
}

/** The inverse of `projectRel`: the relative tick at y (0 on a zero-height plot). */
export function unprojectRel(c: ArrayLike<number>, y: number): number {
  const k = c[1] ?? 0;
  if (k === 0) return 0;
  const u = (y - (c[2] ?? 0)) / k;
  return (c[7] ?? 0) === 1 ? Math.expm1(u) / (c[6] ?? 1) : u;
}

/** `sy` for every mode (26 §3.5): through `projectRel` from `priceLow`; `tick` from `priceOrigin`. */
export function priceToScreen(vp: ViewportState, pane: number, tick: number): number {
  const p = paneOf(vp, pane);
  coefficients(p, p.priceLow, CPU);
  return projectRel(CPU, tick - p.priceLow);
}

/** The inverse of `priceToScreen`; a zero-height plot answers `priceLow`. */
export function screenToPrice(vp: ViewportState, pane: number, y: number): number {
  const p = paneOf(vp, pane);
  coefficients(p, p.priceLow, CPU);
  return p.priceLow + unprojectRel(CPU, y);
}

/** The axis/readout value (BQ-118): a price, or % change / index from the anchor bar's close. */
export function displayValue(p: Readonly<PaneTransform>, tick: number): number {
  const v = priceAt(p, tick);
  if (p.scaleMode === "linear" || p.scaleMode === "log") return v;
  const a = priceAt(p, p.anchorTick);
  if (!(Math.abs(a) > 0)) return Number.NaN; // no anchor (or a zero close): no percentage
  return p.scaleMode === "percent" ? ((v - a) / Math.abs(a)) * 100 : (v / a) * 100;
}

/** The mode's own axis: ticks when affine, ln(price) under log (zoom, pan and the fit). */
const toAxis = (p: Readonly<PaneTransform>, log: boolean, tick: number): number =>
  log ? Math.log(priceAt(p, tick)) : tick;
const fromAxis = (p: Readonly<PaneTransform>, log: boolean, m: number): number =>
  log ? (Math.exp(m) - p.priceOrigin) / p.tickSize : m;

/**
 * Autoscale's fit (BQ-117): ticks [lo, hi] plus the margins as fractions of the window, in log
 * space under log, so a margin can never push the low price to 0 or below.
 */
export function fitPriceRange(p: PaneTransform, lo: number, hi: number): boolean {
  const log = p.scaleMode === "log" && priceAt(p, Math.floor(lo)) > 0;
  const a = toAxis(p, log, lo);
  const b = toAxis(p, log, hi);
  const w = (b - a) / (1 - p.marginTop - p.marginBottom);
  return setPriceRange(
    p,
    fromAxis(p, log, a - p.marginBottom * w),
    fromAxis(p, log, b + p.marginTop * w),
  );
}

/** Price zoom about y (BQ-122): `factor` > 1 zooms in; the price under y stays put. */
export function zoomPrice(p: PaneTransform, y: number, factor: number): boolean {
  if (!(factor > 0) || !Number.isFinite(factor) || !Number.isFinite(y)) return false;
  const log = logOn(p);
  coefficients(p, p.priceLow, CPU);
  const at = toAxis(p, log, p.priceLow + unprojectRel(CPU, y));
  const lo = toAxis(p, log, p.priceLow);
  const hi = toAxis(p, log, p.priceHigh);
  const low = fromAxis(p, log, at - (at - lo) / factor);
  return setPriceRange(p, low, fromAxis(p, log, at + (hi - at) / factor));
}

/** A vertical pan by `dyPx` CSS px: the content follows the pointer (a locked scale only). */
export function panPrice(p: PaneTransform, dyPx: number): boolean {
  coefficients(p, p.priceLow, CPU);
  const k = CPU[1] ?? 0;
  if (k === 0 || !Number.isFinite(dyPx)) return false;
  const log = logOn(p);
  const d = -dyPx / k;
  const low = fromAxis(p, log, toAxis(p, log, p.priceLow) + d);
  return setPriceRange(p, low, fromAxis(p, log, toAxis(p, log, p.priceHigh) + d));
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
  /**
   * `u_k` = [barSpacing, ky, by, index fraction] in device px, `u_viewport` [w, h], then `u_log`
   * [tickSize / p(u_tickBase), on] (E11-S05): [0, 0] for every affine mode.
   */
  readonly floats: Float32Array;
}

export const createPaneUniforms = (): PaneUniforms => ({
  ints: new Int32Array(2),
  floats: new Float32Array(8),
});

/**
 * The uniform block (BQ-75): `x = (float(index - u_indexBase) + 0.5 - frac) * k.x` and, with
 * `t = float(tick - u_tickBase)`, `y = mix(t, log1p(t * u_log.x), u_log.y) * k.y + k.z`, so every
 * float the GPU sees is a small relative value or a ratio (BQ-113).
 */
export function writePaneUniforms(vp: ViewportState, pane: number, out: PaneUniforms): void {
  const p = paneOf(vp, pane);
  const base = Math.floor(vp.leftIndex);
  const tickBase = Math.floor(p.priceLow);
  coefficients(p, tickBase, CPU);
  const d = vp.dpr;
  out.ints[0] = base;
  out.ints[1] = tickBase;
  const f = out.floats;
  f[0] = vp.barSpacing * d;
  f[1] = (CPU[1] ?? 0) * d;
  f[2] = (CPU[2] ?? 0) * d;
  f[3] = vp.leftIndex - base;
  f[4] = vp.plotWidth * d;
  f[5] = vp.height * d;
  f[6] = CPU[6] ?? 0;
  f[7] = CPU[7] ?? 0;
}
