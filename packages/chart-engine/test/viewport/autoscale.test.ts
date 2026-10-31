// E11-S05: autoscale, the log guard and the percent anchor over injected `PriceExtentSource`s
// (BQ-116 to BQ-120), on a real ChartViewport over the synthetic 1-minute map (BQ-111).
import { describe, expect, it } from "vitest";
import {
  AutoScaler,
  ChartViewport,
  columnSource,
  type ExtentColumns,
  logReasonFor,
  type PaneTransform,
  type PriceExtentSource,
  priceToScreen,
} from "../../src/viewport/index.js";
import { minuteMap } from "../interaction/fixtures.js";

const N = 1_000;

/** Bars i with low 1000 + i, high 1010 + i, close 1005 + i (ticks of 0.01 from 0). */
function columns(n = N): { low: Int32Array; high: Int32Array; close: Int32Array; length: number } {
  const low = new Int32Array(n).map((_, i) => 1_000 + i);
  return { low, high: low.map((v) => v + 10), close: low.map((v) => v + 5), length: n };
}

function setup(extra: PriceExtentSource[] = [], cols: ExtentColumns = columns()) {
  const vp = new ChartViewport(minuteMap(N));
  vp.setSize(1000, 500, 1);
  vp.setPanePlot(0, 0, 500);
  vp.scrollTo(100, 10); // bars 100 to 200 visible
  vp.setPriceInfo(0, 0, 0.01);
  const main = columnSource(() => cols);
  const scaler = new AutoScaler(vp, (pane) => (pane === 0 ? [main, ...extra] : []));
  return { vp, p: vp.panes[0] as PaneTransform, main, scaler };
}

/** A drawing source: fixed ticks, whatever the bar range. */
const drawing = (lo: number, hi: number): PriceExtentSource => ({
  kind: "drawing",
  version: 0,
  extent: (_a, _b, out) => ((out[0] = lo), (out[1] = hi), true),
  minLow: () => lo,
});

describe("autoscale (BQ-116, BQ-117)", () => {
  it("fits the visible bars plus 5 % of the window top and bottom, once per change", () => {
    const { vp, p, scaler } = setup();
    vp.scrollTo(100.2, 10);
    expect(scaler.update()).toBe(true);
    // Bars 100 to 200: lows from 1100, highs to 1210; 110 ticks are 90 % of the window.
    expect(p.priceLow).toBeCloseTo(1_100 - (0.05 * 110) / 0.9, 9);
    expect(p.priceHigh).toBeCloseTo(1_210 + (0.05 * 110) / 0.9, 9);
    expect(scaler.update()).toBe(false); // nothing changed: no refit
    expect(scaler.counters.autoscale_recomputes).toBe(1);
    vp.pan(-0.5); // inside the same integer range: still no refit
    expect(scaler.update()).toBe(false);
    vp.pan(-25);
    expect(scaler.update()).toBe(true);
    expect(scaler.counters.autoscale_recomputes).toBe(2);
  });

  it("refits on an in-window mutation (C-29), and an empty extent leaves the range", () => {
    const cols = columns();
    const { p, main, scaler } = setup([], cols);
    scaler.update();
    cols.high[150] = 5_000; // a live tick makes a new high
    main.version += 1;
    expect(scaler.update()).toBe(true);
    expect(p.priceHigh).toBeGreaterThan(5_000);
    const before = [p.priceLow, p.priceHigh];
    cols.length = 0;
    main.version += 1;
    scaler.update();
    expect([p.priceLow, p.priceHigh]).toEqual(before);
  });

  it("a locked scale is never refitted; unlocking refits on the next frame", () => {
    const { vp, p, scaler } = setup();
    scaler.update();
    vp.setScale(0, { auto: false });
    vp.setPriceRange(0, 0, 10);
    vp.pan(-300);
    scaler.update();
    expect([p.priceLow, p.priceHigh]).toEqual([0, 10]);
    vp.setScale(0, { auto: true });
    expect(scaler.update()).toBe(true);
    expect(p.priceLow).toBeGreaterThan(1_000);
  });

  it("'Scale price only' drops overlays from the fit, never from the guard", () => {
    const cols = columns();
    const band = { ...columnSource(() => ({ ...cols, low: cols.low.map(() => -5) })) };
    const overlay: PriceExtentSource = { ...band, kind: "overlay" };
    const { vp, p, scaler } = setup([overlay], cols);
    scaler.update();
    expect(p.priceLow).toBeLessThan(0);
    expect(p.logReason).toBe("non-positive");
    vp.setScale(0, { priceOnly: true });
    scaler.update();
    expect(p.priceLow).toBeGreaterThan(1_000);
    expect(p.logReason).toBe("non-positive");
  });
});

describe("Scenario: Autoscale includes drawings only when asked", () => {
  it("a drawing 20 % above the range is ignored when off, and fitted within one frame when on", () => {
    const { vp, p, scaler } = setup([drawing(1_100, 1_232)]); // 20 % of 110 above 1210
    scaler.update();
    expect(p.priceHigh).toBeLessThan(1_232);
    vp.pan(-20); // the visible range changes: still the bars only
    scaler.update();
    expect(p.priceHigh).toBeLessThan(1_232 + 2);
    vp.setScale(0, { includeDrawings: true });
    expect(scaler.update()).toBe(true); // the next frame, one refit
    expect(priceToScreen(vp, 0, 1_232)).toBeGreaterThan(0);
    expect(priceToScreen(vp, 0, 1_232)).toBeCloseTo(0.05 * 500, 0);
  });
});

describe("Scenario: Percent scale reads as change from the reference bar", () => {
  it("anchors on the left-most fully visible bar's close and re-anchors on a range change", () => {
    const { vp, p, scaler } = setup();
    vp.setScale(0, { mode: "percent" });
    scaler.update();
    expect(p.anchorTick).toBe(1_105); // bar 100's close
    vp.pan(-5); // half a bar: bar 100 is no longer fully visible
    scaler.update();
    expect(p.anchorTick).toBe(1_106);
    vp.pan(-30);
    scaler.update();
    expect(p.anchorTick).toBe(1_109);
  });
});

describe("Scenario: Log is refused, not faked, on non-positive data", () => {
  it("a 0 anywhere in the loaded range refuses log and keeps the previous mode", () => {
    const cols = columns();
    cols.low[3] = 0; // far left of the visible range: the guard covers what is loaded (C-31)
    const { vp, p, scaler } = setup([], cols);
    vp.setScale(0, { mode: "percent" });
    scaler.update();
    expect(p.logReason).toBe("non-positive");
    expect(vp.setScale(0, { mode: "log" })).toBe(true); // the request is recorded, not drawn
    expect([p.scaleMode, p.requestedMode]).toEqual(["percent", "log"]);
    scaler.update();
    expect(p.scaleMode).toBe("percent");
  });

  it("a persisted log before the price origin is drawn once positive bars arrive (D2, D5)", () => {
    const vp = new ChartViewport(minuteMap(N));
    vp.setSize(1000, 500, 1);
    vp.setPanePlot(0, 0, 500);
    vp.scrollTo(100, 10);
    const p = vp.panes[0] as PaneTransform;
    const scaler = new AutoScaler(vp, () => [columnSource(() => columns())]);
    vp.setScale(0, { mode: "log" }); // addPane's PaneOptions.priceScale, before the first bars
    scaler.update();
    expect([p.scaleMode, p.requestedMode, p.logReason]).toEqual([
      "linear",
      "log",
      "no-price-origin",
    ]);
    vp.setPriceInfo(0, 0, 0.01); // the first bars batch's params (BQ-115)
    expect(scaler.update()).toBe(true);
    expect([p.scaleMode, p.requestedMode, p.logReason]).toEqual(["log", "log", null]);
    expect(scaler.counters.log_guard_trips).toBe(0);
  });

  it("a persisted log whose first bars hold a 0 stays linear and keeps the request", () => {
    const cols = columns();
    cols.low[0] = 0;
    const vp = new ChartViewport(minuteMap(N));
    const p = vp.panes[0] as PaneTransform;
    const src = columnSource(() => cols);
    const scaler = new AutoScaler(vp, () => [src]);
    vp.setScale(0, { mode: "log" });
    vp.setPriceInfo(0, 0, 0.01);
    scaler.update();
    expect([p.scaleMode, p.requestedMode, p.logReason]).toEqual(["linear", "log", "non-positive"]);
    cols.low[0] = 1_000; // positive again: available, but never flips by itself
    src.version += 1;
    scaler.update();
    expect([p.scaleMode, p.logReason]).toEqual(["linear", null]);
  });

  it("a negative low arriving while log is active falls back to linear before the frame", () => {
    const cols = columns();
    const { vp, p, main, scaler } = setup([], cols);
    scaler.update();
    expect(vp.setScale(0, { mode: "log" })).toBe(true);
    scaler.update();
    cols.low[999] = -3;
    main.version += 1;
    expect(scaler.update()).toBe(true);
    expect([p.scaleMode, p.requestedMode, p.logReason]).toEqual(["linear", "log", "non-positive"]);
    expect(scaler.counters.log_guard_trips).toBe(1);
    expect(Number.isFinite(priceToScreen(vp, 0, -3))).toBe(true); // no NaN geometry
    cols.low[999] = 1_999; // positive again: log is available but never restores itself
    main.version += 1;
    scaler.update();
    expect([p.scaleMode, p.logReason]).toEqual(["linear", null]);
    expect(scaler.update()).toBe(false);
  });

  it("log needs the price origin (BQ-115): the reason is a code, never copy", () => {
    const vp = new ChartViewport();
    const p = vp.panes[0] as PaneTransform;
    expect(logReasonFor(p, 5)).toBe("no-price-origin");
    vp.setPriceInfo(0, -10, 1);
    expect(logReasonFor(p, 10)).toBe("non-positive");
    expect(logReasonFor(p, 11)).toBeNull();
    expect(logReasonFor(p, Number.NaN)).toBeNull(); // nothing loaded: nothing to refuse
  });
});
