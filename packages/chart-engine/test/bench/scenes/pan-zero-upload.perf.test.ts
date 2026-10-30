// Wall-clock half of the `pan-zero-upload` scene (E11-S01 PR3), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): a pan frame over 100 000 bars stays in the scheduler's 0.3 ms.
import { describe, expect, it } from "vitest";
import { PanZeroUploadBench } from "../../../bench/scenes/pan-zero-upload.js";
import { percentile } from "../../../bench/stats.mjs";

describe("perf budgets: pan over 100 000 bars with zero re-upload", () => {
  it("a pan frame through scheduler and batch builder takes <= 0.3 ms (median of 5 runs)", () => {
    const perFrame: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new PanZeroUploadBench(100_000, () => performance.now());
      const start = performance.now();
      for (let f = 1; f <= 600; f += 1) bench.step(f * 16);
      if (r >= 0) perFrame.push((performance.now() - start) / 600); // run -1 is the warm-up
      expect([bench.builder.uploads, bench.allocationsInFramePath]).toEqual([1, 0]);
    }
    expect(percentile(perFrame, 50) ?? Number.NaN).toBeLessThanOrEqual(0.3);
  });
});
