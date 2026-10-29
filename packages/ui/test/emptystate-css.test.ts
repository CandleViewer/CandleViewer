import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("emptystate.css");

describe("emptystate.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("block: a centred column, padding inset.xl, gap stack.sm; CMP-027's panel shares it", () => {
    const block = find(css.normal, ".cv-empty-state", "padding");
    expect(block).toContain("flex-direction: column");
    expect(block).toContain("align-items: center");
    expect(block).toContain("padding: var(--space-inset-xl)");
    expect(block).toContain("gap: var(--space-stack-sm)");
    expect(block).toContain("text-align: center");
    expect(find(css.normal, '.cv-error-state[data-form="panel"]', "padding")).toBe(block);
  });

  it("the 480 px column cap is 30rem, the one deliberate raw length (no layout token yet)", () => {
    expect(find(css.normal, ".cv-empty-state", "max-inline-size")).toContain(
      "max-inline-size: 30rem",
    );
    expect(css.all.match(/\d+(\.\d+)?rem\b/g)).toEqual(["30rem"]);
  });

  it("glyph size.icon.lg in text.tertiary", () => {
    const glyph = find(css.normal, ".cv-empty-state__glyph", "color");
    expect(glyph).toContain("width: var(--size-icon-lg)");
    expect(glyph).toContain("color: var(--color-text-tertiary)");
  });

  it("type: heading text.primary, description body in text.secondary", () => {
    expect(find(css.normal, ".cv-empty-state__title", "color")).toContain(
      "color: var(--color-text-primary)",
    );
    const desc = find(css.normal, ".cv-empty-state__description", "font");
    expect(desc).toContain("--type-ui-body-font-size");
    expect(desc).toContain("color: var(--color-text-secondary)");
  });

  it("actions: inset.sm apart, stack.md under the words", () => {
    const actions = find(css.normal, ".cv-empty-state__actions", "gap");
    expect(actions).toContain("gap: var(--space-inset-sm)");
    expect(actions).toContain(
      "margin-block-start: calc(var(--space-stack-md) - var(--space-stack-sm))",
    );
  });

  it("never draws the danger tone (backfill is informational)", () => {
    expect(css.all).not.toMatch(/status-danger/);
  });

  it("a T2 action (A-D05-5, 2a): a column, its reason a caption in text.secondary under the button", () => {
    expect(find(css.normal, ".cv-empty-state__action", "flex-direction")).toContain(
      "flex-direction: column",
    );
    const reason = find(css.normal, ".cv-empty-state__reason", "font");
    expect(reason).toContain("--type-ui-caption-font-size");
    expect(reason).toContain("color: var(--color-text-secondary)");
    expect(find(css.normal, ".cv-empty-state__actions[data-gated]", "align-items")).toContain(
      "align-items: flex-start",
    );
  });

  it("the error's Ref: type.num.sm in text.secondary, selectable; CMP-027's words sit in the block unpadded", () => {
    const ref = find(css.normal, ".cv-empty-state__ref", "font");
    expect(ref).toContain("--type-num-sm-font-size");
    expect(ref).toContain("color: var(--color-text-secondary)");
    expect(ref).toContain("user-select: text");
    const words = find(
      css.normal,
      '.cv-empty-state > .cv-error-state[data-form="panel"]',
      "padding",
    );
    expect(words).toContain("padding: 0");
    for (const sel of [".cv-empty-state__reason", ".cv-empty-state__ref"]) {
      expect(find(css.forced, sel, "color")).toContain("color: CanvasText");
    }
  });

  it("wraps and never truncates", () => {
    expect(css.all).toContain("overflow-wrap: anywhere");
    expect(css.all).not.toMatch(/text-overflow|line-clamp/);
  });

  it("forced colours: the words and the glyph CanvasText", () => {
    for (const sel of [
      ".cv-empty-state__glyph",
      ".cv-empty-state__title",
      ".cv-empty-state__description",
    ]) {
      expect(find(css.forced, sel, "color")).toContain("color: CanvasText");
    }
  });
});
