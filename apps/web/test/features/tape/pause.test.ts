// E22-S01 (#714) PR-B: the pause model (D02 §5 P1-P14, D04 §9 FP-01..FP-12) as a reducer.
import { describe, expect, it } from "vitest";
import { LIVE, isPaused, step, type PauseLayers } from "../../../src/features/tape/model/pause";

const run = (s: PauseLayers, ...events: Parameters<typeof step>[1][]) => {
  let state = s;
  const steps = events.map((e) => {
    const out = step(state, e);
    state = out.next;
    return out;
  });
  return { state, steps };
};

describe("tape pause model", () => {
  it("P1 / P2: hover intent pauses softly; leaving with no row focused resumes with an insert", () => {
    const { state, steps } = run(LIVE, { type: "hover" }, { type: "leave" });
    expect(steps[0]).toMatchObject({ paused: "hover", insert: "none" });
    expect(steps[1]).toMatchObject({ insert: "live", resumed: "leave" });
    expect(isPaused(state)).toBe(false);
  });

  it("P3: a park resumes and disarms hover until the next pointermove", () => {
    const { state, steps } = run(LIVE, { type: "hover" }, { type: "park" }, { type: "hover" });
    expect(steps[1]).toMatchObject({ insert: "live", resumed: "park" });
    expect(isPaused(state)).toBe(false); // a still pointer never re-pauses (no oscillation)
    const rearmed = run(state, { type: "rearm" }, { type: "hover" });
    expect(rearmed.state.soft).toBe(true);
  });

  it("P4 / P5: a scroll pause has no park and ends by jump to live", () => {
    const { state, steps } = run(LIVE, { type: "scrollAway" }, { type: "park" }, { type: "leave" });
    expect(steps[0]?.paused).toBe("scroll");
    expect(state.scroll).toBe(true);
    const back = step(state, { type: "jumpLive", focused: false });
    expect(back).toMatchObject({ insert: "live", resumed: "jump" });
  });

  it("P6 / P7: P toggles a hard pause the park never touches", () => {
    const { state, steps } = run(LIVE, { type: "toggleHard", cause: "key" }, { type: "park" });
    expect(steps[0]?.paused).toBe("key");
    expect(state.hard).toBe(true);
    expect(step(state, { type: "toggleHard", cause: "button" })).toMatchObject({
      insert: "live",
      resumed: "button",
    });
  });

  it("P8: a row focus takes a soft or scroll pause over; leaving or parking then does nothing", () => {
    const { state } = run(
      LIVE,
      { type: "hover" },
      { type: "rowFocus" },
      { type: "leave" },
      { type: "park" },
    );
    expect(state).toMatchObject({ focus: true, soft: false });
    const scrolled = run(LIVE, { type: "scrollAway" }, { type: "rowFocus" });
    expect(scrolled.state).toMatchObject({ focus: true, scroll: false });
  });

  it("FP-03 / FP-04: P on a focused row is sticky; P again inserts anchored and the focus pause holds", () => {
    const { state, steps } = run(
      LIVE,
      { type: "rowFocus" },
      { type: "toggleHard", cause: "key" },
      { type: "toggleHard", cause: "key" },
    );
    expect(steps[1]?.insert).toBe("none");
    expect(steps[2]).toMatchObject({ insert: "anchored", resumed: "key" });
    expect(state).toMatchObject({ focus: true, hard: false });
  });

  it("FP-05 / P13: Esc resumes a focus pause, or in a hard pause only releases the selection", () => {
    expect(step(run(LIVE, { type: "rowFocus" }).state, { type: "escape" })).toMatchObject({
      insert: "live",
      resumed: "esc",
    });
    const hard = run(LIVE, { type: "toggleHard", cause: "key" }, { type: "rowFocus" }).state;
    expect(step(hard, { type: "escape" })).toMatchObject({ insert: "none", next: hard });
    expect(step(LIVE, { type: "escape" })).toMatchObject({ insert: "none", next: LIVE });
  });

  it("FP-07: blur resumes, unless the hard layer holds, which keeps the pause and inserts nothing", () => {
    expect(step(run(LIVE, { type: "rowFocus" }).state, { type: "blur" }).resumed).toBe("blur");
    const hard = run(LIVE, { type: "toggleHard", cause: "key" }, { type: "rowFocus" }).state;
    expect(step(hard, { type: "blur" })).toMatchObject({
      insert: "none",
      next: { hard: true, focus: false },
    });
  });

  it("K4: jump to live on a focused row holds the pause; a scroll pause under a hard one drops only scroll", () => {
    const focused = run(LIVE, { type: "rowFocus" }).state;
    expect(step(focused, { type: "jumpLive", focused: true }).next).toBe(focused);
    const both = run(LIVE, { type: "scrollAway" }, { type: "toggleHard", cause: "key" }).state;
    expect(step(both, { type: "jumpLive", focused: false })).toMatchObject({
      insert: "none",
      next: { hard: true, scroll: false },
    });
  });

  it("enters a pause from live once: a second layer emits no second paused", () => {
    const { steps } = run(
      LIVE,
      { type: "toggleHard", cause: "key" },
      { type: "rowFocus" },
      { type: "scrollAway" },
    );
    expect(steps.map((s) => s.paused)).toEqual(["key", undefined, undefined]);
  });
});
