/**
 * Exact decimals for the ticket (#984 BQ 10): a `22` `Decimal` wire string becomes a scaled
 * `BigInt` and never a JS `number`, so a tick or lot multiple is exact and a float error never
 * becomes a `tick_size_violation` at the exchange. Self-contained and worker-safe: plain data
 * (`bigint` survives `structuredClone`), no globals. Modelled on `apps/web`'s positions helper,
 * which a package may not import (C-3.5); the rounding modes add `floor` and `ceil`, the two the
 * server's sizer uses (`24` §9.3, `accounts/sizer.py` `ROUND_FLOOR` / `ROUND_CEILING`).
 */

/** `value = units / 10^scale`, `scale >= 0`. */
export interface Decimal {
  readonly units: bigint;
  readonly scale: number;
}

/**
 * How a value leaves the exact domain: `floor` toward −∞, `ceil` toward +∞, `trunc` toward 0,
 * `half_away` to the nearest with a tie away from 0 (a display rounding only).
 */
export type RoundingMode = "floor" | "ceil" | "trunc" | "half_away";

/** `22` `Decimal`: plain digits, an optional sign and fraction, no exponent, no `+`. */
const DECIMAL = /^-?[0-9]+(\.[0-9]+)?$/;
/**
 * A wire value longer than this many characters and two (a sign and a point) is refused before
 * `BigInt` reads it: a bound on the work, above `numeric(38,18)`'s 38 digits (`21` §3.3.7).
 */
export const MAX_DIGITS = 64;
/**
 * The largest scale a decimal may be taken to (`roundTo`, `div`): twice `MAX_DIGITS`, which covers
 * the scale of a product of two parsed values. A larger target scale is refused.
 */
export const MAX_SCALE = 2 * MAX_DIGITS;

const TEN = 10n;
const pow10 = (n: number): bigint => TEN ** BigInt(n);

export const ZERO: Decimal = Object.freeze({ units: 0n, scale: 0 });
export const ONE: Decimal = Object.freeze({ units: 1n, scale: 0 });

/** The decimal a wire string spells, or `null` for anything else (a number, an exponent, junk). */
export function parseDecimal(text: unknown): Decimal | null {
  if (typeof text !== "string" || text.length > MAX_DIGITS + 2 || !DECIMAL.test(text)) return null;
  const negative = text.startsWith("-");
  const body = negative ? text.slice(1) : text;
  const dot = body.indexOf(".");
  const whole = dot < 0 ? body : body.slice(0, dot);
  const fraction = dot < 0 ? "" : body.slice(dot + 1);
  const units = BigInt(whole + fraction);
  return { units: negative ? -units : units, scale: fraction.length };
}

/** A decimal from a trusted literal (a constant or a test); throws on a typo. */
export function dec(text: string): Decimal {
  const parsed = parseDecimal(text);
  if (parsed === null) throw new TypeError(`not a decimal literal: ${text}`);
  return parsed;
}

function rescale(d: Decimal, scale: number): bigint {
  return d.units * pow10(scale - d.scale);
}

function aligned(a: Decimal, b: Decimal): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale);
  return [rescale(a, scale), rescale(b, scale), scale];
}

export function add(a: Decimal, b: Decimal): Decimal {
  const [x, y, scale] = aligned(a, b);
  return { units: x + y, scale };
}

export function sub(a: Decimal, b: Decimal): Decimal {
  const [x, y, scale] = aligned(a, b);
  return { units: x - y, scale };
}

export function mul(a: Decimal, b: Decimal): Decimal {
  return { units: a.units * b.units, scale: a.scale + b.scale };
}

export const neg = (a: Decimal): Decimal => ({ units: -a.units, scale: a.scale });
export const abs = (a: Decimal): Decimal => (a.units < 0n ? neg(a) : a);
export const sign = (a: Decimal): -1 | 0 | 1 => (a.units === 0n ? 0 : a.units < 0n ? -1 : 1);
export const isZero = (a: Decimal): boolean => a.units === 0n;

/** `-1`, `0` or `1`: numeric order, whatever the scales (`0.50` equals `0.5`). */
export function cmp(a: Decimal, b: Decimal): -1 | 0 | 1 {
  const [x, y] = aligned(a, b);
  return x === y ? 0 : x < y ? -1 : 1;
}

export const eq = (a: Decimal, b: Decimal): boolean => cmp(a, b) === 0;
export const lt = (a: Decimal, b: Decimal): boolean => cmp(a, b) < 0;
export const lte = (a: Decimal, b: Decimal): boolean => cmp(a, b) <= 0;
export const gt = (a: Decimal, b: Decimal): boolean => cmp(a, b) > 0;
export const gte = (a: Decimal, b: Decimal): boolean => cmp(a, b) >= 0;
export const min = (a: Decimal, b: Decimal): Decimal => (cmp(a, b) <= 0 ? a : b);
export const max = (a: Decimal, b: Decimal): Decimal => (cmp(a, b) >= 0 ? a : b);

/** `n / d` as an integer under `mode` (`d` never 0). */
export function divInt(n: bigint, d: bigint, mode: RoundingMode): bigint {
  const q = n / d; // truncates toward zero
  const r = n % d;
  if (r === 0n || mode === "trunc") return q;
  const positive = n < 0n === d < 0n;
  if (mode === "floor") return positive ? q : q - 1n;
  if (mode === "ceil") return positive ? q + 1n : q;
  const twice = (r < 0n ? -r : r) * 2n;
  if (twice < (d < 0n ? -d : d)) return q;
  return positive ? q + 1n : q - 1n;
}

/**
 * A target scale is an integer from 0 to `MAX_SCALE` (a count of decimal places). Anything else
 * is a programming error, refused with a `RangeError` before any work is done.
 */
function checkScale(scale: number): void {
  if (!Number.isSafeInteger(scale) || scale < 0 || scale > MAX_SCALE) {
    throw new RangeError(`a decimal scale must be an integer from 0 to ${MAX_SCALE}`);
  }
}

/**
 * `a` at `scale` places under `mode` (exact when `scale >= a.scale`). Precondition: `scale` is an
 * integer from 0 to `MAX_SCALE` (`RangeError` otherwise).
 */
export function roundTo(a: Decimal, scale: number, mode: RoundingMode): Decimal {
  checkScale(scale);
  if (scale >= a.scale) return { units: rescale(a, scale), scale };
  return { units: divInt(a.units, pow10(a.scale - scale), mode), scale };
}

/**
 * `a / b` at `scale` places under `mode`; `null` when `b` is zero. Precondition: `scale` is an
 * integer from 0 to `MAX_SCALE` (`RangeError` otherwise).
 */
export function div(a: Decimal, b: Decimal, scale: number, mode: RoundingMode): Decimal | null {
  checkScale(scale);
  if (b.units === 0n) return null;
  // a/b = (A·10^sb) / (B·10^sa); at `scale` places that is (A·10^(sb+scale)) / (B·10^sa)
  const n = a.units * pow10(b.scale + scale);
  const d = b.units * pow10(a.scale);
  return { units: divInt(n, d, mode), scale };
}

/**
 * The whole number of `step`s in `a` under `mode` — exact, at any precision: the Python sizer's
 * `(value / step).to_integral_value(rounding)` without its 100-digit context (`floor` of a
 * 100-digit floor is the exact floor). `null` when `step` is zero.
 */
export function stepsIn(a: Decimal, step: Decimal, mode: RoundingMode): bigint | null {
  if (step.units === 0n) return null;
  const [x, y] = aligned(a, step);
  return divInt(x, y, mode);
}

/** `count · step`, at the step's own scale. */
export function timesInt(step: Decimal, count: bigint): Decimal {
  return { units: step.units * count, scale: step.scale };
}

/** Plain text at the decimal's own scale (`-0` never written): a wire-shaped decimal again. */
export function toPlain(a: Decimal): string {
  const negative = a.units < 0n;
  const digits = (negative ? -a.units : a.units).toString().padStart(a.scale + 1, "0");
  const whole = a.scale === 0 ? digits : digits.slice(0, digits.length - a.scale);
  const text = a.scale === 0 ? whole : `${whole}.${digits.slice(digits.length - a.scale)}`;
  return negative ? `-${text}` : text;
}

/** The same value without trailing fraction zeros (`63980.0` → `63980`). */
export function normalise(a: Decimal): Decimal {
  let { units, scale } = a;
  while (scale > 0 && units % TEN === 0n) {
    units /= TEN;
    scale -= 1;
  }
  return { units, scale };
}
