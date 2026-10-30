// The counted half of the `viewport-transform` scene (E11-S03, BQ-80); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { PANES, ViewportTransformBench } from "../../../bench/scenes/viewport-transform.js";

describe("perf scene: the shared transform per pane per frame (counted)", () => {
  it("600 pan frames rewrite the same 3 preallocated blocks and stay finite", () => {
    const bench = new ViewportTransformBench(100_000);
    const blocks = [...bench.blocks];
    const floats = blocks.map((b) => b.floats);
    const left = bench.viewport.leftIndex;
    for (let f = 0; f < 600; f += 1) bench.step();
    expect(bench.blocks.every((b, i) => b === blocks[i] && b.floats === floats[i])).toBe(true);
    expect(bench.viewport.leftIndex).toBeCloseTo(left + 300, 9); // 1 800 px of 6 px bars
    expect(Number.isFinite(bench.checksum)).toBe(true);
    expect(bench.blocks).toHaveLength(PANES);
  });
});
