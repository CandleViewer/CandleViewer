/**
 * E13-S01 (#423) S1: parameter objects: complete, frozen, null-prototype (SR-E13-09, TM IR-14),
 * re-validated from any source (BQ-11), rejected and never clamped (D02 D11).
 */
import { describe, expect, it } from "vitest";
import {
  defaultParams,
  isEdited,
  paramsSignature,
  toWsInstance,
  validateField,
  validateParams,
  withParam,
} from "../../../src/features/indicators/model/params";
import {
  parseParamsSchema,
  type EditableField,
  type ParamField,
} from "../../../src/features/indicators/model/schema";
import type { Params } from "../../../src/features/indicators/model/types";
import { BOLLINGER, CVD, EMA, ZIGZAG } from "./fixtures";
import { int, SEEDS, withSeed } from "./rng";

const fieldsOf = (raw: unknown): readonly ParamField[] => {
  const result = parseParamsSchema(raw);
  if (!result.ok) throw new Error("refused");
  return result.fields;
};
const BB = fieldsOf(BOLLINGER.params_schema);
const ZZ = fieldsOf(ZIGZAG.params_schema);

const ok = (fields: readonly ParamField[], input: unknown): Params => {
  const result = validateParams(fields, input);
  if (!result.ok) throw new Error(JSON.stringify(result.errors));
  return result.params;
};

describe("validateParams", () => {
  it("completes absent values from the defaults, in the schema's order", () => {
    const params = ok(BB, { mult: 2.5 });
    expect(Object.keys(params)).toEqual(["n", "mult"]);
    expect(params).toEqual({ n: 20, mult: 2.5 });
    expect(defaultParams(BB)).toEqual({ n: 20, mult: 2 });
  });

  it("returns a frozen, null-prototype object", () => {
    const params = ok(BB, {});
    expect(Object.getPrototypeOf(params)).toBeNull();
    expect(Object.isFrozen(params)).toBe(true);
  });

  it("drops __proto__ and constructor keys: they never reach live config (TM IR-14)", () => {
    const hostile = JSON.parse(
      '{"__proto__":{"polluted":1},"constructor":{"x":1},"n":30}',
    ) as unknown;
    const params = ok(BB, hostile);
    expect(params).toEqual({ n: 30, mult: 2 });
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
  });

  it("reports every defect, an undeclared key included, and keeps nothing", () => {
    expect(validateParams(BB, { n: 0, mult: 0.15, colour: "#f00" })).toEqual({
      ok: false,
      errors: [
        { name: "colour", rule: "additionalProperties" },
        { name: "n", rule: "minimum" },
        { name: "mult", rule: "multipleOf" },
      ],
    });
  });

  it("refuses wrong types and a non-object, never coercing", () => {
    expect(validateParams(BB, { n: "21" })).toMatchObject({
      ok: false,
      errors: [{ name: "n", rule: "type" }],
    });
    expect(validateParams(fieldsOf(CVD.params_schema), { anchor: "week" })).toMatchObject({
      ok: false,
      errors: [{ name: "anchor", rule: "enum" }],
    });
    for (const input of [null, [], 21, "n=21"]) {
      expect(validateParams(BB, input)).toEqual({
        ok: false,
        errors: [{ name: "", rule: "type" }],
      });
    }
  });

  it("never sends an unsupported field, and refuses a value for one", () => {
    const fields = fieldsOf({
      type: "object",
      properties: {
        label: { type: "string", title: "Label" },
        n: { type: "integer", title: "Period", minimum: 1, maximum: 9, default: 3 },
      },
    });
    expect(ok(fields, {})).toEqual({ n: 3 });
    expect(validateParams(fields, { label: "x" })).toMatchObject({
      ok: false,
      errors: [{ name: "label", rule: "additionalProperties" }],
    });
  });

  it.each(SEEDS)(
    "seed %i: a valid object round-trips unchanged, and an out-of-bound value is refused, not clamped",
    (seed) =>
      withSeed(seed, (next) => {
        for (let i = 0; i < 300; i += 1) {
          const depth = int(next, 1, 5000);
          const deviation = int(next, 0, 500) / 10;
          const params = ok(ZZ, { depth, deviation_pct: deviation });
          expect(ok(ZZ, { ...params })).toEqual(params);
          expect(params).toEqual({ depth, deviation_pct: deviation });
          const outside = next() < 0.5 ? int(next, 5001, 1e6) : -int(next, 1, 1e6);
          const refused = validateParams(ZZ, { depth: outside });
          expect(refused.ok).toBe(false);
        }
      }),
  );
});

describe("the helpers around a parameter object", () => {
  const n = BB[0] as EditableField;

  it("validateField checks one value alone", () => {
    expect(validateField(n, 21)).toBeNull();
    expect(validateField(n, 5001)).toBe("maximum");
  });

  it("withParam replaces one value and keeps the shape", () => {
    const next = withParam(defaultParams(BB), "n", 34);
    expect(next).toEqual({ n: 34, mult: 2 });
    expect(Object.getPrototypeOf(next)).toBeNull();
  });

  it("paramsSignature is equal exactly when the indicator and params are", () => {
    const a = ok(BB, { n: 20, mult: 2 });
    const b = ok(BB, { mult: 2, n: 20 });
    expect(paramsSignature("bollinger", a)).toBe(paramsSignature("bollinger", b));
    expect(paramsSignature("bollinger", a)).not.toBe(paramsSignature("keltner", a));
    expect(paramsSignature("bollinger", a)).not.toBe(
      paramsSignature("bollinger", withParam(a, "n", 21)),
    );
  });

  it("isEdited compares with the descriptor's defaults (D02 D9)", () => {
    expect(isEdited(BB, defaultParams(BB))).toBe(false);
    expect(isEdited(BB, withParam(defaultParams(BB), "mult", 2.5))).toBe(true);
  });

  it("toWsInstance carries indicator and params only, never a key (`23` §6.1)", () => {
    const params = ok(fieldsOf(EMA.params_schema), { n: 34 });
    expect(toWsInstance("ema", params)).toEqual({ indicator: "ema", params: { n: 34 } });
  });
});
