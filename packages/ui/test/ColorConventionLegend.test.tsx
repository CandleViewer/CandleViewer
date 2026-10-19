import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ColorConventionLegend, colourName } from "../src/components/index.js";

const html = (p: Parameters<typeof ColorConventionLegend>[0]): string =>
  renderToStaticMarkup(<ColorConventionLegend {...p} />);

describe("ColorConventionLegend", () => {
  it("states the standard convention as text with glyphs", () => {
    const h = html({ view: "Footprint" });
    expect(h).toContain("Green = buy / bid / up");
    expect(h).toContain("Red = sell / ask / down");
    expect(h).toContain("▲");
    expect(h).toContain('aria-label="Footprint colour legend"');
  });
  it("keeps its rows list items of a list inside the named group (axe `listitem`, #269)", () => {
    expect(html({ view: "Footprint" })).toMatch(
      /^<div role="group" aria-label="Footprint colour legend"[^>]*><ul><li[^>]*>[\s\S]*<\/li><\/ul><\/div>$/,
    );
  });
  it("reflects inversion", () => {
    const h = html({ view: "DOM", convention: "inverted" });
    expect(h).toContain("Red = buy");
    expect(h).toContain("Green = sell");
  });
  it("reflects CVD-safe palette and both together", () => {
    expect(html({ view: "H", palette: "cvd-safe" })).toContain("Blue = buy");
    expect(html({ view: "H", palette: "cvd-safe", convention: "inverted" })).toContain(
      "Orange = buy",
    );
    expect(colourName("sell", "cvd-safe", "standard")).toBe("Orange");
  });
  it("swatches use the directional token variables (remapped per mode by CSS)", () => {
    const h = html({ view: "X", palette: "cvd-safe" });
    expect(h).toContain("var(--color-buy-default)");
    expect(h).toContain("var(--color-sell-default)");
    expect(h).toContain('data-palette="cvd-safe"');
  });
  it("renders optional value on a swatch row", async () => {
    const { SwatchLegendItem } = await import("../src/components/index.js");
    expect(renderToStaticMarkup(<SwatchLegendItem color="red" label="a" value="9" />)).toContain(
      ">9<",
    );
  });
});
