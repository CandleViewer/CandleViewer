// The clock-free half of the `scene-graph` microbench (E11-S01); timing is in the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { SceneGraphBench } from "../../../bench/scenes/scene-graph.js";

describe("scene-graph bench: traverse 3 panes x 12 nodes, zero alloc", () => {
  it("600 pan + data frames reuse the walk, the context and every pooled entry", () => {
    const bench = new SceneGraphBench(3, 12);
    const [walk, stats] = [bench.graph.walk(), bench.ctx.stats];
    for (let f = 1; f <= 600; f += 1) bench.step(f * 16);
    expect(bench.allocationsInFramePath).toBe(0);
    expect([bench.graph.walk() === walk, bench.ctx.stats === stats]).toEqual([true, true]);
    expect(walk.length).toBe(2 + 3 * 20); // chart, time axis; per pane, itself, axis, 6 + 12
    // Warm-up collects all 62; each pan frame, the 36 content nodes and the 4 axes.
    expect([bench.frames, bench.collected]).toEqual([601, 62 + 600 * 40]);
  });
});
