// Wall-clock half of the `candle-lod` scene (E12-S09 PR 1, BQ-07 / BQ-12), run ONLY by `vitest
// --project perf` (engine-bench, no coverage): CPU-side frame cost on the fake GL at 5k / 50k /
// 100k bars × L0 / L1 / L2. No GPU in CI yet: AC2's GPU p95 ≤ 16.6 ms and ≥ 55 fps on the
// reference GPU are E11-T06 #449's rows in PR 2. An L2 pan here is the worst CPU case: a
// one-pass fold of every bar (the bench's stand-in for #418's decimator) plus the entry write.
import { describe, expect, it } from "vitest";
import { CandleLodBench } from "../../../bench/scenes/candle-lod.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

type Step = "pan" | "tick";

/** 5 runs of 200 frames after a warm-up run: every frame's ms. */
function run(n: number, tier: 0 | 1 | 2, step: Step): { p50: number; p95: number } {
  const frames: number[] = [];
  for (let r = -1; r < 5; r += 1) {
    const bench = new CandleLodBench(n, new FakeGl(), tier, () => performance.now());
    for (let f = 1; f <= 200; f += 1) {
      const start = performance.now();
      bench[step](f * 16);
      if (r >= 0) frames.push(performance.now() - start); // run -1 is the warm-up
    }
    expect(bench.allocationsSinceWarm).toBe(0);
  }
  const p = (q: number): number => percentile(frames, q) ?? Number.NaN;
  return { p50: p(50), p95: p(95) };
}

const ROWS = [5_000, 50_000, 100_000].flatMap((n) =>
  ([0, 1, 2] as const).map((t) => [n, t] as const),
);

describe("perf budgets: candle LOD tiers", () => {
  it.each(ROWS)("%i bars at L%i: a pan and a tick frame inside the p95 budget", (n, tier) => {
    for (const step of ["pan", "tick"] as const) {
      const r = run(n, tier, step);
      // L0 / L1: uniforms and one patched bar; L2: the full fold, linear in n (≈ 1 ms at 100k).
      if (tier === 2) expect(r.p95, why(r.p95, 4)).toBeLessThanOrEqual(budget(4));
      else expect(r.p95, why(r.p95, 1)).toBeLessThanOrEqual(budget(1));
    }
  });
});
