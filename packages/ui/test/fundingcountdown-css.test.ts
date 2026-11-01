import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("fundingcountdown.css");
const { normal, forced } = css;

describe("fundingcountdown.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the under-5-minutes glyph takes color.status.warning.strong", () => {
    expect(find(normal, ".cv-funding__warn", "color")).toContain("--color-status-warning-strong");
  });

  it("the rate takes buy, sell and neutral by its sign attribute, on its own text only", () => {
    expect(find(normal, '.cv-funding .cv-funding__rate[data-sign="positive"]', "color")).toContain(
      "--color-buy-default",
    );
    expect(find(normal, '.cv-funding .cv-funding__rate[data-sign="negative"]', "color")).toContain(
      "--color-sell-default",
    );
  });

  it("never uses the disabled colour or opacity (G-T2.2)", () => {
    expect(css.all).not.toMatch(/text-disabled|opacity/);
  });

  it("sentences wrap rather than clip at 200 % zoom (R1)", () => {
    expect(find(normal, ".cv-funding__note", "overflow-wrap")).toContain("anywhere");
  });

  it("forced colours: every colour carrier is CanvasText (R2)", () => {
    expect(forced).toContain("color: CanvasText");
    expect(forced).toContain(".cv-funding__warn");
    expect(forced).toContain(".cv-funding .cv-funding__rate");
  });
});
