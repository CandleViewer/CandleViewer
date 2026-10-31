// Wall-clock half of the `viewport-transform` scene (E11-S03), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): the transform stays within 0.05 ms per pane per frame (3 panes).
import { describe, expect, it } from "vitest";
import { PANES, ViewportTransformBench } from "../../../bench/scenes/viewport-transform.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: the shared transform", () => {
  it("a frame's transform work takes <= 0.05 ms per pane (median of 5 runs)", () => {
    const perPane: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new ViewportTransformBench(100_000);
      const start = performance.now();
      for (let f = 0; f < 600; f += 1) bench.step();
      if (r >= 0) perPane.push((performance.now() - start) / 600 / PANES); // run -1 warms up
    }
    const median = percentile(perPane, 50) ?? Number.NaN;
    expect(median, why(median, 0.05)).toBeLessThanOrEqual(budget(0.05));
  });
});
