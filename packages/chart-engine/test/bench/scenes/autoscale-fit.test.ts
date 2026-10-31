// The counted half of the `autoscale-fit` scene (E11-S05, BQ-126); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { AutoscaleFitBench, VISIBLE } from "../../../bench/scenes/autoscale-fit.js";

describe("perf scene: autoscale over 40 000 visible bars (counted)", () => {
  it("each one-bar pan refits exactly once; an unchanged frame refits nothing", () => {
    const bench = new AutoscaleFitBench(100_000);
    expect(bench.viewport.visibleBars).toBe(VISIBLE);
    const before = bench.scaler.counters.autoscale_recomputes;
    for (let f = 0; f < 50; f += 1) bench.step();
    expect(bench.scaler.counters.autoscale_recomputes - before).toBe(50);
    expect(bench.scaler.update()).toBe(false);
    expect(bench.scaler.counters.autoscale_recomputes - before).toBe(50);
    const p = bench.viewport.panes[0];
    expect(p?.priceLow).toBeLessThan(100_000);
    expect(p?.priceHigh).toBeGreaterThan(105_000);
  });
});
