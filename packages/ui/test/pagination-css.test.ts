import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("pagination.css");
const { normal, forced } = css;

describe("pagination.css contract (CMP-053 cursor mode; E42-D04 D4, §12.1)", () => {
  itIsTokenOnlyAndStatic(css);

  it("a row of buttons space.inset.xs apart that wraps, the reason lines under it", () => {
    const root = find(normal, ".cv-pagination", "flex-direction");
    expect(root).toContain("display: flex");
    expect(root).toContain("flex-direction: column");
    expect(root).toContain("align-items: flex-start");
    expect(root).toContain("gap: var(--space-stack-xs)");
    expect(root).toContain("min-width: 0");
    const row = find(normal, ".cv-pagination__buttons", "gap");
    expect(row).toContain("display: flex");
    expect(row).toContain("flex-wrap: wrap");
    expect(row).toContain("gap: var(--space-inset-xs)");
  });

  it("a T2 reason: type.ui.caption in text.secondary, wrapping (§12.1), never dimmed", () => {
    const reason = find(normal, ".cv-pagination__reason", "color");
    expect(reason).toContain("color: var(--color-text-secondary)");
    expect(reason).toContain("--type-ui-caption-font-size");
    expect(reason).toContain("margin: 0");
    expect(reason).toContain("overflow-wrap: anywhere");
    expect(css.all).not.toMatch(/text-disabled|opacity/);
  });

  it("forced colours: the reason in CanvasText; the buttons keep CMP-001's own rendering", () => {
    expect(find(forced, ".cv-pagination__reason", "color")).toContain("color: CanvasText");
  });
});
