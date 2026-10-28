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
