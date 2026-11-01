/**
 * SCR-103's number formatting (E08-D06 §5 F1-F5, F8): decimal strings in, decimal strings out. Every value is
 * parsed into a BigInt and a scale and never passes through `Number`, `toFixed` or `Intl` (F1). An exponent form
 * the shipped serialiser can print (`1E-7`, CR-3) is expanded exactly first (F2); anything else unparsable
 * has no text, and the caller shows "—" and reports it (`symbol.info_value_malformed`).
 */

/** `unscaled * 10^-scale`, with `scale >= 0`. */
export interface Dec {
  readonly unscaled: bigint;
  readonly scale: number;
}

/** F2's `kind`: an exponent form that was expanded, or a value that could not be read. */
export type Malformed = "exponent" | "unparsable";

export type Parsed =
  { readonly ok: true; readonly dec: Dec; readonly exponent: boolean } | { readonly ok: false };

/** `22`'s `Decimal`. */
const PLAIN = /^(-?)([0-9]+)(?:\.([0-9]+))?$/;
/** What `str(Decimal)` can print besides `PLAIN`: `1E-7`, `1.5E+3`. */
const EXPONENT = /^(-?)([0-9]+)(?:\.([0-9]+))?[eE]([+-]?[0-9]+)$/;
/** An exponent past this is not a price or a quantity; it would only allocate a huge BigInt. */
const MAX_EXPONENT = 60;
/** Digits past this are not a contract value either. */
const MAX_DIGITS = 80;

export function parseDecimal(input: string): Parsed {
  const plain = PLAIN.exec(input);
  if (plain !== null) {
    const [, sign = "", whole = "", fraction = ""] = plain;
    if (whole.length + fraction.length > MAX_DIGITS) return { ok: false };
    const unscaled = BigInt(`${whole}${fraction}`) * (sign === "-" ? -1n : 1n);
    return { ok: true, dec: { unscaled, scale: fraction.length }, exponent: false };
  }
  const found = EXPONENT.exec(input);
  if (found === null) return { ok: false };
  const [, sign = "", whole = "", fraction = "", exp = "0"] = found;
  const power = Number(exp);
  if (Math.abs(power) > MAX_EXPONENT || whole.length + fraction.length > MAX_DIGITS) {
    return { ok: false };
  }
  const digits = BigInt(`${whole}${fraction}`) * (sign === "-" ? -1n : 1n);
  const scale = fraction.length - power;
  const dec: Dec =
    scale < 0
      ? { unscaled: digits * 10n ** BigInt(-scale), scale: 0 }
      : { unscaled: digits, scale };
  return { ok: true, dec, exponent: true };
}

/** The positional text of `dec`, every one of its fraction digits kept ("0.10" stays "0.10"). */
export function toPositional(dec: Dec): string {
  const negative = dec.unscaled < 0n;
  const digits = (negative ? -dec.unscaled : dec.unscaled).toString().padStart(dec.scale + 1, "0");
  const whole = digits.slice(0, digits.length - dec.scale);
  const fraction = digits.slice(digits.length - dec.scale);
  return `${negative ? "-" : ""}${whole}${dec.scale > 0 ? `.${fraction}` : ""}`;
}

/** F3: trailing fraction zeros dropped, never a significant digit; zero has no sign. */
export function minimal(dec: Dec): Dec {
  let { unscaled, scale } = dec;
  while (scale > 0 && unscaled % 10n === 0n) {
    unscaled /= 10n;
    scale -= 1;
  }
  return { unscaled, scale };
}

/** `dec` with exactly `scale` fraction digits (`scale` at least its own). */
export function pad(dec: Dec, scale: number): Dec {
  return { unscaled: dec.unscaled * 10n ** BigInt(Math.max(scale - dec.scale, 0)), scale };
}

/** Equal by value: "0.10" and "0.1" are the same rule. */
export function sameValue(a: Dec, b: Dec): boolean {
  const scale = Math.max(a.scale, b.scale);
  return pad(a, scale).unscaled === pad(b, scale).unscaled;
}

/** F8: a comma groups the integer part only, the point is `.`, whatever the locale. */
export function group(positional: string): string {
  const negative = positional.startsWith("-");
  const [whole = "", fraction] = (negative ? positional.slice(1) : positional).split(".");
  const grouped = whole.replace(/\B(?=([0-9]{3})+(?![0-9]))/g, ",");
  return `${negative ? "-" : ""}${grouped}${fraction === undefined ? "" : `.${fraction}`}`;
}

/** A value as the drawer shows it: `text` is `null` for "—"; `malformed` is what to report, once per field. */
export interface Shown {
  readonly text: string | null;
  readonly malformed: Malformed | null;
}

const UNREADABLE: Shown = { text: null, malformed: "unparsable" };

/** F3 and F8: a rule value (tick, step, quantities, minimum value, leverage), minimal and grouped. */
export function formatRule(input: string | null | undefined): Shown {
  if (typeof input !== "string") return { text: null, malformed: null };
  const parsed = parseDecimal(input);
  if (!parsed.ok) return UNREADABLE;
  return {
    text: group(toPositional(minimal(parsed.dec))),
    malformed: parsed.exponent ? "exponent" : null,
  };
}

/**
 * F4 and F5: a price or quantity at the larger of its step's decimals (the step in minimal form) and its own
 * significant decimals, never rounded. With no step yet (`null`, or one that cannot be read) the value's own
 * decimals are shown as delivered: never a default precision.
 */
export function formatAtStep(input: string | null | undefined, step: string | null): Shown {
  if (typeof input !== "string") return { text: null, malformed: null };
  const parsed = parseDecimal(input);
  if (!parsed.ok) return UNREADABLE;
  const malformed = parsed.exponent ? "exponent" : null;
  const stepParsed = step === null ? null : parseDecimal(step);
  if (stepParsed === null || !stepParsed.ok) {
    return { text: group(toPositional(parsed.dec)), malformed };
  }
  const scale = Math.max(minimal(stepParsed.dec).scale, minimal(parsed.dec).scale);
  return { text: group(toPositional(pad(minimal(parsed.dec), scale))), malformed };
}
