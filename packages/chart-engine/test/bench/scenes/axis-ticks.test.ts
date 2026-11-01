// The counted half of the `axis-ticks` scene (E11-S06, BQ-204); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { AxisTicksBench } from "../../../bench/scenes/axis-ticks.js";

describe("perf scene: the axes rebuild on every pan frame (counted)", () => {
  it("300 pans rebuild both axes each frame with a bounded grid and labels", () => {
    const bench = new AxisTicksBench();
    const { axes } = bench;
    for (let f = 0; f < 300; f += 1) bench.step();
    expect(bench.rebuilt).toBe(300);
    expect(axes.priceLabels.length).toBeGreaterThan(5);
    expect(axes.timeLabels.length).toBeGreaterThan(5);
    // O(candidates), never O(bars): tens of lines for 5 000 bars.
    expect(axes.grid.count).toBeLessThan(100);
    expect(axes.gutter.remeasures).toBe(1); // the magnitude class never changed
    expect(axes.counters.ticksDrawn).toEqual([axes.timeLabels.length, axes.priceLabels.length]);
  });
});
