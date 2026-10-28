import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("searchbox.css");
const CLEAR = ".cv-searchbox .cv-field > .cv-icon-button";

describe("searchbox.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the clear button sits flush with the well's end, under its boundary", () => {
    const clear = find(css.normal, CLEAR, "margin-block");
    expect(clear).toContain("margin-block: calc(var(--cv-field-bw) * -1)");
    expect(clear).toContain("margin-inline-end: calc(var(--cv-field-bw) * -1)");
    expect(clear).toContain("background-clip: padding-box");
  });

  it("hides the native clear control: the component draws its own named button", () => {
    expect(
      find(
        css.normal,
        ".cv-searchbox .cv-field__input::-webkit-search-cancel-button",
        "appearance",
      ),
    ).toContain("appearance: none");
  });

  it("forced colours: the clear glyph ButtonText, GrayText when disabled; no token colour", () => {
    expect(find(css.forced, CLEAR, "color")).toContain("ButtonText");
    expect(
      find(css.forced, ".cv-searchbox .cv-field[data-disabled] > .cv-icon-button", "color"),
    ).toContain("GrayText");
    expect(css.forced).not.toContain("var(--color");
  });
});
