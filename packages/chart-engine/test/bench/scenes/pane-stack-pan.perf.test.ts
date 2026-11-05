// Wall-clock bound for the E11-S09 pane stack (PR 1a review M1), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): a pan frame of 16 panes (E15-K01's `maxPanes`), real runtime, fake GL.
import { describe, expect, it } from "vitest";
import { percentile } from "../../../bench/stats.mjs";
import type { FromWorker } from "../../../src/worker/protocol.js";
import { createRenderRuntime } from "../../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../../gl/fake-gl.js";
import { MIN, minuteMap, T0 } from "../../interaction/fixtures.js";
import { TestClock } from "../../scene/test-clock.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: a 16-pane pan frame", () => {
  it("one coalesced viewport a frame, <= 0.5 ms a frame (median of 5 runs of 600)", () => {
    const perFrame: number[] = [];
    for (let r = -1; r < 5; r += 1) {
      const [clock, out] = [new TestClock(), [] as FromWorker[]];
      const rt = createRenderRuntime({
        runMode: "inline",
        post: (m) => void out.push(m),
        requestFrame: (cb) => void clock.requestFrame(() => cb()),
        now: () => clock.now(),
        setTimer: () => undefined,
        probe: () => FULL,
        timeMap: minuteMap(),
      });
      const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
      const canvas = { width: 1064, height: 1624, getContext: () => new FakeGl({ params: ROOMY }) };
      rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config: { syncGroup: null } });
      for (let k = 0; k < 16; k += 1) cmd({ k: "addPane", pane: k });
      clock.tick(16);
      out.length = 0;
      const start = performance.now();
      for (let f = 1; f <= 600; f += 1) {
        cmd({ k: "setViewport", timeStart: T0 + f * MIN, timeEnd: T0 + (f + 100) * MIN });
        clock.tick(16);
      }
      if (r >= 0) perFrame.push((performance.now() - start) / 600); // run -1 is the warm-up
      const kinds = out.filter((m) => m.t === "viewport" || m.t === "layout").map((m) => m.t);
      expect([kinds.length, new Set(kinds)]).toEqual([600, new Set(["viewport"])]);
      cmd({ k: "release" });
    }
    const median = percentile(perFrame, 50) ?? Number.NaN;
    expect(median, why(median, 0.5)).toBeLessThanOrEqual(budget(0.5));
  });
});
