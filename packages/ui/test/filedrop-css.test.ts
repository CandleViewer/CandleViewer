import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("filedrop.css");

// CMP-067's zone (E15-D09 §3.3's anatomy): a hairline edge, never dashed; a drag changes words and edge.
describe("filedrop.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the zone: inset.xl padding, the card radius and a solid border.default hairline", () => {
    const zone = find(css.normal, ".cv-filedrop__zone", "padding");
    expect(zone).toContain("padding: var(--space-inset-xl)");
    expect(zone).toContain("var(--radius-card)");
    expect(zone).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(css.all).not.toContain("dashed");
  });

  it("one file dragged over: the selected edge and the hover fill", () => {
    const active = find(css.normal, '.cv-filedrop__zone[data-state="active"]', "border-color");
    expect(active).toContain("var(--color-border-selected)");
    expect(active).toContain("var(--color-surface-hover)");
  });

  it("the zone's words in text.secondary", () => {
    expect(find(css.normal, ".cv-filedrop__hint", "color")).toContain(
      "var(--color-text-secondary)",
    );
  });

  it("a T2 reason (2a) is a caption line in text.secondary: the zone's, or under its own apply target", () => {
    const reason = find(css.normal, ".cv-filedrop__reason", "color").replace(/\s+/g, " ");
    expect(reason).toContain("color: var(--color-text-secondary)");
    expect(reason).toContain("var(--type-ui-caption-font-size)");
    const action = find(css.normal, ".cv-filedrop__action", "flex-direction");
    expect(action).toContain("flex-direction: column");
    expect(action).toContain("gap: var(--space-stack-xs)");
    expect(find(css.normal, ".cv-filedrop__actions[data-gated]", "align-items")).toContain(
      "align-items: flex-start",
    );
    expect(find(css.forced, ".cv-filedrop__reason", "color")).toContain("CanvasText");
  });

  it("forced colours: a CanvasText edge, Highlight while a file is over it", () => {
    expect(find(css.forced, ".cv-filedrop__zone", "border-color")).toContain("CanvasText");
    expect(find(css.forced, '.cv-filedrop__zone[data-state="active"]', "border-color")).toContain(
      "Highlight",
    );
  });
});
