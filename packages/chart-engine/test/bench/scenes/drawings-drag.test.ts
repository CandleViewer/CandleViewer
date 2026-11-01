// The counted `drawings-drag` scene (E14-T03 slice 1, B8 skeleton), Scenario 1's isolation: a drag
// re-indexes one record and never updates the price or footprint stand-ins; a pan re-indexes none.
import { describe, expect, it } from "vitest";
import { DRAG_FRAMES, DrawingsDragBench } from "../../../bench/scenes/drawings-drag.js";

describe("Scenario: Dragging a drawing does not touch the price layer (counted)", () => {
  it("200 drawings + 50 order lines over 100 000 bars: one record per drag frame", () => {
    const bench = new DrawingsDragBench();
    expect([bench.drawings.set.size, bench.drawings.reindexed]).toEqual([250, 250]);
    bench.run();
    expect(bench.drawings.reindexed).toBe(250 + DRAG_FRAMES);
    expect(bench.drawings.boundsPasses).toBe(1 + DRAG_FRAMES);
    expect([bench.price.updates, bench.footprint.updates]).toEqual([1, 1]);
    bench.pan(-30);
    expect(bench.drawings.reindexed).toBe(250 + DRAG_FRAMES);
    expect([bench.price.updates, bench.footprint.updates]).toEqual([2, 2]);
  });
});
