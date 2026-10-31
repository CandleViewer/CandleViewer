import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("accountmultiselect.css");

describe("accountmultiselect.css contract (E29-D04 §2.6; E30-D04 §8 tokens)", () => {
  itIsTokenOnlyAndStatic(css);

  it("rows: the row height with CMP-041's inset and radius; options in body type, color.text.primary", () => {
    const row = find(css.normal, ".cv-account-multi-select__row", "min-block-size");
    expect(row).toContain("min-block-size: var(--size-row-height)");
    expect(row).toContain("padding-inline: var(--space-inset-sm)");
    expect(row).toContain("border-radius: var(--radius-control)");
    const option = find(css.normal, ".cv-account-multi-select__option", "font");
    expect(option).toContain("color: var(--color-text-primary)");
    expect(option).toContain("--type-ui-body-font-size");
    expect(option).toContain("gap: var(--space-inset-sm)");
  });

  it("the active row: surface.hover, surface.selected in light (hover equals the overlay there)", () => {
    expect(find(css.normal, ".cv-account-multi-select__row[data-active]", "background")).toContain(
      "--color-surface-hover",
    );
    expect(
      find(
        css.normal,
        ':root[data-theme="light"] .cv-account-multi-select__row[data-active]',
        "background",
      ),
    ).toContain("--color-surface-selected");
  });

  it("the list draws no ring itself; its active row takes CMP-039's inset ring on keyboard focus", () => {
    expect(find(css.normal, ".cv-account-multi-select__list", "outline")).toContain(
      "outline: none",
    );
    const ring = find(
      css.normal,
      ".cv-account-multi-select__list:focus-visible > .cv-account-multi-select__row[data-active]",
      "outline",
    );
    expect(ring).toContain("var(--color-focus-ring)");
    expect(ring).toContain("outline-offset: calc(var(--border-focus) * 1px * -2)");
    expect(
      find(css.normal, ".cv-account-multi-select__list:focus-visible:empty", "outline"),
    ).toContain("var(--color-focus-ring)");
  });

  it("the check box is CMP-005's plate: tertiary hairline on raised, chosen in the primary action fill", () => {
    const box = find(css.normal, ".cv-account-multi-select__box", "border");
    expect(box).toContain("solid var(--color-text-tertiary)");
    expect(box).toContain("background: var(--color-surface-raised)");
    expect(box).toContain("color: var(--color-text-on-action)");
    expect(
      find(
        css.normal,
        '.cv-account-multi-select__option[aria-selected="true"] > .cv-account-multi-select__box',
        "background",
      ),
    ).toContain("--color-action-primary-default");
  });

  it("forced colours: a chosen box is Highlight, the ring Highlight; nothing rides on a token colour", () => {
    const chosen = find(
      css.forced,
      '.cv-account-multi-select__option[aria-selected="true"] > .cv-account-multi-select__box',
      "background",
    );
    expect(chosen).toContain("background: Highlight");
    expect(chosen).toContain("color: HighlightText");
    expect(css.forced).not.toContain("var(--color");
  });
});
