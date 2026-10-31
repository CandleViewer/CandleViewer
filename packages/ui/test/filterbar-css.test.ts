import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("filterbar.css");

describe("filterbar.css contract (E29-D04 §2.8.5)", () => {
  itIsTokenOnlyAndStatic(css);

  it("lays the chips, the add control and Clear all out in a wrapping row at the toolbar gap", () => {
    const body = find(css.normal, ".cv-filter-bar", "display");
    expect(body).toContain("display: flex");
    expect(body).toContain("flex-wrap: wrap");
    expect(body).toContain("gap: var(--space-stack-sm)");
    // `15`'s space.filterbar.* is not a shipped token.
    expect(css.all).not.toContain("--space-filterbar");
  });

  it("draws nothing of its own: no fill, border or colour (the chips and buttons draw themselves)", () => {
    expect(css.normal).not.toMatch(/background|border|color:/);
  });
});
