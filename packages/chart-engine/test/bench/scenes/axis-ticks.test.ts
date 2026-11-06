// The counted half of the `axis-ticks` scene (E11-S06, BQ-204); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { AxisTicksBench, DAILY, MINUTE, WEEKLY } from "../../../bench/scenes/axis-ticks.js";

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

  // BQ-203: outside UTC the day and month loops read offsets from the clock's runs; once the
  // runs in view are known, a repeated sweep over the same pans reads no formatter at all.
  it.each([
    ["America/New_York", "DAILY", DAILY],
    ["America/New_York", "WEEKLY", WEEKLY],
    ["Asia/Singapore", "DAILY", DAILY],
    ["Asia/Singapore", "WEEKLY", WEEKLY],
  ] as const)("%s %s: 0 formatter reads on a repeated pan sweep", (zone, _, shape) => {
    const bench = new AxisTicksBench(4_000, zone, shape);
    const clock = bench.axes.time.clock;
    // The first sweep there and back meets each run once ...
    for (let f = 0; f < 300; f += 1) bench.step();
    for (let f = 0; f < 300; f += 1) bench.step(-1);
    const reads = clock.reads;
    expect(reads).toBeGreaterThan(0);
    // ... and every later pan frame over the same span reads none.
    for (let f = 0; f < 300; f += 1) bench.step();
    for (let f = 0; f < 300; f += 1) bench.step(-1);
    expect(clock.reads - reads).toBe(0);
    expect(bench.rebuilt).toBe(1200);
    expect(bench.axes.timeLabels.length).toBeGreaterThan(3);
  });

  it("axis-render (E11-S06 PR 3): every kept label of both axes in the one text batch", () => {
    const bench = new AxisTicksBench(5_000, "UTC", MINUTE, true);
    const { axes } = bench;
    bench.step();
    const grown = axes.text.grown;
    for (let f = 0; f < 300; f += 1) bench.step();
    const chars = [...axes.priceLabels, ...axes.timeLabels].join("").replaceAll(" ", "");
    expect(axes.text.count).toBe(chars.length);
    expect(axes.text.grown).toBe(grown); // the ring is warm: no growth on a pan
    expect(axes.gutter.remeasures).toBe(1); // measured with the atlas metrics, once
  });
});
