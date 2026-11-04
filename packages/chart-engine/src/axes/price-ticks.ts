// Price-axis tick candidates (E11-S06, README BQ-186 to BQ-188; E11-D02 §4.2, §5.2): steps from
// `{1, 2, 5} × 10^n` ticks (whole ticks, so labels stay on the tick grid), as many as the density
// gap G allows (ideal = range / ⌊paneHeight / G⌋); majors at the smallest decimal-round price
// ≥ 2 steps that the step divides. Log runs decades plus 2× / 5× (decimation keeps those that
// clear the gap) and falls back to the linear ladder when fewer than two are in view; percent
// and indexed run the same ladder in `displayValue` space. The window comes from the transform's
// own inverse at the pane's edges and every y from `priceToScreen`: no second projection.
import { displayValue, priceAt, priceToScreen, screenToPrice } from "../viewport/transform.js";
import type { ViewportState } from "../viewport/types.js";
import type { TickSet } from "./decimate.js";
import { decimalsOf, formatNumber } from "./format.js";

const LADDER = [1, 2, 5] as const;
const ROUND = [1, 5] as const;
const EPS = 1e-9;
/** Candidates run this many density gaps past each pane edge, as hidden blockers (BQ-189). */
export const MARGIN_GAPS = 3;

/** The first `{1, 2, 5} × 10^n` at or above `ideal`, and at least `floor`. */
export function niceStep(ideal: number, floor = 0): number {
  const want = Math.max(ideal, floor);
  if (!(want > 0) || !Number.isFinite(want)) return 1;
  let m = 10 ** Math.floor(Math.log10(want));
  for (;;) {
    for (const f of LADDER) if (f * m >= want * (1 - EPS)) return f * m;
    m *= 10;
  }
}

/** E11-D02 §4.2: the smallest `10^k` or `5 × 10^k` ≥ 2 × `step` that `step` divides. */
export function majorOf(step: number): number {
  let m = 10 ** Math.floor(Math.log10(2 * step));
  for (let k = 0; k < 8; k += 1, m *= 10) {
    for (const c of ROUND) {
      const r = (c * m) / step;
      if (r >= 2 - EPS && Math.abs(r - Math.round(r)) < 1e-6) return c * m;
    }
  }
  return 10 * step;
}

/** What the labels say: a price, a signed percentage or an index (E11-S05 BQ-118). */
export const PRICE_KIND = { price: 0, percent: 1, indexed: 2 } as const;

/** One pane's price candidates; label text is cached by value until the format changes. */
export class PriceTicks {
  kind: number = PRICE_KIND.price;
  decimals = 0;
  /** ⌊log10⌋ of the largest |label value|: the gutter's magnitude class (BQ-201). */
  magnitude = 0;
  /** The pane window in ticks, from the transform's inverse at its edges. */
  lo = 0;
  hi = 0;
  private readonly cache = new Map<number, string>();
  private cacheKey = -1;
  private maxAbs = 0;
  // The pass's inputs, held for `add` (a method, so a pass allocates no closure).
  private vp: ViewportState | null = null;
  private pane = 0;
  private top = 0;
  private height = 0;
  private labelH = 0;
  private margin = 0;
  private set: TickSet | null = null;

  /** Fills `set` for pane `pane` laid out over [top, top + height]; labels are `labelH` high. */
  update(
    vp: ViewportState,
    pane: number,
    top: number,
    height: number,
    gap: number,
    labelH: number,
    set: TickSet,
  ): void {
    set.clear();
    this.maxAbs = 0;
    const p = vp.panes[pane];
    if (p === undefined || !(p.tickSize > 0) || !(height > 0) || !(gap > 0)) return;
    this.vp = vp;
    this.pane = pane;
    this.top = top;
    this.height = height;
    this.labelH = labelH;
    this.set = set;
    const a = screenToPrice(vp, pane, top);
    const b = screenToPrice(vp, pane, top + height);
    const lo = (this.lo = Math.min(a, b));
    const hi = (this.hi = Math.max(a, b));
    const n = Math.max(1, Math.floor(height / gap));
    this.margin = MARGIN_GAPS * gap;
    const ea = screenToPrice(vp, pane, top - this.margin);
    const eb = screenToPrice(vp, pane, top + height + this.margin);
    const elo = Math.min(ea, eb);
    const ehi = Math.max(ea, eb);
    const d0 = displayValue(p, lo);
    const d1 = displayValue(p, hi);
    const linear = p.scaleMode !== "percent" && p.scaleMode !== "indexed";
    if (!linear && Number.isFinite(d0) && Number.isFinite(d1) && d1 !== d0) {
      const step = niceStep(Math.abs(d1 - d0) / n);
      const major = majorOf(step);
      this.format(p.scaleMode === "percent" ? PRICE_KIND.percent : PRICE_KIND.indexed, step);
      const e0 = displayValue(p, elo);
      const e1 = displayValue(p, ehi);
      const k1 = Math.floor(Math.max(e0, e1) / step + EPS);
      for (let k = Math.ceil(Math.min(e0, e1) / step - EPS); k <= k1; k += 1) {
        const v = k * step;
        const r = v / major;
        const tick = lo + ((v - d0) / (d1 - d0)) * (hi - lo);
        this.add(tick, v, 0, Math.abs(r - Math.round(r)) < 1e-6, v);
      }
    } else if (!(p.scaleMode === "log" && this.logTicks(elo, ehi) >= 2)) {
      set.clear();
      this.maxAbs = 0;
      this.format(PRICE_KIND.price, p.tickSize);
      const origin = Math.round(p.priceOrigin / p.tickSize);
      const step = niceStep((hi - lo) / n, 1);
      const major = Math.round(majorOf(step * p.tickSize) / p.tickSize);
      const last = Math.floor(origin + ehi);
      for (let t = Math.ceil((origin + elo) / step) * step; t <= last; t += step) {
        this.add(t - origin, t, t % major === 0 ? 1 : 0, t % major === 0, t * p.tickSize);
      }
    }
    this.magnitude = this.maxAbs > 0 ? Math.floor(Math.log10(this.maxAbs)) : 0;
  }

  /** One candidate at `tick`: identity `value`, label value `v`; outside the pane, none. */
  private add(tick: number, value: number, rank: number, major: boolean, v: number): void {
    const vp = this.vp as ViewportState;
    const y = priceToScreen(vp, this.pane, tick);
    if (!(y >= this.top - this.margin && y <= this.top + this.height + this.margin)) return;
    let text = this.cache.get(value);
    if (text === undefined) {
      const s = formatNumber(v, this.decimals);
      text = this.kind === PRICE_KIND.percent ? `${v > 0 ? "+" : ""}${s}%` : s;
      if (this.cache.size > 512) this.cache.clear();
      this.cache.set(value, text);
    }
    this.maxAbs = Math.max(this.maxAbs, Math.abs(v));
    this.set?.push(y, this.labelH, rank, value, major ? 1 : 0, text);
  }

  /** Decades (rank 1) and their 2× / 5× (rank 0) in view; returns how many were added. */
  private logTicks(lo: number, hi: number): number {
    const p = this.vp?.panes[this.pane];
    if (p === undefined || !(priceAt(p, lo) > 0)) return 0;
    this.format(PRICE_KIND.price, p.tickSize);
    const plo = priceAt(p, lo);
    const phi = priceAt(p, hi);
    let count = 0;
    for (let e = Math.floor(Math.log10(plo)); e <= Math.ceil(Math.log10(phi)); e += 1) {
      for (const c of LADDER) {
        const v = c * 10 ** e;
        if (v < plo || v > phi) continue;
        // Identity in whole-grid ticks, as the linear ladder's, so the two share the text cache.
        this.add((v - p.priceOrigin) / p.tickSize, v / p.tickSize, c === 1 ? 1 : 0, c === 1, v);
        count += 1;
      }
    }
    return count;
  }

  /** The label format: the text cache is dropped when the kind or the decimals change. */
  private format(kind: number, step: number): void {
    this.kind = kind;
    this.decimals = decimalsOf(step);
    const key = kind * 16 + this.decimals;
    if (key !== this.cacheKey) this.cache.clear();
    this.cacheKey = key;
  }
}
