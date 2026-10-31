// E11-S04 PR 1: the worker's gestures, routed by the layout's rects (BQ-100 to BQ-103), over a
// synthetic 1-minute map (BQ-111). The glide runs on a real FrameScheduler with the TestClock.
import { describe, expect, it } from "vitest";
import { Gestures } from "../../src/interaction/gestures.js";
import { MOMENTUM } from "../../src/interaction/momentum.js";
import { DEFAULT_RIGHT_OFFSET } from "../../src/interaction/navigator.js";
import { MOD, plotWidthOf } from "../../src/interaction/wheel.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import {
  ChartViewport,
  DEFAULT_BAR_SPACING,
  indexToScreen,
  screenToIndex,
  screenToPrice,
} from "../../src/viewport/index.js";
import { INPUT, KEY } from "../../src/worker/protocol.js";
import { TestClock } from "../scene/test-clock.js";
import { minuteMap, rows } from "./fixtures.js";

const SIZE = { width: 1064, height: 624 }; // a 1000 × 600 plot
const TIME_Y = 610; // in the time-axis gutter
const { down, move, up, cancel, wheel, dblclick, key } = INPUT;

function chart() {
  const vp = new ChartViewport(minuteMap(5000));
  vp.setSize(plotWidthOf(SIZE.width), 600, 1);
  vp.setPanePlot(0, 0, 600);
  vp.setPriceRange(0, 1_000, 1_100);
  vp.pan(-2000 * vp.barSpacing); // bar 2000 at the left edge: room both ways
  const clock = new TestClock();
  const scheduler = new FrameScheduler(new SceneGraph(), clock);
  let changes = 0;
  const g = new Gestures(vp, SIZE, {
    moved: (c) => void (changes += c ? 1 : 0),
    hover: () => undefined,
    animate: (m) => scheduler.animate(m),
  });
  const mouse = (...r: number[][]): void => g.apply(false, rows(...r));
  const touch = (...r: number[][]): void => g.apply(true, rows(...r));
  const frames = (n: number): void => {
    for (let i = 0; i < n; i += 1) clock.tick(16);
  };
  /** A 2 px/ms flick right across the plot, released while moving. */
  const flick = (): void => {
    mouse([down, 308, 300, 1, 0, 0]);
    for (let x = 324; x <= 500; x += 16) mouse([move, x, 300, 1, 0, 8]);
    mouse([up, 500, 300, 0, 0, 8]);
  };
  return { vp, g, scheduler, mouse, touch, frames, flick, changes: () => changes };
}

describe("drag and coast on the plot", () => {
  it("pans time on a drag and coasts after a flick, resting v₀τ further", () => {
    const { vp, g, scheduler, frames, flick } = chart();
    const start = vp.leftIndex;
    flick();
    const released = vp.leftIndex;
    expect((start - released) * vp.barSpacing).toBeCloseTo(192, 9); // content followed the pointer
    expect(g.momentum.active).toBe(true);
    const v0 = g.momentum.v;
    expect(v0).toBeGreaterThan(MOMENTUM.minPxPerMs);
    for (let i = 0; i < 200 && !scheduler.parked; i += 1) frames(1);
    expect((released - vp.leftIndex) * vp.barSpacing).toBeCloseTo(v0 * MOMENTUM.tauMs, 6);
  });

  it("a vertical plot drag is inert while autoscale is on and pans price once locked", () => {
    const { vp, mouse, changes } = chart();
    const at = vp.leftIndex;
    const drag = (): void =>
      mouse([down, 300, 100, 1, 0, 0], [move, 300, 400, 1, 0, 8], [up, 300, 400, 0, 0, 8]);
    drag();
    expect([vp.leftIndex, changes(), vp.panes[0]?.priceLow]).toEqual([at, 0, 1_000]);
    vp.setScale(0, { auto: false }); // E11-D01 D2: only a locked scale pans price
    drag();
    expect(vp.leftIndex).toBe(at);
    expect(vp.panes[0]?.priceLow).toBeCloseTo(1_050, 9); // 300 px of 600 is half the window
    expect(changes()).toBe(1);
  });
});

describe("Scenario: A new touch cancels momentum immediately", () => {
  it("the glide stops on that frame and the new drag begins from the current position", () => {
    const { vp, g, mouse, touch, frames, flick } = chart();
    flick();
    frames(3);
    expect(g.momentum.active).toBe(true);
    const at = vp.leftIndex;
    touch([down, 400, 300, 5, 0, 0]);
    frames(1);
    expect(vp.leftIndex).toBe(at); // no glide step ran on the frame after the down
    touch([move, 430, 300, 5, 0, 8]);
    expect((at - vp.leftIndex) * vp.barSpacing).toBeCloseTo(30, 9);
    expect(g.momentum.cancelled).toBe(1);
    mouse([down, 1, 1, 1, 0, 0]); // a pointer-down with nothing gliding cancels nothing
    expect(g.momentum.cancelled).toBe(1);
  });
});

describe("coast cancel and no-coast cases (BQ-103)", () => {
  it.each([
    ["a wheel", [wheel, 500, 300, 10, 0, 0]],
    ["a key", [key, KEY.zoomIn, 0, 0, 0, 0]],
    ["a double-click", [dblclick, 500, 300, 0, 0, 0]],
  ])("%s stops a glide where it is", (_, row) => {
    const { g, mouse, frames, flick } = chart();
    flick();
    frames(2);
    mouse(row as number[]);
    expect([g.momentum.active, g.momentum.cancelled]).toEqual([false, 1]);
  });

  it.each([KEY.spaceDown, KEY.spaceUp])("Space (%i) leaves a glide running (D06 D5)", (code) => {
    const { g, mouse, frames, flick } = chart();
    flick();
    frames(2);
    mouse([key, code, 0, 0, 0, 0]);
    expect([g.momentum.active, g.momentum.cancelled]).toEqual([true, 0]);
  });

  it("stop() (setViewport, sync, resize, context loss) is one entry point", () => {
    const { g, flick } = chart();
    flick();
    g.stop();
    expect(g.momentum.active).toBe(false);
  });

  it("a pointercancel ends the drag with no coast; a slow or rested release does not coast", () => {
    const { g, mouse } = chart();
    mouse([down, 300, 300, 1, 0, 0], [move, 400, 300, 1, 0, 8], [cancel, 400, 300, 0, 0, 0]);
    expect(g.momentum.active).toBe(false);
    mouse([down, 300, 300, 1, 0, 0], [move, 302, 300, 1, 0, 16], [up, 302, 300, 0, 0, 16]);
    expect(g.momentum.active).toBe(false); // 0.125 px/ms < 0.3
    mouse([down, 300, 300, 1, 0, 0], [move, 400, 300, 1, 0, 8], [up, 400, 300, 0, 0, 120]);
    expect(g.momentum.active).toBe(false); // rested 120 ms before the up
  });

  it("Scenario: Inertia respects reduced-motion settings — the release position is the rest", () => {
    const { vp, g, frames, flick } = chart();
    g.setMotion(true);
    flick();
    const at = vp.leftIndex;
    expect([g.momentum.active, g.momentum.registered]).toEqual([false, false]); // 0 glide frames
    frames(5);
    expect([g.momentum.active, vp.leftIndex]).toEqual([false, at]);
    g.setMotion(false);
    flick();
    expect(g.momentum.active).toBe(true); // full motion again: both ways (C-22)
  });

  it("a change to reduce mid-coast stops the glide where it is", () => {
    const { vp, g, scheduler, frames, flick } = chart();
    flick();
    frames(2);
    const at = vp.leftIndex;
    g.setMotion(true);
    for (let i = 0; i < 10 && !scheduler.parked; i += 1) frames(1);
    expect([g.momentum.active, g.momentum.cancelled, vp.leftIndex]).toEqual([false, 1, at]);
  });

  it("a second glide reuses the one registered integrator", () => {
    const { g, scheduler, frames, flick } = chart();
    flick();
    frames(1);
    flick();
    expect(g.momentum.registered).toBe(true);
    for (let i = 0; i < 200 && !scheduler.parked; i += 1) frames(1);
    expect(g.momentum.registered).toBe(false);
  });
});

describe("pinch (touch): time zoom about the midpoint, no coast", () => {
  it("the bar under the midpoint follows it while the spread scales barSpacing", () => {
    const { vp, g, touch } = chart();
    touch([down, 400, 300, 1, 0, 0], [down, 600, 300, 2, 0, 0]);
    const s = vp.barSpacing;
    const bar = screenToIndex(vp, 500) + 0.5; // the bar centre nearest the midpoint
    const offset = indexToScreen(vp, bar - 0.5) - 500;
    touch([move, 700, 300, 2, 0, 8]); // midpoint 500 -> 550, spread 200 -> 300
    expect(vp.barSpacing).toBeCloseTo(s * 1.5, 9);
    expect(indexToScreen(vp, bar - 0.5) - 550).toBeCloseTo(offset * 1.5, 6);
    g.velocity.v = 1;
    touch([down, 800, 300, 3, 0, 0]); // a third finger is ignored: no stop, no reset
    expect(g.velocity.v).toBe(1);
    touch([up, 700, 300, 2, 0, 8], [move, 450, 300, 1, 0, 8]);
    touch([up, 450, 300, 1, 0, 8]);
    expect(g.momentum.active).toBe(false); // a pinch never coasts
    touch([cancel, 1, 1, 9, 0, 0]); // an unknown id is ignored
  });
});

describe("active (E11-S08, BQ-134): hover does not pick while a gesture runs", () => {
  it("is true while a finger is down, through a pinch and during a glide", () => {
    const { g, touch, flick } = chart();
    expect(g.active).toBe(false);
    touch([down, 400, 300, 1, 0, 0]);
    expect(g.active).toBe(true); // a finger down
    touch([down, 600, 300, 2, 0, 0], [up, 600, 300, 2, 0, 8]);
    expect(g.active).toBe(true); // pinched, one finger left
    touch([up, 400, 300, 1, 0, 8]);
    expect(g.active).toBe(false); // a pinch never coasts
    flick();
    expect([g.momentum.active, g.active]).toEqual([true, true]); // a glide
    g.stop();
    expect(g.active).toBe(false);
  });
});

describe("axes (BQ-101): the time axis changes barSpacing at the plot's right edge", () => {
  const rightBar = (vp: ChartViewport): number => vp.leftIndex + vp.plotWidth / vp.barSpacing;

  it("a time-axis drag right widens the bars, anchored at the right edge, and never coasts", () => {
    const { vp, g, mouse } = chart();
    const right = rightBar(vp);
    mouse([down, 300, TIME_Y, 1, 0, 0], [move, 400, TIME_Y, 1, 0, 4], [up, 400, TIME_Y, 0, 0, 4]);
    expect(vp.barSpacing).toBeCloseTo(DEFAULT_BAR_SPACING * Math.exp(0.5), 9);
    expect(rightBar(vp)).toBeCloseTo(right, 9);
    expect(g.momentum.active).toBe(false);
  });

  it("a time-axis wheel zooms about the right edge and a double-click restores the spacing", () => {
    const { vp, mouse } = chart();
    const right = rightBar(vp);
    mouse([wheel, 100, TIME_Y, -100, 0, 0]);
    expect(vp.barSpacing).toBeCloseTo(DEFAULT_BAR_SPACING * Math.exp(0.2), 9);
    expect(rightBar(vp)).toBeCloseTo(right, 9);
    mouse([dblclick, 100, TIME_Y, 0, 0, 0]);
    expect(vp.barSpacing).toBeCloseTo(DEFAULT_BAR_SPACING, 12);
    expect(rightBar(vp)).toBeCloseTo(right, 9);
  });

  it("Scenario: Manual drag disengages autoscale and is reversible", () => {
    const { vp, mouse } = chart();
    const p = vp.panes[0];
    const before = [vp.leftIndex, vp.barSpacing];
    // A drag up the price axis zooms price in about where it started, and locks the scale.
    mouse([down, 1030, 150, 1, 0, 0], [move, 900, 50, 1, 0, 8], [up, 900, 50, 0, 0, 8]);
    expect(p?.autoScale).toBe(false);
    expect([vp.leftIndex, vp.barSpacing]).toEqual(before); // time is untouched
    expect(screenToPrice(vp, 0, 150)).toBeCloseTo(1_075, 9);
    expect((p?.priceHigh ?? 0) - (p?.priceLow ?? 0)).toBeCloseTo(100 * Math.exp(-0.5), 9);
    mouse([dblclick, 1030, 300, 0, 0, 0]); // the gutter's double-click restores auto-fit
    expect(p?.autoScale).toBe(true);
    mouse([wheel, 1030, 300, -100, 0, 0]); // a wheel over the gutter zooms price and locks
    expect(p?.autoScale).toBe(false);
    expect((p?.priceHigh ?? 0) - (p?.priceLow ?? 0)).toBeCloseTo(
      100 * Math.exp(-0.5) * Math.exp(-0.2),
      9,
    );
    mouse([dblclick, 500, 300, 0, 0, 0]); // the plot's reset view re-enables auto too
    expect(p?.autoScale).toBe(true);
  });

  it("a plot double-click is Ctrl+Home: the default spacing and the latest bar (BQ-107)", () => {
    const { vp, mouse } = chart();
    mouse([wheel, 500, 300, -300, 0, 0]);
    mouse([dblclick, 500, 300, 0, 0, 0]);
    expect(vp.barSpacing).toBe(DEFAULT_BAR_SPACING);
    expect(vp.rightOffset).toBeCloseTo(DEFAULT_RIGHT_OFFSET, 9);
  });

  it("a pan-class wheel (Shift, or a dominant deltaX) pans the plot by its delta", () => {
    const { vp, mouse } = chart();
    const at = vp.leftIndex;
    mouse([wheel, 500, 300, 60, MOD.shift | MOD.pan, 0]);
    expect((vp.leftIndex - at) * vp.barSpacing).toBeCloseTo(60, 9);
  });
});

describe("keys in the worker (BQ-108, BQ-109)", () => {
  it("+ zooms about the pointer's last plot x; a move over an axis keeps the last plot x", () => {
    const { vp, g, mouse } = chart();
    mouse([move, 250, 300, 0, 0, 8], [move, 1030, 300, 0, 0, 8], [move, 300, TIME_Y, 0, 0, 8]);
    expect(g.pointerX).toBe(250);
    const under = 250 / vp.barSpacing + vp.leftIndex;
    mouse([key, KEY.zoomIn, 0, 0, MOD.shift, 0]);
    expect(vp.barSpacing).toBeCloseTo(DEFAULT_BAR_SPACING * 1.25, 12);
    expect(250 / vp.barSpacing + vp.leftIndex).toBeCloseTo(under, 9);
  });

  it("Space held sets the pan-drag modifier and its release clears it", () => {
    const { vp, g, mouse, changes } = chart();
    mouse([key, KEY.spaceDown, 0, 0, 0, 0]);
    expect(g.panModifier).toBe(true);
    mouse([key, KEY.spaceUp, 0, 0, 0, 0]);
    expect([g.panModifier, vp.barSpacing, changes()]).toEqual([false, DEFAULT_BAR_SPACING, 0]);
  });
});
