// The clock-free half of the `scheduler-overhead` microbench (E11-S01 PR2); timing is in the
// .perf.test.ts. Its 600-frame run is the ticket's "The hot path allocates nothing" scenario.
import { describe, expect, it } from "vitest";
import { FRAME_STAGES } from "../../../bench/instrumentation.mjs";
import { SchedulerOverheadBench } from "../../../bench/scenes/scheduler-overhead.js";

describe("Scenario: The hot path allocates nothing", () => {
  it("600 frames of pan plus data updates reuse every pooled structure", () => {
    const bench = new SchedulerOverheadBench();
    const { scheduler } = bench;
    const reused = [scheduler.ctx, scheduler.timings.ms, scheduler.notice, bench.graph.walk()];
    for (let f = 1; f <= 600; f += 1) bench.step(f * 16);
    expect(bench.allocationsInFramePath).toBe(0);
    const now = [scheduler.ctx, scheduler.timings.ms, scheduler.notice, bench.graph.walk()];
    expect(now.every((o, i) => o === reused[i])).toBe(true);
    // One request per wake, never a second; every frame collected its 36 nodes and 4 axes.
    expect([bench.requests, scheduler.frames, scheduler.ctx.stats.collected]).toEqual([
      601, 601, 40,
    ]);
    expect([scheduler.parked, scheduler.queue.length, scheduler.lod]).toEqual([true, 0, 0]);
    expect(Object.keys(bench.perStageMs())).toEqual(FRAME_STAGES); // the nine 06 §4.3 stages
  });
});
