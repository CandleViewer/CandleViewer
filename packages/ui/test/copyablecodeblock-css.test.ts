import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("copyablecodeblock.css");
const { normal, forced } = css;

describe("copyablecodeblock.css contract (CMP-068; E42-D04 AD-2, §15 stand-ins)", () => {
  itIsTokenOnlyAndStatic(css);

  it("region: color.surface.sunken (the color.surface.code stand-in), text.primary, space.inset.sm", () => {
    const pre = find(normal, ".cv-codeblock__pre", "background");
    expect(pre).toContain("background: var(--color-surface-sunken)");
    expect(pre).toContain("color: var(--color-text-primary)");
    expect(pre).toContain("padding: var(--space-inset-sm)");
    expect(pre).toContain("border-radius: var(--radius-control)");
    expect(pre).toContain("margin: 0");
  });

  it("type.num.sm (font.family.mono, the font.mono stand-in), the text kept as served", () => {
    const pre = find(normal, ".cv-codeblock__pre", "font");
    expect(pre).toContain("--type-num-sm-font-family");
    expect(pre).toContain("--type-num-sm-font-size");
    expect(pre).toContain("white-space: pre");
    expect(find(normal, ".cv-codeblock__code", "font")).toContain("font: inherit");
  });

  it("scrolls both ways inside the host's cap, the only thing on the page that scrolls sideways (16:128)", () => {
    const pre = find(normal, ".cv-codeblock__pre", "overflow");
    expect(pre).toContain("overflow: auto");
    expect(pre).toContain("max-block-size: var(--cv-codeblock-max-height, none)");
    expect(pre).toContain("min-width: 0");
    expect(find(normal, ".cv-codeblock", "min-width")).toContain("min-width: 0");
  });

  it("puts the Copy at the region's end, space.inset.xs under it", () => {
    const root = find(normal, ".cv-codeblock", "gap");
    expect(root).toContain("display: flex");
    expect(root).toContain("flex-direction: column");
    expect(root).toContain("gap: var(--space-inset-xs)");
    expect(find(normal, ".cv-codeblock__actions", "justify-content")).toContain(
      "justify-content: flex-end",
    );
  });

  it("forced colours: the region keeps a CanvasText edge and its text, the fill being dropped", () => {
    const pre = find(forced, ".cv-codeblock__pre", "border");
    expect(pre).toContain("border: 1px solid CanvasText");
    expect(pre).toContain("color: CanvasText");
  });
});
