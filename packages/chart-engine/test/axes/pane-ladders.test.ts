// E11-S09 (BQ-5, BQ-23) in the axis model: every further pane gets its own price ladder (its
// labels go out as `axes.panes`), the time ladder stays one, and the grid stays one ring for the
// whole stack: each pane's price lines in its own rows, time lines through every pane and a rule
// at each pane boundary. The gutter fits the widest ladder of the stack.
import { describe, expect, it } from "vitest";
import { AxisModel } from "../../src/axes/axis-model.js";
import { Gestures } from "../../src/interaction/gestures.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { minuteMap } from "../interaction/fixtures.js";

type Rect = [number, number, number, number];
const THEME = {}; // one object: a new theme identity rebuilds the axes

/** A two-pane stack, 300 + 200 px of plot under one 24 px time strip. */
function stack(gutter = 64) {
  const vp = new ChartViewport(minuteMap(), 1);
  vp.addPane();
  vp.setSize(1000, 524, 1);
  vp.setPanePlot(0, 0, 300);
  vp.setPanePlot(1, 300, 200);
  vp.scrollTo(100, 8);
  vp.setPriceInfo(0, 0, 0.5);
  vp.setPriceRange(0, 100_000, 102_000);
  const layout = {
    width: 1000 + gutter,
    height: 524,
    priceGutter: gutter,
    panes: [{ rect: [0, 0, 1000, 300] as Rect }, { rect: [0, 300, 1000, 200] as Rect }],
    timeAxis: [0, 500, 1000, 24] as Rect,
  };
  return { vp, layout };
}

/** Runs `update` the way the runtime does: once more after a gutter change. */
function settle(axes: AxisModel, s: ReturnType<typeof stack>): number {
  let r = axes.update(s.vp, s.layout, THEME);

  for (let i = 0; i < 3 && (r & 4) !== 0; i += 1) {
    s.layout.priceGutter = axes.gutterWidth;
    r = axes.update(s.vp, s.layout, THEME);
  }
  return r;
}

/** The grid's horizontal lines as CSS y (the ring is device px, y up). */
function horizontals(axes: AxisModel, height: number): number[] {
  const g = axes.grid;
  const ys: number[] = [];
  for (let i = 0; i < g.count; i += 1) {
    const [x0, y0, x1, y1] = g.data.slice(i * 9, i * 9 + 4);
    if (y0 === y1 && x0 !== x1) ys.push(height - (y0 as number));
  }
  return ys;
}

describe("Scenario: every pane has its own price ladder on the one time axis", () => {
  it("test_update_secondPaneWithATickSize_itsLadderLabelsAndLinesInItsRows", () => {
    const s = stack();
    s.vp.setPriceInfo(1, 0, 1);
    s.vp.setPriceRange(1, 2_000, 2_400);
    const axes = new AxisModel();
    axes.addPane(1);
    expect(settle(axes, s) & 2).toBe(2); // labels, the further ladder's included
    const [ladder] = axes.ladders;
    expect(ladder?.labels.length).toBeGreaterThan(2);
    expect(ladder?.labels.every((l) => /^2,[0-4]\d\d$/.test(l))).toBe(true);
    expect(axes.priceLabels.some((l) => l.startsWith("50,"))).toBe(true); // pane 0's own
    const ys = horizontals(axes, 524);
    expect(ys.some((y) => y > 300 && y < 500)).toBe(true); // pane 1's lines in its rows
    expect(ys.some((y) => Math.abs(y - 300) < 1)).toBe(true); // the boundary rule
    // Time lines run from the stack's top to its bottom: one list, every pane.
    const g = axes.grid;
    let through = 0;
    for (let i = 0; i < g.count; i += 1) {
      const [x0, y0, x1, y1] = g.data.slice(i * 9, i * 9 + 4);
      if (x0 === x1 && y0 === 524 - 500 && y1 === 524) through += 1;
    }
    expect(through).toBeGreaterThan(0);
    // A still frame rebuilds nothing; the further pane's own move does.
    expect(axes.update(s.vp, s.layout, THEME)).toBe(0);
    s.vp.setPriceRange(1, 2_000, 2_800);
    expect(axes.update(s.vp, s.layout, THEME)).not.toBe(0);
  });

  it("test_update_secondPaneWithoutATickSize_anEmptyLadderAndStillOneGrid", () => {
    const s = stack();
    const axes = new AxisModel();
    axes.addPane(1);
    settle(axes, s);
    expect(axes.ladders[0]?.labels).toEqual([]);
    expect(axes.timeLabels.length).toBeGreaterThan(0);
  });

  it("test_update_widerLabelsBelow_theGutterFitsTheWidestLadder", () => {
    const s = stack();
    const one = new AxisModel();
    settle(one, s);
    const narrow = s.layout.priceGutter;
    const t = stack();
    t.vp.setPriceInfo(1, 0, 1);
    t.vp.setPriceRange(1, 10_000_000, 90_000_000);
    const two = new AxisModel();
    two.addPane(1);
    settle(two, t);
    expect(t.layout.priceGutter).toBeGreaterThan(narrow);
  });

  it("test_removePane_byKey_theLadderGoesWithItsPaneAndTheOthersKeepTheirKeys", () => {
    const axes = new AxisModel();
    axes.addPane(3);
    axes.addPane(7);
    axes.ladders[1]?.labels.push("kept"); // pane 7's
    axes.removePane(3);
    expect(axes.ladders.map((l) => [l.key, l.labels])).toEqual([[7, ["kept"]]]);
    expect(axes.paneKeys).toEqual([0, 7]);
    axes.removePane(42); // unknown: nothing
    expect(axes.paneKeys).toEqual([0, 7]);
    axes.removePane(0); // the first pane: pane 7's ladder becomes the model's own
    expect(axes.ladders).toEqual([]);
    expect(axes.paneKeys).toEqual([7]);
    axes.addPane(8);
    expect(axes.ladders.map((l) => l.key)).toEqual([8]);
  });
});

describe("Gestures.paneAt (BQ-10)", () => {
  it("test_paneAt_rowsOfTheStack_theIndexOfThePaneHoldingY", () => {
    const s = stack();
    const sink = { moved: () => undefined, hover: () => undefined, animate: () => undefined };
    const g = new Gestures(s.vp, s.layout, sink);
    expect([0, 299.5, 300, 499, 510].map((y) => g.paneAt(y))).toEqual([0, 0, 1, 1, 1]);
    const bare = new Gestures(s.vp, { width: 100, height: 100 }, sink);
    expect(bare.paneAt(80)).toBe(0);
  });
});
