import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("watchlisttabs.css");

// CMP-162's header row (E08-D07 §4.1, D4): the tabs are CMP-042's; this file lays the row out.
describe("watchlisttabs.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the strip's width never follows its content, so a wider row brings tabs back from More lists", () => {
    const strip = find(css.normal, ".cv-wltabs__strip", "flex");
    expect(strip).toContain("flex: 1 1 0");
    expect(strip).toContain("min-inline-size: 0");
    expect(find(css.normal, ".cv-wltabs__list", "flex-wrap")).toContain("flex-wrap: nowrap");
  });

  it("R1 / D30: the row wraps its end group (the panel status, ⋮) at 200 % rather than overflow; + stays whole", () => {
    expect(find(css.normal, ".cv-wltabs__bar", "flex-wrap")).toContain("flex-wrap: wrap");
    const end = find(css.normal, ".cv-wltabs__end", "flex-wrap");
    expect(end).toContain("flex-wrap: wrap");
    expect(end).toContain("min-inline-size: 0");
    expect(end).not.toMatch(/flex:\s*none/);
    expect(find(css.normal, ".cv-wltabs__create", "flex")).toMatch(/flex:\s*none/);
  });

  it("the measured copies are out of the flow, never seen and never a pointer target", () => {
    const ghosts = find(css.normal, ".cv-wltabs__measure", "visibility");
    expect(ghosts).toContain("position: absolute");
    expect(ghosts).toContain("visibility: hidden");
    expect(ghosts).toContain("pointer-events: none");
  });

  it("the row's rule is border.default; CanvasText in forced colours", () => {
    expect(find(css.normal, ".cv-wltabs__bar", "border-block-end")).toContain(
      "var(--color-border-default)",
    );
    expect(find(css.forced, ".cv-wltabs__bar", "border-block-end")).toContain("CanvasText");
  });
});
