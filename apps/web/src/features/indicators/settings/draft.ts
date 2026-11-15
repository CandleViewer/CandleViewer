// E13-S01 (#423) S4: the settings form's draft (SCR-035; D02 D10, D11). A draft holds what each
// field shows: a number field keeps its typed TEXT, so an invalid entry stays visible with its
// message and is never clamped, rounded or coerced (reject, never clamp). The draft is a `Map`
// keyed by the schema's own field names (never a plain object a payload key could reach through),
// and its params are re-validated by `validateParams` before anything leaves the form (BQ-11).
import { parseDecimalText } from "../model/decimal";
import { validateParams } from "../model/params";
import {
  checkNumber,
  checkValue,
  isEditable,
  type EditableField,
  type NumberField,
  type ParamField,
  type ValueRule,
} from "../model/schema";
import type { ParamValue, Params } from "../model/types";

/** A number field's text, an enum's option, a boolean's state. */
export type DraftValue = string | boolean;
export type Draft = ReadonlyMap<string, DraftValue>;

export type FieldRead =
  | { readonly ok: true; readonly value: ParamValue }
  | { readonly ok: false; readonly rule: ValueRule };

const isNumber = (spec: EditableField): spec is NumberField =>
  spec.kind === "integer" || spec.kind === "number";

/** The text a number shows: its shortest round-trip form, never a locale format. */
export const numberText = (value: number): string => String(value);

/** The draft of committed params: what the form shows on open. */
export function draftOf(fields: readonly ParamField[], params: Params): Draft {
  const draft = new Map<string, DraftValue>();
  for (const spec of fields) {
    if (!isEditable(spec)) continue;
    const has = Object.prototype.hasOwnProperty.call(params, spec.name);
    const value = has ? params[spec.name] : spec.default;
    draft.set(spec.name, typeof value === "number" ? numberText(value) : (value as DraftValue));
  }
  return draft;
}

/** One field's draft as a param value, or the first keyword it breaks (D11). */
export function readField(spec: EditableField, raw: DraftValue | undefined): FieldRead {
  if (isNumber(spec)) {
    const value = typeof raw === "string" ? parseDecimalText(raw) : null;
    if (value === null) return { ok: false, rule: "type" };
    const rule = checkNumber(spec, value);
    return rule === null ? { ok: true, value } : { ok: false, rule };
  }
  const rule = checkValue(spec, raw);
  return rule === null ? { ok: true, value: raw as ParamValue } : { ok: false, rule };
}

export interface DraftCheck {
  /** The validated params, or `null` while any field is invalid. */
  readonly params: Params | null;
  /** Each invalid field's broken keyword, in the schema's order. */
  readonly errors: ReadonlyMap<string, ValueRule>;
}

/** Every field read, then the whole object re-validated as any other input would be (BQ-11). */
export function checkDraft(fields: readonly ParamField[], draft: Draft): DraftCheck {
  const errors = new Map<string, ValueRule>();
  const values = Object.create(null) as Record<string, ParamValue>;
  for (const spec of fields) {
    if (!isEditable(spec)) continue;
    const read = readField(spec, draft.get(spec.name));
    if (read.ok) values[spec.name] = read.value;
    else errors.set(spec.name, read.rule);
  }
  if (errors.size > 0) return { params: null, errors };
  const checked = validateParams(fields, values);
  if (checked.ok) return { params: checked.params, errors };
  for (const e of checked.errors)
    errors.set(e.name, e.rule === "additionalProperties" ? "type" : e.rule);
  return { params: null, errors };
}

/** True when the field's draft is valid and differs from the catalogue default (D14 "edited"). */
export function isFieldEdited(spec: EditableField, raw: DraftValue | undefined): boolean {
  const read = readField(spec, raw);
  return read.ok && read.value !== spec.default;
}

const decimals = (step: number): number => {
  const text = String(step);
  const dot = text.indexOf(".");
  return dot < 0 ? 0 : text.length - dot - 1;
};

/**
 * The value a step key moves to (D02 D10: `↑/↓` by `step`, `PageUp/PageDown` ×10): onto the
 * step's grid, in scaled integers so 0.1 + 0.2 lands on 0.3, and never past a bound. A draft that
 * is not a number steps from the bound it would cross towards.
 */
export function stepFrom(spec: NumberField, raw: DraftValue | undefined, times: number): number {
  const parsed = typeof raw === "string" ? parseDecimalText(raw) : null;
  if (parsed === null) return times > 0 ? spec.minimum : spec.maximum;
  // The finer of the two decimal scales, so an off-grid 2.25 steps to 2.3 / 2.2, not past them.
  const scale = 10 ** Math.max(decimals(spec.step), decimals(parsed));
  const grid = Math.round(spec.step * scale);
  const at = Math.round(parsed * scale);
  const index = times > 0 ? Math.floor(at / grid) + times : Math.ceil(at / grid) + times;
  const next = (index * grid) / scale;
  return Math.min(spec.maximum, Math.max(spec.minimum, next));
}
