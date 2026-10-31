// CMP-161 WatchlistRow's number formats (E08-D07 D9, D22): display only, never parsed back. The fixed-decimal body
// comes from `formatNumeric` (exact, no float drift, never "-0"); this file adds grouping, U+2212, the sign, the
// ▲/▼ glyph, significant figures and the countdown.
import { formatNumeric } from "./numeric.js";

/** D9: a negative is written with U+2212 MINUS SIGN, never a hyphen-minus. */
export const MINUS = "−";
/** An absent value (E08-D07 §4.2: named by the cell, "no value yet" or "no 24 h baseline"). */
export const NO_VALUE = "—";

export type WatchlistSign = "positive" | "negative" | "zero";

/** A signed value as drawn: the text with its sign, the glyph that goes with it, and the sign itself. */
export interface SignedText {
  readonly text: string;
  readonly glyph: "▲" | "▼" | "";
  readonly sign: WatchlistSign;
}

const MAX_SCALE = 15;
const clampScale = (scale: number): number =>
  Number.isFinite(scale) ? Math.min(MAX_SCALE, Math.max(0, Math.trunc(scale))) : 0;

const group = (body: string): string => {
  const [whole = "", frac] = body.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac === undefined ? grouped : `${grouped}.${frac}`;
};

const isZero = (body: string): boolean => /^[0.,]*$/.test(body);

/** The magnitude at `decimals`, grouped; "" when it cannot be represented (beyond 15 scaled digits). */
const magnitude = (value: number, decimals: number): string =>
  group(formatNumeric(Math.abs(value), clampScale(decimals)));

/** `body` with its sign: U+2212 for a negative, `+` for a positive when `plus`; zero never signed. */
const signed = (body: string, negative: boolean, plus: boolean): string =>
  isZero(body) ? body : negative ? `${MINUS}${body}` : plus ? `+${body}` : body;

/** D9 Last (and every price column): the instrument's `price_scale`, thousands grouped: "64,012.50". */
export function formatWatchlistPrice(value: number | undefined, scale: number): string {
  if (value === undefined || !Number.isFinite(value)) return NO_VALUE;
  const body = magnitude(value, scale);
  return body === "" ? NO_VALUE : signed(body, value < 0, false);
}

/** D9 24h % and OI Δ: percentage points at 2 dp, signed, with ▲/▼; zero is "0.00%" with neither. */
export function formatSignedPct(points: number, decimals = 2): SignedText {
  if (!Number.isFinite(points)) return { text: NO_VALUE, glyph: "", sign: "zero" };
  const body = magnitude(points, decimals);
  if (isZero(body)) return { text: `${body}%`, glyph: "", sign: "zero" };
  const negative = points < 0;
  return {
    text: `${signed(body, negative, true)}%`,
    glyph: negative ? "▼" : "▲",
    sign: negative ? "negative" : "positive",
  };
}

/** D9 Funding %: percentage points at 4 dp with the sign, never coloured: "+0.0100%". */
export function formatFundingPct(points: number): string {
  return Number.isFinite(points) ? formatSignedPct(points, 4).text : NO_VALUE;
}

const UNITS: ReadonlyArray<readonly [number, string]> = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];

/** The decimals that leave `scaled` (below 1,000) with three significant figures. */
const sigDecimals = (scaled: number): number =>
  scaled === 0 ? 0 : Math.max(0, 3 - (Math.floor(Math.log10(scaled)) + 1));

/** `x` to three significant figures; a rounding that carries into a new digit (0.9996 → 1.00) drops a decimal. */
const threeFigures = (x: number): string => {
  const decimals = sigDecimals(x);
  const body = formatNumeric(x, decimals);
  const carried = sigDecimals(Number(body));
  return carried < decimals ? formatNumeric(x, carried) : body;
};

/**
 * D9 turnover (and the other optional sizes): three significant figures with K, M or B ("1.20B", "840M"), and the
 * whole number, rounded and grouped, for the cell's name ("1,200,000,000"). A value that rounds up to 1,000 of a
 * unit takes the next one: 999,600 is "1.00M", never "1000K".
 */
export function formatSigFigs(value: number): { readonly text: string; readonly full: string } {
  if (!Number.isFinite(value)) return { text: NO_VALUE, full: NO_VALUE };
  const negative = value < 0;
  const abs = Math.abs(value);
  let index = UNITS.findIndex(([size]) => abs >= size);
  const at = (i: number): number => (i < 0 ? abs : abs / (UNITS[i]?.[0] ?? 1));
  let body = threeFigures(at(index));
  if (Number(body) >= 1000 && index !== 0) {
    index = index < 0 ? UNITS.length - 1 : index - 1;
    body = threeFigures(at(index));
  }
  const unit = index < 0 ? "" : (UNITS[index]?.[1] ?? "");
  return {
    text: `${signed(body, negative, false)}${unit}`,
    full: signed(group(formatNumeric(abs, 0)), negative, false),
  };
}

/** D9 spread in bps, 2 dp, never coloured: "0.02". */
export function formatSpreadBps(bps: number): string {
  if (!Number.isFinite(bps)) return NO_VALUE;
  return signed(magnitude(bps, 2), bps < 0, false);
}

const pad = (n: number): string => String(n).padStart(2, "0");

/**
 * D22: whole seconds left as `hh:mm:ss` ("05:28:51"). Under a second, zero or past: `undefined`, which the row
 * draws as "Settling…" until a new target arrives.
 */
export function formatCountdown(msLeft: number): string | undefined {
  if (!Number.isFinite(msLeft)) return undefined;
  const seconds = Math.floor(msLeft / 1000);
  if (seconds <= 0) return undefined;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds % 60)}`;
}

/** A UTC wall-clock time: "16:00:00 UTC" (the countdown's target in its name). */
export function formatUtcTime(ms: number): string {
  const at = new Date(ms);
  return `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}:${pad(at.getUTCSeconds())} UTC`;
}
