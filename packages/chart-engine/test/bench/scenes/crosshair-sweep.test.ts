// The counted half of the `crosshair-sweep` scene (E11-S07, BQ-6); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { CrosshairSweepBench, PX_PER_FRAME } from "../../../bench/scenes/crosshair-sweep.js";

describe("perf scene: the crosshair swept at 1000 px/s (counted)", () => {
  it("300 frames: a rewrite each frame, one edge and one readout per bar, a stable ring", () => {
    const bench = new CrosshairSweepBench();
    bench.step();
    const ring = bench.node.data;
    for (let f = 1; f < 300; f += 1) bench.step();
    expect(bench.node.data).toBe(ring); // no per-frame allocation in the line ring
    expect(bench.node.writes).toBe(300); // the cursor moved every frame
    // 6 px bars at 16.7 px a frame: a new bar every frame, so an edge and a readout each.
    expect(bench.edges).toBe(300);
    expect(bench.posted).toBe(300);
    expect(PX_PER_FRAME).toBeCloseTo(16.67, 2);
    // About 135 vertical and 240 horizontal dashes at DPR 2 over 1856 × 1056 CSS px.
    expect(bench.node.count).toBeGreaterThan(300);
    expect(bench.node.count).toBeLessThan(400);
    expect(bench.text).toMatch(/^[\d,.]+ \d\d \w{3} \d\d:\d\d$/);
  });
});

describe("perf scene: a held → with the chart root focused (E11-S07 BQ-7, counted)", () => {
  it("300 frames: a step and a summary each, the view following, one column write", () => {
    const bench = new CrosshairSweepBench();
    bench.key();
    const ring = bench.node.data;
    for (let f = 1; f < 300; f += 1) bench.key();
    expect(bench.node.data).toBe(ring); // the column fits the ring: no per-frame allocation
    // The view follows under a cursor pinned at the right edge at the same tick: the column and
    // the lines keep their pixels, so they are written once, not once a press.
    expect(bench.node.writes).toBe(1);
    expect(bench.edges).toBe(300); // one bar a press
    expect(bench.posted).toBe(300);
    expect(bench.follows).toBe(300); // from the last visible bar, every step makes the view follow
    expect(bench.said).toMatch(/^\d\d:\d\d, close [\d,.]+, delta /);
    const segs = Array.from({ length: bench.node.count }, (_, i) => bench.node.data[i * 9 + 4]);
    expect(segs.slice(0, 2)).toEqual([8, 4]); // the halo (2 + 2 × 1 px) and core at DPR 2
  });
});
