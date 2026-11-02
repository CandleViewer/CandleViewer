// Wall-clock half of the `dom-mirror` scene (E11-S13 PR-2, BQ-S13-14), run ONLY by `vitest
// --project perf` (engine-bench, no coverage): the 06 §4.3 DOM-mirror slice, p95 <= 1 ms per frame
// write at the 60-row default under a steady 30 bars/s feed (26 §12, F14: 0.8 ms p95 in Chromium).
import { describe, expect, it } from "vitest";
import { DomMirrorBench } from "../../../bench/scenes/dom-mirror.js";
import { percentile } from "../../../bench/stats.mjs";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: the DOM mirror", () => {
  it("60 rows at 30 bars/s: the p95 frame write is <= 1 ms (06 §4.3)", () => {
    const bench = new DomMirrorBench(600, () => performance.now());
    bench.run(); // warm-up
    bench.run();
    const p95 = percentile(Array.from(bench.times), 95) ?? Number.NaN;
    expect(p95, why(p95, 1)).toBeLessThanOrEqual(budget(1));
  });
});
