// Wall-clock half of the E14-T04 availability control (BQ-04), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): 10 000 zero-length segments in one bucket, the worst pile a pane
// may hold (MAX_OBJECTS), and 1 100 brushes of 1 024 anchors at one spot (the budget counts each
// one's anchors), still pick within 1 ms (the per-pick work budget).
import { describe, expect, it } from "vitest";
import { hitViewport } from "../../bench/scenes/hit-pick.js";
import { percentile } from "../../bench/stats.mjs";
import { DrawingAdapter, ObjectIndex, createPickHit } from "../../src/hit/index.js";
import { priceToScreen, timeToScreen } from "../../src/viewport/index.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

const t = 9_900 * 60e6;

/** The median of 5 runs of the p99 of 200 picks (50 warm-up) at (x .. x + 4, y). */
function p99Of(index: ObjectIndex): number {
  const [x, y] = [timeToScreen(index.viewport, t), priceToScreen(index.viewport, 0, 1_000)];
  const hit = createPickHit();
  const runs: number[] = [];
  for (let run = 0; run < 5; run += 1) {
    const times: number[] = [];
    for (let i = 0; i < 250; i += 1) {
      const t0 = performance.now();
      index.pick(x + (i % 5), y, "mouse", hit);
      if (i >= 50) times.push(performance.now() - t0); // the first 50 warm up
    }
    runs.push(percentile(times, 99) ?? Number.NaN);
  }
  return runs.sort((a, b) => a - b)[2] as number;
}

describe("perf budgets: a pathological pile", () => {
  it("10 000 zero-length segments in one bucket: p99 of 200 picks <= 1 ms (median of 5)", () => {
    const index = new ObjectIndex(hitViewport().viewport);
    for (let i = 0; i < 10_000; i += 1) {
      index.registerPickable({
        id: `z${i}`,
        kind: "drawing",
        paneId: "main",
        zIndex: 0,
        widthPx: 1,
        geometry: { type: "segment", t0: t, p0: 1_000, t1: t, p1: 1_000 },
      });
    }
    const p99 = p99Of(index);
    expect(p99, why(p99, 1)).toBeLessThanOrEqual(budget(1));
  });

  it("1 100 brushes of 1 024 anchors at one spot: p99 of 200 picks <= 1 ms (median of 5)", () => {
    const index = new ObjectIndex(hitViewport().viewport);
    const drawings = new DrawingAdapter(index);
    const anchors = Array.from({ length: 1_024 }, (_, i) => [t + (i % 2) * 60e6, 1_000]).flat();
    for (let i = 0; i < 1_100; i += 1) {
      drawings.upsert({
        id: `b${i}`,
        tool: "brush",
        anchors,
        widthPx: 1,
        zIndex: 0,
        locked: false,
        visible: true,
      });
    }
    const p99 = p99Of(index);
    expect(p99, why(p99, 1)).toBeLessThanOrEqual(budget(1));
  });
});
