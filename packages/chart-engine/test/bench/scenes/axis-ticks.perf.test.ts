// Wall-clock half of the `axis-ticks` scene (E11-S06, BQ-204), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): both axes rebuilt in ≤ 1 ms a frame, the ticket's ≤ 0.5 ms
// per axis (median of 5 runs), in UTC and in a zone with DST; and `axis-render` (E11-S06 PR 3):
// the same with both axes' labels written into the SDF batch.
import { describe, expect, it } from "vitest";
import { AxisTicksBench } from "../../../bench/scenes/axis-ticks.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: the axes on a pan frame", () => {
  // America/New_York: a non-UTC zone, whose offsets come from the clock's per-hour cache.
  it.each([
    ["UTC", false],
    ["America/New_York", false],
    ["UTC", true],
  ] as const)(
    "%s (labels drawn: %s): both axes in <= 1 ms (0.5 ms per axis, median of 5 runs)",
    (zone, text) => {
      const perFrame: number[] = [];
      for (let r = -1; r < 5; r += 1) {
        const bench = new AxisTicksBench(5_000, zone, text);
        const start = performance.now();
        for (let f = 0; f < 300; f += 1) bench.step();
        if (r >= 0) perFrame.push((performance.now() - start) / 300); // run -1 warms up
      }
      const median = percentile(perFrame, 50) ?? Number.NaN;
      expect(median, why(median, 1)).toBeLessThanOrEqual(budget(1));
    },
  );
});
