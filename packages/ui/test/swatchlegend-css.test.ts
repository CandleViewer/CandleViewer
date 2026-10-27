import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("swatchlegend.css");
const { normal, forced } = css;

describe("swatchlegend.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("a 16 px size.icon swatch with a strong hairline outline, filled by the keyed colour", () => {
    const swatch = find(normal, ".cv-legend-item__swatch", "width");
    expect(swatch).toContain("width: var(--size-icon)");
    expect(swatch).toContain("height: var(--size-icon)");
    expect(swatch).toContain("calc(var(--border-hairline) * 1px) solid var(--color-border-strong)");
    expect(swatch).toContain("background: var(--cv-legend-swatch)");
  });

  it("row: size.row.height minimum and a space.inset.sm gap", () => {
    const row = find(normal, ".cv-legend-item", "gap");
    expect(row).toContain("gap: var(--space-inset-sm)");
    expect(row).toContain("min-height: var(--size-row-height)");
  });

  it("forced colours: the swatch keeps its colour, edged in CanvasText; the glyph is CanvasText", () => {
    const swatch = find(forced, ".cv-legend-item__swatch", "border-color");
    expect(swatch).toContain("border-color: CanvasText");
    expect(swatch).toContain("forced-color-adjust: none");
    expect(find(forced, ".cv-legend-item__glyph", "color")).toContain("CanvasText");
  });
});
