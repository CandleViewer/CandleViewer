import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("previewtile.css");
const { normal, forced } = css;

describe("previewtile.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("frame: sunken fill, radius.card, the border.default hairline (J2), primary text", () => {
    const frame = find(normal, ".cv-preview-tile__frame", "background");
    expect(frame).toContain("background: var(--color-surface-sunken)");
    expect(frame).toContain("border-radius: var(--radius-card)");
    expect(frame).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(frame).toContain("color: var(--color-text-primary)");
  });

  it("empty, error, notes and caption: caption type in text.secondary, wrapping", () => {
    const text = find(normal, ".cv-preview-tile__caption", "font");
    expect(text).toContain("--type-ui-caption-font-size");
    expect(text).toContain("color: var(--color-text-secondary)");
    expect(text).toContain("overflow-wrap: anywhere");
    expect(find(normal, ".cv-preview-tile__status", "font")).toBe(text);
  });

  it("ladder value: type.num.base in text.primary, tabular", () => {
    const value = find(normal, ".cv-preview-tile__value", "font");
    expect(value).toContain("--type-num-base-font-size");
    expect(value).toContain("color: var(--color-text-primary)");
    expect(value).toContain("tabular-nums");
  });

  it("glyphs: danger.strong for the error, warning.strong for the contrast warning", () => {
    expect(find(normal, ".cv-preview-tile__glyph", "color")).toContain(
      "var(--color-status-danger-strong)",
    );
    expect(find(normal, ".cv-preview-tile__warning > .cv-preview-tile__glyph", "color")).toContain(
      "var(--color-status-warning-strong)",
    );
  });

  it("not interactive: no hover, focus, cursor or opacity", () => {
    expect(css.all).not.toMatch(/:hover|focus|opacity|cursor/);
  });

  it("forced colours: a CanvasText edge and CanvasText text and glyphs", () => {
    expect(find(forced, ".cv-preview-tile__frame", "border-color")).toContain("CanvasText");
    for (const sel of [
      ".cv-preview-tile__status",
      ".cv-preview-tile__caption",
      ".cv-preview-tile__glyph",
    ])
      expect(find(forced, sel, "color")).toContain("CanvasText");
  });
});
