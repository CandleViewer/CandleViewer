// E24-S08 (#783) slice 1 (BQ 2, ruled (6612480577): a recorded deviation until E24-T04 serves a live basis): exact decimal-string arithmetic for the live basis readout.
// The ticket says the client does no arithmetic beyond formatting, but `/market/metrics` serves `basis`
// only on the latest bar and `23` §14.8's ticker carries `mark_price` / `index_price` / `last_price`, not a
// basis. Until the engine serves a live basis, the readout takes one exact subtraction and one rounded
// percentage on the served decimal strings, through BigInt: never a float, never a changed digit. Both go
// away when the engine serves them (E24-T04 follow-up).

/** One decimal: optional minus, 1-30 integer digits, up to 18 decimals (`22` / `23` decimal strings). */
export const DECIMAL = /^(-?)(\d{1,30})(?:\.(\d{1,18}))?$/;

export const isDecimalString = (v: unknown): v is string =>
  typeof v === "string" && DECIMAL.test(v);

interface Scaled {
  readonly units: bigint;
  readonly places: number;
}

function scaled(value: string, places: number): Scaled | null {
  const m = DECIMAL.exec(value);
  if (m === null) return null;
  const [, sign = "", int = "", frac = ""] = m;
  const units = BigInt(`${int}${frac.padEnd(places, "0")}`);
  return { units: sign === "-" ? -units : units, places };
}

const fracLength = (value: string): number => (DECIMAL.exec(value)?.[3] ?? "").length;

function render(units: bigint, places: number): string {
  const negative = units < 0n;
  const digits = (negative ? -units : units).toString().padStart(places + 1, "0");
  const int = digits.slice(0, digits.length - places);
  const frac = digits.slice(digits.length - places);
  const body = places === 0 ? int : `${int}.${frac}`;
  return negative ? `-${body}` : body;
}

/** `a − b`, exact, at the finer of the two operands' decimals; `null` if either is not a decimal. */
export function subtractDecimals(a: string, b: string): string | null {
  const places = Math.max(fracLength(a), fracLength(b));
  const x = scaled(a, places);
  const y = scaled(b, places);
  if (x === null || y === null) return null;
  return render(x.units - y.units, places);
}

/**
 * `numerator / denominator × 100` rounded half away from zero to `places` decimals, as a string; `null`
 * for a non-decimal or a zero denominator. A result that rounds to zero carries no sign.
 */
export function percentOf(numerator: string, denominator: string, places: number): string | null {
  const scale = Math.max(fracLength(numerator), fracLength(denominator));
  const n = scaled(numerator, scale);
  const d = scaled(denominator, scale);
  if (n === null || d === null || d.units === 0n) return null;
  const negative = n.units < 0n !== d.units < 0n;
  const absN = n.units < 0n ? -n.units : n.units;
  const absD = d.units < 0n ? -d.units : d.units;
  const q = (2n * absN * 100n * 10n ** BigInt(places) + absD) / (2n * absD);
  return render(negative ? -q : q, places);
}
