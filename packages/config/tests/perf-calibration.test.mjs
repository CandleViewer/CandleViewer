import { describe, expect, it } from "vitest";
import {
  MAX_SCALE,
  MAX_SPREAD,
  WARN_SPREAD,
  judgeSamples,
  needsResample,
  spreadWarning,
  REFERENCE_CPU_MS,
  budget,
  calibration,
  runnerScale,
  scaleFor,
  attemptLine,
  retryWarning,
  takeLastAssertion,
  scaleFromCalibration,
  summary,
  why,
} from "../src/perf-calibration.mjs";

const REF = 10;

describe("one probe's scale", () => {
  it("a slower runner widens the bound proportionally", () => {
    expect(scaleFor(16, 8)).toBe(2);
    expect(scaleFor(12, 8)).toBe(1.5);
  });
  it("a faster or equal runner never tightens below the spec number", () => {
    expect(scaleFor(4, 8)).toBe(1);
    expect(scaleFor(8, 8)).toBe(1);
  });
  it("a non-finite or non-positive input falls back to the spec number", () => {
    for (const bad of [Number.NaN, Number.POSITIVE_INFINITY, 0, -3]) {
      expect(scaleFor(bad, 8)).toBe(1);
      expect(scaleFor(8, bad)).toBe(1);
    }
  });
});

describe("the factor for a measured probe", () => {
  it("is max(1, cpu / reference)", () => {
    expect(scaleFromCalibration({ cpu: 15 }, REF)).toBe(1.5);
    expect(scaleFromCalibration({ cpu: 20 }, REF)).toBe(2);
    expect(scaleFromCalibration({ cpu: 10 }, REF)).toBe(1);
    expect(scaleFromCalibration({ cpu: 9 }, REF)).toBe(1);
  });
  it("never tightens below the spec number, whatever the spread", () => {
    expect(scaleFromCalibration({ cpu: 1, cpuSpread: 1 }, REF)).toBe(1);
  });
  it("falls back to the spec number on a non-finite measurement", () => {
    expect(scaleFromCalibration({ cpu: Number.NaN }, REF)).toBe(1);
    expect(scaleFromCalibration({ cpu: Number.NaN, cpuSpread: Number.NaN }, REF)).toBe(1);
  });
  it("passes at exactly the cap and refuses above it, with the numbers in the message", () => {
    expect(scaleFromCalibration({ cpu: 30 }, REF)).toBe(MAX_SCALE);
    expect(() => scaleFromCalibration({ cpu: 31 }, REF)).toThrow(
      /runner too slow \(calibration cpu 31\.00 ms vs reference 10 ms, factor 3\.10 > 3\)/,
    );
  });
  it("takes the cap as a parameter", () => {
    expect(() => scaleFromCalibration({ cpu: 20 }, REF, 1.5)).toThrow(/> 1\.5/);
  });
});

describe("an untrustworthy calibration fails", () => {
  it("fails when the probe's 5 samples spread by more than the limit", () => {
    expect(MAX_SPREAD).toBe(2);
    expect(WARN_SPREAD).toBe(1.5);
    expect(scaleFromCalibration({ cpu: 10, cpuSpread: 2 }, REF)).toBe(1);
    expect(() => scaleFromCalibration({ cpu: 10, cpuSpread: 2.01 }, REF)).toThrow(
      /calibration untrustworthy \(cpu 10\.00 ms, sample spread 2\.01 > limit 2\)/,
    );
    expect(() => scaleFromCalibration({ cpu: 10, cpuSpread: 1.2, refuse: true }, REF)).toThrow(
      /untrustworthy/,
    );
  });
  it("fails closed on an infinite spread (a zero-time best sample)", () => {
    expect(() =>
      scaleFromCalibration({ cpu: 10, cpuSpread: Number.POSITIVE_INFINITY }, REF),
    ).toThrow(/untrustworthy/);
  });
});

// The real probes run here under V8 coverage, which inflates them: assert only that they are
// finite, positive and memoised. Never assert a magnitude or a scale bound in this file.
describe("calibration, budget and why on this process", () => {
  it("measures finite positive durations and memoises them", () => {
    const first = calibration();
    expect(Number.isFinite(first.cpu)).toBe(true);
    expect(first.cpu).toBeGreaterThan(0);
    expect(calibration()).toBe(first);
    expect(first.cpuSpread).toBeGreaterThanOrEqual(1);
    expect(summary()).toMatch(
      /^calibration cpu=\S+ cpu spread=\S+ resampled=(yes|no) reference=\S+ factor=\S+$/,
    );
  });
  it("records a positive reference figure and a cap above 1", () => {
    expect(REFERENCE_CPU_MS).toBeGreaterThan(0);
    expect(MAX_SCALE).toBeGreaterThan(1);
  });
  it("scales the spec number by the runner scale, never below it", () => {
    let scale;
    try {
      scale = runnerScale();
    } catch (error) {
      // Coverage on a slow host can exceed the cap or the spread limit: refusal is the contract.
      expect(String(error)).toMatch(/runner too slow|untrustworthy/);
      expect(() => budget(120)).toThrow(/runner too slow|untrustworthy/);
      return;
    }
    expect(scale).toBeGreaterThanOrEqual(1);
    expect(budget(120)).toBeCloseTo(120 * scale, 9);
  });
  it("explains a result with measured, scaled bound and calibration", () => {
    let text;
    try {
      text = why(130, 120);
    } catch (error) {
      expect(String(error)).toMatch(/runner too slow|untrustworthy/);
      return;
    }
    expect(text).toContain("measured 130 ms");
    expect(text).toContain("spec 120 ms");
    expect(text).toContain("calibration cpu=");
  });
});

describe("why() on the refusal paths keeps the measured value", () => {
  it("appends measured to 'runner too slow' and keeps failing closed", () => {
    const slow = { cpu: REFERENCE_CPU_MS * 4, cpuSpread: 1 };
    expect(() => why(130, 120, slow)).toThrow(
      /runner too slow[^]*factor 4\.00 > 3[^]*\[measured 130 ms vs spec 120 ms\]/,
    );
  });
  it("appends measured to 'calibration untrustworthy'", () => {
    const noisy = { cpu: 20.6, cpuSpread: 2.5 };
    expect(() => why(7, 5, noisy)).toThrow(/untrustworthy[^]*\[measured 7 ms vs spec 5 ms\]/);
  });
  it("passes a trustworthy calibration through with the same text as before", () => {
    const ok = { cpu: REFERENCE_CPU_MS, cpuSpread: 1 };
    expect(why(4, 5, ok)).toContain("measured 4 ms vs bound 5.000 ms");
  });
});

describe("retry reporting", () => {
  it("formats the warning annotation with the test, attempt and the three values", () => {
    expect(retryWarning("decode 10k frames", 2, 118.4567, 21.5, 124.5)).toBe(
      "::warning title=perf retry::decode 10k frames passed on attempt 2 — measured 118.457 ms, " +
        "calibration 21.5 ms, bound 124.5 ms",
    );
  });
  it("shows n/a when no assertion recorded a value", () => {
    expect(retryWarning("t", 3, undefined, undefined, undefined)).toContain("measured n/a ms");
  });
  it("formats an attempt line for a failing attempt", () => {
    expect(attemptLine("t", 1, "fail", { measured: 130, calibration: 21, bound: 120 })).toBe(
      "perf attempt=1 state=fail test=t measured=130 ms calibration=21 ms bound=120 ms",
    );
  });
  it("records and clears the last assertion from why()", () => {
    takeLastAssertion();
    why(10, 120, { cpu: REFERENCE_CPU_MS, cpuSpread: 1 });
    expect(takeLastAssertion()).toMatchObject({ measured: 10, bound: 120 });
    expect(takeLastAssertion()).toBeUndefined();
  });
});

describe("judgeSamples: the pure trust decision", () => {
  const set = (min, max) => [min, min, (min + max) / 2, max, min];
  it("accepts a spread of 1.5 or less with no warning and no resample", () => {
    const j = judgeSamples(set(10, 15));
    expect(j).toMatchObject({ cpu: 10, spread: 1.5, resampled: false, warn: false, refuse: false });
  });
  it("accepts 1.5 < spread <= 2.0 with a warning and no resample (least of five)", () => {
    const j = judgeSamples(set(10, 20));
    expect(j).toMatchObject({ cpu: 10, spread: 2, resampled: false, warn: true, refuse: false });
    expect(needsResample(set(10, 20))).toBe(false);
  });
  it("needs a resample only above 2.0 (the 2.0 / 2.01 boundary)", () => {
    expect(needsResample(set(10, 20))).toBe(false);
    expect(needsResample(set(10, 20.1))).toBe(true);
    expect(judgeSamples(set(10, 20.1)).refuse).toBe(true);
  });
  it("accepts a quiet second set: median of all ten, warn when the ten spread > 1.5", () => {
    const first = [10, 10, 10, 10, 25];
    const second = [10, 11, 12, 12, 13];
    const j = judgeSamples(first, second);
    expect(j.resampled).toBe(true);
    expect(j.refuse).toBe(false);
    expect(j.cpu).toBe(10.5);
    expect(j.spread).toBe(2.5);
    expect(j.warn).toBe(true);
  });
  it("always warns on an accepted resample (the ten include the noisy first set)", () => {
    const j = judgeSamples([10, 10, 10, 10, 20.5], [10, 10, 10, 10, 10]);
    expect(j).toMatchObject({ cpu: 10, resampled: true, warn: true, refuse: false });
  });
  it("refuses only when BOTH sets exceed 2.0", () => {
    expect(judgeSamples(set(10, 25), set(10, 25))).toMatchObject({ resampled: true, refuse: true });
    expect(judgeSamples(set(10, 25), set(10, 20)).refuse).toBe(false);
    expect(judgeSamples(set(10, 25), set(10, 20.1)).refuse).toBe(true);
  });
  it("formats the annotation", () => {
    expect(spreadWarning(42, 1.6, 20.5, false)).toBe(
      "::warning title=perf calibration::process 42 cpu spread 1.600 > 1.5 (cpu 20.500 ms, resampled no)",
    );
  });
});
