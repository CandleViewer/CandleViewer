// Wall-clock half of the `text-batch` scene (E11-S11 PR B, BQ-275), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): B3's CPU batching sub-gate, <= 2.0 ms per frame.
import { describe, expect, it } from "vitest";
import { TextBatchBench } from "../../../bench/scenes/text-batch.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: dense cell text", () => {
  it("12,500 glyphs written, built and submitted in <= 2.0 ms (median of 50 frames)", () => {
    const bench = new TextBatchBench(new FakeGl());
    for (let i = 0; i < 10; i += 1) bench.step(); // warm-up
    const runs: number[] = [];
    for (let i = 0; i < 50; i += 1) {
      const start = performance.now();
      bench.step();
      runs.push(performance.now() - start);
    }
    const median = percentile(runs, 50) ?? Number.NaN;
    expect(median, why(median, 2)).toBeLessThanOrEqual(budget(2));
    expect([bench.backend.trace.draws, bench.allocationsInFramePath]).toEqual([1, 0]);
  });
});
