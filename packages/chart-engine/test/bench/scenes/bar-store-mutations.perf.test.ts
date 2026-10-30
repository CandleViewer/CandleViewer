// Wall-clock half of the `bar-store` mutation microbench (E11-T03), run ONLY by `vitest --project
// perf` (engine-bench, no coverage). The ticket's micro-bench budget: 1 M appends in ≤ 120 ms.
import { describe, expect, it } from "vitest";
import { percentile } from "../../../bench/stats.mjs";
import { BarStore } from "../../../src/model/index.js";

describe("perf budgets: bar-store mutations", () => {
  it("1 M one-bar appends, past the 200 000 ceiling, take ≤ 120 ms (median of 5 runs)", () => {
    const one = Int32Array.of(1_000);
    const bar = { time: new Float64Array(1), open: one, high: one, low: one, close: one };
    const batch = { ...bar, volume: Float32Array.of(1), priceOrigin: 0, tickSize: 1 };
    const runs: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const store = new BarStore();
      const start = performance.now();
      for (let i = 0; i < 1_000_000; i += 1) {
        batch.time[0] = i;
        store.append(batch);
      }
      if (r >= 0) runs.push(performance.now() - start); // run -1 is the warm-up
      expect(store.length).toBe(200_000);
    }
    expect(percentile(runs, 50) ?? Number.NaN).toBeLessThanOrEqual(120);
  });
});
