import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("splitbutton.css");
const button = loadCss("button.css");

/** A selector's class and attribute count: no ids or types here, and both sides share the `:is()` list. */
function weight(selector: string): number {
  return (selector.match(/\.[\w-]+|\[[^\]]+\]|:(?!is|not)[\w-]+/g) ?? []).length;
}

describe("splitbutton.css contract (E29-D04 §2.8.4)", () => {
  itIsTokenOnlyAndStatic(css);

  it("joins the halves along a hairline seam with square inner corners", () => {
    const root = find(css.normal, ".cv-split-button", "display");
    expect(root).toContain("display: inline-flex");
    expect(root).toContain("gap: calc(var(--border-hairline) * 1px)");
    expect(find(css.normal, ".cv-split-button > .cv-button", "border-start-end-radius")).toContain(
      "border-end-end-radius: 0",
    );
    expect(
      find(css.normal, ".cv-split-button > .cv-icon-button", "border-start-start-radius"),
    ).toContain("border-end-start-radius: 0");
  });

  it("busy keeps the label and its leading glyph visible and never shows a turning spinner", () => {
    const keep =
      '.cv-split-button > .cv-button[aria-busy="true"]:not([data-side]) > :is(.cv-button__label, .cv-button__icon)';
    expect(find(css.normal, keep, "opacity")).toContain("opacity: 1");
    expect(
      find(css.normal, '.cv-split-button > .cv-button[aria-busy="true"] > .cv-spinner', "display"),
    ).toContain("display: none");
  });

  it("out-weighs CMP-001's loading rule rather than relying on file order", () => {
    const hide =
      '.cv-button[aria-busy="true"]:not([data-side]) > :is(.cv-button__label, .cv-button__icon)';
    expect(find(button.normal, hide, "opacity")).toContain("opacity: 0");
    const keep = `.cv-split-button > ${hide}`;
    expect(weight(keep)).toBeGreaterThan(weight(hide));
  });

  it("adds no T2 look of its own: a gated half keeps CMP-001's and CMP-002's", () => {
    expect(css.all).not.toMatch(/data-gated|aria-disabled/);
  });
});
