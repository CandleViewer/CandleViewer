import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const list = loadCss("fuzzylist.css");
const search = loadCss("symbolsearch.css");

describe("fuzzylist.css contract (CMP-213, E08-D05 §6.1)", () => {
  itIsTokenOnlyAndStatic(list);

  it("every row is one size.row.height, so the window counts rows; the list is the visible rows tall", () => {
    expect(find(list.normal, ".cv-fuzzylist__row", "block-size")).toContain(
      "block-size: var(--size-row-height)",
    );
    expect(find(list.normal, ".cv-fuzzylist__header", "block-size")).toContain(
      "block-size: var(--size-row-height)",
    );
    expect(find(list.normal, ".cv-fuzzylist__list", "max-block-size")).toContain(
      "calc(var(--cv-fuzzylist-rows, 8) * var(--size-row-height))",
    );
  });

  it("the match is weight and tone, semibold primary over secondary, with no mark fill", () => {
    const match = find(list.normal, ".cv-fuzzylist__match", "font-weight");
    expect(match).toContain("font-weight: var(--font-weight-semibold)");
    expect(match).toContain("color: var(--color-text-primary)");
    expect(match).toContain("background: none");
    expect(find(list.normal, ".cv-fuzzylist__row", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
  });

  it("active: the selected fill and a border.thick border.selected bar; hover tints, light's interim fill", () => {
    const active = find(list.normal, ".cv-fuzzylist__row[data-active]", "background");
    expect(active).toContain("background: var(--color-surface-selected)");
    expect(active).toContain("border-inline-start-color: var(--color-border-selected)");
    expect(find(list.normal, ".cv-fuzzylist__row", "border-inline-start")).toContain(
      "calc(var(--border-thick) * 1px) solid transparent",
    );
    expect(find(list.normal, ".cv-fuzzylist__row:hover", "background")).toContain(
      "var(--color-surface-hover)",
    );
    expect(
      find(list.normal, ':root[data-theme="light"] .cv-fuzzylist__row:hover', "background"),
    ).toContain("var(--color-surface-selected)");
  });

  it("delisted: struck in the delisted text, the chip's glyph the delisted indicator; skeleton static", () => {
    const label = find(
      list.normal,
      ".cv-fuzzylist__row[data-delisted] .cv-fuzzylist__label",
      "color",
    );
    expect(label).toContain("color: var(--color-data-confidence-delisted-text)");
    expect(label).toContain("text-decoration: line-through");
    expect(
      find(list.normal, ".cv-fuzzylist__row[data-delisted] .cv-fuzzylist__chip", "--cv-tag-glyph"),
    ).toContain("var(--color-data-confidence-delisted-indicator)");
    expect(
      find(list.normal, ".cv-fuzzylist__skeleton .cv-skeleton__block::after", "content"),
    ).toContain("content: none");
  });

  it("forced colours: the active row is Highlight with a HighlightText bar; no token colour survives", () => {
    const active = find(list.forced, ".cv-fuzzylist__row[data-active]", "background");
    expect(active).toContain("background: Highlight");
    expect(active).toContain("border-inline-start-color: HighlightText");
    expect(find(list.forced, ".cv-fuzzylist__row:hover", "background")).toContain("Canvas");
    expect(list.forced).not.toMatch(/var\(--/);
  });
});

describe("symbolsearch.css contract (CMP-160, E08-D05 D-10)", () => {
  itIsTokenOnlyAndStatic(search);

  it("the ARMED pill is E30-D02's: text.primary on warning.subtle, a warning.strong hairline and glyph", () => {
    const pill = find(search.normal, ".cv-symbolsearch__armed", "background");
    expect(pill).toContain("background: var(--color-status-warning-subtle)");
    expect(pill).toContain("color: var(--color-text-primary)");
    expect(pill).toContain("solid var(--color-status-warning-strong)");
    expect(find(search.normal, ".cv-symbolsearch__armed > svg", "color")).toContain(
      "color: var(--color-status-warning-strong)",
    );
    expect(search.forced).not.toMatch(/var\(--/);
  });
});
