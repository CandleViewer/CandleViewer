import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("copybutton.css");
const { normal, forced } = css;

describe("copybutton.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("conv. 20: no ring, no dimming and no box of its own; the nested CMP-002 owns them", () => {
    expect(css.all).not.toMatch(/outline|opacity|border|background|width|height/);
  });

  it("copied: the glyph in status.success.default", () => {
    expect(find(normal, '.cv-copy-button[data-state="copied"] svg', "color")).toContain(
      "var(--color-status-success-default)",
    );
  });

  it("failed (E20): the glyph in status.danger.default", () => {
    expect(find(normal, '.cv-copy-button[data-state="failed"] svg', "color")).toContain(
      "var(--color-status-danger-default)",
    );
  });

  it("forced colours: the glyph follows CMP-002's system colour", () => {
    expect(find(forced, ".cv-copy-button[data-state] svg", "color")).toContain("currentcolor");
  });
});
