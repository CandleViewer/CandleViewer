import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("sparkline.css");
const { normal, forced } = css;

describe("sparkline.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("uncoloured data ink is text.tertiary; colorBySign binds buy / sell / neutral .default", () => {
    expect(find(normal, ".cv-sparkline", "color")).toContain("var(--color-text-tertiary)");
    for (const [trend, token] of [
      ["up", "--color-buy-default"],
      ["down", "--color-sell-default"],
      ["flat", "--color-neutral-default"],
    ] as const) {
      const sel = `.cv-sparkline[data-color-by-sign][data-trend="${trend}"]`;
      expect(find(normal, sel, "color"), trend).toContain(`var(${token})`);
    }
  });

  it("the line is a currentColor stroke with no fill and round caps and joins", () => {
    const line = find(normal, ".cv-sparkline__line", "stroke");
    expect(line).toContain("fill: none");
    expect(line).toContain("stroke: currentColor");
    expect(line).toContain("stroke-linecap: round");
    expect(line).toContain("stroke-linejoin: round");
  });

  it("forced colours: every stroke colour becomes CanvasText", () => {
    for (const sel of [
      ".cv-sparkline",
      '.cv-sparkline[data-color-by-sign][data-trend="up"]',
      '.cv-sparkline[data-color-by-sign][data-trend="down"]',
      '.cv-sparkline[data-color-by-sign][data-trend="flat"]',
    ]) {
      expect(find(forced, sel, "color"), sel).toContain("color: CanvasText");
    }
    expect(forced).not.toContain("var(--");
  });
});
