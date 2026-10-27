import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("kbd.css");
const { normal, forced } = css;

describe("kbd.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("caps: raised fill, a strong hairline edge, radius.xs, type.num.xs in text.secondary", () => {
    const cap = find(normal, ".cv-kbd__cap", "border");
    expect(cap).toContain("background: var(--color-surface-raised)");
    expect(cap).toContain("calc(var(--border-hairline) * 1px) solid var(--color-border-strong)");
    expect(cap).toContain("border-radius: var(--radius-xs)");
    expect(cap).toContain("padding-inline: var(--space-inset-xs)");
    expect(cap).toContain("color: var(--color-text-secondary)");
    expect(cap).toContain("font-size: var(--type-num-xs-font-size)");
    expect(cap).toContain("font-variant-numeric: tabular-nums");
    expect(cap).toMatch(/min-width: calc\(1lh \+/);
  });

  it("caps sit space.inset.xs apart and never wrap apart", () => {
    const caps = find(normal, ".cv-kbd__caps", "gap");
    expect(caps).toContain("gap: var(--space-inset-xs)");
    expect(caps).toContain("flex-wrap: nowrap");
  });

  it("forced colours: CanvasText edge and text on Canvas", () => {
    const cap = find(forced, ".cv-kbd__cap", "border-color");
    expect(cap).toContain("border-color: CanvasText");
    expect(cap).toContain("color: CanvasText");
    expect(find(forced, ".cv-kbd__word", "color")).toContain("CanvasText");
  });
});
