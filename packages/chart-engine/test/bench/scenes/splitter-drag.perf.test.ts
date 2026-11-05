// Wall-clock bound for the E11-S09 splitter drag (PR 1b review M1), run ONLY by `vitest --project
// perf` (engine-bench, no coverage): every drag step of 16 panes re-keys and rewrites the grid
// ring (`axis-model.ts`, a hairline per boundary) and posts one `layout`. Real runtime, fake GL.
import { describe, expect, it } from "vitest";
import { percentile } from "../../../bench/stats.mjs";
import { type FromWorker, INPUT } from "../../../src/worker/protocol.js";
import { createRenderRuntime } from "../../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../../gl/fake-gl.js";
import { minuteMap } from "../../interaction/fixtures.js";
import { TestClock } from "../../scene/test-clock.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

describe("perf budgets: a splitter drag across 16 panes", () => {
  it("one layout a step, <= 0.5 ms a frame (median of 5 runs of 600)", () => {
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
      const ptr = (...row: number[]): void =>
        rt.handle({ t: "input", id: 1, kind: "pointer", events: new Float32Array(row) });
      const canvas = { width: 1064, height: 1624, getContext: () => new FakeGl({ params: ROOMY }) };
      rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config: { syncGroup: null } });
      for (let k = 0; k < 16; k += 1) cmd({ k: "addPane", pane: k });
      clock.tick(16);
      const laid = out.filter((m): m is Extract<FromWorker, { t: "layout" }> => m.t === "layout");
      const y0 = laid.at(-1)?.panes[7]; // the boundary under pane 7
      const at = y0 === undefined ? Number.NaN : y0.top + y0.height;
      ptr(INPUT.down, 500, at, 1, 0, 0);
      out.length = 0;
      const start = performance.now();
      for (let f = 1; f <= 600; f += 1) {
        ptr(INPUT.move, 500, at + (f % 2 === 0 ? -20 : 20), 1, 0, 16); // both panes keep > 48 px
        clock.tick(16);
      }
      if (r >= 0) perFrame.push((performance.now() - start) / 600); // run -1 is the warm-up
      expect(out.filter((m) => m.t === "layout")).toHaveLength(600);
      cmd({ k: "release" });
    }
    const median = percentile(perFrame, 50) ?? Number.NaN;
    expect(median, why(median, 0.5)).toBeLessThanOrEqual(budget(0.5));
  });
});
