// Wall-clock half of the `candle-series` scene (E12-S06), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): CPU-side frame cost on the fake GL (no GPU in CI yet, so the
// 55 fps / 512 MB claims stay modelled until E11-T06 / T08). Pan and feed frames at 100k bars.
import { describe, expect, it } from "vitest";
import { CandleSeriesBench } from "../../../bench/scenes/candle-series.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

const median = (run: (bench: CandleSeriesBench, t: number) => void, n: number): number => {
  const per: number[] = [];
  for (let r = -1; r < 5; r += 1) {
    const bench = new CandleSeriesBench(n, new FakeGl(), () => performance.now());
    const start = performance.now();
    for (let f = 1; f <= 300; f += 1) run(bench, f * 16);
    if (r >= 0) per.push((performance.now() - start) / 300); // run -1 is the warm-up
    expect(bench.allocationsSinceWarm).toBe(0);
  }
  return percentile(per, 50) ?? Number.NaN;
};

describe("perf budgets: candle series", () => {
  it.each([5_000, 100_000])("%i bars: a pan frame <= 0.3 ms (median of 5 runs)", (n) => {
    const ms = median((b, t) => b.pan(t), n);
    expect(ms, why(ms, 0.3)).toBeLessThanOrEqual(budget(0.3));
  });

  it.each([5_000, 100_000])("%i bars: a feed frame <= 0.3 ms (median of 5 runs)", (n) => {
    const ms = median((b, t) => b.feed(t), n);
    expect(ms, why(ms, 0.3)).toBeLessThanOrEqual(budget(0.3));
  });
});
