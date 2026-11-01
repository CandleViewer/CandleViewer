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

  it("the tier glyphs take their inks, the words text.primary; Critical draws a border.thick accent", () => {
    const glyph = (tier: string): string =>
      find(
        css.normal,
        `.cv-positions-grid__liq[data-tier="${tier}"] .cv-positions-grid__tier-glyph`,
        "color",
      );
    expect(glyph("watch")).toContain("var(--color-text-secondary)");
    expect(glyph("near")).toContain("var(--color-status-warning-strong)");
    expect(glyph("critical")).toContain("var(--color-status-danger-strong)");
    expect(
      find(css.normal, '.cv-positions-grid__row[data-liq="critical"] > :first-child', "box-shadow"),
    ).toContain("inset calc(var(--border-thick) * 1px) 0 0 0 var(--color-status-danger-strong)");
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

  it("forced colours: the accent and the chip keep a real edge; the selected row takes Highlight", () => {
    expect(
      find(css.forced, '.cv-positions-grid__row[data-liq="critical"] > :first-child', "box-shadow"),
    ).toContain("CanvasText");
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
