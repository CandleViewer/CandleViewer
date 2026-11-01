// The counted `b6-sync4` scene (E11-S09 PR 2, #446 "Four synced charts in budget"): structure and
// counters only. The B6 timing (≤ 16.7 ms aggregate, worker CPU ≤ 70 %) is the owner-run
// hardware leg on the reference machine; nothing here reads a clock.
import { describe, expect, it } from "vitest";
import {
  B6_CHARTS,
  B6_FRAMES,
  B6_LEAD_FRAMES,
  B6Sync4Bench,
} from "../../../bench/scenes/b6-sync4.js";
import { FakeGl, FULL, ROOMY } from "../../gl/fake-gl.js";

describe("Scenario: Four synced charts in budget (structure and counters)", () => {
  it("4 charts in one group: one frame per chart per tick, every member in step, no echo", () => {
    const bench = new B6Sync4Bench(
      () => new FakeGl({ params: ROOMY }),
      () => FULL,
    ).run();
    const c = bench.counters;
    expect(c.ticks).toBe(B6_FRAMES);
    expect(bench.runtime.size).toBe(B6_CHARTS);
    const sync = bench.runtime.syncCounters;
    // `echoes` is a hub-level guard the runtime never reaches; no echo shows as one frame per
    // chart per tick and every member in step, below.
    expect(sync).toMatchObject({ groupMembers: B6_CHARTS, dropped: 0 });
    expect(sync.maxPropagationsPerFrame).toBe(1);
    // Every leader sweep reaches the others: about one propagation per session frame.
    expect(sync.propagations).toBeGreaterThan(B6_FRAMES * 0.9);
    expect(c.maxFramesPerChartPerTick).toBe(1); // no echo frame, ever
    expect(c.rangeMismatches).toBe(0);
    expect(c.lateFollows).toBe(0); // a member follows in the leader's tick (BQ-12)
    // Each chart drew on most frames: its own sweep, or the remote line it follows.
    for (const n of c.frames) expect(n).toBeGreaterThan(B6_FRAMES / 2);
    // The stand-in content's chassis: the grid and the crosshair, 2 draws a chart (BQ-23).
    expect(c.maxDrawCalls).toBeLessThanOrEqual(2);
    expect(bench.posted.filter((m) => m.t === "error")).toEqual([]);
    expect(B6Sync4Bench.leaderOf(B6_LEAD_FRAMES * B6_CHARTS)).toBe(1); // the leaders rotate
  });

  it("is deterministic for a seed", () => {
    const run = (): string =>
      JSON.stringify(
        new B6Sync4Bench(
          () => new FakeGl({ params: ROOMY }),
          () => FULL,
        ).run().counters,
      );
    expect(run()).toBe(run());
  });
});
