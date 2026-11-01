// Wall-clock half of the `crosshair-sweep` scene (E11-S07, BQ-6), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): the crosshair's per-frame work in <= 0.3 ms (median of 5
// runs), a held `→` key step (E11-S07 BQ-7) within the same budget, and the CPU dash rewrite
// alone measured and reported against it.
import { describe, expect, it } from "vitest";
import { CrosshairSweepBench } from "../../../bench/scenes/crosshair-sweep.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

const FRAMES = 600;

function median(run: (b: CrosshairSweepBench) => void): number {
  const perFrame: number[] = [];
  for (let r = -1; r < 5; r += 1) {
    const bench = new CrosshairSweepBench();
    const start = performance.now();
    for (let f = 0; f < FRAMES; f += 1) run(bench);
    if (r >= 0) perFrame.push((performance.now() - start) / FRAMES); // run -1 warms up
  }
  return percentile(perFrame, 50) ?? Number.NaN;
}

describe("perf budgets: the crosshair on a 1000 px/s sweep", () => {
  it("resolve, dashed lines, readout and text in <= 0.3 ms a frame (median of 5 runs)", () => {
    const ms = median((b) => b.step());
    console.info(`crosshair-sweep: frame ${ms.toFixed(4)} ms/frame`);
    expect(ms, why(ms, 0.3)).toBeLessThanOrEqual(budget(0.3));
  });

  it("a held → with the root focused (step, column, readout, summary) in <= 0.3 ms a frame", () => {
    const ms = median((b) => b.key());
    console.info(`crosshair-sweep: key step ${ms.toFixed(4)} ms/frame`);
    expect(ms, why(ms, 0.3)).toBeLessThanOrEqual(budget(0.3));
  });

  it("the CPU dash rewrite alone (~375 instances at DPR 2) in <= 0.3 ms a frame", () => {
    const ms = median((b) => b.dash());
    console.info(`crosshair-sweep: CPU dash rewrite ${ms.toFixed(4)} ms/frame`);
    expect(ms, why(ms, 0.3)).toBeLessThanOrEqual(budget(0.3));
  });
});
