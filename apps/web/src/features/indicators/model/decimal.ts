// E13-S01 (#423) S1: exact decimal checks for a JSON number. `multipleOf` is checked in decimal on
// the value's shortest repr, as the server does (`catalogue.py` `_checked`; `24` §7.4): 0.3 is a
// multiple of 0.1 although 0.3 / 0.1 is not 3 in binary64 (D02 D10).

/** `mantissa × 10^-scale`, exactly. */
interface Exact {
  readonly mantissa: bigint;
  readonly scale: number;
}

const REPR = /^(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/;

/** A finite number at its shortest round-trip repr (what `String(x)` gives), as an exact decimal. */
function exact(value: number): Exact | null {
  if (!Number.isFinite(value)) return null;
  const match = REPR.exec(String(value));
  if (match === null) return null;
  const [, sign = "", whole = "0", fraction = "", exponent = "0"] = match;
  let scale = fraction.length - Number(exponent);
  let digits = `${whole}${fraction}`;
  if (scale < 0) {
    digits += "0".repeat(-scale);
    scale = 0;
  }
  return { mantissa: BigInt(`${sign}${digits}`), scale };
}

const scaled = (x: Exact, scale: number): bigint => x.mantissa * 10n ** BigInt(scale - x.scale);

/** True when `value` is an exact multiple of `step` (> 0) in decimal. */
export function isDecimalMultiple(value: number, step: number): boolean {
  const v = exact(value);
  const s = exact(step);
  if (v === null || s === null || s.mantissa <= 0n) return false;
  const scale = Math.max(v.scale, s.scale);
  return scaled(v, scale) % scaled(s, scale) === 0n;
}

const NUMBER_TEXT = /^-?\d+(?:\.\d+)?$/;

/**
 * A typed field value as a number, or `null` when it is not a plain decimal: no exponent, hex,
 * `Infinity` or empty string (reject, never clamp or coerce; D02 D11).
 */
export function parseDecimalText(text: string): number | null {
  const trimmed = text.trim();
  if (!NUMBER_TEXT.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}
