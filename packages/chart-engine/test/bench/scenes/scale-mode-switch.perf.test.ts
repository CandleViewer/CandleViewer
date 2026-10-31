// Wall-clock half of the `scale-mode-switch` scene (E11-S05, BQ-126), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): ≤ 0.05 ms of uniforms per pane per switch (3 panes).
import { describe, expect, it } from "vitest";
import { PANES, ScaleModeSwitchBench } from "../../../bench/scenes/scale-mode-switch.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: a scale-mode switch", () => {
  it("rewrites a pane's uniforms in <= 0.05 ms (median of 5 runs)", () => {
    const perPane: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new ScaleModeSwitchBench(100_000);
      const start = performance.now();
      for (let f = 0; f < 600; f += 1) bench.step();
      if (r >= 0) perPane.push((performance.now() - start) / 600 / PANES); // run -1 warms up
    }
    const median = percentile(perPane, 50) ?? Number.NaN;
    expect(median, why(median, 0.05)).toBeLessThanOrEqual(budget(0.05));
  });
});
