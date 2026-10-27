// CMP-020 NumericText formatting (E05-D02 conv. 16, §5 E14): '.' decimal and ',' grouping in every
// locale, zero never signed, an abbreviated value carries its expanded reading. The fixed-decimal body
// comes from `formatNumeric` (exact, no float drift, never "-0"); this file adds grouping, sign and units.
import { formatNumeric } from "./numeric.js";

export type NumericFormat = "price" | "qty" | "pct" | "pnl" | "notional";
export type SignDisplay = "auto" | "always" | "never";
export type NumericSign = "positive" | "negative" | "zero";

/** Decimals when `precision` is omitted, from the drawn examples ('-420.00', '-0.250', '1.2M'). */
export const DEFAULT_PRECISION: Readonly<Record<NumericFormat, number>> = {
  price: 2,
  qty: 3,
  pct: 2,
  pnl: 2,
  notional: 1,
};

/** `notional` abbreviates from 1,000 (E14 leaves the threshold to the stories). */
const UNITS: ReadonlyArray<readonly [number, string]> = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];

export interface DisplayNumber {
  /** The visible text. */
  readonly text: string;
  /**
   * What assistive technology reads instead of `text`: the full value of an abbreviation
   * ("1,200,000"), or "no value" for "—". Absent when the text reads as it is.
   */
  readonly expanded?: string;
  /** Sign of the value as displayed (after rounding); absent when the value is not finite. */
  readonly sign?: NumericSign;
}

const group = (body: string): string => {
  const [whole = "", frac] = body.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac === undefined ? grouped : `${grouped}.${frac}`;
};

/**
 * Fixed decimals of a magnitude. Rounding is `toFixed`'s, on the binary double (950.55 is
 * 950.5499…, so "950.5"): fine for display only, never for order values. Beyond 15 significant
 * digits the whole part is exact and the decimals are zeros, so the column stays aligned.
 */
const fixed = (abs: number, precision: number): string =>
  formatNumeric(abs, precision) ||
  `${BigInt(Math.round(abs)).toString()}${precision > 0 ? `.${"0".repeat(precision)}` : ""}`;

const MAX_PRECISION = 15;
/** `formatNumeric` throws outside 0..15; a display value clamps instead of failing the render. */
const clampPrecision = (precision: number): number =>
  Number.isFinite(precision) ? Math.min(MAX_PRECISION, Math.max(0, Math.trunc(precision))) : 0;

const isZero = (body: string): boolean => /^[0.,]*$/.test(body);

const withSign = (body: string, negative: boolean, signDisplay: SignDisplay): string =>
  isZero(body) || signDisplay === "never"
    ? body
    : negative
      ? `-${body}`
      : signDisplay === "always"
        ? `+${body}`
        : body;

/**
 * Formats a display-only number. `pct` takes percentage points (12.5 → "12.50%"). `pnl` is always
 * signed whatever `signDisplay` says. A non-finite value renders "—", read as "no value", with no
 * sign. `precision` is clamped to 0..15.
 */
export function formatDisplayNumber(
  value: number,
  format: NumericFormat,
  opts: { readonly precision?: number; readonly signDisplay?: SignDisplay } = {},
): DisplayNumber {
  const precision = clampPrecision(opts.precision ?? DEFAULT_PRECISION[format]);
  const signDisplay = format === "pnl" ? "always" : (opts.signDisplay ?? "auto");
  if (!Number.isFinite(value)) return { text: "—", expanded: "no value" };
  const negative = value < 0;
  const abs = Math.abs(value);
  let index = format === "notional" ? UNITS.findIndex(([size]) => abs >= size) : -1;
  let body = fixed(index < 0 ? abs : abs / (UNITS[index]?.[0] ?? 1), precision);
  // The unit follows the rounded body: 999.96 is "1.0K" and 999,960 "1.0M", never "1000.0K".
  if (format === "notional" && index !== 0 && Number(body) >= 1000) {
    index = index < 0 ? UNITS.length - 1 : index - 1;
    body = fixed(abs / (UNITS[index]?.[0] ?? 1), precision);
  }
  const sign: NumericSign = isZero(body) ? "zero" : negative ? "negative" : "positive";
  const suffix = format === "pct" ? "%" : index < 0 ? "" : (UNITS[index]?.[1] ?? "");
  const text = `${withSign(group(body), negative, signDisplay)}${suffix}`;
  if (index < 0) return { text, sign };
  const cents = fixed(abs, Math.max(precision, 2));
  const full = cents.includes(".") ? cents.replace(/0+$/, "").replace(/\.$/, "") : cents;
  return { text, expanded: withSign(group(full), negative, signDisplay), sign };
}
