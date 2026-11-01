// E11-S07 BQ-7 (pending ruling; supersedes C-21) in the render runtime: the plot's keys step the
// keyboard data cursor (←/→ one bar, Shift and PgUp/PgDn ten, ↑/↓ one tick, Home/End the loaded
// ends), the view follows at the edge, only key moves post `a11y` (BQ-3) with "first bar" /
// "last bar" once per arrival, the pointer takes the lines back when it moves and hands them back
// when it leaves, and while the root has focus the cursor bar is the D10 column.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MOD } from "../../src/interaction/wheel.js";
import { CrosshairNode } from "../../src/overlays/crosshair-node.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import {
  BACKGROUND_TOKEN,
  INPUT,
  KEY,
  type FromWorker,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { columnSource } from "../../src/viewport/index.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { MIN_US, source, T0, timeMap } from "../overlays/fixture.js";

const BARS = source(50);
const THEME = {
  [BACKGROUND_TOKEN]: "#000000",
  "color.crosshair": "#ff0000",
  "color.focus.ring": "#00ff00",
};
const RING = "rgba(0, 255, 0, 1)";

type Of<T extends FromWorker["t"]> = Extract<FromWorker, { t: T }>;
let out: FromWorker[];
let rt: RenderRuntime;
const frame = (n = 1): void => void vi.advanceTimersByTime(16 * n);
const of = <T extends FromWorker["t"]>(t: T): Of<T>[] =>
  out.filter((m): m is Of<T> => m.t === t && m.id === 1);
const lastCross = (): Of<"crosshair"> | undefined => of("crosshair").at(-1);

function make(): FakeCtx2D {
  const ctx = new FakeCtx2D();
  rt.handle({
    t: "init",
    id: 1,
    canvas: { width: 464, height: 300, getContext: () => ctx },
    dpr: 1,
    theme: THEME,
    config: { bench: false, syncGroup: null },
  } satisfies ToWorker);
  rt.handle({
    t: "data",
    id: 1,
    store: "bars",
    op: "replace",
    layout: { count: 0, columns: [], params: [64_000, 1] },
    buffer: new ArrayBuffer(0),
  });
  // Bars 10 to 30 over the plot (~20 px each); 30 is the last fully visible bar.
  const cmd = { k: "setViewport", timeStart: T0 + 10 * MIN_US, timeEnd: T0 + 30 * MIN_US } as const;
  rt.handle({ t: "command", id: 1, cmd });
  frame(2);
  return ctx;
}

/** One key row on the plot, then a frame. */
function press(code: number, mods = 0): void {
  rt.handle({
    t: "input",
    id: 1,
    kind: "key",
    events: new Float32Array([INPUT.key, code, 0, 0, mods, 0]),
  });
  frame();
}
const move = (x: number, y: number): void =>
  rt.handle({
    t: "input",
    id: 1,
    kind: "pointer",
    events: new Float32Array([INPUT.move, x, y, 0, 0, 0]),
  });
const focus = (focused: boolean): void =>
  rt.handle({ t: "command", id: 1, cmd: { k: "setFocus", focused } });
const strokes = (ctx: FakeCtx2D, from: number, style: string): number =>
  ctx.paths.slice(from).filter((p) => p.op === "stroke" && p.style === style).length;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: timeMap(50),
    priceSources: [columnSource(() => BARS)],
    readoutSources: [BARS],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("BQ-7: key stepping", () => {
  it("test_firstPress_placesTheCursorOnTheLastVisibleBar_atItsClose", () => {
    make();
    press(KEY.right);
    expect(lastCross()).toMatchObject({ driver: "key", visible: true, bar: 30, price: 280 });
    expect(of("a11y")).toEqual([
      {
        t: "a11y",
        id: 1,
        cursorSummary: "14:30, close 64,280, delta +25",
        short: "14:30, 64,280",
        origin: "key",
      },
    ]);
  });

  it("test_steps_barShiftPageAndLevel_moveByTheirAmounts", () => {
    make();
    press(KEY.left); // placed on 30
    const bars: number[] = [];
    const step = (code: number, mods = 0): void => {
      press(code, mods);
      bars.push(lastCross()?.bar ?? -1);
    };
    step(KEY.left);
    step(KEY.left, MOD.shift);
    step(KEY.pageUp);
    step(KEY.pageDown);
    step(KEY.right, MOD.shift);
    expect(bars).toEqual([29, 19, 9, 19, 29]);
    press(KEY.up);
    expect(lastCross()?.price).toBe(250 + 30 + 1); // one tick up from the seeded close
    press(KEY.down);
    press(KEY.down);
    expect(lastCross()?.price).toBe(250 + 30 - 1);
    expect(lastCross()?.bar).toBe(29); // a level step keeps the bar
  });

  it("test_homeEnd_jumpToTheLoadedEnds_theViewFollows_andTheEdgeIsSaidOnce", () => {
    make();
    press(KEY.home);
    expect(lastCross()).toMatchObject({ bar: 0, driver: "key" });
    expect(lastCross()?.x).toBeGreaterThan(0); // the view followed: bar 0 is on screen
    expect(of("a11y").at(-1)?.cursorSummary).toMatch(/, first bar$/);
    const said = of("a11y").length;
    const views = of("viewport").length;
    press(KEY.left); // at the first bar: no move, nothing said, the view stays
    press(KEY.left, MOD.shift);
    expect([of("a11y").length, of("viewport").length]).toEqual([said, views]);
    press(KEY.end);
    expect(lastCross()?.bar).toBe(49);
    expect(of("viewport").length).toBe(views + 1); // the view followed to the last bar
    expect(of("a11y").at(-1)?.short).toMatch(/, last bar$/);
    press(KEY.right);
    expect(of("a11y")).toHaveLength(said + 1);
    press(KEY.up); // a level step on the last bar is said, without the edge again
    expect(of("a11y").at(-1)?.cursorSummary).not.toMatch(/bar$/);
    press(KEY.left);
    expect(of("a11y").at(-1)?.cursorSummary).not.toMatch(/bar$/); // off the edge: plain
  });

  it("test_stepPastTheVisibleEdge_scrollsOneBar_andKeepsTheCursorVisible", () => {
    make();
    press(KEY.right); // 30, the last visible bar
    const x = lastCross()?.x ?? 0;
    const views = of("viewport").length;
    press(KEY.right);
    expect(lastCross()?.bar).toBe(31);
    expect(of("viewport").length).toBe(views + 1); // the view followed
    expect(lastCross()?.x).toBeCloseTo(x, 6); // by exactly one bar
  });

  it("test_ctrlHome_isStillTheViewReset_notACursorStep", () => {
    make();
    press(KEY.home, MOD.ctrl);
    expect(of("crosshair")).toEqual([]);
    expect(of("a11y")).toEqual([]);
  });
});

describe("BQ-3: only keyboard moves are announced", () => {
  it("test_pointerHover_neverPostsA11y_andTakesTheLinesBack_untilItLeaves", () => {
    make();
    move(100, 80);
    frame();
    move(140, 90);
    frame();
    expect(of("a11y")).toEqual([]);
    press(KEY.right); // the selected cursor starts on its own, not at the pointer
    expect(lastCross()).toMatchObject({ driver: "key", bar: 30 });
    expect(of("a11y")).toHaveLength(1);
    move(141, 90); // a real move: the pointer drives again, silently
    frame();
    expect(lastCross()?.driver).toBe("pointer");
    const leave = new Float32Array([INPUT.leave, 0, 0, 0, 0, 0]);
    rt.handle({ t: "input", id: 1, kind: "pointer", events: leave });
    move(Number.NaN, Number.NaN);
    frame();
    // D02 §7.3: a keyboard-placed cursor stays when the pointer leaves; it is not re-announced.
    expect(lastCross()).toMatchObject({ driver: "key", bar: 30, visible: true });
    expect(of("a11y")).toHaveLength(1);
  });

  it("test_remoteSync_neverAnnounces_evenWithAKeyCursorPlaced", () => {
    make();
    press(KEY.right);
    const n = of("a11y").length;
    rt.handle({
      t: "sync",
      groupId: "g",
      timeRange: [T0 + 10 * MIN_US, T0 + 30 * MIN_US],
      crosshair: T0 + 12 * MIN_US,
    });
    frame(2);
    expect(of("a11y")).toHaveLength(n);
  });

  it("test_heldKey_30Presses_oneA11yPerMove_theHostCoalesces", () => {
    make();
    press(KEY.home);
    for (let i = 0; i < 30; i += 1) {
      rt.handle({
        t: "input",
        id: 1,
        kind: "key",
        events: new Float32Array([INPUT.key, KEY.right, 0, 0, 0, 0]),
      });
      vi.advanceTimersByTime(100);
    }
    const said = of("a11y").slice(1);
    expect(said).toHaveLength(30); // one per move, never per frame (BQ-13 coalesces on the host)
    expect(said.at(-1)?.cursorSummary).toMatch(/^14:30, /);
  });
});

describe("E06-D03 D10: the focus column", () => {
  it("test_focusedRoot_withAKeyCursor_drawsTheColumn_blurRemovesIt", () => {
    const ctx = make();
    press(KEY.right);
    let from = ctx.paths.length;
    expect(strokes(ctx, from, RING)).toBe(0);
    focus(true);
    frame();
    expect(strokes(ctx, from, RING)).toBe(1);
    from = ctx.paths.length;
    move(100, 80); // the pointer's crosshair moves; the column stays on the selected bar
    frame();
    expect(strokes(ctx, from, RING)).toBe(1);
    from = ctx.paths.length;
    focus(false);
    frame();
    expect(strokes(ctx, from, RING)).toBe(0);
  });

  it("test_focus_withNoKeyCursor_requestsNoFrame_theIdlePathStaysO1", () => {
    make();
    frame(4);
    const before = vi.getTimerCount();
    focus(true);
    expect(vi.getTimerCount()).toBe(before); // nothing to draw: no frame requested
    focus(true); // unchanged: a no-op
    focus(false);
    expect(vi.getTimerCount()).toBe(before);
  });

  it("test_setFocus_malformed_isRejectedAtTheBoundary", () => {
    make();
    out = [];
    rt.handle({ t: "command", id: 1, cmd: { k: "setFocus", focused: "yes" } });
    expect(out.filter((m) => m.t === "error")).toHaveLength(1);
  });
});

describe("BQ-7: the pointer leaving hands the lines back to a live key cursor", () => {
  it("test_pointerLeave_withAKeyCursorPlaced_linesReturnToTheKeyCursor_silently", () => {
    make();
    press(KEY.left); // the key cursor on 30
    move(100, 80); // the pointer takes the lines
    frame();
    expect(lastCross()?.driver).toBe("pointer");
    const said = of("a11y").length;
    const leave = new Float32Array([INPUT.leave, 100, 80, 0, 0, 0]);
    rt.handle({ t: "input", id: 1, kind: "pointer", events: leave });
    frame();
    expect(lastCross()).toMatchObject({ driver: "key", bar: 30, visible: true });
    expect(of("a11y")).toHaveLength(said); // handing back is not a key move
  });
});

describe("BQ-7: Esc and a data replace clear the key cursor (back to the idle path)", () => {
  const clear = (): void => rt.handle({ t: "command", id: 1, cmd: { k: "clearCursor" } });
  const replace = (): void =>
    rt.handle({
      t: "data",
      id: 1,
      store: "bars",
      op: "replace",
      layout: { count: 0, columns: [], params: [64_000, 1] },
      buffer: new ArrayBuffer(0),
    });
  const view = (): void =>
    rt.handle({
      t: "command",
      id: 1,
      cmd: { k: "setViewport", timeStart: T0 + 5 * MIN_US, timeEnd: T0 + 25 * MIN_US },
    });

  it.each([
    ["Esc (clearCursor)", clear],
    ["a bars replace", replace],
  ])("%s: the lines and column hide, nothing is said, later frames skip the crosshair", (_, go) => {
    const ctx = make();
    press(KEY.right);
    focus(true);
    frame();
    const said = of("a11y").length;
    go();
    frame();
    expect(lastCross()).toMatchObject({ visible: false });
    // Silent (the spec has no copy for it): one `cleared` notice, no summary to speak.
    expect(of("a11y").slice(said)).toEqual([
      { t: "a11y", id: 1, cursorSummary: "", origin: "key", cleared: true },
    ]);
    const from = ctx.paths.length;
    const write = vi.spyOn(CrosshairNode.prototype, "write");
    view(); // a viewport frame on an idle chart
    frame(2);
    expect(write).not.toHaveBeenCalled(); // O(1): the crosshair stage is skipped
    expect(strokes(ctx, from, RING)).toBe(0); // no column
    write.mockRestore();
    press(KEY.right); // the next key starts afresh on the last visible bar
    expect(lastCross()).toMatchObject({ driver: "key", visible: true });
  });

  it("test_clear_withNoKeyCursor_isANoOp_requestingNoFrame", () => {
    make();
    frame(4);
    const before = vi.getTimerCount();
    clear();
    expect(vi.getTimerCount()).toBe(before);
  });
});

describe("the data case: element counts (a1e78f9b's dangling-else regression)", () => {
  it.each(["footprint", "heatmap", "profile", "bars"] as const)(
    "a %s replace sets the count to n; an append adds n; a patch leaves it",
    (store) => {
      make();
      const batch = (op: "replace" | "append" | "patch", n: number): void =>
        rt.handle({
          t: "data",
          id: 1,
          store,
          op,
          layout: { count: n, columns: [{ offset: 0, bytes: 4 }], params: [64_000, 1] },
          buffer: new ArrayBuffer(4 * n),
        });
      batch("replace", 5);
      expect(rt.elementCounts(1)?.[store]).toBe(5);
      batch("append", 3);
      expect(rt.elementCounts(1)?.[store]).toBe(8);
      batch("patch", 2);
      expect(rt.elementCounts(1)?.[store]).toBe(8);
      batch("replace", 4);
      expect(rt.elementCounts(1)?.[store]).toBe(4);
    },
  );

  it("test_nonBarsReplace_leavesAPlacedKeyCursor_aBarsReplaceClearsIt", () => {
    make();
    press(KEY.right);
    const replace = (store: "footprint" | "bars"): void =>
      rt.handle({
        t: "data",
        id: 1,
        store,
        op: "replace",
        layout: { count: 0, columns: [], params: [64_000, 1] },
        buffer: new ArrayBuffer(0),
      });
    replace("footprint");
    frame();
    expect(lastCross()).toMatchObject({ driver: "key", visible: true });
    replace("bars");
    frame();
    expect(of("a11y").at(-1)).toMatchObject({ cleared: true });
  });
});
