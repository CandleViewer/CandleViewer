import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("maskedvalue.css");
const { normal, forced } = css;

describe("maskedvalue.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("conv. 20: no ring and no dimming of its own; the nested CMP-002 and CMP-033 own them", () => {
    expect(css.all).not.toMatch(/outline|opacity/);
  });

  it("the box: surface.raised, a border.hairline in border.default, radius.control, control height", () => {
    const box = (prop: string): string => find(normal, ".cv-masked-value__box", prop);
    expect(box("background")).toContain("var(--color-surface-raised)");
    expect(box("border")).toContain("var(--color-border-default)");
    expect(box("--cv-masked-value-bw")).toContain("calc(var(--border-hairline) * 1px)");
    expect(box("border-radius")).toContain("var(--radius-control)");
    expect(box("min-height")).toContain("var(--size-control-height)");
    expect(box("padding-inline")).toContain("var(--space-inset-sm)");
  });

  it("the value in text.primary wraps at any character; the mask in text.secondary never wraps", () => {
    expect(find(normal, ".cv-masked-value__value", "color")).toContain("var(--color-text-primary)");
    expect(find(normal, ".cv-masked-value__value", "overflow-wrap")).toContain("anywhere");
    expect(css.all).not.toMatch(/text-overflow|ellipsis/);
    expect(find(normal, ".cv-masked-value__mask", "color")).toContain(
      "var(--color-text-secondary)",
    );
    expect(find(normal, ".cv-masked-value__mask", "white-space")).toContain("nowrap");
  });

  it("buttons space.inset.xs apart and never grow; the countdown space.stack.xs under the box", () => {
    expect(find(normal, ".cv-masked-value__actions", "gap")).toContain("var(--space-inset-xs)");
    expect(find(normal, ".cv-masked-value__actions", "flex")).toContain("flex: none");
    expect(find(normal, ".cv-masked-value", "gap")).toContain("var(--space-stack-xs)");
  });

  it("the countdown line: type.ui.caption in text.tertiary", () => {
    const line = (prop: string): string => find(normal, ".cv-masked-value__countdown", prop);
    expect(line("color")).toContain("var(--color-text-tertiary)");
    expect(line("font")).toContain("var(--type-ui-caption-font-size)");
  });

  it("S4: print never shows a revealed value", () => {
    expect(normal).toMatch(/@media print\s*\{\s*\.cv-masked-value__value\s*\{\s*display: none;/);
  });

  it("forced colours: the box edge and every text in CanvasText", () => {
    expect(find(forced, ".cv-masked-value__box", "border-color")).toContain("CanvasText");
    for (const part of ["value", "mask", "countdown"])
      expect(find(forced, `.cv-masked-value__${part}`, "color")).toContain("CanvasText");
  });
});
