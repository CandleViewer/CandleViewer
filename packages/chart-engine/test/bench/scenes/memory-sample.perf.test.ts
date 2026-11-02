// Wall-clock half of the `memory-sample` scene (E11-S15, BQ-S15-12), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): one MemoryAccount sample at the bench scale costs ≤ 0.2 ms, and
// a long run of samples allocates nothing the young generation would have to collect.
import { GCProfiler } from "node:v8";
import { describe, expect, it } from "vitest";
import { MemorySampleBench } from "../../../bench/scenes/memory-sample.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: the memory sample", () => {
  it("one sample of the bench-scale account takes <= 0.2 ms (median of 5 runs)", () => {
    const bench = new MemorySampleBench();
    const perSample: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const start = performance.now();
      for (let i = 0; i < 1_000; i += 1) bench.step(i);
      if (r >= 0) perSample.push((performance.now() - start) / 1_000); // run -1 warms up
    }
    const median = percentile(perSample, 50) ?? Number.NaN;
    expect(median, why(median, 0.2)).toBeLessThanOrEqual(budget(0.2));
  });

  it("a million warm samples trigger at most one young-generation collection (closures included)", () => {
    // A sample that allocates leaves garbage the young generation must collect: totalBytes as
    // `sources.map(...).reduce(...)` scavenged 24-25 times here (proved, then reverted), and even one
    // 32-byte closure a sample is ~32 MB over the run. A sample that allocates nothing leaves the
    // collector idle; one scavenge is tolerated, for a young generation already near full at start.
    const bench = new MemorySampleBench();
    let sink = 0;
    for (let i = 0; i < 100_000; i += 1) sink = bench.step(i); // warm up: tier up to optimised code
    const profiler = new GCProfiler();
    profiler.start();
    for (let i = 0; i < 1_000_000; i += 1) sink = bench.step(i);
    const stats = profiler.stop()?.statistics ?? [];
    const collections = stats.length;
    expect(sink).toBeGreaterThan(0);
    expect(collections <= 1, JSON.stringify(stats.map((s) => s.gcType))).toBe(true); // a GC count, not a wall-clock bound
  });
});
