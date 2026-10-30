// Wall-clock half of the `scheduler-overhead` microbench (E11-S01 PR2), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): the Perf bullet, <= 0.3 ms per frame, 3 panes x 12 nodes.
import { describe, expect, it } from "vitest";
import { SchedulerOverheadBench } from "../../../bench/scenes/scheduler-overhead.js";
import { percentile } from "../../../bench/stats.mjs";

describe("perf budgets: frame scheduler overhead", () => {
  it("a pan + data frame through the scheduler takes <= 0.3 ms (median of 5 runs)", () => {
    const perFrame: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new SchedulerOverheadBench(() => performance.now());
      const start = performance.now();
      for (let f = 1; f <= 600; f += 1) bench.step(f * 16);
      if (r >= 0) perFrame.push((performance.now() - start) / 600); // run -1 is the warm-up
      expect(bench.allocationsInFramePath).toBe(0);
    }
    expect(percentile(perFrame, 50) ?? Number.NaN).toBeLessThanOrEqual(0.3);
  });
});
