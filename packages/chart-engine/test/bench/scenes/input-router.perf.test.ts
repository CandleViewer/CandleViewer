// Wall-clock half of the `input-router` scene (E11-S04 PR 1, BQ-112), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): 06 §4.3's input stage stays within 1 ms a frame.
import { describe, expect, it } from "vitest";
import { InputRouterBench } from "../../../bench/scenes/input-router.js";
import { percentile } from "../../../bench/stats.mjs";

describe("perf budgets: the input router", () => {
  it("the input stage of a drag, glide and wheel frame takes <= 1 ms (median of 5 runs)", () => {
    const perFrame: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new InputRouterBench(100_000, () => performance.now());
      for (let f = 0; f < 600; f += 1) bench.step(f, f * 16);
      if (r >= 0) perFrame.push(bench.inputMs / 600); // run -1 warms up
      expect(bench.registrations).toBe(10);
    }
    expect(percentile(perFrame, 50) ?? Number.NaN).toBeLessThanOrEqual(1);
  });
});
