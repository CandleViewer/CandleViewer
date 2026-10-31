// Wall-clock half of the `resize-drag` scene (E11-S10 PR 2, BQ-154), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): the p95 CPU of one drag resize (policy, runtime resize and its
// frame on the fake GL), each step timed on its own so the reallocating steps are the tail it
// reads, is <= 1 ms, a small slice of budget #1's 16.6 ms frame. The real-GPU p95 is G-35.
import { describe, expect, it } from "vitest";
import { DRAG_FRAMES, ResizeDragBench } from "../../../bench/scenes/resize-drag.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";
import { FakeGl, FULL, ROOMY } from "../../gl/fake-gl.js";

describe("perf budgets: a 2 s splitter drag", () => {
  it("the p95 CPU per drag resize, with its frame, is <= 1 ms (5 drags, 600 steps)", () => {
    const perStep: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new ResizeDragBench(new FakeGl({ params: ROOMY }), () => FULL);
      for (let f = 0; f < DRAG_FRAMES; f += 1) {
        const start = performance.now();
        bench.step(f);
        if (r >= 0) perStep.push(performance.now() - start); // drag -1 warms up
      }
      expect(bench.settle().dragShrinks).toBe(0);
    }
    const p95 = percentile(perStep, 95) ?? Number.NaN;
    expect(p95, why(p95, 1)).toBeLessThanOrEqual(budget(1));
  });
});
