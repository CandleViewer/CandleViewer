import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("formfield.css");

describe("formfield.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("stacked: the label over the control, space.stack.xs apart", () => {
    const root = find(css.normal, ".cv-formfield", "flex-direction");
    expect(root).toContain("flex-direction: column");
    expect(root).toContain("gap: var(--space-stack-xs)");
  });

  it("inline: a wrapping row, space.field.gap to the control, the host's label column", () => {
    const row = find(css.normal, '.cv-formfield[data-layout="inline"]', "flex-flow");
    expect(row).toContain("flex-flow: row wrap");
    expect(row).toContain("column-gap: var(--space-field-gap)");
    const label = find(
      css.normal,
      '.cv-formfield[data-layout="inline"] > .cv-formfield__label',
      "flex",
    );
    expect(label).toContain("flex: 0 0 var(--cv-formfield-label-width, auto)");
    expect(label).toContain("min-height: var(--size-control-height)");
  });

  it("label: type.ui.label in text.secondary; (optional) in text.tertiary", () => {
    const label = find(css.normal, ".cv-formfield__label", "font");
    expect(label).toContain("--type-ui-label-font-size");
    expect(label).toContain("color: var(--color-text-secondary)");
    expect(find(css.normal, ".cv-formfield__optional", "color")).toContain(
      "var(--color-text-tertiary)",
    );
  });

  it("reason and help: type.ui.caption in text.secondary, space.stack.xs above", () => {
    const line = find(css.normal, ".cv-formfield__line", "font");
    expect(line).toContain("--type-ui-caption-font-size");
    expect(line).toContain("color: var(--color-text-secondary)");
    expect(line).toContain("padding-block-start: var(--space-stack-xs)");
  });

  it("only plain disabled dims, and only the label; T2 never dims, the lines never do", () => {
    expect(css.all).not.toContain("data-gated");
    expect(find(css.normal, ".cv-formfield__line", "opacity")).toBe("");
    expect(
      find(css.normal, ".cv-formfield[data-disabled] > .cv-formfield__label", "opacity"),
    ).toContain("opacity: var(--opacity-disabled)");
  });

  it("the error line is never hidden: it is a pre-rendered live region", () => {
    expect(css.all).not.toMatch(/display: none|visibility: hidden/);
  });

  it("forced colours: label and lines CanvasText, plain disabled GrayText, no token colour", () => {
    expect(find(css.forced, ".cv-formfield__label", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-formfield__line", "color")).toContain("CanvasText");
    const off = find(css.forced, ".cv-formfield[data-disabled] > .cv-formfield__label", "color");
    expect(off).toContain("color: GrayText");
    expect(off).toContain("opacity: 1");
    expect(css.forced).not.toContain("var(--color");
  });
});
