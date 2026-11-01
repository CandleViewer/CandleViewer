import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("filterbar.css");

describe("filterbar.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the bar and its chip list wrap at any width or text scale, gapped by space.inset.sm", () => {
    for (const selector of [".cv-filterbar", ".cv-filterbar__chips"]) {
      const block = find(css.normal, selector, "flex-wrap");
      expect(block).toContain("flex-wrap: wrap");
      expect(block).toContain("gap: var(--space-inset-sm)");
    }
    const list = find(css.normal, ".cv-filterbar__chips", "list-style");
    expect(list).toContain("list-style: none");
    expect(list).toContain("padding: 0");
    const chip = find(css.normal, ".cv-filterbar__chip", "max-width");
    expect(chip).toContain("min-width: 0");
    expect(chip).toContain("max-width: 100%");
  });

  it("the empty line and the T2 reason are text.secondary at full strength, never dimmed", () => {
    const words = find(css.normal, ".cv-filterbar__reason", "color");
    expect(words).toContain("color: var(--color-text-secondary)");
    expect(find(css.normal, ".cv-filterbar__empty", "color")).toBe(words);
    expect(css.all).not.toMatch(/opacity|text-disabled/);
  });

  it("T2: no lock or glyph rule of the bar's own; CMP-001 draws its named lock (as CMP-177's controls)", () => {
    expect(css.all).not.toMatch(/cv-filterbar__lock|\.cv-button/);
  });

  it("forced colours: the words CanvasText, no token", () => {
    expect(find(css.forced, ".cv-filterbar__reason", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-filterbar__empty", "color")).toContain("CanvasText");
    expect(css.forced).not.toContain("var(--color");
  });
});
