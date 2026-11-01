// E11-S06 axis-stop keys (README BQ-194 to BQ-196; E11-D02 §7.1, §7.2): the key map, every price
// and time key on the shared viewport, and the announcement each one asks for.
import { describe, expect, it } from "vitest";
import { AxisModel, SAY } from "../../src/axes/axis-model.js";
import { axisKeyCode, priceAxisKey, timeAxisKey } from "../../src/interaction/axis-keys.js";
import { MOD } from "../../src/interaction/wheel.js";
import { ChartViewport, DEFAULT_BAR_SPACING } from "../../src/viewport/index.js";
import { KEY } from "../../src/worker/protocol.js";
import { minuteMap } from "../interaction/fixtures.js";

function vp(): ChartViewport {
  const v = new ChartViewport(minuteMap());
  v.setSize(1200, 600, 1);
  v.setPanePlot(0, 0, 600);
  v.setPriceInfo(0, 0, 0.5);
  v.setPriceRange(0, 1_000, 2_000);
  v.scrollTo(1_000, 6);
  return v;
}
const span = (v: ChartViewport): number =>
  (v.panes[0]?.priceHigh ?? 0) - (v.panes[0]?.priceLow ?? 0);

describe("axisKeyCode", () => {
  it("maps the stop's keys and leaves chords to the page", () => {
    const k = (key: string, mods = 0, code = ""): number => axisKeyCode(key, code, mods);
    expect([k("ArrowUp"), k("ArrowDown"), k("PageUp"), k("PageDown")]).toEqual([
      KEY.up,
      KEY.down,
      KEY.pageUp,
      KEY.pageDown,
    ]);
    expect([k("ArrowLeft"), k("ArrowRight"), k("Home"), k("End")]).toEqual([
      KEY.left,
      KEY.right,
      KEY.home,
      KEY.end,
    ]);
    expect([k("+"), k("="), k("x", 0, "NumpadAdd"), k("-"), k("x", 0, "NumpadSubtract")]).toEqual([
      KEY.zoomIn,
      KEY.zoomIn,
      KEY.zoomIn,
      KEY.zoomOut,
      KEY.zoomOut,
    ]);
    expect([k("Home", MOD.ctrl), k("ArrowUp", MOD.ctrl), k("ArrowUp", MOD.alt), k("Tab")]).toEqual([
      KEY.home,
      0,
      0,
      0,
    ]);
  });
});

describe("priceAxisKey (BQ-195)", () => {
  it("Up / Down rescale 10 % (Shift 25 %) about the centre and lock", () => {
    const v = vp();
    const s0 = span(v);
    expect(priceAxisKey(v, 0, KEY.up, 0)).toBe(SAY.priceLocked);
    expect(span(v) / s0).toBeCloseTo(0.9, 9);
    expect(priceAxisKey(v, 0, KEY.down, MOD.shift)).toBe(SAY.priceRange);
    expect(span(v) / s0).toBeCloseTo(0.9 / 0.75, 9);
  });

  it("PageUp / PageDown shift by half the height and lock; Home releases", () => {
    const v = vp();
    const low = v.panes[0]?.priceLow ?? 0;
    expect(priceAxisKey(v, 0, KEY.pageUp, 0)).toBe(SAY.priceLocked);
    expect((v.panes[0]?.priceLow ?? 0) - low).toBeCloseTo(span(v) / 2, 6);
    expect(priceAxisKey(v, 0, KEY.pageDown, 0)).toBe(SAY.priceRange);
    expect(v.panes[0]?.priceLow).toBeCloseTo(low, 6);
    expect(priceAxisKey(v, 0, KEY.home, 0)).toBe(SAY.priceAuto);
    expect(priceAxisKey(v, 0, KEY.home, 0)).toBe(SAY.none); // already auto
    expect(priceAxisKey(v, 0, KEY.left, 0)).toBe(SAY.none);
    expect(priceAxisKey(v, 3, KEY.up, 0)).toBe(SAY.none); // no such pane
  });
});

describe("timeAxisKey (BQ-196)", () => {
  it("pans 10 % (Shift a width), zooms about the centre, fits, goes live, resets spacing", () => {
    const v = vp();
    const left = v.leftIndex;
    expect(timeAxisKey(v, KEY.left, 0)).toBe(SAY.timeRange);
    expect(left - v.leftIndex).toBeCloseTo(120 / 6, 9);
    expect(timeAxisKey(v, KEY.right, MOD.shift)).toBe(SAY.timeRange);
    expect(v.leftIndex - left).toBeCloseTo(1200 / 6 - 120 / 6, 9);
    const centre = 600 / v.barSpacing + v.leftIndex;
    expect(timeAxisKey(v, KEY.zoomIn, MOD.shift)).toBe(SAY.spacing);
    expect(v.barSpacing).toBeCloseTo(7.5, 9);
    expect(600 / v.barSpacing + v.leftIndex).toBeCloseTo(centre, 9);
    expect(timeAxisKey(v, KEY.home, MOD.ctrl)).toBe(SAY.defaultSpacing);
    expect(v.barSpacing).toBeCloseTo(DEFAULT_BAR_SPACING, 9);
    expect(timeAxisKey(v, KEY.home, 0)).toBe(SAY.fitted);
    expect([v.leftIndex, v.barSpacing]).toEqual([0, 1200 / 2000]);
    expect(timeAxisKey(v, KEY.end, 0)).toBe(SAY.live);
    expect(timeAxisKey(v, KEY.up, 0)).toBe(SAY.none);
  });

  it("each SAY reads as E11-D02's words", () => {
    const v = vp();
    const m = new AxisModel();
    const say = (code: number): string | null => {
      m.say = code;
      return m.takeSay(v);
    };
    expect(say(SAY.live)).toBe("Following live");
    expect(say(SAY.fitted)).toBe("Fitted 2,000 bars");
    expect(say(SAY.defaultSpacing)).toBe("Default spacing");
    expect(say(SAY.spacing)).toBe("6 pixels per bar");
    expect(say(SAY.timeRange)).toMatch(/^\d\d \w{3} \d\d:\d\d to \d\d \w{3} \d\d:\d\d$/);
    expect(say(SAY.none)).toBeNull();
  });
});
