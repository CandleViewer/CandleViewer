// The counted half of the `resize-drag` scene (E11-S10 PR 2, BQ-154); timing is in the
// .perf.test.ts. The drag runs through the host's growth policy and the runtime on the fake GL.
import { describe, expect, it } from "vitest";
import { DRAG_FRAMES, ResizeDragBench, SETTLE_FRAMES } from "../../../bench/scenes/resize-drag.js";
import { FakeGl, FULL, ROOMY } from "../../gl/fake-gl.js";

describe("Scenario: Dragging a splitter does not cause reallocation storms", () => {
  it("reallocates at most once per 128 px of growth, never shrinks mid-drag, trims once after", () => {
    const gl = new FakeGl({ params: ROOMY });
    const bench = new ResizeDragBench(gl, () => FULL);
    for (let f = 0; f < DRAG_FRAMES; f += 1) bench.step(f);
    const drawn = gl.viewports.length;
    bench.settle();
    const growth = bench.maxWidth - 1200;
    expect(growth).toBeGreaterThan(128); // the seeded drag crosses several steps
    expect(bench.dragReallocations).toBeGreaterThan(0);
    expect(bench.dragReallocations).toBeLessThanOrEqual(Math.ceil(growth / 128));
    expect(bench.dragShrinks).toBe(0);
    expect([bench.trims, bench.settleFrames]).toEqual([1, SETTLE_FRAMES]);
    expect(bench.canvas.reallocations - bench.dragReallocations).toBe(1); // the trim
    expect(bench.canvas.width).toBe(bench.sizer.exactWidth);
    // The trim alone repaints: its frame draws the whole, now unpadded, store.
    expect(gl.viewports.slice(drawn).at(-1)).toEqual([0, 0, bench.sizer.exactWidth, 800]);
    const counters = bench.runtime.resizeCounters(1);
    expect(counters?.reallocations).toBe(bench.canvas.reallocations);
    // Every drag frame drew; none raised an error.
    const frames = bench.posted.filter((m) => m.t === "error");
    expect(frames).toEqual([]);
    expect(gl.log.filter((c) => c === "viewport").length).toBeGreaterThanOrEqual(DRAG_FRAMES);
  });
});
