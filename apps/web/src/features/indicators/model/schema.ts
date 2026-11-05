// E13-S01 (#423) S1: the closed JSON Schema subset the settings form renders (SR-E13-09; IR-03,
// IR-37; D06 §8.3 frozen (1); D02 D10). Accepted per property: `type` (integer, number, string with
// `enum`, boolean), `title`, `default`, `minimum`, `maximum`, `multipleOf`, `enum`. A combinator or
// reference keyword anywhere (`$ref`, `pattern`, `oneOf`…) refuses the whole schema; an unknown
// `type` is one read-only "unsupported" row. Nothing recurses into the payload and every loop is
// bounded, so a hostile schema is refused in constant work per property, never by hanging.
import { isDecimalMultiple } from "./decimal";

/** The server's parameter-name rule (`catalogue.py` `_NAME`). */
const NAME = /^[a-z][a-z0-9_]{0,31}$/;
/** Names that could reach an object's prototype chain: dropped, never read (TM IR-14). */
const RESERVED = new Set(["__proto__", "constructor", "prototype"]);
/** `IndicatorPresetInput.params` `maxProperties` (`22`); one form never shows more. */
export const MAX_PARAMS = 64;
/**
 * Sanity bounds on a rendered name, title or option and on an enum's options: `22` and `24` own no
 * `maxLength` / `maxItems` for them, so they are generous and PROPOSED to `22`'s owner as contract
 * rows, never product limits (the catalogue's descriptor and output names share the text bound).
 */
export const SANITY_MAX_TEXT = 1024;
export const SANITY_MAX_ENUM = 1024;
/** Plain text only: no markup or control characters (SR-E13-09 "no HTML in titles"). */
const UNSAFE_TEXT = /[<>&\p{Cc}]/u;
const ALLOWED = new Set(["type", "title", "default", "minimum", "maximum", "multipleOf", "enum"]);
/** Keys an unsupported (nested) type may carry: allowed, never read. */
const STRUCTURAL = new Set(["properties", "items", "required", "additionalProperties"]);
const ROOT_ALLOWED = new Set(["type", "properties", "additionalProperties", "title"]);
const SUPPORTED = new Set(["boolean", "string", "integer", "number"]);

interface FieldBase {
  readonly name: string;
  readonly title: string;
}
export interface NumberField extends FieldBase {
  readonly kind: "integer" | "number";
  readonly minimum: number;
  readonly maximum: number;
  /** The decimal step; 1 for an integer without one. */
  readonly step: number;
  readonly default: number;
}
export interface EnumField extends FieldBase {
  readonly kind: "enum";
  readonly options: readonly string[];
  readonly default: string;
}
export interface BooleanField extends FieldBase {
  readonly kind: "boolean";
  readonly default: boolean;
}
/** A property outside the subset: rendered read-only, never sent (the server takes its default). */
export interface UnsupportedField extends FieldBase {
  readonly kind: "unsupported";
}
export type ParamField = NumberField | EnumField | BooleanField | UnsupportedField;
export type EditableField = Exclude<ParamField, UnsupportedField>;

export type SchemaResult =
  { readonly ok: true; readonly fields: readonly ParamField[] } | { readonly ok: false };

const REFUSED: SchemaResult = Object.freeze({ ok: false });

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const own = (record: Record<string, unknown>, key: string): unknown =>
  Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined;

const safeText = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length > 0 &&
  value.length <= SANITY_MAX_TEXT &&
  !UNSAFE_TEXT.test(value);

const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

/** The field for one property, `"unsupported"` for a shape outside the subset, `null` to refuse. */
function field(name: string, raw: unknown): ParamField | null {
  if (!isRecord(raw)) return null;
  const type = own(raw, "type");
  const supported = typeof type === "string" && SUPPORTED.has(type);
  const keys = Object.keys(raw);
  if (keys.some((key) => !ALLOWED.has(key) && (supported || !STRUCTURAL.has(key)))) return null;
  const title = own(raw, "title");
  if (!safeText(title)) return null;
  const fallback = own(raw, "default");
  const enumValues = own(raw, "enum");
  if (type === "boolean") {
    return typeof fallback === "boolean"
      ? { kind: "boolean", name, title, default: fallback }
      : null;
  }
  if (type === "string" && enumValues !== undefined) {
    if (
      !Array.isArray(enumValues) ||
      enumValues.length === 0 ||
      enumValues.length > SANITY_MAX_ENUM
    ) {
      return null;
    }
    const options: string[] = [];
    const seen = new Set<string>();
    for (const option of enumValues as unknown[]) {
      if (!safeText(option) || seen.has(option)) return null;
      seen.add(option);
      options.push(option);
    }
    if (typeof fallback !== "string" || !options.includes(fallback)) return null;
    return { kind: "enum", name, title, options: Object.freeze(options), default: fallback };
  }
  if (type === "integer" || type === "number") {
    if (enumValues !== undefined) return null;
    const minimum = own(raw, "minimum");
    const maximum = own(raw, "maximum");
    const multipleOf = own(raw, "multipleOf");
    if (minimum === undefined || maximum === undefined) return { kind: "unsupported", name, title };
    if (!finite(minimum) || !finite(maximum) || minimum > maximum) return null;
    if (multipleOf !== undefined && (!finite(multipleOf) || multipleOf <= 0)) return null;
    const step = typeof multipleOf === "number" ? multipleOf : 1;
    if (type === "integer" && !Number.isInteger(step)) return null;
    if (type === "number" && multipleOf === undefined) return { kind: "unsupported", name, title };
    const candidate: NumberField = { kind: type, name, title, minimum, maximum, step, default: 0 };
    if (!finite(fallback) || checkNumber(candidate, fallback) !== null) return null;
    return { ...candidate, default: fallback };
  }
  return { kind: "unsupported", name, title };
}

export type ValueRule = "type" | "minimum" | "maximum" | "multipleOf" | "enum";

/** The first keyword a numeric value breaks, in the server's order (`_checked`), or `null`. */
export function checkNumber(spec: NumberField, value: number): ValueRule | null {
  if (!Number.isFinite(value)) return "type";
  if (spec.kind === "integer" && !Number.isInteger(value)) return "type";
  if (value < spec.minimum) return "minimum";
  if (value > spec.maximum) return "maximum";
  return isDecimalMultiple(value, spec.step) ? null : "multipleOf";
}

/** The first keyword `value` breaks for `spec`, or `null` when it is valid. */
export function checkValue(spec: EditableField, value: unknown): ValueRule | null {
  switch (spec.kind) {
    case "boolean":
      return typeof value === "boolean" ? null : "type";
    case "enum":
      return typeof value === "string" && spec.options.includes(value) ? null : "enum";
    case "integer":
    case "number":
      return typeof value === "number" ? checkNumber(spec, value) : "type";
  }
}

/** The descriptor's `params_schema` as form fields in property order, or refused (SR-E13-09). */
export function parseParamsSchema(raw: unknown): SchemaResult {
  if (!isRecord(raw)) return REFUSED;
  if (Object.keys(raw).some((key) => !ROOT_ALLOWED.has(key))) return REFUSED;
  if (own(raw, "type") !== "object") return REFUSED;
  const additional = own(raw, "additionalProperties");
  if (additional !== undefined && additional !== false) return REFUSED;
  const properties = own(raw, "properties") ?? {};
  if (!isRecord(properties)) return REFUSED;
  const names = Object.keys(properties);
  if (names.length > MAX_PARAMS) return REFUSED;
  const fields: ParamField[] = [];
  for (const name of names) {
    if (RESERVED.has(name)) continue;
    if (!NAME.test(name)) return REFUSED;
    const parsed = field(name, properties[name]);
    if (parsed === null) return REFUSED;
    fields.push(Object.freeze(parsed));
  }
  return Object.freeze({ ok: true, fields: Object.freeze(fields) });
}

export const isEditable = (spec: ParamField): spec is EditableField => spec.kind !== "unsupported";
