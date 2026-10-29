import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("table.css");

describe("table.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the header row sticks to the region's top on surface.hover, with the border.subtle rule", () => {
    const header = find(css.normal, ".cv-table__header", "position");
    expect(header).toContain("position: sticky");
    expect(header).toContain("inset-block-start: 0");
    expect(header).toContain("background: var(--color-surface-hover)");
    expect(header).toContain(
      "border-block-end: calc(var(--border-hairline) * 1px) solid var(--color-border-subtle)",
    );
    expect(find(css.normal, ".cv-table__table", "border-collapse")).toContain(
      "border-collapse: separate",
    );
  });

  it("zebra rows: odd canvas, even raised, hover on surface.hover", () => {
    expect(find(css.normal, ".cv-table__row", "background")).toContain("--color-surface-canvas");
    expect(find(css.normal, ".cv-table__row:nth-child(even)", "background")).toContain(
      "--color-surface-raised",
    );
    expect(find(css.normal, ".cv-table__row:hover", "background")).toContain(
      "--color-surface-hover",
    );
  });

  it("rows take size.row.height; cells never use text.tertiary", () => {
    expect(find(css.normal, ".cv-table__cell", "block-size")).toContain("var(--size-row-height)");
    expect(find(css.normal, ".cv-table__cell", "color")).toContain("--color-text-primary");
    expect(find(css.normal, ".cv-table__cell", "color")).not.toContain("tertiary");
  });

  it("text cells truncate with an ellipsis; numeric cells end-align and never wrap", () => {
    const text = find(css.normal, ".cv-table__text", "text-overflow");
    expect(text).toContain("text-overflow: ellipsis");
    expect(text).toContain("white-space: nowrap");
    expect(text).toContain("overflow: hidden");
    const numeric = find(css.normal, ".cv-table__cell[data-numeric]", "text-align");
    expect(numeric).toContain("text-align: end");
    expect(numeric).toContain("white-space: nowrap");
  });

  it("the scroll region scrolls and draws the inset focus ring", () => {
    expect(find(css.normal, ".cv-table__region", "overflow")).toContain("overflow: auto");
    expect(find(css.normal, ".cv-table__region:focus-visible", "outline")).toContain(
      "var(--color-focus-ring)",
    );
  });

  it("grid mode: a body cell's scroll margin is the header row's height, so focus never hides under it", () => {
    expect(find(css.normal, ".cv-table__cell", "scroll-margin-block-start")).toContain(
      "scroll-margin-block-start: var(--size-row-height)",
    );
    expect(find(css.normal, ".cv-table__header", "block-size")).toContain(
      "block-size: var(--size-row-height)",
    );
    // The header's select box is held to the row height, so the header row stays one row tall.
    expect(find(css.normal, ".cv-table__select .cv-choice", "min-block-size")).toContain(
      "var(--size-row-height)",
    );
  });

  it("selected rows take action.selected, over the zebra and hover; Highlight in forced colours", () => {
    const selected = find(css.normal, '.cv-table__row[aria-selected="true"]', "background");
    expect(selected).toContain("var(--color-action-selected)");
    expect(find(css.normal, '.cv-table__row[aria-selected="true"]:hover', "background")).toContain(
      "var(--color-action-selected)",
    );
    expect(find(css.forced, '.cv-table__row[aria-selected="true"]', "background")).toContain(
      "Highlight",
    );
  });

  it("the select box's label is clipped, never display: none, so it still names the box", () => {
    const label = find(css.normal, ".cv-table__select .cv-choice__label", "clip-path");
    expect(label).toContain("clip-path: inset(50%)");
    expect(label).not.toContain("display: none");
  });

  it("forced colours: CanvasText header and row rules, a Highlight ring, the glyph currentColor", () => {
    expect(find(css.forced, ".cv-table__header", "border-block-end")).toContain("CanvasText");
    expect(find(css.forced, ".cv-table__row .cv-table__cell", "border-block-end")).toContain(
      "CanvasText",
    );
    expect(find(css.forced, ".cv-table__region:focus-visible", "outline-color")).toContain(
      "Highlight",
    );
    expect(find(css.forced, ".cv-table__sort-glyph", "color")).toContain("currentColor");
    expect(css.forced).not.toContain("var(--color");
  });
});
