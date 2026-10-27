import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("countdown.css");
const { normal, forced } = css;

describe("countdown.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the digits take the host sentence's colour, with no colour step at a threshold (J1 (b))", () => {
    expect(find(normal, ".cv-countdown .cv-countdown__digits", "color")).toContain(
      "color: inherit",
    );
    expect(css.all).not.toMatch(/data-phase|--color-status/);
  });

  it("the count never splits across lines", () => {
    expect(find(normal, ".cv-countdown", "white-space")).toContain("white-space: nowrap");
  });

  it("forced colours: CanvasText digits", () => {
    expect(find(forced, ".cv-countdown .cv-countdown__digits", "color")).toContain(
      "color: CanvasText",
    );
  });
});
