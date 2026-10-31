import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("columnpicker.css");

// CMP-056's list rows: the boxes and buttons are CMP-005's and CMP-002's; this file lays the rows out.
describe("columnpicker.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("a plain list, one row per column at least a row high, its move buttons together at the end", () => {
    expect(find(css.normal, ".cv-colpicker__list", "list-style")).toContain("list-style: none");
    expect(find(css.normal, ".cv-colpicker__item", "min-block-size")).toContain(
      "var(--size-row-height)",
    );
    expect(find(css.normal, ".cv-colpicker__moves", "flex")).toContain("flex: none");
  });

  it("a locked row's reason (2a) wraps under its box, indented to the label, in a caption line", () => {
    expect(find(css.normal, ".cv-colpicker__item", "flex-wrap")).toContain("flex-wrap: wrap");
    const reason = find(css.normal, ".cv-colpicker__reason", "color").replace(/\s+/g, " ");
    expect(reason).toContain("flex: 1 0 100%");
    expect(reason).toContain(
      "padding-inline-start: calc(var(--size-control-height) + var(--space-field-gap))",
    );
    expect(reason).toContain("var(--type-ui-caption-font-size)");
  });

  it("binds one colour, the reason's text.secondary (E09-D09 §2.2): CanvasText in forced colours", () => {
    expect(css.normal.match(/var\(--color-[\w-]+\)/g)).toEqual(["var(--color-text-secondary)"]);
    expect(find(css.forced, ".cv-colpicker__reason", "color")).toContain("CanvasText");
  });
});
