/**
 * Money and prices as exact decimals (E29-S01 #911, the ticket's "Decimal-safe money"; D02 D-7): a
 * wire decimal string (`22` `Decimal`, `23` §13 `decimal`) becomes a scaled `BigInt` and never a JS
 * `number`, so a sum, an R or a liquidation distance is exact until the one display rounding. The
 * display itself (grouping, U+2212, `+`) is `packages/ui`'s `decimalText`; this module computes.
 */

/** `value = units / 10^scale`, `scale >= 0`. */
export interface Decimal {
  readonly units: bigint;
  readonly scale: number;
}

/** `22` `Decimal` and `23` §13 `decimal`: plain digits, an optional sign and fraction, no exponent. */
const DECIMAL = /^-?[0-9]+(\.[0-9]+)?$/;
/** `numeric(38,18)` (`21` §3.3.7) holds 38 digits; a wire value past this many is refused. */
export const MAX_DIGITS = 64;

const TEN = 10n;
const pow10 = (n: number): bigint => TEN ** BigInt(n);

export const ZERO: Decimal = Object.freeze({ units: 0n, scale: 0 });

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

/** A decimal from a trusted literal (a threshold constant); throws on a typo. */
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

export function sum(values: readonly Decimal[]): Decimal {
  return values.reduce(add, ZERO);
}

/** `n / d` rounded half away from zero (`d` never 0). */
function roundedQuotient(n: bigint, d: bigint): bigint {
  const q = n / d; // truncates toward zero
  const r = n % d;
  if (r === 0n) return q;
  const twice = (r < 0n ? -r : r) * 2n;
  if (twice < (d < 0n ? -d : d)) return q;
  return n < 0n === d < 0n ? q + 1n : q - 1n;
}

/** `a` at `scale` places, half away from zero (a display rounding, D-7). */
export function round(a: Decimal, scale: number): Decimal {
  if (scale >= a.scale) return { units: rescale(a, scale), scale };
  return { units: roundedQuotient(a.units, pow10(a.scale - scale)), scale };
}

/** `a / b` at `scale` places, half away from zero; `null` when `b` is zero. */
export function div(a: Decimal, b: Decimal, scale: number): Decimal | null {
  if (b.units === 0n) return null;
  // a/b = (A·10^sb) / (B·10^sa); at `scale` places that is (A·10^(sb+scale)) / (B·10^sa)
  const n = a.units * pow10(b.scale + scale);
  const d = b.units * pow10(a.scale);
  return { units: roundedQuotient(n, d), scale };
}

/** Plain text at the decimal's own scale (`-0` never written): a wire-shaped decimal again. */
export function toPlain(a: Decimal): string {
  const negative = a.units < 0n;
  const digits = (negative ? -a.units : a.units).toString().padStart(a.scale + 1, "0");
  const whole = a.scale === 0 ? digits : digits.slice(0, digits.length - a.scale);
  const text = a.scale === 0 ? whole : `${whole}.${digits.slice(digits.length - a.scale)}`;
  return negative ? `-${text}` : text;
}

/** The same value without trailing fraction zeros (`63980.0` → `63980`), as the WS mapper writes it. */
export function normalise(a: Decimal): Decimal {
  let { units, scale } = a;
  while (scale > 0 && units % TEN === 0n) {
    units /= TEN;
    scale -= 1;
  }
  return { units, scale };
}

/** Two wire strings name the same amount (`0.250` and `0.25`); `false` when either is no decimal. */
export function sameAmount(a: unknown, b: unknown): boolean {
  const x = parseDecimal(a);
  const y = parseDecimal(b);
  return x !== null && y !== null && cmp(x, y) === 0;
}
