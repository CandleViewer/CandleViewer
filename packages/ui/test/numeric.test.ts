import { describe, expect, it } from "vitest";
import {
  formatNumeric,
  parseNumericInput,
  stepValue,
  validateNumeric,
  valueText,
} from "../src/components/internal/numeric.js";

const p = (text: string, precision: number) => parseNumericInput(text, { precision });

describe("parseNumericInput", () => {
  it.each([
    ["1.5", 2, 1.5],
    [" 42 ", 0, 42],
    ["-5", 1, -5],
    ["+0.30", 2, 0.3],
    [".5", 1, 0.5],
    ["5.", 1, 5],
    ["1.500", 1, 1.5],
    ["-0", 1, 0],
    [".0", 0, 0],
  ])("%j at precision %i is %d", (text, precision, value) => {
    expect(p(text, precision)).toEqual({ ok: true, value, rounded: false });
  });
  it.each([
    ["1.25", 1, 1.3],
    ["1.24", 1, 1.2],
    ["-1.25", 1, -1.3],
    ["-0.25", 1, -0.3],
    ["1.005", 2, 1.01],
    ["-1.005", 2, -1.01],
    ["0.999", 2, 1],
    ["0.004", 2, 0],
    ["-0.004", 2, 0],
    ["2.5", 0, 3],
    [".5", 0, 1],
  ])(
    "rounds %j at precision %i to %d (half away from zero, on digits)",
    (text, precision, value) => {
      expect(p(text, precision)).toEqual({ ok: true, value, rounded: true });
    },
  );
  it.each([
    ["", "empty"],
    ["   ", "empty"],
    ["abc", "not-a-number"],
    ["1,5", "not-a-number"],
    ["1,000.5", "not-a-number"],
    [".", "not-a-number"],
    ["-", "not-a-number"],
    ["1e3", "not-a-number"],
    ["NaN", "not-a-number"],
    ["Infinity", "not-a-number"],
    ["-Infinity", "not-a-number"],
    ["+.5x", "not-a-number"],
    ["5 5", "not-a-number"],
    ["1".repeat(400), "too-many-digits"],
    ["123456789012345.5", "too-many-digits"],
    ["999999999999999", "too-many-digits"],
  ] as const)("%j is refused as %s", (text, reason) => {
    expect(p(text, 1)).toEqual({ ok: false, reason });
  });
});

describe("preconditions", () => {
  it.each([-1, 1.5, 16, NaN])("precision %d throws", (precision) => {
    expect(() => p("1", precision)).toThrow(RangeError);
    expect(() => formatNumeric(1, precision)).toThrow(RangeError);
  });
  it("rounding up into 16 digits is refused", () => {
    expect(p("999999999999999.5", 0)).toEqual({ ok: false, reason: "too-many-digits" });
    expect(p("12345678901234", 0)).toEqual({ ok: true, value: 12345678901234, rounded: false });
  });
});

describe("formatNumeric / valueText", () => {
  it.each([NaN, Infinity, -Infinity, 1e21, 1e15])("%d is not representable: empty text", (v) => {
    expect(formatNumeric(v, 2)).toBe("");
    expect(valueText(v, 2, "%")).toBe(" %");
  });
  it.each([
    [1.5, 2, "1.50"],
    [1234567.891, 1, "1234567.9"],
    [0.05, 2, "0.05"],
    [-0.05, 2, "-0.05"],
    [-0.001, 2, "0.00"],
    [7, 0, "7"],
    [-7, 0, "-7"],
  ])("formats %d at %i as %s", (v, prec, out) => expect(formatNumeric(v, prec)).toBe(out));
  it("adds the unit to the value text", () => {
    expect(valueText(5, 0, "%")).toBe("5 %");
    expect(valueText(0.5, 2)).toBe("0.50");
  });
});

describe("validateNumeric", () => {
  it.each([
    [-5, "below-min"],
    [0, "in-range"],
    [10, "in-range"],
    [10.1, "above-max"],
  ] as const)("%d against 0..10 is %s", (v, out) => {
    expect(validateNumeric(v, { min: 0, max: 10 })).toBe(out);
  });
  it("fails closed on NaN", () => expect(validateNumeric(NaN, { min: 0 })).toBe("not-a-number"));
  it("treats missing bounds as open", () => expect(validateNumeric(-1e9, {})).toBe("in-range"));
  it("AC: min 0, step 0.1, typed -5 is below-min and not clamped", () => {
    const r = p("-5", 1);
    expect(r).toEqual({ ok: true, value: -5, rounded: false });
    if (r.ok) expect(validateNumeric(r.value, { min: 0 })).toBe("below-min");
  });
});

describe("stepValue", () => {
  it("adds 0.1 + 0.2 exactly at precision 1", () => {
    expect(stepValue(0.1, 0.1, "up", 2, 1)).toBe(0.3);
    expect(0.1 + 0.2).not.toBe(0.3);
  });
  it.each([
    [1, 0.5, "up", 1, 2, 1.5],
    [1, 0.5, "down", 10, 2, -4],
    [0.3, 0.1, "down", 1, 1, 0.2],
  ] as const)("steps %d by %d %s x%d", (v, s, d, m, prec, out) => {
    expect(stepValue(v, s, d, m, prec)).toBe(out);
  });
  it("clamps to the bounds, never beyond", () => {
    expect(stepValue(9.95, 0.1, "up", 1, 2, 0, 10)).toBe(10);
    expect(stepValue(0.05, 0.1, "down", 1, 2, 0, 10)).toBe(0);
    expect(stepValue(10, 0.1, "up", 1, 1, 0, 10)).toBe(10);
  });
  it("clamps to an off-grid bound value itself", () => {
    expect(stepValue(10, 0.01, "up", 1, 2, undefined, 10.005)).toBe(10.005);
    expect(stepValue(0.01, 0.01, "down", 1, 2, 0.005)).toBe(0.005);
  });
  it("clamps a start outside the range; min wins over max; one-sided bounds", () => {
    expect(stepValue(-5, 1, "up", 1, 0, 0, 10)).toBe(0);
    expect(stepValue(20, 1, "down", 1, 0, 0, 10)).toBe(10);
    expect(stepValue(5, 1, "up", 1, 0, 8, 3)).toBe(8);
    expect(stepValue(5, 1, "down", 1, 0, 5)).toBe(5);
    expect(stepValue(5, 1, "up", 1, 0, undefined, 5)).toBe(5);
  });
  it("returns a non-representable value unchanged", () => {
    expect(stepValue(Infinity, 1, "up", 1, 0)).toBe(Infinity);
    expect(stepValue(NaN, 1, "up", 1, 0)).toBeNaN();
  });
  it.each([
    ["multiplier 0.5", () => stepValue(1, 1, "up", 0.5, 0)],
    ["multiplier NaN", () => stepValue(1, 1, "up", NaN, 0)],
    ["multiplier -1", () => stepValue(1, 1, "up", -1, 0)],
    ["step finer than precision", () => stepValue(1, 0.001, "up", 1, 2)],
    ["step 0", () => stepValue(1, 0, "up", 1, 2)],
    ["step NaN", () => stepValue(1, NaN, "up", 1, 2)],
    ["precision 20", () => stepValue(1, 1, "up", 1, 20)],
  ])("throws for %s", (_n, fn) => expect(fn).toThrow(RangeError));
});

// mulberry32, fixed seed: deterministic.
const rng = (seed: number) => () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

describe("seeded fuzz (2000 cases)", () => {
  it("round-trips step and format/parse, and stays on the 10^-precision grid", () => {
    const next = rng(264);
    for (let i = 0; i < 2000; i++) {
      const precision = Math.floor(next() * 7);
      const grid = 10 ** precision;
      const value = (Math.floor(next() * 2e8) - 1e8) / grid;
      const step = (1 + Math.floor(next() * 1000)) / grid;
      const mult = 1 + Math.floor(next() * 100);
      const up = stepValue(value, step, "up", mult, precision);
      expect(stepValue(up, step, "down", mult, precision)).toBe(value);
      for (const v of [value, up]) {
        const text = formatNumeric(v, precision);
        const parsed = p(text, precision);
        expect(parsed).toEqual({ ok: true, value: v, rounded: false });
        expect(parsed.ok && formatNumeric(parsed.value, precision)).toBe(text);
        expect(Number.isInteger(Number(text.replace(".", "")))).toBe(true);
        expect(text.split(".")[1]?.length ?? 0).toBe(precision);
      }
    }
  });
});
