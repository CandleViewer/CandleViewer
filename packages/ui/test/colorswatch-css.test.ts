import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("colorswatch.css");
const { normal, forced } = css;
const HOVER = '.cv-swatch[role="radio"]:hover:not([data-disabled], [data-gated], :focus-visible)';

describe("colorswatch.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("a size.control.height square, radius.control, filled by the displayed colour", () => {
    const sw = find(normal, ".cv-swatch", "width");
    expect(sw).toContain("width: var(--size-control-height)");
    expect(sw).toContain("height: var(--size-control-height)");
    expect(sw).toContain("border-radius: var(--radius-control)");
    expect(sw).toContain("background: var(--cv-swatch-color)");
    expect(sw).toContain("calc(var(--border-hairline) * 1px) solid transparent");
    expect(sw).toMatch(/flex: none/);
  });

  it("glyphs: text.inverse by default, text.on-action when named; check at size.icon, badge at size.icon.sm", () => {
    expect(find(normal, ".cv-swatch", "color")).toContain("color: var(--color-text-inverse)");
    expect(find(normal, '.cv-swatch[data-glyph="on-action"]', "color")).toContain(
      "var(--color-text-on-action)",
    );
    expect(find(normal, ".cv-swatch__check", "width")).toContain("width: var(--size-icon)");
    const badge = find(normal, ".cv-swatch__badge", "position");
    expect(badge).toContain("width: var(--size-icon-sm)");
    expect(badge).toMatch(/right: 0;[\s\S]*bottom: 0/);
  });

  it("picker: wraps at the B5 space.inset.sm gap", () => {
    const picker = find(normal, ".cv-swatch-picker", "gap");
    expect(picker).toContain("gap: var(--space-inset-sm)");
    expect(picker).toContain("flex-wrap: wrap");
  });

  it("hover: a hairline text.secondary outline outside, never while the focus ring shows", () => {
    const hover = find(normal, HOVER, "outline");
    expect(hover).toContain("calc(var(--border-hairline) * 1px) solid var(--color-text-secondary)");
    expect(hover).toContain("outline-offset: 0");
    expect(hover).not.toMatch(/background/);
  });

  it("plain disabled dims the whole swatch; gated never dims the colour", () => {
    expect(find(normal, ".cv-swatch[data-disabled]", "opacity")).toContain(
      "opacity: var(--opacity-disabled)",
    );
    expect(find(normal, ".cv-swatch[data-gated]", "cursor")).not.toMatch(/opacity|background/);
  });

  it("forced colours: the true colour is kept with a CanvasText edge", () => {
    const sw = find(forced, ".cv-swatch", "forced-color-adjust");
    expect(sw).toContain("forced-color-adjust: none");
    expect(sw).toContain("border-color: CanvasText");
    expect(sw).not.toMatch(/background/);
  });

  it("forced colours: Highlight edge on hover, GrayText edge when disabled or gated", () => {
    const hover = find(forced, HOVER, "border-color");
    expect(hover).toContain("border-color: Highlight");
    expect(hover).toContain("outline: none");
    expect(find(forced, ".cv-swatch[data-disabled]", "border-color")).toContain("GrayText");
    expect(find(forced, ".cv-swatch[data-gated]", "border-color")).toContain("GrayText");
  });
});
