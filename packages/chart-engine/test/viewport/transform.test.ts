// E11-S03 units: the shared transform against hand-computed values, its clamps and degenerate
// cases. The 10 000-case properties are transform.property.test.ts; precision is precision.test.ts.
import { describe, expect, it } from "vitest";
import { bars } from "../../bench/scenes/pan-zero-upload.js";
import { BarStore } from "../../src/model/BarStore.js";
import {
  BAR_SPACING_MAX,
  BAR_SPACING_MIN,
  ChartViewport,
  createPaneUniforms,
  INT32_TICKS,
  type IndexTimeMap,
  indexToScreen,
  priceToScreen,
  screenToIndex,
  screenToPrice,
  screenToTime,
  timeToScreen,
  writePaneUniforms,
} from "../../src/viewport/index.js";

const MIN = 60e6;
const T0 = Date.UTC(2026, 10, 24, 0, 0) * 1000; // µs

/** 1 000 one-minute bars from T0 in a real BarStore: it fits `IndexTimeMap` as is (BQ-67). */
function fixed(n = 1000): ChartViewport {
  const store = new BarStore();
  store.append(bars(n, T0));
  const vp = new ChartViewport(store);
  vp.setSize(800, 400, 1);
  vp.setPanePlot(0, 0, 400);
  vp.setTimeRange(T0 + 10 * MIN, T0 + 110 * MIN); // bar 10's centre at x = 0, 8 px a bar
  vp.setPriceRange(0, 1000, 1100);
  return vp;
}

describe("Scenario: Round-trips are exact (hand-computed mappings)", () => {
  it("maps bar index, time and price for a fixed viewport", () => {
    const vp = fixed();
    expect([vp.leftIndex, vp.barSpacing, vp.timeStart, vp.timeEnd]).toEqual([
      10.5,
      8,
      T0 + 10 * MIN,
      T0 + 110 * MIN,
    ]);
    expect([indexToScreen(vp, 10), indexToScreen(vp, 20)]).toEqual([0, 80]);
    expect([screenToIndex(vp, 80), screenToIndex(vp, 3.99), screenToIndex(vp, 4)]).toEqual([
      20, 10, 11,
    ]);
    expect(timeToScreen(vp, T0 + 20 * MIN + 30e6)).toBe(84); // interpolated through the map
    expect(screenToTime(vp, 84)).toBe(T0 + 20 * MIN + 30e6);
    expect([1000, 1050, 1100].map((t) => priceToScreen(vp, 0, t))).toEqual([400, 200, 0]);
    expect(screenToPrice(vp, 0, 100)).toBe(1075);
  });

  it("keeps bars evenly spaced across a time gap and extrapolates past the loaded range", () => {
    const s = [0, 60, 120, 600, 660].map((x) => x * 1e6);
    const map: IndexTimeMap = {
      length: s.length,
      indexToTime: (i) => s[i] ?? Number.NaN,
      timeToIndex: (t) => s.filter((x) => x <= t).length - 1,
    };
    const vp = new ChartViewport(map);
    vp.setSize(100, 100, 1);
    vp.setTimeRange(0, 4 * MIN); // index 0 to 2.25: the gap is one bar wide
    expect(indexToScreen(vp, 3) - indexToScreen(vp, 2)).toBeCloseTo(indexToScreen(vp, 1), 9);
    expect(timeToScreen(vp, 300e6)).toBeCloseTo(indexToScreen(vp, 2.375), 9);
    expect(screenToTime(vp, indexToScreen(vp, 6))).toBe(780e6); // + 2 × the last delta (60 s)
    expect(screenToTime(vp, indexToScreen(vp, -1))).toBe(-60e6);
  });
});

describe("clamping happens in the setters", () => {
  it("bounds barSpacing to [0.05, 200] and rejects non-finite input unchanged", () => {
    const vp = fixed();
    expect(vp.zoomAt(400, 1e6)).toBe(true);
    expect(vp.barSpacing).toBe(BAR_SPACING_MAX);
    vp.zoomAt(400, 1e-9);
    expect(vp.barSpacing).toBe(BAR_SPACING_MIN);
    const before = [vp.leftIndex, vp.barSpacing];
    expect([vp.zoomAt(Number.NaN, 2), vp.zoomAt(1, Infinity), vp.zoomAt(1, -1)]).toEqual([
      false,
      false,
      false,
    ]);
    expect([vp.pan(Number.NaN), vp.setTimeRange(5, 5), vp.setPriceRange(0, 2, 1)]).toEqual([
      false,
      false,
      false,
    ]);
    expect([vp.leftIndex, vp.barSpacing]).toEqual(before);
  });

  it("never stores a NaN: a huge anchor at the minimum spacing is rejected (BQ-73)", () => {
    const vp = new ChartViewport();
    vp.setSize(800, 400, 1);
    vp.zoomAt(0, 1e-9);
    const before = [vp.leftIndex, vp.barSpacing];
    expect(vp.zoomAt(1.7e308, 1)).toBe(false);
    expect([vp.leftIndex, vp.barSpacing]).toEqual(before);
    const block = createPaneUniforms();
    writePaneUniforms(vp, 0, block);
    expect(Number.isFinite(block.floats[3])).toBe(true);
  });

  it("limits rightOffset to [-(n - 1), visibleBars - 1] (BQ-69)", () => {
    const vp = fixed();
    vp.pan(-1e9); // drag left: the last bar reaches the left edge and stops there
    expect([vp.leftIndex, vp.rightOffset]).toEqual([999, vp.visibleBars - 1]);
    vp.pan(1e9); // drag right: bar 0 stays on screen
    expect([vp.leftIndex, vp.rightOffset]).toEqual([1 - vp.visibleBars, -999]);
    expect(screenToIndex(vp, 799)).toBe(0);
  });

  it.each([
    ["left edge", 0],
    ["centre", 400],
    ["right edge", 800],
  ])("zoomAt keeps the bar under the %s anchor fixed", (_, x) => {
    const vp = fixed();
    vp.pan(-2000); // away from the clamps
    const at = x / vp.barSpacing + vp.leftIndex;
    for (const factor of [1.25, 0.5, 3]) {
      vp.zoomAt(x, factor);
      expect(x / vp.barSpacing + vp.leftIndex).toBeCloseTo(at, 9);
    }
  });
});

describe("degenerate cases", () => {
  it("an empty price window widens to one tick; a zero-height plot answers priceLow", () => {
    const vp = fixed();
    vp.setPriceRange(0, 5, 5);
    expect([vp.panes[0]?.priceLow, vp.panes[0]?.priceHigh]).toEqual([4.5, 5.5]);
    expect(Number.isFinite(priceToScreen(vp, 0, 5))).toBe(true);
    vp.setPanePlot(0, 0, 0);
    expect(screenToPrice(vp, 0, 10)).toBe(4.5);
    expect(priceToScreen(vp, 7, 5)).toBe(0); // an unknown pane maps through a 0-height plot
  });

  it("a sub-tick price window widens to one tick, so ky stays finite in float32", () => {
    const vp = fixed();
    expect(vp.setPriceRange(0, 0, 1e-40)).toBe(true);
    const [lo, hi] = [vp.panes[0]?.priceLow ?? 0, vp.panes[0]?.priceHigh ?? 0];
    expect(hi - lo).toBeCloseTo(1, 12);
    const block = createPaneUniforms();
    writePaneUniforms(vp, 0, block);
    expect(Number.isFinite(block.floats[1])).toBe(true);
  });

  it("a zero-width plot neither pans nor zooms; a range keeps its spacing", () => {
    const vp = new ChartViewport();
    expect([vp.pan(10), vp.zoomAt(0, 2), vp.setTimeRange(0, MIN)]).toEqual([false, false, true]);
    expect([vp.barSpacing, vp.leftIndex]).toEqual([6, 0.5]);
    expect(vp.setSize(-1, 0, 1)).toBe(false);
  });

  it("no bars: a free 60 s grid; one bar: the clamp pins it on screen", () => {
    const vp = new ChartViewport();
    vp.setSize(600, 100, 1);
    expect(screenToTime(vp, indexToScreen(vp, 3))).toBe(3 * MIN);
    expect(vp.pan(1e6)).toBe(true); // no bars, no limit
    const one = fixed(1);
    one.pan(-1e9);
    expect(one.leftIndex).toBe(0);
    one.pan(1e9);
    expect(screenToIndex(one, one.plotWidth - 1)).toBe(0);
    one.setMap(new BarStore());
    expect(one.map.length).toBe(0);
  });

  it("keeps ticks and the bar index inside the int32 bases, so no uniform wraps (BQ-75)", () => {
    const vp = new ChartViewport();
    vp.setSize(600, 100, 1);
    expect(vp.setPriceRange(0, 0, INT32_TICKS)).toBe(false);
    expect(vp.setPriceRange(0, -INT32_TICKS, 0)).toBe(false);
    expect(vp.setPriceRange(0, 1 - INT32_TICKS, INT32_TICKS - 1)).toBe(true);
    vp.pan(-1e15); // no bars: the free grid still stops at the int32 domain
    expect(vp.leftIndex).toBe(INT32_TICKS);
    vp.pan(1e15);
    expect(vp.leftIndex).toBe(-INT32_TICKS);
    const wide = fixed();
    wide.setSize(1e12, 100, 1); // a plot wider than 2^31 bars still keeps the base in range
    wide.pan(-1e12);
    wide.pan(1e15);
    expect(wide.leftIndex).toBeGreaterThanOrEqual(-INT32_TICKS);
    const block = createPaneUniforms();
    writePaneUniforms(wide, 0, block);
    expect(block.ints[0]).toBe(-INT32_TICKS);
  });
});
