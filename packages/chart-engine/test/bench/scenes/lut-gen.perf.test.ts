// Wall-clock half of the `lut-gen` scene (E11-T04 PR-3, BQ-T04-09), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): each colour LUT in <= 2 ms (the ticket's Performance note),
// so a theme switch's three LUTs stay inside 26 §5 rule 1's one-frame theme switch.
import { describe, expect, it } from "vitest";
import { LutGenBench } from "../../../bench/scenes/lut-gen.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

const CALLS = 20; // per run, so a run is well above the timer's resolution

function medianMs(step: () => void): number {
  const runs: number[] = [];
  for (let r = -1; r < 5; r += 1) {
    const start = performance.now();
    for (let i = 0; i < CALLS; i += 1) step();
    if (r >= 0) runs.push((performance.now() - start) / CALLS); // run -1 is the warm-up
  }
  return percentile(runs, 50) ?? Number.NaN;
}

describe("perf budgets: colour LUT generation", () => {
  it.each(["bid", "ask", "delta"] as const)("the %s LUT in <= 2 ms (median of 5 runs)", (lut) => {
    const bench = new LutGenBench();
    const median = medianMs(() => bench.stepOne(lut));
    expect(median, why(median, 2)).toBeLessThanOrEqual(budget(2));
  });

  it("a whole theme switch (three LUTs) in <= 6 ms (median of 5 runs)", () => {
    const bench = new LutGenBench();
    const median = medianMs(() => bench.step());
    expect(median, why(median, 6)).toBeLessThanOrEqual(budget(6));
  });
});
