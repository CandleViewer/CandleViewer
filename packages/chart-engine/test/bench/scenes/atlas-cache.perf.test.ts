// Wall-clock half of the `atlas-cache` scene (E11-S11 PR A, BQ-275), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): the cache read's CPU side within B9's 5 ms restore.
import { describe, expect, it } from "vitest";
import { AtlasCacheBench } from "../../../bench/scenes/atlas-build.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: SDF atlas cache read", () => {
  it("key + shape + checksum of the packed-rows record in <= 1 ms (median of 5 runs)", () => {
    const bench = new AtlasCacheBench();
    const runs: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const start = performance.now();
      expect(bench.step()).toBe(true);
      if (r >= 0) runs.push(performance.now() - start); // run -1 is the warm-up
    }
    const median = percentile(runs, 50) ?? Number.NaN;
    expect(median, why(median, 1)).toBeLessThanOrEqual(budget(1));
  });
});
