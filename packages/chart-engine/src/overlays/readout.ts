// The readout field model (E11-S07, CMP-197; E11-D02 §7.3, E06-D03 D1/D5): the ordered fields
// O, H, L, C, Vol, Δ, then each provider's (E13's indicators), formatted at the instrument's tick
// precision through `axes/format.ts`, plus the bar time and the cursor's full and short spoken
// summaries. The field array and its objects are pooled: `build` rewrites them only when the bar,
// the snap, the providers or the data at that bar changed, and allocates nothing otherwise.
// Values are read at the bar (never interpolated); a missing volume or delta reads "unavailable",
// never 0. DOM-free.
import {
  clockText,
  createZoned,
  dateText,
  decimalsOf,
  formatNumber,
  ZoneClock,
} from "../axes/format.js";
import type { SnapField } from "./crosshair.js";

/** One series' bars as columns (µs time, ticks from `priceOrigin`); `BarView` fits structurally. */
export interface BarSource {
  readonly time: ArrayLike<number>;
  readonly open: ArrayLike<number>;
  readonly high: ArrayLike<number>;
  readonly low: ArrayLike<number>;
  readonly close: ArrayLike<number>;
  readonly volume?: ArrayLike<number> | null;
  readonly delta?: ArrayLike<number> | null;
  readonly priceOrigin: number;
  readonly tickSize: number;
  readonly length: number;
}

export interface ReadoutField {
  key: string;
  label: string;
  value: string;
  unit: string;
  colorToken: string;
}

/** E13's seam: a visible series' value at a bar, already formatted; null reads "unavailable". */
export interface ReadoutProvider {
  readonly key: string;
  readonly label: string;
  readonly unit?: string;
  readonly colorToken?: string;
  value(bar: number): string | null;
}

export const UNAVAILABLE = "unavailable";
/** E11-D02 §7.3 D10: values are never coloured by direction (glyph and sign carry it). */
export const VALUE_TOKEN = "color.text.primary";
const MINUS = "−";

const BASE = [
  ["open", "O", "Open"],
  ["high", "H", "High"],
  ["low", "L", "Low"],
  ["close", "C", "Close"],
  ["volume", "Vol", "Volume"],
  ["delta", "Δ", "Delta"],
] as const;
const BASE_COUNT = BASE.length;
/** time, open, high, low, close, volume, delta at the cached bar. */
const RAW = 7;

const field = (): ReadoutField => ({ key: "", label: "", value: "", unit: "", colorToken: "" });

/** "+200", "−128", "0" (sign as text, E11-D02 D10). */
export function signedText(v: number, decimals: number): string {
  const s = formatNumber(Math.abs(v), decimals);
  if (s === formatNumber(0, decimals)) return s;
  return (v < 0 ? MINUS : "+") + s;
}

/** A float32 quantity's decimals: at most 3, at float32's 7 significant digits (no noise). */
const qtyDecimals = (v: number): number => Math.min(3, decimalsOf(Number(v.toPrecision(7))));

/** Volume at its own precision (up to 3 decimals). */
export const volumeText = (v: number): string => formatNumber(v, qtyDecimals(v));

const read = (col: ArrayLike<number> | null | undefined, i: number): number => {
  if (col === null || col === undefined) return Number.NaN;
  const v = col[i];
  return v === undefined ? Number.NaN : v;
};

export class Readout {
  /** The pooled, ordered fields; its identity never changes. Empty without a bar. */
  readonly fields: ReadoutField[] = [];
  /** "14 Oct 13:42" in the chart's zone (BQ-17); "" without a bar. */
  timeText = "";
  /** The full spoken form, "14:05, close 64,210, delta −128" (E06-D03 D1/D5). */
  full = "";
  /** The held-key form, "14:12, 64,232" (E06-D03 D5). */
  short = "";
  /** Count of rebuilds (tests and the counters). */
  rebuilds = 0;

  private readonly clock: ZoneClock;
  private readonly zoned = createZoned();
  private readonly pool: ReadoutField[] = [];
  private providers: readonly ReadoutProvider[] = [];
  private providerRev = 0;
  private readonly raw = new Float64Array(RAW).fill(Number.NaN);
  private src: BarSource | null = null;
  private bar = -2;
  private snap: SnapField = null;
  private rev = -1;
  private origin = Number.NaN;
  private tickSize = Number.NaN;

  constructor(timeZone = "UTC") {
    this.clock = new ZoneClock(timeZone);
  }

  /** E13's providers, in order after Δ; the next `build` rebuilds. */
  setProviders(providers: readonly ReadoutProvider[]): void {
    this.providers = providers;
    this.providerRev += 1;
  }

  /** Forces the next `build` to rebuild (a provider's value changed at the same bar). */
  invalidate(): void {
    this.providerRev += 1;
  }

  /**
   * The fields for `bar` of `src`, labelling the snapped field in full ("High", AC6). True when
   * the fields were rewritten; false (and no allocation) when nothing they read has changed.
   */
  build(src: BarSource | null, bar: number, snap: SnapField): boolean {
    const n = src === null ? 0 : src.length;
    const valid = src !== null && bar >= 0 && bar < n && src.tickSize > 0;
    let same =
      src === this.src &&
      bar === this.bar &&
      snap === this.snap &&
      this.rev === this.providerRev &&
      (src === null || (src.priceOrigin === this.origin && src.tickSize === this.tickSize));
    if (valid) same = this.sameRaw(src, bar) && same;
    if (same) return false;
    this.src = src;
    this.bar = bar;
    this.snap = snap;
    this.rev = this.providerRev;
    this.origin = src === null ? Number.NaN : src.priceOrigin;
    this.tickSize = src === null ? Number.NaN : src.tickSize;
    this.rebuilds += 1;
    if (!valid) {
      this.raw.fill(Number.NaN);
      this.fields.length = 0;
      this.timeText = "";
      this.full = "";
      this.short = "";
      return true;
    }
    this.write(src, bar, snap);
    return true;
  }

  /** Records the bar's raw values; true when all equal the previous ones (NaN equals NaN). */
  private sameRaw(src: BarSource, i: number): boolean {
    let same = this.rec(0, read(src.time, i));
    same = this.rec(1, read(src.open, i)) && same;
    same = this.rec(2, read(src.high, i)) && same;
    same = this.rec(3, read(src.low, i)) && same;
    same = this.rec(4, read(src.close, i)) && same;
    same = this.rec(5, read(src.volume, i)) && same;
    return this.rec(6, read(src.delta, i)) && same;
  }

  private rec(k: number, v: number): boolean {
    const same = Object.is(this.raw[k], v);
    this.raw[k] = v;
    return same;
  }

  private slot(k: number): ReadoutField {
    let f = this.pool[k];
    if (f === undefined) {
      f = field();
      this.pool[k] = f;
    }
    this.fields[k] = f;
    return f;
  }

  private write(src: BarSource, bar: number, snap: SnapField): void {
    const raw = this.raw;
    const dec = decimalsOf(src.tickSize);
    const price = (tick: number): string =>
      Number.isFinite(tick)
        ? formatNumber(src.priceOrigin + tick * src.tickSize, dec)
        : UNAVAILABLE;
    for (let k = 0; k < BASE_COUNT; k += 1) {
      const [key, short, long] = BASE[k] as (typeof BASE)[number];
      const f = this.slot(k);
      const v = raw[k + 1] ?? Number.NaN;
      f.key = key;
      f.label = key === snap ? long : short;
      f.unit = "";
      f.colorToken = VALUE_TOKEN;
      if (k < 4) f.value = price(v);
      else if (!Number.isFinite(v)) f.value = UNAVAILABLE;
      else f.value = k === 4 ? volumeText(v) : signedText(v, qtyDecimals(v));
    }
    // The direction glyph after the close (E11-D02 §7.3); equal open and close carry none.
    const o = raw[1] ?? Number.NaN;
    const c = raw[4] ?? Number.NaN;
    const close = this.fields[3];
    if (close !== undefined && c > o) close.value += " ▲";
    else if (close !== undefined && c < o) close.value += " ▼";
    const ps = this.providers;
    for (let p = 0; p < ps.length; p += 1) {
      const pr = ps[p] as ReadoutProvider;
      const f = this.slot(BASE_COUNT + p);
      const v = pr.value(bar);
      f.key = `ind:${pr.key}`;
      f.label = pr.label;
      f.value = v === null ? UNAVAILABLE : v;
      f.unit = pr.unit ?? "";
      f.colorToken = pr.colorToken ?? VALUE_TOKEN;
    }
    this.fields.length = BASE_COUNT + ps.length;
    const t = raw[0] ?? Number.NaN;
    const z = this.clock.fields(t / 1000, this.zoned);
    const hm = Number.isFinite(t) ? clockText(z.ms, false) : UNAVAILABLE;
    this.timeText = Number.isFinite(t) ? `${dateText(z)} ${hm}` : UNAVAILABLE;
    const closeText = price(c);
    const d = raw[6] ?? Number.NaN;
    const deltaText = Number.isFinite(d) ? signedText(d, qtyDecimals(d)) : UNAVAILABLE;
    this.full = `${hm}, close ${closeText}, delta ${deltaText}`;
    this.short = `${hm}, ${closeText}`;
  }
}
