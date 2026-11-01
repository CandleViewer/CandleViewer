// Wall-clock half of the `forming-tick` scene (E12-S10), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): a live tick on the forming bar of a 100 000-bar series (the store
// merge, the ring's one slot, the marks' rescan, then the frame on the fake GL) stays far inside
// a frame at p95, and the mutation alone (store + ring + marks) is a small fraction of it.
import { describe, expect, it } from "vitest";
import { FormingTickBench } from "../../../bench/scenes/forming-tick.js";
import { percentile } from "../../../bench/stats.mjs";
import { BAR_FLAG } from "../../../src/model/BarStore.js";
import { candleBars } from "../../../bench/scenes/candle-series.js";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

const TICKS = 3_000;

describe("perf budgets: the forming bar's live tick", () => {
  it("100 000 bars: a tick frame p95 <= 0.3 ms (median of 5 runs)", () => {
    const p95s: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new FormingTickBench(100_000, new FakeGl(), () => performance.now());
      const per = new Float64Array(TICKS);
      for (let f = 0; f < TICKS; f += 1) {
        const start = performance.now();
        bench.tick(64 + f * 16);
        per[f] = performance.now() - start;
      }
      if (r >= 0) p95s.push(percentile(Array.from(per), 95) ?? Number.NaN); // run -1: warm-up
      expect(bench.allocationsSinceWarm).toBe(0);
    }
    const ms = percentile(p95s, 50) ?? Number.NaN;
    expect(ms, why(ms, 0.3)).toBeLessThanOrEqual(budget(0.3));
  });

  it("100 000 bars: 10 000 tick mutations (store + ring + marks) take <= 10 ms", () => {
    const runs: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const bench = new FormingTickBench(100_000, new FakeGl());
      const { store, ring } = bench.scene;
      const live = candleBars(1);
      (live.flags as Uint8Array)[0] = BAR_FLAG.forming;
      live.time[0] = store.indexToTime(store.length - 1);
      live.open[0] = 1_000;
      const start = performance.now();
      for (let i = 0; i < 10_000; i += 1) {
        live.close[0] = 997 + (i % 3);
        ring.sync(store, store.append(live, true));
      }
      if (r >= 0) runs.push(performance.now() - start);
      expect(bench.allocationsSinceWarm).toBe(0);
    }
    const ms = percentile(runs, 50) ?? Number.NaN;
    expect(ms, why(ms, 10)).toBeLessThanOrEqual(budget(10));
  });
});
