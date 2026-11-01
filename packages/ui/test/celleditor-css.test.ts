import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("celleditor.css");

describe("celleditor.css contract (E29-D02 §7; E09-D09 §2.2)", () => {
  itIsTokenOnlyAndStatic(css);

  it("draws the open editor as the cell with a 2px color.focus.ring border (D02 §7)", () => {
    const root = find(css.normal, ".cv-cell-editor", "--cv-cell-editor-bw");
    expect(root).toContain("--cv-cell-editor-bw: calc(var(--border-thick) * 1px)");
    const open = find(
      css.normal,
      ".cv-cell-editor[data-editing] > .cv-cell-editor__well",
      "border-color",
    );
    expect(open).toContain("border-color: var(--color-focus-ring)");
  });

  it("sets the digits in tabular type.num.base, right-aligned, and never truncates them", () => {
    const input = find(css.normal, ".cv-cell-editor__input", "font-variant-numeric");
    expect(input).toContain("font-family: var(--type-num-base-font-family)");
    expect(input).toContain("font-variant-numeric: tabular-nums");
    expect(input).toContain("text-align: end");
    expect(css.normal).not.toMatch(/text-overflow:\s*ellipsis/);
  });

  it("marks a refused value with the danger boundary, at the same width", () => {
    const refused = find(
      css.normal,
      ".cv-cell-editor[data-invalid] > .cv-cell-editor__well",
      "border-color",
    );
    expect(refused).toContain("border-color: var(--color-status-danger-default)");
  });

  it("draws T2 in color.text.tertiary, never opacity.disabled or color.text.disabled (G-T2.2)", () => {
    const gated = find(css.normal, ".cv-cell-editor[data-gated] .cv-cell-editor__input", "color");
    expect(gated).toContain("color: var(--color-text-tertiary)");
    expect(gated).not.toMatch(/opacity|text-disabled/);
    expect(find(css.normal, ".cv-cell-editor__lock", "color")).toContain(
      "var(--color-text-tertiary)",
    );
  });

  it("keeps every state in forced colours: Highlight while open, FieldText for a gated value", () => {
    expect(
      find(css.forced, ".cv-cell-editor[data-editing] > .cv-cell-editor__well", "border-color"),
    ).toContain("Highlight");
    expect(
      find(css.forced, ".cv-cell-editor[data-invalid] > .cv-cell-editor__well", "border-color"),
    ).toContain("FieldText");
    expect(
      find(css.forced, ".cv-cell-editor[data-gated] .cv-cell-editor__input", "color"),
    ).toContain("FieldText");
    expect(
      find(css.forced, ".cv-cell-editor[data-disabled] .cv-cell-editor__input", "color"),
    ).toContain("GrayText");
  });
});
