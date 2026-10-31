// E11-S05 units: every price-scale mode through the one transform, against hand-computed values;
// linear bit-identical to E11-S03; the log shader path through a CPU stand-in (BQ-78's
// Math.fround emulation of `bar-cell`); the 2D painter through `projectRel` (BQ-114).
import { describe, expect, it } from "vitest";
import { paintBarCell } from "../../src/canvas2d/painters.js";
import { attributeOffset, PROGRAM } from "../../src/scene/instance-layout.js";
import {
  ChartViewport,
  createPaneUniforms,
  displayValue,
  fitPriceRange,
  type PaneTransform,
  type PaneUniforms,
  priceAt,
  priceToScreen,
  projectRel,
  screenToPrice,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { shaderY } from "./shader-stand-in.js";

const fr = Math.fround;

/** E11-S03's shader y (pre-S05), for the bit-identity check. */
const shaderYPreS05 = (tick: number, b: PaneUniforms, dpr: number): number =>
  fr(fr(fr(tick - (b.ints[1] ?? 0)) * (b.floats[1] ?? 0)) + (b.floats[2] ?? 0)) / dpr;

/** A 1000 px plot over BTC at 0.5 ticks: priceOrigin 0, so tick 128 000 is 64 000. */
function btc(mode: PaneTransform["scaleMode"] = "linear", dpr = 1): ChartViewport {
  const vp = new ChartViewport();
  vp.setSize(1200, 1000, dpr);
  vp.setPanePlot(0, 0, 1000);
  vp.setPriceInfo(0, 0, 0.5);
  const p = vp.panes[0] as PaneTransform;
  p.logReason = null;
  vp.setScale(0, { mode });
  vp.setPriceRange(0, 100_000, 200_000); // 50 000 to 100 000
  return vp;
}

describe("each mode against hand-computed values", () => {
  it("log: sy = ln(p / pLow) / ln(pHigh / pLow) × -plotHeight + plotBottom (26 §3.5)", () => {
    const vp = btc("log");
    expect(priceToScreen(vp, 0, 100_000)).toBe(1000);
    expect(priceToScreen(vp, 0, 200_000)).toBeCloseTo(0, 9);
    const mid = Math.sqrt(100_000 * 200_000); // the geometric mean sits mid-plot
    expect(priceToScreen(vp, 0, mid)).toBeCloseTo(500, 9);
    expect(screenToPrice(vp, 0, 500)).toBeCloseTo(mid, 6);
    expect(priceToScreen(vp, 0, 150_000)).toBeCloseTo(
      (-Math.log(1.5) / Math.log(2)) * 1000 + 1000,
      9,
    );
  });

  it("percent and indexed draw as linear and relabel from the anchor's close (BQ-118)", () => {
    const lin = btc("linear");
    for (const mode of ["percent", "indexed"] as const) {
      const vp = btc(mode);
      for (const t of [100_000, 123_456, 200_000]) {
        expect(priceToScreen(vp, 0, t)).toBe(priceToScreen(lin, 0, t));
      }
      const p = vp.panes[0] as PaneTransform;
      expect(displayValue(p, 150_000)).toBeNaN(); // no anchor yet
      p.anchorTick = 120_000; // a close of 60 000
      expect(displayValue(p, 132_000)).toBeCloseTo(mode === "percent" ? 10 : 110, 12);
      expect(displayValue(p, 120_000)).toBe(mode === "percent" ? 0 : 100);
    }
    expect(displayValue(lin.panes[0] as PaneTransform, 3)).toBe(1.5); // a price, not a percent
  });

  it("invert flips the mapping after the mode's own projection, in every mode", () => {
    for (const mode of ["linear", "log", "percent", "indexed"] as const) {
      const vp = btc(mode);
      const up = [100_000, 140_000, 200_000].map((t) => priceToScreen(vp, 0, t));
      vp.setScale(0, { inverted: true });
      const inv = [100_000, 140_000, 200_000].map((t) => priceToScreen(vp, 0, t));
      inv.forEach((y, i) => expect(y).toBeCloseTo(1000 - (up[i] as number), 9));
      expect(screenToPrice(vp, 0, inv[1] as number)).toBeCloseTo(140_000, 6);
    }
  });

  it("log needs a positive price at the window's base; otherwise it projects linearly", () => {
    const vp = btc("log");
    vp.setPriceRange(0, -10, 100); // prices -5 to 50: log cannot hold them
    const lin = btc("linear");
    lin.setPriceRange(0, -10, 100);
    expect(priceToScreen(vp, 0, 40)).toBe(priceToScreen(lin, 0, 40));
    expect(Number.isFinite(screenToPrice(vp, 0, 3))).toBe(true);
  });

  it("priceAt is NaN until the tick size is known (BQ-115)", () => {
    const vp = new ChartViewport();
    expect(priceAt(vp.panes[0] as PaneTransform, 10)).toBeNaN();
    expect(vp.setPriceInfo(0, 100, 0)).toBe(false);
    expect(vp.setPriceInfo(0, 100, 0.01)).toBe(true);
    expect(priceAt(vp.panes[0] as PaneTransform, 10)).toBeCloseTo(100.1, 12);
    expect(vp.setPriceInfo(0, 100, 0.01)).toBe(false);
  });
});

describe("linear stays bit-identical to E11-S03 (BQ-113 rider)", () => {
  it("uniform values, the shader's y and priceToScreen are unchanged; u_log is [0, 0]", () => {
    for (const [low, high, dpr] of [
      [127_900.3, 128_100.3, 2],
      [-3_000.7, 52_000.1, 1],
      [0, 1, 3],
    ] as const) {
      const vp = new ChartViewport();
      vp.setSize(1280, 800, dpr);
      vp.setPanePlot(0, 0, 800);
      vp.setPriceRange(0, low, high);
      const b = createPaneUniforms();
      writePaneUniforms(vp, 0, b);
      const ky = -800 / (high - low);
      const tickBase = Math.floor(low);
      expect([...b.ints]).toEqual([0, tickBase]);
      expect(b.floats[1]).toBe(fr(ky * dpr));
      expect(b.floats[2]).toBe(fr(((tickBase - low) * ky + 0 + 800) * dpr));
      expect([b.floats[6], b.floats[7]]).toEqual([0, 0]);
      for (const t of [low, (low + high) / 2, high, Math.round(low) + 17]) {
        expect(shaderY(t, b, dpr)).toBe(shaderYPreS05(t, b, dpr));
        expect(priceToScreen(vp, 0, t)).toBe((t - low) * ky + 0 + 800);
      }
    }
  });
});

describe("linear on the CPU with a plot below another pane (README BQ-113)", () => {
  it("priceToScreen is the GPU's `rel · k + b`, within 1 ulp of E11-S03's sum", () => {
    const vp = new ChartViewport();
    vp.setSize(1280, 800, 1);
    vp.setPanePlot(0, 337.25, 400);
    vp.setPriceRange(0, 127_900.3, 128_100.3);
    const ky = -400 / 200;
    for (const t of [127_900.3, 128_000, 128_031.7, 128_100.3]) {
      const old = (t - 127_900.3) * ky + 337.25 + 400;
      const y = priceToScreen(vp, 0, t);
      expect(y).toBe((t - 127_900.3) * ky + (0 * ky + 337.25 + 400)); // the shader's association
      expect(Math.abs(y - old)).toBeLessThanOrEqual(Number.EPSILON * Math.abs(old));
      expect(screenToPrice(vp, 0, y)).toBeCloseTo(t, 9);
    }
  });
});

describe("Scenario: Log scale re-projects everything, not just candles", () => {
  it("a drawing's two (bar, price) anchors sit on the candles' shader y within 0.01 px", () => {
    const vp = btc("log", 2);
    const b = createPaneUniforms();
    writePaneUniforms(vp, 0, b);
    expect(b.floats[7]).toBe(1);
    expect(Math.abs(b.floats[6] ?? 0)).toBeLessThan(1); // a ratio, never an absolute price
    for (const anchor of [101_234, 187_001]) {
      // The drawing, the level and the profile project through priceToScreen; the candle on GPU.
      expect(Math.abs(shaderY(anchor, b, 2) - priceToScreen(vp, 0, anchor))).toBeLessThan(0.01);
    }
    const linear = btc("linear", 2);
    expect(priceToScreen(vp, 0, 101_234)).not.toBeCloseTo(priceToScreen(linear, 0, 101_234), 0);
  });

  it("the 2D painter places a log cell through projectRel on the same pixels", () => {
    const vp = btc("log", 2);
    const b = createPaneUniforms();
    writePaneUniforms(vp, 0, b);
    const CELL = attributeOffset(PROGRAM.barCell, "a_cell");
    const SIZE = attributeOffset(PROGRAM.barCell, "a_size");
    const data = new Float32Array(16);
    const ints = new Int32Array(data.buffer);
    ints[CELL] = 0;
    ints[CELL + 1] = 150_000;
    data[SIZE] = 1;
    data[SIZE + 1] = 2_000;
    const rects: number[][] = [];
    const ctx = { rect: (...r: number[]) => void rects.push(r) };
    const [w, h] = [b.floats[4] ?? 0, b.floats[5] ?? 0];
    paintBarCell(ctx as never, { data, ints, at: 0, block: b, w, h });
    const [, y, , height] = rects[0] ?? [];
    const top = priceToScreen(vp, 0, 152_000) * 2;
    expect(Math.abs((y ?? 0) - top)).toBeLessThan(0.02);
    expect(Math.abs((y ?? 0) + (height ?? 0) - priceToScreen(vp, 0, 150_000) * 2)).toBeLessThan(
      0.02,
    );
    expect(projectRel(b.floats, 0)).toBe(b.floats[2]);
  });

  it.todo(
    "Integration: candles, a trend line, a level and a profile in linear and in log, per " +
      "theme, co-anchored within 0.1 % pixel diff in a golden image (E11-T08, #391; README G-16)",
  );
});

describe("autoscale's fit (BQ-117)", () => {
  it("adds 5 % of the window top and bottom; under log, in log space and never to 0", () => {
    const vp = btc("linear");
    const p = vp.panes[0] as PaneTransform;
    fitPriceRange(p, 1_000, 1_900);
    expect(p.priceLow).toBeCloseTo(950, 9);
    expect(p.priceHigh).toBeCloseTo(1_950, 9);
    p.marginTop = 0.45;
    p.marginBottom = 0;
    fitPriceRange(p, 1_000, 1_100);
    expect(p.priceLow).toBe(1_000);
    expect(p.priceHigh).toBeCloseTo(1_000 + 100 / 0.55, 9);
    vp.setScale(0, { mode: "log", marginTop: 0.05, marginBottom: 0.05 });
    fitPriceRange(p, 2, 200); // prices 1 to 100: two decades
    expect(priceToScreen(vp, 0, 2)).toBeCloseTo(950, 6);
    expect(priceToScreen(vp, 0, 200)).toBeCloseTo(50, 6);
    expect(priceAt(p, p.priceLow)).toBeGreaterThan(0);
  });
});
