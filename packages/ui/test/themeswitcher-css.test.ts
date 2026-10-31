import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("themeswitcher.css");

describe("themeswitcher.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the segments and the switch sit space.inset.sm apart and wrap, never overflow", () => {
    const root = find(css.normal, ".cv-theme-switcher", "gap");
    expect(root).toContain("gap: var(--space-inset-sm)");
    expect(root).toContain("flex-wrap: wrap");
    expect(root).toContain("max-width: 100%");
  });
});
