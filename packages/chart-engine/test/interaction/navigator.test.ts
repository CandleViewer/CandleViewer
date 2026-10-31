// E11-S04 PR 2: the keyboard equivalents, pure (BQ-106 to BQ-109), over a synthetic 1-minute map
// (BQ-111). Every move is a cut; the worker rows that drive these are in runtime-input.test.ts.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_RIGHT_OFFSET,
  isSpace,
  keyCode,
  navigate,
  resetView,
  toEnd,
  zoomAnchor,
} from "../../src/interaction/navigator.js";
import { MOD } from "../../src/interaction/wheel.js";
import {
  ChartViewport,
  DEFAULT_BAR_SPACING,
  EMPTY_TIME_MAP,
  indexToScreen,
} from "../../src/viewport/index.js";
import { KEY } from "../../src/worker/protocol.js";
import { minuteMap } from "./fixtures.js";

function view(n = 5000, width = 1000): ChartViewport {
  const vp = new ChartViewport(n === 0 ? EMPTY_TIME_MAP : minuteMap(n));
  vp.setSize(width, 600, 1);
  vp.scrollTo(2000); // room both ways
  return vp;
}

describe("Scenario: Every pointer gesture has a keyboard equivalent", () => {
  it("←, → and Shift+→ pan by one bar and by ten (C-21: no data cursor yet)", () => {
    const vp = view();
    expect(navigate(vp, KEY.left, 0, Number.NaN)).toBe(true);
    expect(vp.leftIndex).toBe(1999);
    navigate(vp, KEY.right, 0, Number.NaN);
    navigate(vp, KEY.right, MOD.shift, Number.NaN);
    expect(vp.leftIndex).toBe(2010);
    navigate(vp, KEY.left, MOD.shift, Number.NaN);
    expect([vp.leftIndex, vp.barSpacing]).toEqual([2000, DEFAULT_BAR_SPACING]);
  });

  it("Home puts bar 0 at the left edge; End the latest bar 12 bars in from the right", () => {
    const vp = view();
    navigate(vp, KEY.home, 0, Number.NaN);
    expect(vp.leftIndex).toBe(0);
    expect(indexToScreen(vp, 0)).toBe(DEFAULT_BAR_SPACING / 2);
    navigate(vp, KEY.end, 0, Number.NaN);
    expect(vp.rightOffset).toBeCloseTo(DEFAULT_RIGHT_OFFSET, 9);
    expect(navigate(vp, KEY.end, 0, Number.NaN)).toBe(false); // already there
  });

  it("End clamps the offset to visibleBars − 1 when fewer than 13 bars fit", () => {
    const vp = view(5000, 60); // 10 bars visible
    toEnd(vp);
    expect(vp.rightOffset).toBeCloseTo(vp.visibleBars - 1, 9); // the latest bar stays on screen
  });

  it("+ and − zoom by 1.1 (Shift: 1.25) about the pointer's plot x, which stays put", () => {
    const vp = view();
    const at = (x: number): number => x / vp.barSpacing + vp.leftIndex;
    const before = at(400);
    navigate(vp, KEY.zoomIn, 0, 400);
    expect(vp.barSpacing).toBeCloseTo(DEFAULT_BAR_SPACING * 1.1, 12);
    expect(at(400)).toBeCloseTo(before, 9);
    navigate(vp, KEY.zoomOut, MOD.shift, 400);
    expect(vp.barSpacing).toBeCloseTo((DEFAULT_BAR_SPACING * 1.1) / 1.25, 12);
    expect(at(400)).toBeCloseTo(before, 9);
  });

  it("with no pointer in the plot, +/- zoom about the latest bar, or the right edge", () => {
    const vp = view();
    toEnd(vp);
    const x = indexToScreen(vp, 4999);
    expect(zoomAnchor(vp, Number.NaN)).toBe(x);
    navigate(vp, KEY.zoomIn, 0, Number.NaN);
    expect(indexToScreen(vp, 4999)).toBeCloseTo(x, 9);
    expect(zoomAnchor(view(0), Number.NaN)).toBe(1000);
  });

  it("Ctrl+Home resets the spacing and shows the latest bar (autoscale is E11-S05's, G-5)", () => {
    const vp = view();
    navigate(vp, KEY.zoomIn, MOD.shift, 300);
    expect(navigate(vp, KEY.home, MOD.ctrl, Number.NaN)).toBe(true);
    expect(vp.barSpacing).toBe(DEFAULT_BAR_SPACING);
    expect(vp.rightOffset).toBeCloseTo(DEFAULT_RIGHT_OFFSET, 9);
    expect(resetView(vp)).toBe(false);
  });

  it("Ctrl or Meta with + or − is the browser's or the app's zoom: ignored", () => {
    const vp = view();
    for (const mods of [MOD.ctrl, MOD.meta, MOD.ctrl | MOD.shift]) {
      expect(navigate(vp, KEY.zoomIn, mods, 400)).toBe(false);
      expect(navigate(vp, KEY.zoomOut, mods, 400)).toBe(false);
    }
    expect(vp.barSpacing).toBe(DEFAULT_BAR_SPACING);
    expect(navigate(vp, KEY.spaceDown, 0, 400)).toBe(false); // not a viewport key
  });
});

describe("which keys the chart takes (the router's filter)", () => {
  it.each([
    ["ArrowLeft", "ArrowLeft", 0, KEY.left],
    ["ArrowRight", "ArrowRight", MOD.shift, KEY.right],
    ["Home", "Home", 0, KEY.home],
    ["Home", "Home", MOD.ctrl, KEY.home],
    ["End", "End", 0, KEY.end],
    ["+", "Equal", MOD.shift, KEY.zoomIn],
    ["=", "Equal", 0, KEY.zoomIn],
    ["+", "NumpadAdd", 0, KEY.zoomIn],
    ["-", "Minus", 0, KEY.zoomOut],
    ["_", "Minus", MOD.shift, KEY.zoomOut],
    ["Subtract", "NumpadSubtract", 0, KEY.zoomOut],
    ["=", "Equal", MOD.ctrl, 0], // browser zoom
    ["-", "Minus", MOD.meta, 0], // app zoom
    ["ArrowLeft", "ArrowLeft", MOD.ctrl, 0], // replay's Ctrl+←
    ["ArrowRight", "ArrowRight", MOD.alt, 0], // browser history, replay ticks (E26)
    ["End", "End", MOD.ctrl, 0],
    ["a", "KeyA", 0, 0],
  ])("%s (%s, mods %d) → %d", (key, code, mods, want) => {
    expect(keyCode(key, code, mods)).toBe(want);
  });

  it("Space is the pan-drag modifier, never a viewport key", () => {
    expect([isSpace(" ", "Space"), isSpace("Unidentified", "Space"), isSpace("x", "KeyX")]).toEqual(
      [true, true, false],
    );
    expect(keyCode(" ", "Space", 0)).toBe(0);
  });
});

describe("C-2.16: the navigator is DOM-free", () => {
  it("imports only the viewport, the protocol and the wheel maths, and names no DOM global", () => {
    const src = readFileSync(
      new URL("../../src/interaction/navigator.ts", import.meta.url),
      "utf8",
    );
    const imports = [...src.matchAll(/from "([^"]+)"/g)].map((m) => m[1]);
    expect(imports).toEqual([
      "../viewport/Viewport.js",
      "../viewport/transform.js",
      "../worker/protocol.js",
      "./wheel.js",
    ]);
    expect(src).not.toMatch(/\b(document|window|navigator\.|matchMedia|HTMLElement)\b/);
  });
});
