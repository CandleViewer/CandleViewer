// Wall-clock half of the `candle-ring` scene (E12-S06), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): a live-feed tick (merge-patch + append, store + ring + 2 batch
// patches) over 100 000 bars stays far inside a frame.
import { describe, expect, it } from "vitest";
import { CandleRingBench } from "../../../bench/scenes/candle-ring.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: candle ring live feed", () => {
  it("100 000 feed steps over 100 000 bars take <= 60 ms (median of 5 runs)", () => {
    const runs: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new CandleRingBench(100_000);
      const start = performance.now();
      for (let i = 0; i < 100_000; i += 1) bench.step();
      if (r >= 0) runs.push(performance.now() - start); // run -1 is the warm-up
      expect(bench.allocationsInMutationPath).toBe(0);
    }
    const median = percentile(runs, 50) ?? Number.NaN;
    expect(median, why(median, 60)).toBeLessThanOrEqual(budget(60));
  });
});
