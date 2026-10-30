// Wall-clock half of the `degraded-2d-pan` scene (E11-T05, README BQ-95), run ONLY by `vitest
// --project perf` (engine-bench, no coverage): the CPU side of a 2D pan frame over 20 000 bars
// (collect, build, bucket, path calls on a fake context) fits a 30 fps frame with room to rasterise.
// The real-canvas ≥ 30 fps at 20 000 bars is a per-release manual record (BQ-61's precedent).
import { describe, expect, it } from "vitest";
import { Degraded2dPanBench } from "../../../bench/scenes/degraded-2d-pan.js";
import { percentile } from "../../../bench/stats.mjs";
import type { Ctx2DLike } from "../../../src/canvas2d/ctx2d.js";

/** A context that does nothing: the timing is the engine's CPU side alone. */
const silent = (): Ctx2DLike => ({
  fillStyle: "",
  strokeStyle: "",
  lineWidth: 1,
  clearRect: () => undefined,
  fillRect: () => undefined,
  beginPath: () => undefined,
  rect: () => undefined,
  moveTo: () => undefined,
  lineTo: () => undefined,
  fill: () => undefined,
  stroke: () => undefined,
});

describe("perf budgets: degraded-2d pan over 20 000 bars", () => {
  it("a 2D pan frame's CPU side takes <= 8 ms (median of 60 frames, after warm-up)", () => {
    const bench = new Degraded2dPanBench(silent(), 20_000);
    for (let i = 0; i < 10; i += 1) bench.step(-2);
    const runs: number[] = [];
    for (let i = 0; i < 60; i += 1) {
      const start = performance.now();
      bench.step(-2);
      runs.push(performance.now() - start);
    }
    expect(percentile(runs, 50) ?? Number.NaN).toBeLessThanOrEqual(8);
  });
});
