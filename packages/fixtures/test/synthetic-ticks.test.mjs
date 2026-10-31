import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  SYNTHETIC_TICK_PRESETS,
  formatTicks,
  generatePresetTicks,
  generateTicks,
  mulberry32,
} from "../src/synthetic-ticks.mjs";

describe("synthetic ticks", () => {
  it("generateTicks_sameSeed_identicalStream", () => {
    expect(generateTicks({ seed: 7 })).toEqual(generateTicks({ seed: 7 }));
    expect(generateTicks({ seed: 7 })).not.toEqual(generateTicks({ seed: 8 }));
  });

  it("mulberry32_seed1_matchesPinnedValues", () => {
    const r = mulberry32(1);
    expect([r(), r()]).toEqual([0.6270739405881613, 0.002735721180215478]);
  });

  it("burst_preset_is40HzFor5s", () => {
    const t = generatePresetTicks("burst");
    expect(t).toHaveLength(200);
    expect(t.map((x) => x.tMs).slice(0, 3)).toEqual([0, 25, 50]);
    expect(t.at(-1).tMs).toBe(4975);
  });

  it("idle_preset_isOneTickEveryFiveSeconds", () => {
    const t = generatePresetTicks("idle");
    expect(t).toHaveLength(12);
    expect(t[1].tMs - t[0].tMs).toBe(5000);
  });

  it("steady40hz_preset_hasSpacingOf25ms", () => {
    const t = generatePresetTicks("steady-40hz");
    expect(t).toHaveLength(2400);
    expect(new Set(t.slice(1).map((x, i) => x.tMs - t[i].tMs))).toEqual(new Set([25]));
    expect(Object.keys(SYNTHETIC_TICK_PRESETS)).toEqual(["burst", "idle", "steady-40hz"]);
  });

  it("generateTicks_overrides_applyStartAndRate", () => {
    const t = generateTicks({ rateHz: 10, durationMs: 1000, startMs: 1_000_000 });
    expect(t).toHaveLength(10);
    expect(t[0].tMs).toBe(1_000_000);
    expect(t[1].tMs).toBe(1_000_100);
  });

  it("generateTicks_moves_areNonDegenerateAndConsistent", () => {
    const t = generateTicks({ seed: 3, durationMs: 60_000 });
    const n = (m) => t.filter((x) => x.move === m).length;
    for (const m of ["up", "down", "flat"]) expect(n(m)).toBeGreaterThan(t.length * 0.1);
    let prev = 6_500_000;
    for (const x of t) {
      expect(x.priceTicks - prev).toBe({ up: 1, down: -1, flat: 0 }[x.move]);
      prev = x.priceTicks;
    }
  });

  it("generateTicks_prices_areIntegerTicksAndDecimalStrings", () => {
    const [first] = generateTicks({ startPriceTicks: 6_500_005 });
    expect(Number.isInteger(first.priceTicks)).toBe(true);
    expect(first.price).toMatch(/^\d+\.\d{2}$/);
    expect(formatTicks(6_500_005, 2)).toBe("65000.05");
    expect(formatTicks(7, 0)).toBe("7");
  });

  it("generateTicks_invalidRate_throws", () => {
    expect(() => generateTicks({ rateHz: 0 })).toThrow(RangeError);
    expect(() => generatePresetTicks("nope")).toThrow(RangeError);
  });

  it("source_hasNoWallClockOrUnseededRandom", () => {
    const src = readFileSync(new URL("../src/synthetic-ticks.mjs", import.meta.url), "utf8")
      .split("\n")
      .filter((l) => !l.trimStart().startsWith("//"))
      .join("\n");
    expect(src).not.toMatch(/Date\.now|new Date|performance\.now|Math\.random|setTimeout/);
  });
});
