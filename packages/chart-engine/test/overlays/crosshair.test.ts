// E11-S07 crosshair model: bar-centre snap, magnet off / weak / strong with the 2 px release
// hysteresis, the edge-triggered event (BQ-10) and the pure key stepper.
import { describe, expect, it } from "vitest";
import {
  applyStep,
  createCrosshair,
  createStepResult,
  hideCrosshair,
  resolvePointer,
  snapBarX,
  STEP,
  stepCursor,
  takeBarEdge,
} from "../../src/overlays/crosshair.js";
import { indexToScreen, priceToScreen } from "../../src/viewport/index.js";
import { source, viewport } from "./fixture.js";

// Bar 3 (x in [30, 40) at 10 px): O 203, H 303, L 103, C 253 → y 397, 297, 497, 347.
const X3 = 35;
const HIGH_Y = 600 - 303;

describe("crosshair: bar-centre snap", () => {
  it("test_resolvePointer_fractionalX_landsOnBarCentre", () => {
    const vp = viewport(50, 10, 0.25);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, null, 33.3, 120, "off");
    expect(s.bar).toBe(3);
    expect(s.x).toBe(indexToScreen(vp, 3));
    expect(snapBarX(vp, 33.3)).toBe(s.x);
    expect(s.driver).toBe("pointer");
    expect(s.visible).toBe(true);
  });

  it("test_resolvePointer_magnetOff_nearestTickAndFreeY", () => {
    const vp = viewport(50);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, source(50), X3, 120.4, "off");
    expect(s.tick).toBe(480); // 600 - 120.4 = 479.6 → 480
    expect(s.y).toBe(120.4);
    expect(s.snap).toBeNull();
  });
});

describe("crosshair: magnet", () => {
  it("test_strongMagnet_12pxFromHigh_snapsToHigh", () => {
    const vp = viewport(50);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, source(50), X3, HIGH_Y - 12, "strong");
    expect(s.snap).toBe("high");
    expect(s.tick).toBe(303);
    expect(s.y).toBe(priceToScreen(vp, 0, 303));
  });

  it("test_strongMagnet_farFromEveryField_stillSnapsToNearest", () => {
    const vp = viewport(50);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, source(50), X3, 10, "strong");
    expect(s.snap).toBe("high");
    resolvePointer(s, vp, 0, source(50), X3, 590, "strong");
    expect(s.snap).toBe("low");
  });

  it("test_weakMagnet_enterAt12_notAt13", () => {
    const vp = viewport(50);
    const bars = source(50);
    const a = createCrosshair();
    resolvePointer(a, vp, 0, bars, X3, HIGH_Y - 12, "weak");
    expect(a.snap).toBe("high");
    const b = createCrosshair();
    resolvePointer(b, vp, 0, bars, X3, HIGH_Y - 13, "weak");
    expect(b.snap).toBeNull();
    expect(b.tick).toBe(316);
  });

  it("test_weakMagnet_heldSnap_holdsAt13_releasesAt14", () => {
    const vp = viewport(50);
    const bars = source(50);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 12, "weak");
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 13, "weak");
    expect(s.snap).toBe("high");
    expect(s.y).toBe(HIGH_Y);
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 14, "weak");
    expect(s.snap).toBeNull();
    expect(s.y).toBe(HIGH_Y - 14);
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 13, "weak"); // re-entry needs 12 px again
    expect(s.snap).toBeNull();
  });

  it("test_weakMagnet_holdDoesNotCrossBarsOrHiding", () => {
    const vp = viewport(50);
    const bars = source(50);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 12, "weak");
    resolvePointer(s, vp, 0, bars, X3 + 10, HIGH_Y - 13 - 1, "weak"); // bar 4: H 304, 14 px...
    expect(s.bar).toBe(4);
    expect(s.snap).toBeNull();
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 12, "weak");
    hideCrosshair(s);
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 13, "weak");
    expect(s.snap).toBeNull();
  });

  it("test_weakMagnet_nearerFieldInRadius_winsOverHeld", () => {
    const vp = viewport(50);
    const bars = source(50);
    bars.close[3] = 300; // C 3 ticks under H
    const s = createCrosshair();
    resolvePointer(s, vp, 0, bars, X3, HIGH_Y - 1, "weak");
    expect(s.snap).toBe("high");
    resolvePointer(s, vp, 0, bars, X3, 600 - 300, "weak");
    expect(s.snap).toBe("close");
  });

  it("test_magnet_outsideData_isFree", () => {
    const vp = viewport(5);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, source(5), 95, 300, "strong");
    expect(s.bar).toBe(9);
    expect(s.snap).toBeNull();
    expect(s.tick).toBe(300);
  });
});

describe("crosshair: edge-triggered event (BQ-10, AC5)", () => {
  it("test_takeBarEdge_200pxSweepInOne240pxBar_firesOnce", () => {
    const vp = viewport(20, 240, 0, 4800);
    const bars = source(20);
    const s = createCrosshair();
    let edges = 0;
    const ticks = new Set<number>();
    for (let x = 250; x <= 450; x += 1) {
      resolvePointer(s, vp, 0, bars, x, 50 + x, "off");
      if (takeBarEdge(s)) edges += 1;
      ticks.add(s.tick);
    }
    expect(edges).toBe(1);
    expect(s.bar).toBe(1);
    expect(ticks.size).toBeGreaterThan(100); // the price moved every frame without an event
    resolvePointer(s, vp, 0, bars, 500, 50, "off");
    expect(takeBarEdge(s)).toBe(true);
  });

  it("test_takeBarEdge_hiddenOrSameBarOnReentry_noEvent", () => {
    const vp = viewport(20);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, null, X3, 10, "off");
    expect(takeBarEdge(s)).toBe(true);
    hideCrosshair(s);
    expect(takeBarEdge(s)).toBe(false);
    expect(s.visible).toBe(false);
    expect(s.driver).toBe("none");
    resolvePointer(s, vp, 0, null, X3, 20, "off");
    expect(takeBarEdge(s)).toBe(false);
  });
});

describe("crosshair: key stepping", () => {
  // 100 bars, 10 px, left 50.5 over 1200 px: fully visible bars 51..169 → clamped by data at 99.
  const vp = viewport(100, 10, 50.5);
  const r = createStepResult();

  it("test_stepCursor_unplaced_landsOnLastVisibleBar", () => {
    stepCursor(vp, 100, -1, Number.NaN, STEP.barNext, 1, r);
    expect(r.bar).toBe(99);
    expect(r.edge).toBe(1);
    const narrow = viewport(100, 10, 10.5, 300); // fully visible 11..39
    stepCursor(narrow, 100, -1, Number.NaN, STEP.barPrev, 1, r);
    expect(r.bar).toBe(39);
    expect(r.follow).toBe(0);
  });

  it("test_stepCursor_barSteps_byOneAndTen", () => {
    expect(stepCursor(vp, 100, 60, 5, STEP.barNext, 1, r).bar).toBe(61);
    expect(stepCursor(vp, 100, 60, 5, STEP.barPrev, 1, r).bar).toBe(59);
    expect(stepCursor(vp, 100, 60, 5, STEP.pageNext, 1, r).bar).toBe(70);
    expect(stepCursor(vp, 100, 60, 5, STEP.pagePrev, 1, r).bar).toBe(50);
    expect(r.tick).toBe(5);
    expect(r.clamped).toBe(false);
  });

  it("test_stepCursor_atLoadedEdges_clampsAndFlags", () => {
    stepCursor(vp, 100, 0, 5, STEP.barPrev, 1, r);
    expect([r.bar, r.edge, r.clamped]).toEqual([0, -1, true]);
    stepCursor(vp, 100, 95, 5, STEP.pageNext, 1, r);
    expect([r.bar, r.edge, r.clamped]).toEqual([99, 1, false]);
    stepCursor(vp, 100, 99, 5, STEP.barNext, 1, r);
    expect([r.bar, r.edge, r.clamped]).toEqual([99, 1, true]);
    stepCursor(vp, 100, 3, 5, STEP.pagePrev, 1, r);
    expect([r.bar, r.edge, r.clamped]).toEqual([0, -1, false]);
  });

  it("test_stepCursor_firstLast_andViewFollow", () => {
    stepCursor(vp, 100, 60, 5, STEP.first, 1, r);
    expect([r.bar, r.follow]).toEqual([0, -51]);
    stepCursor(vp, 100, 60, 5, STEP.last, 1, r);
    expect([r.bar, r.follow]).toEqual([99, 0]);
    const narrow = viewport(100, 10, 10.5, 300); // fully visible 11..39
    expect(stepCursor(narrow, 100, 39, 5, STEP.barNext, 1, r).follow).toBe(1);
    expect(stepCursor(narrow, 100, 11, 5, STEP.barPrev, 1, r).follow).toBe(-1);
    expect(stepCursor(narrow, 100, 20, 5, STEP.barNext, 1, r).follow).toBe(0);
  });

  it("test_stepCursor_priceLevels_andUnseededTick", () => {
    expect(stepCursor(vp, 100, 60, 5, STEP.levelUp, 4, r).tick).toBe(9);
    expect(stepCursor(vp, 100, 60, 5, STEP.levelDown, 4, r).tick).toBe(1);
    expect(r.bar).toBe(60);
    expect(stepCursor(vp, 100, 60, Number.NaN, STEP.levelUp, 1, r).tick).toBeNaN();
  });

  it("test_stepCursor_noData_noCursor", () => {
    stepCursor(vp, 0, 3, 5, STEP.barNext, 1, r);
    expect([r.bar, r.edge, r.follow]).toEqual([-1, 0, 0]);
    expect(r.tick).toBeNaN();
  });

  it("test_applyStep_placesKeyCursor", () => {
    const s = createCrosshair();
    applyStep(s, vp, 0, stepCursor(vp, 100, 60, 250, STEP.barNext, 1, r));
    expect(s).toMatchObject({ driver: "key", visible: true, bar: 61, tick: 250, snap: null });
    expect(s.x).toBe(indexToScreen(vp, 61));
    expect(s.y).toBe(350);
    applyStep(s, vp, 0, stepCursor(vp, 100, 60, Number.NaN, STEP.barNext, 1, r));
    expect(s.y).toBeNaN();
    applyStep(s, vp, 0, stepCursor(vp, 0, 60, 1, STEP.barNext, 1, r));
    expect(s.visible).toBe(false);
  });
});
