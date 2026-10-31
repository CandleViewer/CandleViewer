// Wall-clock half of the `scene-graph` microbench (E11-S01), run ONLY by `vitest --project perf`
// (engine-bench, no coverage). The traversal is a slice of the scheduler's 0.3 ms/frame overhead
// budget for 3 panes x 12 nodes (the ticket's Perf bullet), so it must fit inside it alone.
import { describe, expect, it } from "vitest";
import { SceneGraphBench } from "../../../bench/scenes/scene-graph.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: scene-graph traversal", () => {
  it("a pan + data frame over 3 panes x 12 nodes takes < 0.3 ms (median of 5 runs)", () => {
    const perFrame: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new SceneGraphBench(3, 12);
      const start = performance.now();
      for (let f = 1; f <= 600; f += 1) bench.step(f * 16);
      if (r >= 0) perFrame.push((performance.now() - start) / 600); // run -1 is the warm-up
      expect(bench.allocationsInFramePath).toBe(0);
    }
    const median = percentile(perFrame, 50) ?? Number.NaN;
    expect(median, why(median, 0.3)).toBeLessThan(budget(0.3));
  });
});
