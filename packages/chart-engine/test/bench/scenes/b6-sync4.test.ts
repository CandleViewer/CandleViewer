// The counted half of B6 (E11-S09 PR 2b, #446 "Four synced charts stay within budget"): four
// charts on two runtimes in one group, relayed by the registry. CI asserts structure and counters
// only; the 16.7 ms p95 and 70 % CPU leg is the owner-run hardware G-row (package README).
import { describe, expect, it } from "vitest";
import { B6_CHARTS, B6_FRAMES, SyncFourBench } from "../../../bench/scenes/b6-sync4.js";
import { FakeCtx2D } from "../../canvas2d/fake-ctx2d.js";
import { FULL } from "../../gl/fake-gl.js";

const canvas = () => {
  const ctx = new FakeCtx2D();
  return { width: 264, height: 100, ctx, getContext: () => ctx };
};

describe("Scenario: Four synced charts stay within budget (B6, counted leg)", () => {
  it("test_b6_four_members_at_most_one_propagation_per_group_per_frame_and_no_echo", () => {
    const bench = new SyncFourBench(canvas, () => FULL).run();
    let members = 0;
    for (const w of bench.workers) {
      const ids = w === bench.workers[0] ? [1, 2] : [3, 4];
      for (const id of ids) {
        const c = w.runtime.syncCounters(id);
        expect(c?.propagationsPerFrameMax).toBeLessThanOrEqual(1);
        expect(c?.echoes).toBe(0);
        expect(c?.groupMembers).toBe(B6_CHARTS / 2);
      }
      members += w.runtime.syncCounters(ids[0] as number)?.groupMembers ?? 0;
    }
    expect(members).toBe(B6_CHARTS);
    expect(bench.registry.groupCount).toBe(1);
    expect(bench.maxRelayedPerFrame).toBeLessThanOrEqual(1); // one relayed sync per group a frame
    expect(bench.registry.counters.relayed).toBeGreaterThan(B6_FRAMES / 4); // the relay ran
    expect(bench.delivered).toBeGreaterThan(B6_FRAMES / 4); // and reached the other runtime
    const applied = [1, 2, 3, 4].map((id) => bench.workerOf(id).runtime.syncCounters(id)?.applied);
    expect(applied.every((n) => (n ?? 0) > 0)).toBe(true); // every chart followed a peer
    expect(bench.said).toEqual(["Panes linked: time, crosshair"]); // once, never per frame
    bench.dispose();
    expect(bench.said).toHaveLength(1); // every member disposed: nobody is left to hear it
    expect(bench.registry.groupCount).toBe(0);
  });
});
