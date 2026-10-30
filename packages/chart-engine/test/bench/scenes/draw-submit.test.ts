// The clock-free half of the `draw-submit` scene (E11-S02 PR2); timing is in the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { DrawSubmitBench } from "../../../bench/scenes/draw-submit.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("draw-submit scene", () => {
  it("submits a 3-pane frame of 18 draws from 3 programs and estimates its GPU memory", () => {
    const bench = new DrawSubmitBench(new FakeGl());
    for (let i = 0; i < 3; i += 1) bench.step();
    const { trace, programs } = bench.backend;
    expect([trace.draws, programs.stats.compiles]).toEqual([18, 3]);
    expect(bench.backend.gpuMemoryMbEstimate).toBeCloseTo((18 * 16384 + 262144) / 2 ** 20, 9);
  });
});
