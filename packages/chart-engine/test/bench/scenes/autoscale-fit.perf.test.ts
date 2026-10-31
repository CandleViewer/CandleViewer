// Wall-clock half of the `autoscale-fit` scene (E11-S05, BQ-126), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): one refit over 40 000 visible bars within 06 §4.3's 2 ms
// data-window stage.
import { describe, expect, it } from "vitest";
import { AutoscaleFitBench } from "../../../bench/scenes/autoscale-fit.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: autoscale", () => {
  it("refits 40 000 visible bars in <= 2 ms (median of 5 runs)", () => {
    const perFit: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new AutoscaleFitBench(100_000);
      const start = performance.now();
      for (let f = 0; f < 100; f += 1) bench.step();
      if (r >= 0) perFit.push((performance.now() - start) / 100); // run -1 warms up
    }
    const median = percentile(perFit, 50) ?? Number.NaN;
    expect(median, why(median, 2)).toBeLessThanOrEqual(budget(2));
  });
});
