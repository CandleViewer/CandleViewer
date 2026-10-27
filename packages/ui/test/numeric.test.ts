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
    expect(p(text, precision)).toEqual({ ok: true, value });
  });
  it.each([
    ["", "empty"],
    ["   ", "empty"],
    ["abc", "not-a-number"],
    ["1,5", "not-a-number"],
    ["1,000.5", "not-a-number"],
    [".", "not-a-number"],
    ["-", "not-a-number"],
    ["1e3", "not-a-number"],
    ["1.25", "too-many-decimals"],
  ] as const)("%j is refused as %s", (text, reason) => {
    expect(p(text, 1)).toEqual({ ok: false, reason });
  });
});

describe("formatNumeric / valueText", () => {
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
  it("treats missing bounds as open", () => expect(validateNumeric(-1e9, {})).toBe("in-range"));
  it("AC: min 0, step 0.1, typed -5 is below-min and not clamped", () => {
    const r = p("-5", 1);
    expect(r).toEqual({ ok: true, value: -5 });
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
        expect(p(text, precision)).toEqual({ ok: true, value: v });
        expect(Number.isInteger(Math.round(v * grid))).toBe(true);
        expect(Math.abs(v * grid - Math.round(v * grid))).toBeLessThan(1e-3);
        expect(text.split(".")[1]?.length ?? 0).toBe(precision);
      }
    }
  });
});
