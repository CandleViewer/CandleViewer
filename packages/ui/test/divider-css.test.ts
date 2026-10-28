import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("divider.css");
const { normal, forced } = css;

describe("divider.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("draws a 1 px color.border.subtle rule as a border, never a background", () => {
    expect(find(normal, ".cv-divider", "border")).toContain("var(--color-border-subtle)");
    expect(normal).not.toMatch(/background/);
    expect(find(normal, '.cv-divider[data-orientation="horizontal"]', "height")).toContain(
      "border-block-start-width: calc(var(--border-hairline) * 1px)",
    );
    expect(find(normal, '.cv-divider[data-orientation="vertical"]', "min-height")).toContain(
      "min-height: var(--size-control-height)",
    );
  });

  it("insets horizontal by space.inset.md and vertical by space.inset.xs", () => {
    expect(
      find(normal, '.cv-divider[data-orientation="horizontal"][data-inset]', "margin-inline"),
    ).toContain("var(--space-inset-md)");
    expect(
      find(normal, '.cv-divider[data-orientation="vertical"][data-inset]', "margin-block"),
    ).toContain("var(--space-inset-xs)");
  });

  it("labels: a space.inset.sm gap, the caption never truncates, the rule shrinks first", () => {
    expect(find(normal, ".cv-divider-label", "gap")).toContain("gap: var(--space-inset-sm)");
    expect(find(normal, ".cv-divider-label__text", "flex")).not.toMatch(/ellipsis|nowrap/);
    expect(find(normal, ".cv-divider-label__rule.cv-divider", "flex")).toContain("flex: 1 1 0");
  });

  it("forced colours: the rule turns CanvasText", () => {
    expect(find(forced, ".cv-divider", "border-color")).toContain("border-color: CanvasText");
  });
});
