// Exact stepping for the in-cell number editor (E29-S02 BQ-11; E29-D02 §7, E29-D01 D12). A price or a quantity is
// the wire's decimal string (`cv://ws/v1/common.schema.json#/$defs/decimal`), stepped by the instrument's tick or
// lot on a scaled BigInt and never through a binary double. Nothing here rounds: a typed value off the step stays
// off it and is reported so ("without its blur auto-round", D02 §7), and a step lands on a multiple of the step.
// Typed text may carry the grid's own thousands grouping ("2,495.00", `15` CMP-008): well-formed groups of three
// are dropped, and anything else with a comma is no number ("2,5" is never 25: in a price that is a 10x error).

/** A non-negative decimal as an exact scaled integer: its value is `units / 10^scale`. */
export interface StepDecimal {
  readonly units: bigint;
  readonly scale: number;
}

/**
 * Longest text read, sign and point included: a bound on the work `BigInt` does, set above `numeric(38,18)`'s 38
 * digits (`21` §3.3.7) as `decimalText` and the web model's `decimal.ts` do.
 */
export const MAX_TEXT = 66;

/** The wire's decimal (the host's `value`, `step` and `min`): digits, an optional fraction, no sign or exponent. */
const WIRE = /^[0-9]+(?:\.[0-9]+)?$/;
/** What a person may type once trimmed: the wire's form, or a bare leading or trailing point (".5", "5."). */
const TYPED = /^([0-9]*)(?:\.([0-9]*))?$/;
/** The same with well-formed thousands grouping: one to three digits, then groups of exactly three ("2,495.00"). */
const GROUPED = /^([0-9]{1,3}(?:,[0-9]{3})+)(?:\.([0-9]*))?$/;

const pow10 = (n: number): bigint => 10n ** BigInt(n);

function fromParts(whole: string, fraction: string): StepDecimal {
  return { units: BigInt(`${whole}${fraction}` || "0"), scale: fraction.length };
}

/** The host's decimal string, or null for anything else (a sign, an exponent, a space, junk, too long). */
export function parseWire(text: string): StepDecimal | null {
  if (text.length > MAX_TEXT || !WIRE.test(text)) return null;
  const [whole = "", fraction = ""] = text.split(".");
  return fromParts(whole, fraction);
}

/**
 * Typed text, trimmed: the wire's form, ".5" / "5.", or either with well-formed grouping, which is dropped
 * ("2,495.00" is 2495.00); null for "", ".", a sign, malformed grouping ("2,5", "12,34") or anything else.
 */
export function parseTyped(text: string): StepDecimal | null {
  const trimmed = text.trim();
  if (trimmed.length > MAX_TEXT) return null;
  const match = GROUPED.exec(trimmed) ?? TYPED.exec(trimmed);
  if (match === null) return null;
  const [, whole = "", fraction = ""] = match;
  if (whole === "" && fraction === "") return null;
  return fromParts(whole.replaceAll(",", ""), fraction);
}

/** Plain text at the value's own scale: "0.050" stays "0.050"; never a grouping comma, never an exponent. */
export function toText(value: StepDecimal): string {
  const digits = value.units.toString().padStart(value.scale + 1, "0");
  if (value.scale === 0) return digits;
  const cut = digits.length - value.scale;
  return `${digits.slice(0, cut)}.${digits.slice(cut)}`;
}

/**
 * The same value at `scale` places when that loses no digit (`2500` at 2 is `2500.00`); a finer value keeps its own
 * scale, so nothing is ever dropped or rounded.
 */
export function widen(value: StepDecimal, scale: number): StepDecimal {
  if (scale <= value.scale) return value;
  return { units: value.units * pow10(scale - value.scale), scale };
}

function aligned(a: StepDecimal, b: StepDecimal): readonly [bigint, bigint] {
  const scale = Math.max(a.scale, b.scale);
  return [widen(a, scale).units, widen(b, scale).units];
}

/** Numeric order, whatever the scales (`0.50` equals `0.5`). */
export function compareDecimal(a: StepDecimal, b: StepDecimal): -1 | 0 | 1 {
  const [x, y] = aligned(a, b);
  return x === y ? 0 : x < y ? -1 : 1;
}

/** Whether `value` is a whole multiple of `step` (> 0), exactly. */
export function isOnStep(value: StepDecimal, step: StepDecimal): boolean {
  const [v, s] = aligned(value, step);
  return s > 0n && v % s === 0n;
}

/** Why typed text cannot be committed, or the value it spells. */
export type StepCheck =
  | { readonly kind: "ok"; readonly value: StepDecimal }
  | { readonly kind: "empty" | "not_a_number" | "not_positive" | "off_step" | "below_min" };

/**
 * Judges typed text against the step and the lowest valid value, in that order of reasons: no number, zero or less
 * (a minus sign before a number included: "-5" is below zero, not "no number"), off the step, below `min`. It never
 * rounds: "2495.03" on a 0.1 tick is `off_step`, never 2495.0.
 */
export function checkTyped(text: string, step: StepDecimal, min?: StepDecimal): StepCheck {
  const trimmed = text.trim();
  if (trimmed === "") return { kind: "empty" };
  const value = parseTyped(trimmed);
  if (value === null) {
    const negative = trimmed.startsWith("-") && parseTyped(trimmed.slice(1)) !== null;
    return { kind: negative ? "not_positive" : "not_a_number" };
  }
  if (value.units <= 0n) return { kind: "not_positive" };
  if (!isOnStep(value, step)) return { kind: "off_step" };
  if (min !== undefined && compareDecimal(value, min) < 0) return { kind: "below_min" };
  return { kind: "ok", value };
}

export type StepDirection = "up" | "down";

/**
 * One press: `times` steps (a whole number, at least 1) from `value` in `direction`, at the step's scale. A value on
 * the step moves by `times` steps; a value off it lands first on the adjacent multiple in that direction, which
 * counts as the first step. The result is never below the smallest positive multiple of the step that is at least
 * `min`, so a step down never reaches zero.
 */
export function stepFrom(
  value: StepDecimal,
  step: StepDecimal,
  direction: StepDirection,
  times: number,
  min?: StepDecimal,
): StepDecimal {
  if (!Number.isSafeInteger(times) || times < 1)
    throw new RangeError("times must be a whole number >= 1");
  if (step.units <= 0n) throw new RangeError("step must be above zero");
  const [v, s] = aligned(value, step);
  const quotient = v / s; // both non-negative, so this is the floor
  const onStep = v % s === 0n;
  const n = BigInt(times);
  let k = direction === "up" ? quotient + n : onStep ? quotient - n : quotient - n + 1n;
  const floor = lowestMultiple(step, min);
  if (k < floor) k = floor;
  return { units: k * step.units, scale: step.scale };
}

/** The index of the smallest positive multiple of `step` that is at least `min` (1 without one). */
function lowestMultiple(step: StepDecimal, min: StepDecimal | undefined): bigint {
  if (min === undefined) return 1n;
  const [m, s] = aligned(min, step);
  const k = m / s + (m % s === 0n ? 0n : 1n);
  return k < 1n ? 1n : k;
}
