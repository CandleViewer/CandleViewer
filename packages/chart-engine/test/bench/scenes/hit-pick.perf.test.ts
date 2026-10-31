// Wall-clock half of the `hit-pick` scene (E11-S08, BQ-141), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): R5 / B8 / 06 §4.3, the p95 of 1 000 picks within 1 ms.
import { describe, expect, it } from "vitest";
import { HitPickBench } from "../../../bench/scenes/hit-pick.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: picking", () => {
  it.each([250, 1_000])("%i objects: the p95 of 1 000 picks is <= 1 ms (R5, B8)", (n) => {
    const bench = new HitPickBench(n, () => performance.now());
    bench.run(); // warm-up
    bench.run();
    const p95 = percentile(Array.from(bench.times), 95) ?? Number.NaN;
    expect(p95, why(p95, 1)).toBeLessThanOrEqual(budget(1));
  });
});
