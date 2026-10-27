import { describe, expect, it } from "vitest";
import {
  REPEAT_LIMIT,
  REPEAT_WINDOW_MS,
  createCrashGuard,
} from "../../../src/features/system-states/crashGuard";

/** Records one crash of `id` at each time; returns each result. */
function run(times: number[], id = "p"): boolean[] {
  let t = 0;
  const guard = createCrashGuard(() => t);
  return times.map((at) => ((t = at), guard.record(id)));
}

describe("createCrashGuard (E10-D03 §9.4: 3 crashes in 2 min)", () => {
  it("uses the spec's window, not the ticket's one minute", () => {
    expect([REPEAT_LIMIT, REPEAT_WINDOW_MS]).toEqual([3, 120_000]);
  });

  it("trips on a third crash exactly 2:00 after the first (inclusive)", () => {
    expect(run([0, 60_000, 120_000])).toEqual([false, false, true]);
  });

  it("does not trip 1 ms past the window, then slides", () => {
    expect(run([0, 2_000, 120_001, 122_000])).toEqual([false, false, false, true]);
  });

  it("counts each boundary id on its own ring", () => {
    const guard = createCrashGuard(() => 0);
    guard.record("a");
    guard.record("a");
    expect([guard.record("b"), guard.record("a")]).toEqual([false, true]);
  });
});
