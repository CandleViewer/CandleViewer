import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("confidencedots.css");
const { normal, forced } = css;

describe("confidencedots.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("one info tone: the filled dot is status.info.default and no other status tone appears", () => {
    expect(find(normal, ".cv-confidence__dot[data-filled]", "background")).toContain(
      "var(--color-status-info-default)",
    );
    expect(css.all.match(/--color-status-[a-z]+/g) ?? []).toEqual(["--color-status-info"]);
    expect(css.all).not.toMatch(/data-level/);
  });

  it("dots: 8 px from inset.xs padding, radius.badge, the empty one a 1 px text.tertiary ring", () => {
    const dot = find(normal, ".cv-confidence__dot", "padding");
    expect(dot).toContain("padding: var(--space-inset-xs)");
    expect(dot).toContain("border-radius: var(--radius-badge)");
    expect(dot).toContain(
      "inset 0 0 0 calc(var(--border-hairline) * 1px) var(--color-text-tertiary)",
    );
  });

  it("gaps: inset.xs between dots, inset.sm to the label; the label is caption in text.secondary", () => {
    expect(find(normal, ".cv-confidence__dots", "gap")).toContain("gap: var(--space-inset-xs)");
    const root = find(normal, ".cv-confidence", "gap");
    expect(root).toContain("gap: var(--space-inset-sm)");
    expect(root).toContain("var(--type-ui-caption-font-size)");
    expect(find(normal, ".cv-confidence__label", "color")).toContain("var(--color-text-secondary)");
  });

  it("forced colours keep filled versus empty: a CanvasText fill and a CanvasText ring", () => {
    const empty = find(forced, ".cv-confidence__dot", "border");
    expect(empty).toContain("border: 1px solid CanvasText");
    expect(empty).toContain("padding: calc(var(--space-inset-xs) - 1px)");
    const full = find(forced, ".cv-confidence__dot[data-filled]", "background");
    expect(full).toContain("background: CanvasText");
    expect(full).toContain("forced-color-adjust: none");
    expect(find(forced, ".cv-confidence__label", "color")).toContain("CanvasText");
  });
});
