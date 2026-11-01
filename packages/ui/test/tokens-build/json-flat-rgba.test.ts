import { describe, expect, it } from "vitest";
import {
  hexToRgba,
  isEngineToken,
} from "../../../../tools/style-dictionary/formats/json-flat-rgba.js";

describe("json/flat-rgba format helpers", () => {
  it("converts a 6-digit hex colour to sRGB 0..1 RGBA floats", () => {
    expect(hexToRgba("#2EBD59")).toEqual([0.1804, 0.7412, 0.349, 1]);
  });

  it("accepts hex without a leading #", () => {
    expect(hexToRgba("2EBD59")).toEqual([0.1804, 0.7412, 0.349, 1]);
  });

  it("supports an 8-digit hex with alpha", () => {
    const [, , , a] = hexToRgba("#00000080");
    expect(a).toBeCloseTo(0.502, 2);
  });

  it("throws on a non-hex value (TOKENS-E003 upstream guard)", () => {
    expect(() => hexToRgba("not-a-color")).toThrow(/not a hex colour/);
  });

  it("classifies chart-category token names as engine tokens", () => {
    expect(isEngineToken("color.candle.up")).toBe(true);
    expect(isEngineToken("color.footprint.bid")).toBe(true);
    expect(isEngineToken("color.buy.default")).toBe(true);
  });

  it("routes the chart slots and the CVD-safe palette to the engine (E11-D05 §4, G16)", () => {
    expect(isEngineToken("color.chart.pane.bg.default")).toBe(true);
    expect(isEngineToken("color.chart.pill.text.on-marker")).toBe(true);
    expect(isEngineToken("color.cvd.heatmap.bid.1")).toBe(true);
    expect(isEngineToken("color.cvd.buy")).toBe(true);
  });

  it("excludes non-chart token names from the engine filter", () => {
    expect(isEngineToken("color.text.primary")).toBe(false);
    expect(isEngineToken("space.inset.md")).toBe(false);
  });
});
