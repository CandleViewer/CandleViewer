import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("link.css");
const { normal, forced } = css;

describe("link.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("link colour, always underlined, the surrounding type", () => {
    const base = find(normal, ".cv-link", "color");
    expect(base).toContain("color: var(--color-text-link)");
    expect(base).toContain("text-decoration-line: underline");
    expect(base).toContain("font: inherit");
  });

  it("square ring (E8): no radius and no ring of its own; CMP-039 draws it", () => {
    expect(css.all).not.toMatch(/border-radius|outline|box-shadow/);
  });

  it("external mark: a plain inline box that never wraps, so the joiner binds the glyph", () => {
    const mark = find(normal, ".cv-link__external", "white-space");
    expect(mark).toContain("white-space: nowrap");
    expect(mark).not.toMatch(/display/);
  });

  it("external glyph: an inline-block size.icon, inset.xs from the last word", () => {
    const glyph = find(normal, ".cv-link__glyph", "width");
    expect(glyph).toContain("display: inline-block");
    expect(glyph).toContain("width: var(--size-icon)");
    expect(glyph).toContain("height: var(--size-icon)");
    expect(glyph).toContain("margin-inline-start: var(--space-inset-xs)");
  });

  it("disabled dims with opacity.disabled", () => {
    expect(find(normal, '.cv-link[aria-disabled="true"]', "opacity")).toContain(
      "var(--opacity-disabled)",
    );
  });

  it("forced colours: LinkText, GrayText when disabled, the underline kept", () => {
    expect(find(forced, ".cv-link", "color")).toContain("LinkText");
    const disabled = find(forced, '.cv-link[aria-disabled="true"]', "color");
    expect(disabled).toContain("GrayText");
    expect(disabled).toContain("opacity: 1");
    expect(forced).not.toMatch(/text-decoration/);
  });
});
