// Wall-clock half of the `volume-ring` scene (E12-S08 pre-stage), run ONLY by `vitest --project
// perf` (no coverage): a live-feed tick over 100 000 bars stays far inside a frame, and the
// per-frame work allocates nothing (the heap does not grow over 100 000 frames).
import { describe, expect, it } from "vitest";
import { VolumeRingBench } from "../../../bench/scenes/volume-ring.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: volume ring live feed", () => {
  it("100 000 feed steps over 100 000 bars take <= 60 ms (median of 5 runs)", () => {
    const runs: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new VolumeRingBench(100_000);
      const start = performance.now();
      for (let i = 0; i < 100_000; i += 1) bench.step();
      if (r >= 0) runs.push(performance.now() - start); // run -1 is the warm-up
      expect(bench.allocationsInMutationPath).toBe(0);
    }
    const median = percentile(runs, 50) ?? Number.NaN;
    expect(median, why(median, 60)).toBeLessThanOrEqual(budget(60));
  });

  it("the per-frame work allocates nothing: the ring array and the block words keep identity", () => {
    const bench = new VolumeRingBench(5_000);
    const [data, ints, palette, geom] = [
      bench.series.ring.data,
      bench.series.block.ints,
      bench.series.palette,
      bench.series.geom,
    ];
    for (let i = 0; i < 100_000; i += 1) bench.frame();
    expect(bench.series.ring.data).toBe(data);
    expect([bench.series.block.ints, bench.series.palette, bench.series.geom]).toEqual([
      ints,
      palette,
      geom,
    ]);
    expect(bench.allocationsInMutationPath).toBe(0);
  });
});
