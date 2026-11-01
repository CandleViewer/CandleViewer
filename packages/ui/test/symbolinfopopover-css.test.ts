import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("symbolinfopopover.css");

describe("symbolinfopopover.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("text wraps at 200 % zoom (R1) and never takes the disabled colour", () => {
    expect(find(css.normal, ".cv-symbol-info__message", "overflow-wrap")).toContain("anywhere");
    expect(css.all).not.toMatch(/text-disabled|opacity/);
  });

  it("forced colours: the message text is CanvasText (R2)", () => {
    expect(css.forced).toContain("color: CanvasText");
  });
});
