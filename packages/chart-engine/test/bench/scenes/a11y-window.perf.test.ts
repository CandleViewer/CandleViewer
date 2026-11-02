// Wall-clock and allocation half of the `a11y-window` scene (E11-S13 PR-1, BQ-S13-01; rule 31),
// run ONLY by `vitest --project perf` (engine-bench, no coverage): over a 200k-bar BarStore, a pan
// frame through the real render runtime (publishA11y posting one `a11y` a frame) and the per-frame
// window core alone fit their budgets, and neither allocates on the frame path.
import { GCProfiler } from "node:v8";
import { describe, expect, it } from "vitest";
import {
  A11Y_BARS,
  A11yComputeBench,
  A11yWindowBench,
  probeAllocations,
} from "../../../bench/scenes/a11y-window.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: the a11y window over 200k bars", () => {
  it("a runtime pan frame, publishA11y included, takes <= 0.5 ms (median of 300 frames)", () => {
    const bench = new A11yWindowBench();
    for (let i = 0; i < 100; i += 1) bench.step(); // warm-up
    const runs: number[] = [];
    for (let i = 0; i < 300; i += 1) {
      const start = performance.now();
      bench.step();
      runs.push(performance.now() - start);
    }
    const median = percentile(runs, 50) ?? Number.NaN;
    // The first frame, then one a pan; the one error is init's degraded-2d notice (no GL here).
    expect([bench.a11yPosts, bench.errors, bench.lastError]).toEqual([401, 1, "ENGINE_NO_WEBGL2"]);
    expect(median, why(median, 0.5)).toBeLessThanOrEqual(budget(0.5));
  });

  it("the window core (compute, compare, copy) takes <= 0.005 ms (median of 5 runs)", () => {
    const bench = new A11yComputeBench();
    const perStep: number[] = [];
    let sink = 0;
    for (let r = -1; r < 5; r += 1) {
      const start = performance.now();
      for (let i = 0; i < 10_000; i += 1) sink = bench.step(i);
      if (r >= 0) perStep.push((performance.now() - start) / 10_000); // run -1 warms up
    }
    const median = percentile(perStep, 50) ?? Number.NaN;
    expect(sink).toBeGreaterThan(0);
    expect(median, why(median, 0.005)).toBeLessThanOrEqual(budget(0.005));
  });
});

describe("zero allocation on the a11y frame path (rule 31)", () => {
  it("600 runtime pan frames call no allocating built-in, and each posts its moved range", () => {
    const bench = new A11yWindowBench();
    for (let i = 0; i < 10; i += 1) bench.step(); // warm-up
    const posts = bench.a11yPosts;
    const calls = probeAllocations(() => {
      for (let i = 0; i < 600; i += 1) bench.step();
    });
    expect(calls).toBe(0);
    expect([bench.a11yPosts - posts, bench.errors]).toEqual([600, 1]); // init's notice only
    expect(bench.lastViewFirst > A11Y_BARS / 2, "the pan reached the far half").toBe(true); // a count, not a wall-clock bound
  });

  it("a million warm window-core steps trigger at most one young-generation collection", () => {
    // A core that allocates leaves garbage the young generation must collect: one spread window a
    // step scavenged many times here (proved, then reverted). `sink` is assigned, never summed: a
    // sum past the Smi range boxes a double a step in the loop itself. One scavenge is tolerated
    // for a young generation already near full at the start.
    const bench = new A11yComputeBench();
    let sink = 0;
    for (let i = 0; i < 100_000; i += 1) sink = bench.step(i); // tier up to optimised code
    const profiler = new GCProfiler();
    profiler.start();
    for (let i = 0; i < 1_000_000; i += 1) sink = bench.step(i);
    const stats = profiler.stop()?.statistics ?? [];
    expect(sink).toBeGreaterThan(0);
    expect(bench.changes > 1_000_000, "the view moves every step").toBe(true); // a count, not a wall-clock bound
    expect(stats.length <= 1, JSON.stringify(stats.map((s) => s.gcType))).toBe(true); // a GC count, not a wall-clock bound
  });

  it("the probe trips on Object.assign and slice, and restores every built-in it wrapped", () => {
    const assign = Object.assign;
    const slice = Array.prototype.slice;
    const into = { a: 0 };
    expect(
      probeAllocations(() => {
        Object.assign(into, { a: 1 });
        void [1, 2, 3].slice(1);
      }),
    ).toBe(2);
    expect([Object.assign, Array.prototype.slice]).toEqual([assign, slice]);
    expect(() =>
      probeAllocations(() => {
        throw new Error("boom");
      }),
    ).toThrow("boom");
    expect(Object.assign).toBe(assign);
  });
});
