import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("errorstate.css");

describe("errorstate.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the glyph takes the severity's .strong: danger by default, warning on warning", () => {
    expect(find(css.normal, ".cv-error-state", "--cv-error-strong")).toContain(
      "--cv-error-strong: var(--color-status-danger-strong)",
    );
    expect(
      find(css.normal, '.cv-error-state[data-severity="warning"]', "--cv-error-strong"),
    ).toContain("--cv-error-strong: var(--color-status-warning-strong)");
    expect(find(css.normal, ".cv-error-state__glyph", "color")).toContain(
      "color: var(--cv-error-strong)",
    );
  });

  it("glyph size.icon; the panel's size.icon.lg", () => {
    expect(find(css.normal, ".cv-error-state__glyph", "width")).toContain(
      "width: var(--size-icon)",
    );
    expect(
      find(css.normal, '.cv-error-state[data-form="panel"] > .cv-error-state__glyph', "width"),
    ).toContain("width: var(--size-icon-lg)");
  });

  it("message body in text.primary outside the banner (the banner's is CMP-028's body-strong)", () => {
    const text = find(
      css.normal,
      '.cv-error-state[data-form="panel"] .cv-error-state__text',
      "font",
    );
    expect(text).toContain("--type-ui-body-font-size");
    expect(text).toContain("color: var(--color-text-primary)");
    expect(
      find(css.normal, '.cv-error-state[data-form="inline"] .cv-error-state__text', "font"),
    ).toBe(text);
    expect(css.all).not.toMatch(/\.cv-error-state\[data-form="banner"\] \.cv-error-state__text/);
  });

  it("the banner draws no box of its own: CMP-028's callout.css owns it", () => {
    expect(css.all).not.toMatch(/border-inline-start|status-danger-subtle|status-warning-subtle/);
  });

  it("inline: one row, inset.xs apart, no fill", () => {
    const row = find(css.normal, '.cv-error-state[data-form="inline"]', "gap");
    expect(row).toContain("gap: var(--space-inset-xs)");
    expect(row).not.toContain("background");
  });

  it("summary: its links stack.xs apart, an unstyled list", () => {
    const items = find(css.normal, ".cv-error-state__items", "gap");
    expect(items).toContain("gap: var(--space-stack-xs)");
    expect(items).toContain("list-style: none");
  });

  it("details: num.sm text.secondary on surface.raised, radius.control, inset.sm, selectable, scrolling", () => {
    const box = find(css.normal, ".cv-error-state__details:not([hidden])", "background");
    expect(box).toContain("background: var(--color-surface-raised)");
    expect(box).toContain("border-radius: var(--radius-control)");
    expect(box).toContain("padding: var(--space-inset-sm)");
    const text = find(css.normal, ".cv-error-state__details-text", "font-size");
    expect(text).toContain("font-size: var(--type-num-sm-font-size)");
    expect(text).toContain("color: var(--color-text-secondary)");
    expect(text).toContain("user-select: text");
    expect(text).toContain("overflow: auto");
    expect(css.all).not.toMatch(/text-overflow|line-clamp/);
  });

  it("forced colours: words and glyph CanvasText, the details box a 1px CanvasText border", () => {
    expect(find(css.forced, ".cv-error-state__glyph", "color")).toContain("color: CanvasText");
    expect(find(css.forced, ".cv-error-state__text", "color")).toContain("color: CanvasText");
    expect(find(css.forced, ".cv-error-state__details:not([hidden])", "border")).toContain(
      "border: 1px solid CanvasText",
    );
  });
});
