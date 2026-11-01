import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("celleditor.css");

describe("celleditor.css contract (E29-D02 §7; E09-D09 §2.2)", () => {
  itIsTokenOnlyAndStatic(css);

  it("draws the open editor as the cell with a 2px color.focus.ring border at border.focus (D02 §7)", () => {
    const root = find(css.normal, ".cv-cell-editor", "--cv-cell-editor-bw");
    expect(root).toContain("--cv-cell-editor-bw: calc(var(--border-focus) * 1px)");
    const open = find(
      css.normal,
      ".cv-cell-editor[data-editing] > .cv-cell-editor__well",
      "border-color",
    );
    expect(open).toContain("border-color: var(--color-focus-ring)");
  });

  it("fills the cell at the density's control height (D04H §B, DR-9)", () => {
    expect(find(css.normal, ".cv-cell-editor", "display")).toContain("display: flex");
    const well = find(css.normal, ".cv-cell-editor__well", "min-block-size");
    expect(well).toContain("min-block-size: var(--size-control-height)");
  });

  it("sets the digits in tabular type.num.base, right-aligned, and never truncates them", () => {
    const input = find(css.normal, ".cv-cell-editor__input", "font-variant-numeric");
    expect(input).toContain("font-family: var(--type-num-base-font-family)");
    expect(input).toContain("font-variant-numeric: tabular-nums");
    expect(input).toContain("text-align: end");
    expect(css.normal).not.toMatch(/text-overflow:\s*ellipsis/);
  });

  it("marks a refused value with the danger boundary at the same width, the focus ring kept outside it", () => {
    const refused = find(
      css.normal,
      ".cv-cell-editor[data-invalid] > .cv-cell-editor__well",
      "border-color",
    );
    expect(refused).toContain("border-color: var(--color-status-danger-default)");
    expect(refused).toContain("outline: var(--cv-cell-editor-bw) solid var(--color-focus-ring)");
  });

  it("keeps a T2 value's own look: no colour, no dimming on the gated value (E29-D04 §4.1)", () => {
    const gated = ".cv-cell-editor[data-gated] .cv-cell-editor__input";
    expect(find(css.normal, gated, "cursor")).toContain("cursor: not-allowed");
    expect(find(css.normal, gated, "color")).toBe("");
    expect(find(css.normal, gated, "opacity")).toBe("");
    expect(css.all).not.toMatch(/text-disabled/);
  });

  it("draws a re-shown reason 2a: the lock tertiary, the reason secondary, never dimmed (G-T2.2)", () => {
    expect(find(css.normal, ".cv-cell-editor__lock", "color")).toContain(
      "color: var(--color-text-tertiary)",
    );
    const reason = find(css.normal, ".cv-cell-editor__reason[data-shown]", "color");
    expect(reason).toContain("color: var(--color-text-secondary)");
    expect(reason).not.toMatch(/opacity/);
  });

  it("lays the note over the rows below, out of the flow, on CMP-016's surface (D01 D13 b)", () => {
    const note = find(css.normal, ".cv-cell-editor__note", "position");
    expect(note).toContain("position: absolute");
    expect(note).toContain("inset-block-start: 100%");
    expect(note).toContain("pointer-events: none");
    expect(note).toContain("background: var(--color-surface-overlay)");
    expect(note).toContain("box-shadow: var(--elevation-popover)");
    expect(note).toContain("border-radius: var(--radius-card)");
    expect(note).toContain("solid var(--color-border-default)");
    expect(note).toContain("max-width: min(20rem");
    expect(note).toContain("var(--type-ui-caption-font-size)");
    expect(find(css.normal, ".cv-cell-editor", "position")).toContain("position: relative");
  });

  it("keeps the live value in type.num.sm's tabular figures, so its digits line up with the cell's", () => {
    const live = find(css.normal, ".cv-cell-editor__live", "font-family");
    expect(live).toContain("font-family: var(--type-num-sm-font-family)");
    expect(live).toContain("font-variant-numeric: tabular-nums");
  });

  it("keeps every state in forced colours: Highlight while open and for the ring, the note's edge", () => {
    expect(
      find(css.forced, ".cv-cell-editor[data-editing] > .cv-cell-editor__well", "border-color"),
    ).toContain("Highlight");
    const refused = find(
      css.forced,
      ".cv-cell-editor[data-invalid] > .cv-cell-editor__well",
      "border-color",
    );
    expect(refused).toContain("FieldText");
    expect(refused).toContain("outline-color: Highlight");
    expect(find(css.forced, ".cv-cell-editor__note", "border-color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-cell-editor__lock", "color")).toContain("CanvasText");
    expect(
      find(css.forced, ".cv-cell-editor[data-disabled] .cv-cell-editor__input", "color"),
    ).toContain("GrayText");
  });
});
