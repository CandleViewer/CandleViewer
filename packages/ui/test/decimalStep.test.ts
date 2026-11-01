// E29-S02 (#912) BQ-11: the in-cell editor's exact decimal stepping. Unit cases, then properties over seeded cases
// (mulberry32 loops, as the chart engine's property tests run them: the workspace has no fast-check, and a new
// dependency is out of this PR's scope). Nothing may round, and nothing may pass through a binary double.
import { describe, expect, it } from "vitest";
import {
  MAX_TEXT,
  checkTyped,
  compareDecimal,
  isOnStep,
  parseTyped,
  parseWire,
  stepFrom,
  toText,
  widen,
  type StepDecimal,
} from "../src/components/internal/decimalStep.js";

const d = (text: string): StepDecimal => {
  const parsed = parseWire(text);
  if (parsed === null) throw new TypeError(`not a decimal: ${text}`);
  return parsed;
};
const text = (value: StepDecimal): string => toText(value);

describe("parsing: the wire's form, and what a person types", () => {
  it("reads the wire's decimal exactly and refuses a sign, an exponent, a space or junk", () => {
    expect(parseWire("2500")).toEqual({ units: 2500n, scale: 0 });
    expect(parseWire("0.050")).toEqual({ units: 50n, scale: 3 });
    for (const bad of ["-1", "+1", "1e3", " 1", "1 ", "1,000", ".5", "5.", "", "0x10", "١"])
      expect(parseWire(bad)).toBeNull();
    expect(parseWire("9".repeat(MAX_TEXT + 1))).toBeNull();
  });

  it("takes typed text trimmed, with a bare point either side, never a sign or grouping", () => {
    expect(parseTyped(" 2495.00 ")).toEqual({ units: 249500n, scale: 2 });
    expect(parseTyped(".5")).toEqual({ units: 5n, scale: 1 });
    expect(parseTyped("5.")).toEqual({ units: 5n, scale: 0 });
    for (const bad of ["", ".", " ", "-2", "+2", "2,495", "2e3", "2..5", "abc"])
      expect(parseTyped(bad)).toBeNull();
  });

  it("writes plain text at the value's own scale", () => {
    expect(text({ units: 50n, scale: 3 })).toBe("0.050");
    expect(text({ units: 0n, scale: 2 })).toBe("0.00");
    expect(text({ units: 123n, scale: 0 })).toBe("123");
  });

  it("widens without dropping a digit, and never narrows", () => {
    expect(text(widen(d("2500"), 2))).toBe("2500.00");
    expect(text(widen(d("2500.005"), 2))).toBe("2500.005");
    expect(compareDecimal(d("0.50"), d("0.5"))).toBe(0);
    expect(compareDecimal(d("0.49"), d("0.5"))).toBe(-1);
  });
});

describe("checkTyped: reasons in order, and never a rounding", () => {
  const tick = d("0.01");

  it("accepts a value on the tick and returns it as typed", () => {
    const check = checkTyped("2495.00", tick);
    expect(check.kind).toBe("ok");
    expect(check.kind === "ok" && text(check.value)).toBe("2495.00");
  });

  it("refuses an empty, a non-number, zero, an off-step and a below-min value, in that order", () => {
    expect(checkTyped("  ", tick).kind).toBe("empty");
    expect(checkTyped("abc", tick).kind).toBe("not_a_number");
    expect(checkTyped("0", tick).kind).toBe("not_positive");
    expect(checkTyped("0.000", tick).kind).toBe("not_positive");
    expect(checkTyped("2495.003", tick).kind).toBe("off_step");
    expect(checkTyped("0.0005", d("0.001"), d("0.001")).kind).toBe("off_step");
    expect(checkTyped("0.002", d("0.001"), d("0.005")).kind).toBe("below_min");
  });

  it("reads 2,495.03 on a 0.1 tick as off the step, never as 2,495.0", () => {
    expect(checkTyped("2495.03", d("0.1")).kind).toBe("off_step");
  });
});

describe("stepFrom", () => {
  const tick = d("0.1");

  it("moves an on-step value by whole steps, at the step's scale", () => {
    expect(text(stepFrom(d("63950"), tick, "up", 1))).toBe("63950.1");
    expect(text(stepFrom(d("63950.0"), tick, "down", 10))).toBe("63949.0");
    expect(text(stepFrom(d("2500.00"), d("0.01"), "down", 1))).toBe("2499.99");
  });

  it("lands an off-step value on the adjacent multiple first", () => {
    expect(text(stepFrom(d("2495.03"), tick, "up", 1))).toBe("2495.1");
    expect(text(stepFrom(d("2495.03"), tick, "down", 1))).toBe("2495.0");
    expect(text(stepFrom(d("2495.03"), tick, "up", 10))).toBe("2496.0");
    expect(text(stepFrom(d("2495.03"), tick, "down", 10))).toBe("2494.1");
  });

  it("never steps to zero or below, nor below the lowest valid value", () => {
    expect(text(stepFrom(d("0.1"), tick, "down", 1))).toBe("0.1");
    expect(text(stepFrom(d("0.003"), d("0.001"), "down", 10, d("0.002")))).toBe("0.002");
    expect(text(stepFrom(d("0.003"), d("0.001"), "down", 1, d("0.0025")))).toBe("0.003");
  });

  it("refuses a step of zero and a count below one", () => {
    expect(() => stepFrom(d("1"), d("0"), "up", 1)).toThrow(RangeError);
    expect(() => stepFrom(d("1"), tick, "up", 0)).toThrow(RangeError);
    expect(() => stepFrom(d("1"), tick, "up", 1.5)).toThrow(RangeError);
  });
});

/** mulberry32: seedable, the same sequence everywhere (the chart engine's `bench/fixtures/rng.mjs`). */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CASES = 2_000;
const BASE = 912_000;

/** A random case: a step from Bybit's shapes (1, 5, 0.5, 0.1 … 1e-8), a value of up to 12 digits at up to 10 places. */
function arbitrary(rng: () => number): { step: StepDecimal; value: StepDecimal; times: number } {
  const steps = ["1", "5", "0.5", "0.1", "0.05", "0.01", "0.0025", "0.001", "0.0001", "0.00000001"];
  const step = d(steps[Math.floor(rng() * steps.length)] ?? "0.1");
  const scale = Math.floor(rng() * 11);
  const digits = 1 + Math.floor(rng() * 12);
  let units = 0n;
  for (let i = 0; i < digits; i += 1) units = units * 10n + BigInt(Math.floor(rng() * 10));
  const times = rng() < 0.5 ? 1 : 1 + Math.floor(rng() * 20);
  return { step, value: { units: units === 0n ? 1n : units, scale }, times };
}

/** `a + n × step` or `a − n × step`, by aligned BigInts: the reference the properties compare with. */
const shifted = (a: StepDecimal, step: StepDecimal, n: bigint): StepDecimal => {
  const scale = Math.max(a.scale, step.scale);
  const x = widen(a, scale).units;
  const s = widen(step, scale).units;
  return { units: x + n * s, scale };
};

describe("properties (seeded, 2 000 cases each)", () => {
  it("a step always lands on a multiple of the step, strictly past the value", () => {
    for (let c = 0; c < CASES; c += 1) {
      const rng = mulberry32(BASE + c);
      const { step, value, times } = arbitrary(rng);
      const up = stepFrom(value, step, "up", times);
      expect(isOnStep(up, step)).toBe(true);
      expect(compareDecimal(up, value)).toBe(1);
      // the times-th multiple above, exactly: `times` steps back are no longer above the value
      expect(compareDecimal(shifted(up, step, -BigInt(times)), value)).toBeLessThanOrEqual(0);
      const down = stepFrom(value, step, "down", times);
      expect(isOnStep(down, step)).toBe(true);
      const floor = compareDecimal(down, step) === 0;
      if (!floor) {
        expect(compareDecimal(down, value)).toBe(-1);
        expect(compareDecimal(shifted(down, step, BigInt(times)), value)).toBeGreaterThanOrEqual(0);
      }
      expect(down.units > 0n).toBe(true);
    }
  });

  it("up then down by the same count returns an on-step value exactly", () => {
    for (let c = 0; c < CASES; c += 1) {
      const rng = mulberry32(BASE + CASES + c);
      const { step, value, times } = arbitrary(rng);
      const onStep = stepFrom(value, step, "up", 1);
      const back = stepFrom(stepFrom(onStep, step, "up", times), step, "down", times);
      expect(text(back)).toBe(text(onStep));
    }
  });

  it("checkTyped never rounds: a value is accepted exactly when it is on the step, as typed", () => {
    for (let c = 0; c < CASES; c += 1) {
      const rng = mulberry32(BASE + 2 * CASES + c);
      const { step, value } = arbitrary(rng);
      const typed = text(value);
      const check = checkTyped(typed, step);
      expect(check.kind === "ok").toBe(isOnStep(value, step));
      if (check.kind === "ok") expect(text(check.value)).toBe(typed);
      else expect(check.kind).toBe("off_step");
    }
  });

  it("text round-trips exactly through parseWire, whatever the scale", () => {
    for (let c = 0; c < CASES; c += 1) {
      const rng = mulberry32(BASE + 3 * CASES + c);
      const { value } = arbitrary(rng);
      expect(parseWire(text(value))).toEqual(value);
    }
  });
});
