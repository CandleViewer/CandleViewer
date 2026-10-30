// Wall-clock half of the `gl-registry` scene (E11-S02 PR1), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): the registry's share of the 2 s restore (30 §5.3 criterion 8).
import { describe, expect, it } from "vitest";
import { GlRegistryBench } from "../../../bench/scenes/gl-registry.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";

describe("perf budgets: GL registry invalidate + recreate", () => {
  it("1 000 resources invalidate and recreate in <= 5 ms (median of 5 runs)", () => {
    const runs: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new GlRegistryBench(new FakeGl());
      const start = performance.now();
      expect(bench.step()).toBe(0);
      if (r >= 0) runs.push(performance.now() - start); // run -1 is the warm-up
    }
    expect(percentile(runs, 50) ?? Number.NaN).toBeLessThanOrEqual(5);
  });
});
