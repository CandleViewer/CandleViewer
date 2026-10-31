// Wall-clock half of the `draw-submit` scene (E11-S02 PR2), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): 06 §4.3's composite + present slice for a 3-pane frame.
import { describe, expect, it } from "vitest";
import { DrawSubmitBench } from "../../../bench/scenes/draw-submit.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: draw submission", () => {
  it("a 3-pane frame builds and submits in <= 1.6 ms (median of 50 frames)", () => {
    const bench = new DrawSubmitBench(new FakeGl());
    for (let i = 0; i < 10; i += 1) bench.step(); // warm-up: compiles and first uploads
    const runs: number[] = [];
    for (let i = 0; i < 50; i += 1) {
      const start = performance.now();
      bench.step();
      runs.push(performance.now() - start);
    }
    const median = percentile(runs, 50) ?? Number.NaN;
    expect(median, why(median, 1.6)).toBeLessThanOrEqual(budget(1.6));
  });
});
