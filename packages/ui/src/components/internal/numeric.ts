// CMP-008 core logic (E05-D02 conv. 27): explicit decimal `precision`, "." decimal, no locale
// guessing, no grouping. Arithmetic is on scaled integers (BigInt), never float `x + step`.

export type ParseResult =
  | { readonly ok: true; readonly value: number }
  | { readonly ok: false; readonly reason: "empty" | "not-a-number" | "too-many-decimals" };
export type NumericRange = { readonly min?: number; readonly max?: number };
export type Validity = "in-range" | "below-min" | "above-max";

const NUMBER_RE = /^([+-]?)(\d*)(?:\.(\d*))?$/;

const toScaled = (value: number, precision: number): bigint =>
  BigInt(value.toFixed(precision).replace(".", ""));

const fromScaled = (scaled: bigint, precision: number): string => {
  const digits = (scaled < 0n ? -scaled : scaled).toString().padStart(precision + 1, "0");
  const cut = digits.length - precision;
  const body = precision === 0 ? digits : `${digits.slice(0, cut)}.${digits.slice(cut)}`;
  return scaled < 0n ? `-${body}` : body;
};

/** Fixed decimal string, "." separator, no grouping, "-0" never produced. */
export const formatNumeric = (value: number, precision: number): string =>
  fromScaled(toScaled(value, precision), precision);

/** Parses typed text; never clamps and never rounds (extra non-zero decimals are refused). */
export const parseNumericInput = (
  text: string,
  opts: { readonly precision: number },
): ParseResult => {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: false, reason: "empty" };
  const m = NUMBER_RE.exec(trimmed);
  const [, sign = "", whole = "", frac = ""] = m ?? [];
  if (m === null || (whole === "" && frac === "")) return { ok: false, reason: "not-a-number" };
  if (/[^0]/.test(frac.slice(opts.precision))) return { ok: false, reason: "too-many-decimals" };
  const scaled = BigInt(
    `${whole}${frac.slice(0, opts.precision).padEnd(opts.precision, "0")}` || "0",
  );
  return { ok: true, value: Number(fromScaled(sign === "-" ? -scaled : scaled, opts.precision)) };
};

/** Typed values are only ever judged, never clamped. */
export const validateNumeric = (value: number, { min, max }: NumericRange): Validity =>
  min !== undefined && value < min
    ? "below-min"
    : max !== undefined && value > max
      ? "above-max"
      : "in-range";

/** value +/- step * multiplier (a whole number) on scaled integers; clamps to min/max. */
export const stepValue = (
  value: number,
  step: number,
  direction: "up" | "down",
  multiplier: number,
  precision: number,
  min?: number,
  max?: number,
): number => {
  const delta = toScaled(step, precision) * BigInt(multiplier);
  let next = toScaled(value, precision) + (direction === "up" ? delta : -delta);
  if (max !== undefined && next > toScaled(max, precision)) next = toScaled(max, precision);
  if (min !== undefined && next < toScaled(min, precision)) next = toScaled(min, precision);
  return Number(fromScaled(next, precision));
};

/** `aria-valuetext`: the formatted value with its unit ("5 %"). */
export const valueText = (value: number, precision: number, suffix?: string): string =>
  suffix ? `${formatNumeric(value, precision)} ${suffix}` : formatNumeric(value, precision);
