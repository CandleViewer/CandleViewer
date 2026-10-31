// The counted half of the `input-router` scene (E11-S04 PR 1, BQ-112); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { InputRouterBench } from "../../../bench/scenes/input-router.js";

describe("Scenario: Pan and zoom stay above the frame floor (the input stage, counted)", () => {
  it("600 frames of drag, glide and wheel register one integrator per release, no growth", () => {
    const bench = new InputRouterBench(100_000);
    const { momentum, velocity } = bench.gestures;
    for (let f = 0; f < 600; f += 1) bench.step(f, f * 16);
    // Ten releases at 1.5 px/ms, each glide over (its wheel cancels it) before the next drag.
    expect([bench.registrations, momentum.cancelled]).toEqual([10, 10]);
    expect(bench.gestures.momentum).toBe(momentum); // the one preallocated integrator
    expect(bench.gestures.velocity).toBe(velocity);
    expect(bench.changes).toBeGreaterThan(300);
    expect(Number.isFinite(bench.viewport.leftIndex)).toBe(true);
    expect(bench.scheduler.frames).toBe(600);
  });
});
