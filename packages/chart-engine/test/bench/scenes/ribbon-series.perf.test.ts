// Wall-clock half of the `ribbon-series` scene (E12-S07 PR B), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): CPU-side frame cost on the fake GL (no GPU in CI yet, so
// the GPU side stays modelled until E11-T06 / T08). Pan and feed frames at 5k and 100k bars for
// line, area and baseline, 600 bars in view (L1 / L0) and every bar at the spacing floor (L2).
import { describe, expect, it } from "vitest";
import { RibbonSeriesBench } from "../../../bench/scenes/ribbon-series.js";
import type { RibbonKind } from "../../../src/layers/index.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

const median = (
  run: (bench: RibbonSeriesBench, t: number) => void,
  n: number,
  kind: RibbonKind,
  window: number,
): number => {
  const per: number[] = [];
  for (let r = -1; r < 5; r += 1) {
    const now = (): number => performance.now();
    const bench = new RibbonSeriesBench(n, new FakeGl(), now, kind, window);
    const start = performance.now();
    for (let f = 1; f <= 300; f += 1) run(bench, f * 16);
    if (r >= 0) per.push((performance.now() - start) / 300); // run -1 is the warm-up
    expect(bench.allocationsSinceWarm).toBe(0);
  }
  return percentile(per, 50) ?? Number.NaN;
};

describe("perf budgets: ribbon series (line, area, baseline)", () => {
  for (const kind of ["line", "area", "baseline"] as const) {
    for (const window of [600, 0]) {
      const view = window > 0 ? `${window} in view` : "the spacing floor";
      it.each([5_000, 100_000])(`%i ${kind} bars, ${view}: pan / feed <= 0.3 ms`, (n) => {
        const pan = median((b, t) => b.pan(t), n, kind, window);
        expect(pan, why(pan, 0.3)).toBeLessThanOrEqual(budget(0.3));
        const feed = median((b, t) => b.feed(t), n, kind, window);
        expect(feed, why(feed, 0.3)).toBeLessThanOrEqual(budget(0.3));
      });
    }
  }
});
