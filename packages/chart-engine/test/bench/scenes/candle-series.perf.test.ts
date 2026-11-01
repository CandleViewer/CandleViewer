// Wall-clock half of the `candle-series` scene (E12-S06), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): CPU-side frame cost on the fake GL (no GPU in CI yet, so the
// 55 fps / 512 MB claims stay modelled until E11-T06 / T08). Pan, feed and theme-switch frames at
// 5k and 100k bars: each frame timed alone, the median and p95 bound, `gpuMemoryMbEstimate`
// recorded and bound; pan and feed also on OHLC bars (120 in view: the stem and ticks path). The AC:
// a theme switch takes < 1 ms and uploads nothing.
import { describe, expect, it } from "vitest";
import { CandleSeriesBench } from "../../../bench/scenes/candle-series.js";
import { percentile } from "../../../bench/stats.mjs";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

type Step = (bench: CandleSeriesBench, t: number) => void;
type Shape = "candles" | "bars";

/** 5 runs of 300 frames after a warm-up run: every frame's ms, and the run's GPU estimate. */
function run(
  step: Step,
  n: number,
  shape: Shape = "candles",
  window = 0,
): { p50: number; p95: number; gpuMb: number; bytes: number } {
  const frames: number[] = [];
  let gpuMb = 0;
  let bytes = 0;
  for (let r = -1; r < 5; r += 1) {
    const bench = new CandleSeriesBench(n, new FakeGl(), () => performance.now(), shape, window);
    bench.backend.takeUploadedBytes();
    for (let f = 1; f <= 300; f += 1) {
      const start = performance.now();
      step(bench, f * 16);
      if (r >= 0) frames.push(performance.now() - start); // run -1 is the warm-up
    }
    expect(bench.allocationsSinceWarm).toBe(0);
    gpuMb = bench.backend.gpuMemoryMbEstimate;
    bytes = bench.backend.takeUploadedBytes();
  }
  const p = (q: number): number => percentile(frames, q) ?? Number.NaN;
  return { p50: p(50), p95: p(95), gpuMb, bytes };
}

/** One shared ring per series: capacity (a power of two ≥ n) × 20 B, far under 512 MB. */
function memory(r: { gpuMb: number; bytes: number }, n: number, uploads: boolean): void {
  const ringMb = (2 ** Math.ceil(Math.log2(n)) * 20) / 2 ** 20;
  expect(r.gpuMb, `gpuMemoryMbEstimate ${r.gpuMb} MB`).toBeCloseTo(ringMb, 3);
  if (!uploads) expect(r.bytes, "uploaded bytes").toBe(0);
}

describe("perf budgets: candle series", () => {
  it.each([5_000, 100_000])("%i bars: a pan frame, median <= 0.3 ms, p95 <= 1 ms", (n) => {
    const r = run((b, t) => b.pan(t), n);
    expect(r.p50, why(r.p50, 0.3)).toBeLessThanOrEqual(budget(0.3));
    expect(r.p95, why(r.p95, 1)).toBeLessThanOrEqual(budget(1));
    memory(r, n, false);
  });

  it.each([5_000, 100_000])("%i bars: a feed frame, median <= 0.3 ms, p95 <= 1 ms", (n) => {
    const r = run((b, t) => b.feed(t), n);
    expect(r.p50, why(r.p50, 0.3)).toBeLessThanOrEqual(budget(0.3));
    expect(r.p95, why(r.p95, 1)).toBeLessThanOrEqual(budget(1));
    memory(r, n, true);
  });

  // The AC: a theme switch takes < 1 ms (p95) and uploads nothing.
  it.each([5_000, 100_000])("%i bars: a theme switch frame, p95 <= 1 ms", (n) => {
    const r = run((b, t) => b.switchTheme(t), n);
    expect(r.p95, why(r.p95, 1)).toBeLessThanOrEqual(budget(1));
    memory(r, n, false);
  });

  it.each([5_000, 100_000])("%i OHLC bars: a pan frame, median <= 0.3 ms, p95 <= 1 ms", (n) => {
    const r = run((b, t) => b.pan(t), n, "bars", 120);
    expect(r.p50, why(r.p50, 0.3)).toBeLessThanOrEqual(budget(0.3));
    expect(r.p95, why(r.p95, 1)).toBeLessThanOrEqual(budget(1));
    memory(r, n, false);
  });

  it.each([5_000, 100_000])("%i OHLC bars: a feed frame, median <= 0.3 ms, p95 <= 1 ms", (n) => {
    const r = run((b, t) => b.feed(t), n, "bars", 120);
    expect(r.p50, why(r.p50, 0.3)).toBeLessThanOrEqual(budget(0.3));
    expect(r.p95, why(r.p95, 1)).toBeLessThanOrEqual(budget(1));
    memory(r, n, true);
  });
});
