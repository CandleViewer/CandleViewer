// Decimal-string display (E29-S01; E29-D02 D-7, E29-D04 §2.3). Money, quantities and R arrive as the wire's
// decimal strings (`cv://ws/v1/common.schema.json#/$defs/decimal`) and are shown without ever becoming a binary
// double: rounding is half away from zero on a scaled BigInt, the minus is U+2212, a "+" leads a positive value
// when the caller asks for it, and the whole part is grouped with ",". Display only: never parse this text back for
// an order (C-2.12: the server's figure is the figure).

/** The wire's decimal: an optional "-", digits, and optional decimals (no exponent, no "+", no bare point). */
const DECIMAL = /^(-?)([0-9]+)(?:\.([0-9]+))?$/;

/** U+2212 MINUS SIGN: the minus of every signed figure (E29-D02 D-7; `05` §4.3). */
export const MINUS = "−";

/** The most decimal places a display may ask for; a request outside 0..MAX_PLACES is clamped, never thrown. */
export const MAX_PLACES = 18;

/** A decimal as an exact scaled integer: its value is `units / 10^scale`. */
export interface ScaledDecimal {
  readonly units: bigint;
  readonly scale: number;
}

/** The sign of a value as it is shown, after rounding. */
export type DecimalSign = "positive" | "negative" | "zero";

export interface DecimalText {
  /** The visible text: grouped, U+2212 for a minus, "+" on a positive value when asked; zero is never signed. */
  readonly text: string;
  /** The grouped magnitude without a sign, for a spoken reading that puts a word first ("profit 8.00"). */
  readonly magnitude: string;
  /** The sign of the value as shown: "-0.004" at two places shows "0.00", so it is zero. */
  readonly sign: DecimalSign;
}

export interface DecimalTextOptions {
  /** Places shown (the instrument's tick or lot, D02 D-7); omitted, the string's own. Clamped to 0..MAX_PLACES. */
  readonly places?: number;
  /** A "+" before a positive value (every P&L and R, D02 D-7). Zero and negative values are unaffected. */
  readonly plus?: boolean;
}

/** Parses the wire's decimal string exactly; anything else (an exponent, a "+", a space, "") is null. */
export function parseDecimal(text: string): ScaledDecimal | null {
  const match = DECIMAL.exec(text);
  if (match === null) return null;
  const [, minus = "", whole = "", fraction = ""] = match;
  const magnitude = BigInt(`${whole}${fraction}`);
  return { units: minus === "-" ? -magnitude : magnitude, scale: fraction.length };
}

/** `value` at `places` decimals, rounded half away from zero on the scaled integer, never through a double. */
export function roundDecimal(value: ScaledDecimal, places: number): ScaledDecimal {
  const drop = value.scale - places;
  if (drop <= 0) return { units: value.units * 10n ** BigInt(-drop), scale: places };
  const divisor = 10n ** BigInt(drop);
  const negative = value.units < 0n;
  const magnitude = negative ? -value.units : value.units;
  const quotient = magnitude / divisor;
  const rounded = (magnitude % divisor) * 2n >= divisor ? quotient + 1n : quotient;
  return { units: negative ? -rounded : rounded, scale: places };
}

const group = (whole: string): string => whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** The magnitude's digits with "," grouping and "." before the decimals: "1,234.05". */
function digitsOf(value: ScaledDecimal): string {
  const units = value.units < 0n ? -value.units : value.units;
  const padded = units.toString().padStart(value.scale + 1, "0");
  const cut = padded.length - value.scale;
  const whole = group(padded.slice(0, cut));
  return value.scale === 0 ? whole : `${whole}.${padded.slice(cut)}`;
}

/** A caller's places as a whole number in 0..MAX_PLACES: a display clamps rather than fail the render. */
const clampPlaces = (places: number): number =>
  Number.isFinite(places) ? Math.min(MAX_PLACES, Math.max(0, Math.trunc(places))) : 0;

/**
 * The display of a wire decimal string, or null when `text` is not one (the host then shows "—" with its spoken
 * reason). Grouping is ",", the point ".", in every locale (E05-D02 conv. 16); the minus is U+2212.
 */
export function formatDecimal(text: string, options: DecimalTextOptions = {}): DecimalText | null {
  const parsed = parseDecimal(text);
  if (parsed === null) return null;
  const value =
    options.places === undefined ? parsed : roundDecimal(parsed, clampPlaces(options.places));
  const sign: DecimalSign =
    value.units === 0n ? "zero" : value.units < 0n ? "negative" : "positive";
  const magnitude = digitsOf(value);
  const lead =
    sign === "negative" ? MINUS : sign === "positive" && options.plus === true ? "+" : "";
  return { text: `${lead}${magnitude}`, magnitude, sign };
}
