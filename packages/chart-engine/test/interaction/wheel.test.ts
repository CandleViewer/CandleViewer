// E11-S04 PR 1: cursor-anchored wheel zoom, delta-mode normalisation and the layout regions.
import { describe, expect, it } from "vitest";
import { Gestures } from "../../src/interaction/gestures.js";
import {
  DELTA_LINE_PX,
  MOD,
  plotWidthOf,
  REGION,
  regionAt,
  wheelFactor,
  wheelPx,
} from "../../src/interaction/wheel.js";
import { ChartViewport, timeToScreen } from "../../src/viewport/index.js";
import { INPUT } from "../../src/worker/protocol.js";
import { AT_14, MIN, minuteMap, rows } from "./fixtures.js";

const SIZE = { width: 1280, height: 744 }; // a 1216 × 720 plot

function chart(): { vp: ChartViewport; g: Gestures; moves: boolean[] } {
  const vp = new ChartViewport(minuteMap());
  vp.setSize(plotWidthOf(SIZE.width), 720, 1);
  vp.setTimeRange(AT_14 - 90 * MIN, AT_14 + 60 * MIN);
  const moves: boolean[] = [];
  const g = new Gestures(vp, SIZE, {
    moved: (c) => moves.push(c),
    hover: () => undefined,
    animate: () => undefined,
  });
  return { vp, g, moves };
}

describe("Scenario: Zoom is anchored to the cursor", () => {
  it.each([
    ["a plain wheel", 0],
    ["a Ctrl+wheel (a trackpad pinch, BQ-100)", MOD.ctrl],
  ])("the 14:00 bar stays within 0.5 px at every one of three notches: %s", (_, mods) => {
    const { vp, g } = chart();
    const x = timeToScreen(vp, AT_14);
    expect(x).toBeGreaterThan(600); // off-centre, so a centre zoom would move it
    const spacing = vp.barSpacing;
    for (let notch = 1; notch <= 3; notch += 1) {
      g.apply(false, rows([INPUT.wheel, x, 300, -100, mods, 16]));
      expect(Math.abs(timeToScreen(vp, AT_14) - x)).toBeLessThanOrEqual(0.5);
      expect(vp.barSpacing).toBeCloseTo(spacing * Math.exp(0.2 * notch), 9); // zoomed in
    }
  });

  it("anchors at the true plot x: an x in the price gutter zooms nothing (RULED (5))", () => {
    const { vp, g, moves } = chart();
    const before = [vp.leftIndex, vp.barSpacing];
    g.apply(false, rows([INPUT.wheel, 1250, 300, -100, 0, 0]));
    expect([vp.leftIndex, vp.barSpacing]).toEqual(before);
    expect(moves).toEqual([]);
  });
});

describe("wheel normalisation (the ticket's unit list)", () => {
  it("deltaMode 0 / 1 / 2 is ×1 / ×16 / ×the plot height", () => {
    expect([wheelPx(3, 0, 720), wheelPx(3, 1, 720), wheelPx(-1, 2, 720)]).toEqual([
      3,
      3 * DELTA_LINE_PX,
      -720,
    ]);
    expect(wheelFactor(0)).toBe(1);
    expect(wheelFactor(100)).toBeLessThan(1); // a wheel down zooms out (BQ-70)
  });

  it("classifies the plot, the time axis and the price axis from the layout's gutters", () => {
    const [w, h] = [SIZE.width, SIZE.height];
    expect(regionAt(0, 0, w, h)).toBe(REGION.plot);
    expect(regionAt(1215, 719, w, h)).toBe(REGION.plot);
    expect(regionAt(1215, 720, w, h)).toBe(REGION.time);
    expect(regionAt(1216, 10, w, h)).toBe(REGION.price);
    expect(regionAt(1270, 740, w, h)).toBe(REGION.price); // the corner
    expect(plotWidthOf(10)).toBe(0);
  });
});
