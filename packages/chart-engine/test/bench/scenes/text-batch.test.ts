// The counted half of the `text-batch` scene (E11-S11 PR B, BQ-275): "Dense cell text renders
// within its measured budget" — one instanced draw call, 12,500 glyphs, nothing allocated.
import { describe, expect, it } from "vitest";
import { TextBatchBench } from "../../../bench/scenes/text-batch.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("perf scene: dense cell text (B3 text, counted)", () => {
  it("2,500 cells × 2 numbers: 12,500 glyphs in one draw call; 60 pans allocate nothing", () => {
    const bench = new TextBatchBench(new FakeGl());
    for (let f = 0; f < 60; f += 1) bench.step();
    const { trace } = bench.backend;
    expect([trace.draws, trace.triangles, bench.cells.count]).toEqual([1, 25_000, 12_500]);
    expect(bench.allocationsInFramePath).toBe(0);
    expect(bench.metrics.counters.replacedGlyphs).toBe(0);
  });
});
