import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

// CMP-114's stylesheet (E29-D02 §12; E29-D04 §2.1, D04H §C.1 Tokens): tokens only, static, and the bindings the
// design names, so a swap of one of them is a reviewed change.
const css = loadCss("positionsgrid.css");

describe("positionsgrid.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("rows: raised data rows (over the zebra), hover, the selected fill; canvas group headers", () => {
    const even = ".cv-positions-grid .cv-positions-grid__row:nth-child(even)";
    expect(find(css.normal, even, "background")).toContain("var(--color-surface-raised)");
    expect(
      find(css.normal, ".cv-positions-grid .cv-positions-grid__row:hover", "background"),
    ).toContain("var(--color-surface-hover)");
    expect(
      find(
        css.normal,
        '.cv-positions-grid .cv-positions-grid__row[aria-selected="true"]',
        "background",
      ),
    ).toContain("var(--color-surface-selected)");
    expect(
      find(css.normal, ".cv-positions-grid .cv-positions-grid__group", "background"),
    ).toContain("var(--color-surface-canvas)");
  });

  it("data rows: a border.subtle hairline drawn inside the cells, so a row keeps its height (D02 §12)", () => {
    const rule = find(
      css.normal,
      ".cv-positions-grid .cv-positions-grid__row > .cv-table__cell",
      "box-shadow",
    );
    expect(rule).toContain(
      "box-shadow: inset 0 calc(var(--border-hairline) * -1 * 1px) 0 0 var(--color-border-subtle)",
    );
    expect(rule).not.toMatch(/(^|[\s;])(border[\w-]*|block-size|padding[\w-]*)\s*:/);
  });

  it("column headers: canvas, text.secondary over a border.default rule, the sorted one text.primary (D02 §12)", () => {
    const header = find(css.normal, ".cv-positions-grid .cv-table__header", "background");
    expect(header).toContain("background: var(--color-surface-canvas)");
    expect(header).toContain("color: var(--color-text-secondary)");
    expect(header).toContain("border-block-end-color: var(--color-border-default)");
    for (const sorted of ["ascending", "descending"])
      expect(
        find(css.normal, `.cv-positions-grid .cv-table__header[aria-sort="${sorted}"]`, "color"),
      ).toContain("var(--color-text-primary)");
  });

  it("numerals: the plain numeric cells in type.num.base with tabular figures, as longhands (D02 §12, D-8)", () => {
    const num = find(css.normal, ".cv-positions-grid .cv-positions-grid__num", "font-family");
    expect(num).toContain("font-family: var(--type-num-base-font-family)");
    expect(num).toContain("font-size: var(--type-num-base-font-size)");
    expect(num).toContain("font-weight: var(--type-num-base-font-weight)");
    expect(num).toContain("line-height: var(--type-num-base-line-height)");
    expect(num).toContain("font-variant-numeric: tabular-nums");
    // The shorthand would reset the tabular figures.
    expect(num).not.toMatch(/(^|[\s;])font:/);
    expect(find(css.normal, ".cv-positions-grid .cv-positions-grid__tier-word", "font")).toContain(
      "var(--type-ui-body-font-family)",
    );
  });

  it("cells: inset.sm compact, inset.md comfortable, inset.xs in the dock", () => {
    expect(find(css.normal, ".cv-positions-grid .cv-table__cell", "padding-inline")).toContain(
      "var(--space-inset-sm)",
    );
    expect(
      find(
        css.normal,
        '.cv-positions-grid[data-density="comfortable"] .cv-table__cell',
        "padding-inline",
      ),
    ).toContain("var(--space-inset-md)");
    expect(
      find(
        css.normal,
        '.cv-positions-grid[data-variant="narrow"] .cv-table__cell',
        "padding-inline",
      ),
    ).toContain("var(--space-inset-xs)");
  });

  it("the tier glyphs take their inks; Critical draws a border.thick × size.icon accent, not the row's height", () => {
    const glyph = (tier: string): string =>
      find(
        css.normal,
        `.cv-positions-grid__liq[data-tier="${tier}"] .cv-positions-grid__tier-glyph`,
        "color",
      );
    expect(glyph("watch")).toContain("var(--color-text-secondary)");
    expect(glyph("near")).toContain("var(--color-status-warning-strong)");
    expect(glyph("critical")).toContain("var(--color-status-danger-strong)");
    const accent = find(
      css.normal,
      '.cv-positions-grid__row[data-liq="critical"] > :first-child::before',
      "background",
    );
    expect(accent).toContain("background: var(--color-status-danger-strong)");
    expect(accent).toContain("inline-size: calc(var(--border-thick) * 1px)");
    expect(accent).toContain("block-size: var(--size-icon-sm)");
    expect(accent).toContain("position: absolute");
    expect(
      find(
        css.normal,
        '.cv-positions-grid[data-density="comfortable"] .cv-positions-grid__row[data-liq="critical"] > :first-child::before',
        "block-size",
      ),
    ).toContain("block-size: var(--size-icon-md)");
    expect(css.normal).not.toContain('[data-liq="critical"] > :first-child {');
  });

  it("the side glyph carries buy and sell; units are text.secondary", () => {
    expect(find(css.normal, '.cv-positions-grid__side-glyph[data-side="long"]', "color")).toContain(
      "var(--color-buy-default)",
    );
    expect(
      find(css.normal, '.cv-positions-grid__side-glyph[data-side="short"]', "color"),
    ).toContain("var(--color-sell-default)");
    expect(find(css.normal, ".cv-positions-grid__unit", "color")).toContain(
      "var(--color-text-secondary)",
    );
  });

  it("the paused chip: control height, neutral.subtle, danger.subtle when critical", () => {
    const chip = find(css.normal, ".cv-positions-grid__paused", "background");
    expect(chip).toContain("min-block-size: var(--size-control-height)");
    expect(chip).toContain("var(--color-neutral-subtle)");
    expect(
      find(css.normal, '.cv-positions-grid__paused[data-tone="critical"]', "background"),
    ).toContain("var(--color-status-danger-subtle)");
  });

  it("forced colours: the accent keeps its fill as CanvasText; the chip and the header a real edge; selection Highlight", () => {
    const accent = find(
      css.forced,
      '.cv-positions-grid__row[data-liq="critical"] > :first-child::before',
      "background",
    );
    expect(accent).toContain("forced-color-adjust: none");
    expect(accent).toContain("background: CanvasText");
    expect(css.all).not.toContain("box-shadow: inset 2px");
    expect(
      find(css.forced, ".cv-positions-grid .cv-table__header", "border-block-end-color"),
    ).toContain("CanvasText");
    // The chip's edge is the hairline token, as the data rows' rule is (border.hairline).
    expect(find(css.forced, ".cv-positions-grid__paused", "border")).toContain(
      "border: calc(var(--border-hairline) * 1px) solid CanvasText",
    );
    expect(
      find(
        css.forced,
        '.cv-positions-grid .cv-positions-grid__row[aria-selected="true"]',
        "background",
      ),
    ).toContain("Highlight");
    expect(css.forced).not.toContain("var(--color");
  });
});
