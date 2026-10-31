// The counted half of the `scale-mode-switch` scene (E11-S05, BQ-126); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { PANES, ScaleModeSwitchBench } from "../../../bench/scenes/scale-mode-switch.js";

describe("perf scene: a scale-mode switch is a projection change (counted)", () => {
  it("400 switches over 100 000 bars rewrite the same 3 blocks and stay finite", () => {
    const bench = new ScaleModeSwitchBench(100_000);
    const floats = bench.blocks.map((b) => b.floats);
    const logs = new Set<number>();
    for (let f = 0; f < 400; f += 1) {
      bench.step();
      logs.add(bench.blocks[0]?.floats[7] ?? -1);
      expect(Number.isFinite(bench.checksum)).toBe(true);
    }
    expect(bench.blocks.every((b, i) => b.floats === floats[i])).toBe(true);
    expect([...logs].sort()).toEqual([0, 1]); // both shader paths were exercised
    expect(bench.blocks).toHaveLength(PANES);
  });
});
