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

  it("the active row (aria-current): the selected fill, and a 2 px border.selected bar on its first cell", () => {
    expect(find(css.normal, '.cv-table__row[aria-current="true"]', "background")).toContain(
      "var(--color-surface-selected)",
    );
    expect(
      find(css.normal, '.cv-table__row[aria-current="true"] > :first-child', "box-shadow"),
    ).toContain("inset calc(var(--border-thick) * 1px) 0 0 0 var(--color-border-selected)");
    expect(
      find(css.forced, '.cv-table__row[aria-current="true"] > :first-child', "border-inline-start"),
    ).toContain("Highlight");
  });

  it("a T2 sort header: label and lock in text.tertiary, not-allowed; never text.disabled or opacity", () => {
    const gated = find(css.normal, '.cv-table__sort[aria-disabled="true"]', "color");
    expect(gated).toContain("var(--color-text-tertiary)");
    expect(gated).toContain("cursor: not-allowed");
    expect(css.all).not.toMatch(/text-disabled|opacity/);
    expect(find(css.normal, ".cv-table__lock", "display")).toContain("inline-flex");
  });

  it("a header status glyph trails the label; the stale tone takes the stale indicator", () => {
    expect(find(css.normal, '.cv-table__header-status[data-tone="stale"]', "color")).toContain(
      "var(--color-data-confidence-stale-indicator)",
    );
  });

  it("a header's label is a block that shrinks and ellipsises, never a clipped run (E08-D07 §4.1)", () => {
    const label = find(css.normal, ".cv-table__label", "text-overflow");
    expect(label).toContain("display: block");
    expect(label).toContain("min-inline-size: 0");
    expect(label).toContain("overflow: hidden");
    expect(label).toContain("text-overflow: ellipsis");
    expect(label).toContain("white-space: nowrap");
    // A plain header lays its label and status glyph out as the sort button does: one line, end-aligned if numeric.
    const head = find(css.normal, ".cv-table__head", "display");
    expect(head).toContain("display: flex");
    expect(head).toContain("min-inline-size: 0");
    expect(
      find(css.normal, ".cv-table__header[data-numeric] .cv-table__head", "justify-content"),
    ).toContain("justify-content: flex-end");
  });

  // E08-D07 §4.1's 784 px reference, the orchestrator's interim ruling (2026-10-31): an end-aligned header's words sit
  // against its end, where the values' end padding lines them up, so its start padding is no alignment edge and the
  // label takes it as room. No copy, breakpoint or column width change; a start-aligned header, the stacked reflow and
  // the end padding keep what they had. (The lasting answer, shorter headers or a wider reference, is E08-D07's.)
  describe("an end-aligned header uses its start padding as room (E08-D07 §4.1, interim)", () => {
    const header = '.cv-table:not([data-layout="stacked"]) .cv-table__header[data-numeric]';
    const sort = `${header} .cv-table__sort`;
    const start = (body: string): string => body.replace("padding-inline-start: 0", "");
    /** The selectors of every rule that sets `prop`, as `find` reads a selector list. */
    const settersOf = (prop: string): string[] =>
      [...css.normal.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
        .filter((rule) => new RegExp(`(^|[\\s;])${prop}\\s*:`).test(rule[2] ?? ""))
        .flatMap((rule) =>
          (rule[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
        );

    it("a plain end-aligned header gives its label its start padding and keeps its end padding", () => {
      const rule = find(css.normal, header, "padding-inline-start");
      expect(rule).toContain("padding-inline-start: 0");
      // Nothing else of its padding moves: the end side stays the token the values' cells use.
      expect(start(rule)).not.toContain("padding");
    });

    it("an end-aligned sort button gives its label its start padding and keeps its end padding", () => {
      const rule = find(css.normal, sort, "padding-inline-start");
      expect(rule).toContain("padding-inline-start: 0");
      expect(start(rule)).not.toContain("padding");
    });

    it("the end padding that is kept is the cells' own, so a header's words still end where its values end", () => {
      const padding = (selector: string): string | undefined =>
        /(^|[\s;])padding\s*:\s*([^;]+);/.exec(find(css.normal, selector, "padding"))?.[2]?.trim();
      const both = "0 var(--space-inset-sm)";
      expect(padding(".cv-table__header")).toBe(both);
      expect(padding(".cv-table__sort")).toBe(both);
      expect(padding(".cv-table__cell")).toBe(both);
    });

    it("no other rule moves a start padding: start-aligned headers and the stacked reflow keep both", () => {
      // Both rules are scoped out of the stacked reflow, where headers wrap as blocks and none is end-aligned.
      expect(settersOf("padding-inline-start")).toEqual([header, sort]);
      expect(settersOf("padding-left")).toEqual([]);
      expect(settersOf("padding-inline")).toEqual([]);
    });
  });

  it("spacer rows hold the undrawn rows' height and nothing else", () => {
    const spacer = find(css.normal, ".cv-table__spacer > td", "padding");
    expect(spacer).toContain("padding: 0");
    expect(spacer).toContain("border: 0");
    expect(find(css.normal, ".cv-table__spacer", "background")).toContain("transparent");
  });
});
