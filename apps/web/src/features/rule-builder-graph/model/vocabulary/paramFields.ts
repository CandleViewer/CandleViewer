/**
 * The action inspector's parameter fields (E37-S02): each property of the served `params_schema`, in the order
 * served, as a descriptor the inspector draws a control for, so a new action or parameter needs no client change
 * (AC 1). Two are never plain controls: `only_tighten` is fixed at `true` wherever served (rules never loosen a
 * stop, #4137; the server refuses `false` on the three stop actions), and a placing action's `stop_loss` is its native
 * stop, never emptied (E36-D02 §8, E32-D01 §5.2 Arm A: FZ-1 on a clear attempt). Pure: no React, no DOM global.
 */
import { STOP_FIELD, stopLineOf } from "./actions.js";
import type { VocabularyAction } from "./types.js";

/**
 * The control a parameter takes: by its schema's `enum` or `type`; `value` when the schema names no type (any
 * value); `fixed` is shown, never edited; `nativeStop` keeps its value on a clear attempt.
 */
export type ParamKind =
  | "choice"
  | "number"
  | "integer"
  | "flag"
  | "text"
  | "list"
  | "group"
  | "value"
  | "fixed"
  | "nativeStop";

export type ParamScalar = string | number | boolean | null;

export interface ParamField {
  /** The `params` key, as served. */
  readonly name: string;
  readonly kind: ParamKind;
  /** In the schema's `required` list. */
  readonly required: boolean;
  /** A choice's values, as served. */
  readonly options: readonly ParamScalar[];
  /** A list's item kind. */
  readonly items: ParamKind | undefined;
  /** The served `default`; a fixed field's one value. */
  readonly initial: unknown;
  readonly minimum: number | undefined;
  readonly exclusiveMinimum: number | undefined;
  readonly maximum: number | undefined;
  readonly exclusiveMaximum: number | undefined;
}

/** The parameter values no rule may change: a stop only tightens (#4137; `24` §8.8 rule 5). */
const FIXED: Readonly<Record<string, true>> = { only_tighten: true };

const KINDS: Readonly<Record<string, ParamKind>> = {
  number: "number",
  integer: "integer",
  boolean: "flag",
  string: "text",
  array: "list",
  object: "group",
};

type Schema = Readonly<Record<string, unknown>>;

const isSchema = (value: unknown): value is Schema =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const numberOr = (value: unknown): number | undefined =>
  typeof value === "number" ? value : undefined;

const kindOf = (schema: Schema): ParamKind => {
  if (Array.isArray(schema["enum"])) return "choice";
  const type = schema["type"];
  return typeof type === "string" && Object.hasOwn(KINDS, type)
    ? (KINDS[type] as ParamKind)
    : "value";
};

const isScalar = (value: unknown): value is ParamScalar =>
  value === null || ["string", "number", "boolean"].includes(typeof value);

/** Every parameter of `action`, in the order its schema serves them. */
export function paramFields(action: VocabularyAction): ParamField[] {
  const schema = action.params_schema ?? {};
  const properties = isSchema(schema["properties"]) ? schema["properties"] : {};
  const required = Array.isArray(schema["required"]) ? schema["required"] : [];
  const stopField = stopLineOf(action).native?.kind === "field";
  return Object.entries(properties).map(([name, value]) => {
    const property = isSchema(value) ? value : {};
    const fixed = Object.hasOwn(FIXED, name);
    const kind = fixed
      ? "fixed"
      : stopField && name === STOP_FIELD
        ? "nativeStop"
        : kindOf(property);
    const values = property["enum"];
    const options = kind === "choice" && Array.isArray(values) ? values.filter(isScalar) : [];
    const items =
      kind === "list" && isSchema(property["items"]) ? kindOf(property["items"]) : undefined;
    return {
      name,
      kind,
      required: required.includes(name),
      options,
      items,
      initial: fixed ? FIXED[name] : property["default"],
      minimum: numberOr(property["minimum"]),
      exclusiveMinimum: numberOr(property["exclusiveMinimum"]),
      maximum: numberOr(property["maximum"]),
      exclusiveMaximum: numberOr(property["exclusiveMaximum"]),
    };
  });
}

/**
 * `params` as the editor writes them: a fixed parameter that holds another value takes its fixed one, and so does
 * `only_tighten` on a stop action whose schema does not serve it (`stopLineOf`'s ratchet: the validator's three stop
 * actions), so no write carries `only_tighten: false`; an absent one stays absent (its default is that value), as
 * does the rest.
 */
export function withFixedValues(
  action: VocabularyAction,
  params: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  const written: Record<string, unknown> = { ...params };
  for (const field of paramFields(action)) {
    if (field.kind === "fixed" && Object.hasOwn(written, field.name))
      written[field.name] = field.initial;
  }
  if (stopLineOf(action).ratchet === undefined) return written;
  for (const [name, value] of Object.entries(FIXED)) {
    if (Object.hasOwn(written, name)) written[name] = value;
  }
  return written;
}
