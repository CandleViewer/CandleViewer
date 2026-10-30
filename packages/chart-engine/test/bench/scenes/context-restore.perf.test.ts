// Wall-clock half of the `context-restore` scene (E11-S02 PR3), run ONLY by `vitest --project perf`
// (engine-bench, no coverage): the CPU side of the R1 restore (30 §5.3 exit criterion 8).
import { describe, expect, it } from "vitest";
import { ContextRestoreBench } from "../../../bench/scenes/context-restore.js";
import { RESTORE_BUDGET_MS } from "../../../src/gl/context-loss.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("perf budgets: context restore", () => {
  it("rebuilds 100 000 bars and 3 panes and draws within the 2 s R1 budget", () => {
    const clock = { now: () => performance.now(), setTimer: () => undefined };
    const bench = new ContextRestoreBench(new FakeGl(), clock);
    bench.scene.step(); // first compiles and uploads
    expect(bench.cycle()).toBeLessThanOrEqual(RESTORE_BUDGET_MS);
  });
});
