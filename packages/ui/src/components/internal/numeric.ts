// CMP-008 core logic (E05-D02 conv. 27): explicit decimal `precision`, "." decimal, no locale
// guessing, no grouping. Arithmetic is on scaled integers (BigInt), never float `x + step`.

export type ParseResult =
  | { readonly ok: true; readonly value: number; readonly rounded: boolean }
  | { readonly ok: false; readonly reason: "empty" | "not-a-number" | "too-many-digits" };
export type NumericRange = { readonly min?: number; readonly max?: number };
export type Validity = "in-range" | "below-min" | "above-max" | "not-a-number";

const NUMBER_RE = /^([+-]?)(\d*)(?:\.(\d*))?$/;
// Scaled values stay below 10^15 so Number(...) of the result is exact (2^53 > 9e15).
const MAX_DIGITS = 15;

// Programmer errors (precision / multiplier / step) throw; data problems return typed results.
const checkPrecision = (precision: number): void => {
  if (!Number.isInteger(precision) || precision < 0 || precision > MAX_DIGITS) {
    throw new RangeError(`precision must be an integer 0..${MAX_DIGITS}`);
  }
};

/** Scaled integer of an on-grid value, or null when not finite or beyond 15 scaled digits. */
const toScaled = (value: number, precision: number): bigint | null =>
  Number.isFinite(value) && Math.abs(value) * 10 ** precision < 10 ** MAX_DIGITS
    ? BigInt(value.toFixed(precision).replace(".", ""))
    : null;

const fromScaled = (scaled: bigint, precision: number): string => {
  const digits = (scaled < 0n ? -scaled : scaled).toString().padStart(precision + 1, "0");
  const cut = digits.length - precision;
  const body = precision === 0 ? digits : `${digits.slice(0, cut)}.${digits.slice(cut)}`;
  return scaled < 0n ? `-${body}` : body;
};

/** Fixed decimal string, "." separator, no grouping, "-0" never produced; "" if not representable. */
export const formatNumeric = (value: number, precision: number): string => {
  checkPrecision(precision);
  const scaled = toScaled(value, precision);
  return scaled === null ? "" : fromScaled(scaled, precision);
};

/**
 * Parses typed text and rounds it to `precision` on the decimal digits (exact, half away from
 * zero). E05-D02 G18: "on blur the value is parsed, rounded to `precision` (the host may caption
 * it '(rounded to nearest tick)') and range-checked"; `rounded` drives that caption. Never clamps:
 * the caller range-checks the rounded value with `validateNumeric`. More than 15 significant
 * digits after rounding is refused (`too-many-digits`) so no precision is lost silently.
 */
export const parseNumericInput = (
  text: string,
  opts: { readonly precision: number },
): ParseResult => {
  checkPrecision(opts.precision);
  const trimmed = text.trim();
  if (trimmed === "") return { ok: false, reason: "empty" };
  const m = NUMBER_RE.exec(trimmed);
  const [, sign = "", whole = "", frac = ""] = m ?? [];
  if (m === null || (whole === "" && frac === "")) return { ok: false, reason: "not-a-number" };
  const rest = frac.slice(opts.precision);
  const kept = `${whole}${frac.slice(0, opts.precision).padEnd(opts.precision, "0")}` || "0";
  const magnitude = BigInt(kept) + (/^[5-9]/.test(rest) ? 1n : 0n);
  if (magnitude >= 10n ** BigInt(MAX_DIGITS)) return { ok: false, reason: "too-many-digits" };
  const value = Number(fromScaled(sign === "-" ? -magnitude : magnitude, opts.precision));
  return { ok: true, value, rounded: /[^0]/.test(rest) };
};

/** Typed values are only ever judged, never clamped. Non-finite fails closed. */
export const validateNumeric = (value: number, { min, max }: NumericRange): Validity =>
  Number.isNaN(value)
    ? "not-a-number"
    : min !== undefined && value < min
      ? "below-min"
      : max !== undefined && value > max
        ? "above-max"
        : "in-range";

/**
 * value +/- step * multiplier on scaled integers; clamps to the bound value itself (min wins over
 * max). Preconditions (throw RangeError): integer precision 0..15, whole multiplier >= 0, step a
 * positive multiple of 10^-precision (a finer step would become 0). A non-representable value
 * (non-finite, > 15 scaled digits) is returned unchanged.
 */
export const stepValue = (
  value: number,
  step: number,
  direction: "up" | "down",
  multiplier: number,
  precision: number,
  min?: number,
  max?: number,
): number => {
  checkPrecision(precision);
  if (!Number.isInteger(multiplier) || multiplier < 0) {
    throw new RangeError("multiplier must be a whole number >= 0");
  }
  const unit = toScaled(step, precision);
  if (unit === null || unit <= 0n) throw new RangeError("step must be >= 10^-precision");
  const from = toScaled(value, precision);
  if (from === null) return value;
  const delta = unit * BigInt(multiplier);
  let next = Number(fromScaled(from + (direction === "up" ? delta : -delta), precision));
  if (max !== undefined && next > max) next = max;
  if (min !== undefined && next < min) next = min;
  return next;
};

/** `aria-valuetext`: the formatted value with its unit ("5 %"). */
export const valueText = (value: number, precision: number, suffix?: string): string =>
  suffix ? `${formatNumeric(value, precision)} ${suffix}` : formatNumeric(value, precision);
