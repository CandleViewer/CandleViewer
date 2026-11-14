/**
 * E13-S01 (#423) S1: the closed JSON Schema subset (SR-E13-09; TM IR-03, IR-14, IR-37; D06 §8.3
 * frozen (1); D02 D10) and the decimal step check (`24` §7.4).
 */
import { describe, expect, it } from "vitest";
import {
  isDecimalMultiple,
  parseDecimalText,
} from "../../../src/features/indicators/model/decimal";
import {
  checkNumber,
  parseParamsSchema,
  type NumberField,
  type ParamField,
} from "../../../src/features/indicators/model/schema";
import { BOLLINGER, CVD, EMA, VOLUME } from "./fixtures";
import { int, SEEDS, withSeed } from "./rng";

const fieldsOf = (raw: unknown): readonly ParamField[] => {
  const result = parseParamsSchema(raw);
  if (!result.ok) throw new Error("refused");
  return result.fields;
};
const withProp = (prop: unknown, root: Record<string, unknown> = {}) => ({
  type: "object",
  additionalProperties: false,
  properties: { n: prop },
  ...root,
});
const PERIOD = { type: "integer", title: "Period", minimum: 1, maximum: 5000, default: 21 };

describe("parseParamsSchema: the subset the server serves", () => {
  it("maps a period to an integer stepper with step 1", () => {
    expect(fieldsOf(EMA.params_schema)).toEqual([
      {
        kind: "integer",
        name: "n",
        title: "Period",
        minimum: 1,
        maximum: 5000,
        step: 1,
        default: 21,
      },
    ]);
  });

  it("keeps a fraction's decimal step and the property order", () => {
    const fields = fieldsOf(BOLLINGER.params_schema);
    expect(fields.map((f) => f.name)).toEqual(["n", "mult"]);
    expect(fields[1]).toMatchObject({
      kind: "number",
      step: 0.1,
      minimum: 0.1,
      maximum: 10,
      default: 2,
    });
  });

  it("maps a string enum to a select and an empty schema to no fields", () => {
    expect(fieldsOf(CVD.params_schema)[0]).toMatchObject({
      kind: "enum",
      options: ["session", "utc_day"],
      default: "session",
    });
    expect(fieldsOf(VOLUME.params_schema)).toEqual([]);
  });

  it("maps a boolean to a toggle", () => {
    expect(fieldsOf(withProp({ type: "boolean", title: "Show", default: true }))[0]).toEqual({
      kind: "boolean",
      name: "n",
      title: "Show",
      default: true,
    });
  });

  it("renders a type outside the subset as one read-only unsupported row", () => {
    for (const prop of [
      { type: "string", title: "Label", default: "x" },
      { type: "object", title: "Nested", properties: { a: { $ref: "#" } } },
      { type: "array", title: "List", items: {} },
      { type: "integer", title: "Unbounded", default: 1 },
      { type: "number", title: "No step", minimum: 0, maximum: 1, default: 0.5 },
    ]) {
      expect(fieldsOf(withProp(prop))).toEqual([
        { kind: "unsupported", name: "n", title: prop.title },
      ]);
    }
  });
});

describe("parseParamsSchema: the edges of its bounds", () => {
  it("accepts minimum equal to maximum (a one-value stepper)", () => {
    expect(fieldsOf(withProp({ ...PERIOD, minimum: 21, maximum: 21 }))).toMatchObject([
      { kind: "integer", minimum: 21, maximum: 21, default: 21 },
    ]);
  });

  it("accepts a title and 1,024 options at the sanity bounds (no owner in 22 / 24)", () => {
    const options = Array.from({ length: 1024 }, (_, i) => `v${i}`);
    const title = "x".repeat(1024);
    expect(
      fieldsOf(withProp({ type: "string", title, enum: options, default: "v0" })),
    ).toMatchObject([{ kind: "enum", title, options }]);
  });
});

describe("parseParamsSchema: a hostile schema is refused, never rendered", () => {
  it.each([
    ["$ref on a property", withProp({ ...PERIOD, $ref: "#/x" })],
    [
      "pattern",
      withProp({ type: "string", title: "P", enum: ["a"], default: "a", pattern: "(a+)+$" }),
    ],
    ["oneOf", withProp({ ...PERIOD, oneOf: [] })],
    ["$defs at the root", withProp(PERIOD, { $defs: {} })],
    ["patternProperties at the root", withProp(PERIOD, { patternProperties: {} })],
    ["additionalProperties true", withProp(PERIOD, { additionalProperties: true })],
    ["a root that is not an object schema", { type: "array" }],
    ["HTML in a title", withProp({ ...PERIOD, title: "<img src=x onerror=alert(1)>" })],
    ["a control character in a title", withProp({ ...PERIOD, title: "Per\u0000iod" })],
    ["a title past the 1,024 sanity bound", withProp({ ...PERIOD, title: "x".repeat(1025) })],
    ["no title", withProp({ type: "integer", minimum: 1, maximum: 5, default: 1 })],
    ["a default outside its bounds", withProp({ ...PERIOD, default: 0 })],
    [
      "a default off its step",
      withProp({ ...PERIOD, type: "number", multipleOf: 0.5, default: 1.2 }),
    ],
    ["minimum above maximum", withProp({ ...PERIOD, minimum: 9, maximum: 1 })],
    ["a non-finite bound", withProp({ ...PERIOD, maximum: "Infinity" })],
    ["a zero step", withProp({ ...PERIOD, type: "number", multipleOf: 0 })],
    ["a fractional step on an integer", withProp({ ...PERIOD, multipleOf: 0.5 })],
    [
      "an enum default outside it",
      withProp({ type: "string", title: "A", enum: ["a"], default: "b" }),
    ],
    [
      "a duplicate enum option",
      withProp({ type: "string", title: "A", enum: ["a", "a"], default: "a" }),
    ],
    ["an enum on a number", withProp({ ...PERIOD, enum: [1] })],
    ["a non-boolean toggle default", withProp({ type: "boolean", title: "B", default: "yes" })],
    ["a parameter name off the server's rule", { type: "object", properties: { "N-1": PERIOD } }],
    ["a property that is not an object", withProp("integer")],
    ["a non-object", "{}"],
    ["null", null],
  ])("%s", (_label, raw) => {
    expect(parseParamsSchema(raw)).toEqual({ ok: false });
  });

  it("drops prototype-reaching names and never reads them (TM IR-14)", () => {
    const raw = JSON.parse(
      `{"type":"object","properties":{"__proto__":{"type":"boolean","title":"X","default":true},"constructor":{"type":"boolean","title":"Y","default":true},"n":${JSON.stringify(PERIOD)}}}`,
    ) as unknown;
    expect(fieldsOf(raw).map((f) => f.name)).toEqual(["n"]);
  });

  // BQ-11 rider (ruling 6652282467): the 100 ms bound is an injected-clock assertion, never wall
  // clock (40-testing quality rules). The clock, in microseconds, is charged a pessimistic 100 µs per
  // payload value read and per key listing, so the bound holds exactly when the work is bounded.
  const READ_US = 100;
  const BOUND_US = 100_000;
  const charged = (raw: Record<string, unknown>, clock: { now: number }): Record<string, unknown> =>
    new Proxy(raw, {
      get(target, key, receiver) {
        clock.now += READ_US;
        return Reflect.get(target, key, receiver) as unknown;
      },
      ownKeys(target) {
        clock.now += READ_US;
        return Reflect.ownKeys(target);
      },
    });

  it("refuses more than 64 parameters before reading any, inside 100 ms of the injected clock", () => {
    const clock = { now: 0 };
    const properties: Record<string, unknown> = {};
    for (let i = 0; i < 20_000; i += 1) properties[`p${i}`] = charged({ $ref: "#" }, clock);
    const root = charged({ type: "object", properties: charged(properties, clock) }, clock);
    expect(parseParamsSchema(root)).toEqual({ ok: false });
    expect(clock.now).toBeLessThan(BOUND_US);
  });

  it("refuses a hostile 64th parameter inside 100 ms of the injected clock", () => {
    const clock = { now: 0 };
    const properties: Record<string, unknown> = {};
    for (let i = 0; i < 63; i += 1) properties[`p${i}`] = charged({ ...PERIOD }, clock);
    properties["p63"] = charged({ ...PERIOD, $ref: "#" }, clock);
    const root = charged({ type: "object", properties: charged(properties, clock) }, clock);
    expect(parseParamsSchema(root)).toEqual({ ok: false });
    expect(clock.now).toBeGreaterThan(0);
    expect(clock.now).toBeLessThan(BOUND_US);
  });

  it("refuses a deep or wide enum without recursing", () => {
    let deep: unknown = 1;
    for (let i = 0; i < 10_000; i += 1) deep = [deep];
    const wide = Array.from({ length: 1025 }, (_, i) => `v${i}`);
    expect(
      parseParamsSchema(withProp({ type: "string", title: "A", enum: [deep], default: "a" })),
    ).toEqual({ ok: false });
    expect(
      parseParamsSchema(withProp({ type: "string", title: "A", enum: wide, default: "v0" })),
    ).toEqual({ ok: false });
  });
});

describe("the decimal step (D02 D10: a binary64 division refuses 0.3 for 0.1)", () => {
  it("accepts exact decimal multiples binary64 gets wrong", () => {
    expect(0.3 % 0.1).not.toBe(0);
    expect(isDecimalMultiple(0.3, 0.1)).toBe(true);
    expect(isDecimalMultiple(0.7, 0.1)).toBe(true);
    expect(isDecimalMultiple(0.021, 0.001)).toBe(true);
    expect(isDecimalMultiple(1e21, 0.1)).toBe(true);
    expect(isDecimalMultiple(1.5e-7, 5e-8)).toBe(true);
  });

  it("refuses off-step values and a non-positive or non-finite step", () => {
    expect(isDecimalMultiple(0.25, 0.1)).toBe(false);
    expect(isDecimalMultiple(0.30000000000000004, 0.1)).toBe(false);
    expect(isDecimalMultiple(1, 0)).toBe(false);
    expect(isDecimalMultiple(1, -0.1)).toBe(false);
    expect(isDecimalMultiple(Number.NaN, 0.1)).toBe(false);
  });

  it.each(SEEDS)("seed %i: k × step at the step's scale is always a multiple", (seed) =>
    withSeed(seed, (next) => {
      for (let i = 0; i < 500; i += 1) {
        const places = int(next, 0, 4);
        const step = int(next, 1, 9) / 10 ** places;
        const k = int(next, -100_000, 100_000);
        const value = Number((k * step).toFixed(places));
        expect(isDecimalMultiple(value, step)).toBe(true);
      }
    }),
  );

  it("parses plain decimal text only", () => {
    expect(parseDecimalText(" 21 ")).toBe(21);
    expect(parseDecimalText("-0.5")).toBe(-0.5);
    for (const text of ["", "1e3", "0x10", "Infinity", "1.", ".5", "1,5", "NaN"]) {
      expect(parseDecimalText(text)).toBeNull();
    }
  });
});

describe("checkNumber: reject, never clamp (D02 D11), in the server's keyword order", () => {
  const spec: NumberField = {
    kind: "number",
    name: "mult",
    title: "Standard deviations",
    minimum: 0.1,
    maximum: 10,
    step: 0.1,
    default: 2,
  };
  const period: NumberField = { ...spec, kind: "integer", minimum: 1, maximum: 5000, step: 1 };

  it("names the first keyword broken", () => {
    expect(checkNumber(spec, 0)).toBe("minimum");
    expect(checkNumber(spec, 10.1)).toBe("maximum");
    expect(checkNumber(spec, 0.15)).toBe("multipleOf");
    expect(checkNumber(spec, Number.POSITIVE_INFINITY)).toBe("type");
    expect(checkNumber(period, 2.5)).toBe("type");
    expect(checkNumber(period, 5000)).toBeNull();
  });
});
