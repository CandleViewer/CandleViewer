/**
 * Fixed-point decimals for the worked example's sizing port (E28-S01, SR-E28-09): a `bigint` scaled
 * by 10^30, so a price, a quantity step and a fee rate are exact and a quotient rounds as the server
 * rounds it (`candleviewer.accounts.sizer` works at 100 digits, rounding down; 30 places is past every
 * lot step and tick the contract can hold, 18). `apps/web` takes no decimal library (no new dependency
 * for one preview); never `number` for a money figure (`AGENTS.md` §5).
 */
export type Dec = bigint;

const PLACES = 30;
const SCALE = 10n ** BigInt(PLACES);

export const ZERO: Dec = 0n;

/** A plain decimal string (`"64000.0"`, `"-1.5"`, `"0.001"`); anything else is `null`. */
export function dec(text: string): Dec | null {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text.trim());
  if (m === null) return null;
  const frac = (m[3] ?? "").slice(0, PLACES).padEnd(PLACES, "0");
  const value = BigInt(m[2] ?? "0") * SCALE + BigInt(frac === "" ? "0" : frac);
  return m[1] === "-" ? -value : value;
}

/** Like `dec`, for a value the caller has already validated. */
export function decOf(text: string): Dec {
  const value = dec(text);
  if (value === null) throw new RangeError(`not a decimal: ${text}`);
  return value;
}

export const int = (n: number): Dec => BigInt(n) * SCALE;

/** The value with no exponent and no trailing zeros (`"0.416"`, `"26624"`). */
export function show(value: Dec): string {
  const sign = value < 0n ? "-" : "";
  const abs = value < 0n ? -value : value;
  const whole = abs / SCALE;
  const frac = (abs % SCALE).toString().padStart(PLACES, "0").replace(/0+$/, "");
  return `${sign}${whole.toString()}${frac === "" ? "" : `.${frac}`}`;
}

function divRound(n: bigint, d: bigint, up: boolean): bigint {
  if (d === 0n) throw new RangeError("division by zero");
  const q = n / d;
  const exact = q * d === n;
  if (exact) return q;
  const negative = n < 0n !== d < 0n;
  // `/` truncates toward 0: floor moves a negative one down, ceiling a positive one up
  if (up) return negative ? q : q + 1n;
  return negative ? q - 1n : q;
}

export const add = (a: Dec, b: Dec): Dec => a + b;
export const sub = (a: Dec, b: Dec): Dec => a - b;
export const mul = (a: Dec, b: Dec, up = false): Dec => divRound(a * b, SCALE, up);
export const div = (a: Dec, b: Dec, up = false): Dec => divRound(a * SCALE, b, up);
export const max = (a: Dec, b: Dec): Dec => (a > b ? a : b);
export const min = (a: Dec, b: Dec): Dec => (a < b ? a : b);
export const positive = (a: Dec): Dec => (a > 0n ? a : 0n);
export const abs = (a: Dec): Dec => (a < 0n ? -a : a);

/** `value` on the grid of `step`, rounded down (`up` false) or up. */
export function toGrid(value: Dec, step: Dec, up = false): Dec {
  return divRound(value, step, up) * step;
}
