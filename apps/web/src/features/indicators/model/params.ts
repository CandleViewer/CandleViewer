// E13-S01 (#423) S1: parameter objects. Every value that reaches an instance (typed, from a preset,
// from a bundle) is re-validated here first (BQ-11); the result is a complete, frozen,
// null-prototype object in the schema's order (SR-E13-09, TM IR-14). Reject, never clamp (D02 D11).
import {
  checkValue,
  isEditable,
  type EditableField,
  type ParamField,
  type ValueRule,
} from "./schema";
import type { ParamValue, Params, WsIndicatorInstance } from "./types";

/** Keys that could reach a prototype chain: dropped, never read (TM IR-14). */
const RESERVED = new Set(["__proto__", "constructor", "prototype"]);

export interface ParamError {
  readonly name: string;
  readonly rule: ValueRule | "additionalProperties";
}

export type ParamsResult =
  | { readonly ok: true; readonly params: Params }
  | { readonly ok: false; readonly errors: readonly ParamError[] };

function freezeParams(entries: readonly (readonly [string, ParamValue])[]): Params {
  const out = Object.create(null) as Record<string, ParamValue>;
  for (const [name, value] of entries) out[name] = value;
  return Object.freeze(out);
}

/** The defaults of every editable field: the params of a fresh instance. */
export const defaultParams = (fields: readonly ParamField[]): Params =>
  freezeParams(fields.filter(isEditable).map((f) => [f.name, f.default] as const));

/**
 * `input` checked against `fields`: an absent value takes its default, an undeclared key is
 * `additionalProperties`, and every defect is reported (the form marks each field). An
 * unsupported field is never sent, so the server applies its default (`23` §6.1).
 */
export function validateParams(fields: readonly ParamField[], input: unknown): ParamsResult {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return { ok: false, errors: [{ name: "", rule: "type" }] };
  }
  const record = input as Record<string, unknown>;
  const declared = new Map<string, ParamField>(fields.map((f) => [f.name, f]));
  const errors: ParamError[] = [];
  for (const key of Object.keys(record)) {
    if (RESERVED.has(key)) continue;
    const spec = declared.get(key);
    if (spec === undefined || !isEditable(spec))
      errors.push({ name: key, rule: "additionalProperties" });
  }
  const entries: [string, ParamValue][] = [];
  for (const spec of fields) {
    if (!isEditable(spec)) continue;
    const present = Object.prototype.hasOwnProperty.call(record, spec.name);
    const value = present ? record[spec.name] : spec.default;
    const rule = checkValue(spec, value);
    if (rule !== null) errors.push({ name: spec.name, rule });
    else entries.push([spec.name, value as ParamValue]);
  }
  return errors.length > 0 ? { ok: false, errors } : { ok: true, params: freezeParams(entries) };
}

/** One field's value checked alone (the form validates on each change). */
export const validateField = (spec: EditableField, value: unknown): ValueRule | null =>
  checkValue(spec, value);

/** Params with one value replaced; the caller has validated it. */
export const withParam = (params: Params, name: string, value: ParamValue): Params =>
  freezeParams(Object.keys(params).map((k) => [k, k === name ? value : (params[k] as ParamValue)]));

/**
 * A canonical text of an indicator and its complete params: equal exactly when both are equal,
 * whatever the key order. A local identity for "already on the chart" (D02 D4), not the server's
 * `spec_hash` (`23` §6.1 `key`, read-only) nor T01's instance key.
 */
export function paramsSignature(indicator: string, params: Params): string {
  const keys = Object.keys(params).sort();
  return JSON.stringify([indicator, keys.map((k) => [k, params[k]])]);
}

/** True when `params` differ from the fields' defaults (D02 D9 "edited"). */
export function isEdited(fields: readonly ParamField[], params: Params): boolean {
  return fields.some((f) => isEditable(f) && params[f.name] !== f.default);
}

/** The `indicators.*` `sub` entry of a server instance: `indicator` and `params` only (`23` §6.1). */
export function toWsInstance(indicator: string, params: Params): WsIndicatorInstance {
  return { indicator, params: { ...params } };
}
