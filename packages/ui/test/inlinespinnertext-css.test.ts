import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("inlinespinnertext.css");

describe("inlinespinnertext.css contract", () => {
  // The rotation and its reduced-motion stop are CMP-014's (spinner.css); this file adds no motion.
  itIsTokenOnlyAndStatic(css);

  it("the status row: inset.xs gap, type.ui.body in text.secondary", () => {
    const row = find(css.normal, ".cv-inline-spinner-text__status", "gap");
    expect(row).toContain("gap: var(--space-inset-xs)");
    expect(row).toContain("--type-ui-body-font-size");
    expect(row).toContain("color: var(--color-text-secondary)");
  });

  it("the nested spinner's arc in color.action.primary.default", () => {
    expect(find(css.normal, ".cv-inline-spinner-text__status > .cv-spinner", "color")).toContain(
      "var(--color-action-primary-default)",
    );
  });

  it("Cancel sits inset.sm after the text; the text wraps after the spinner", () => {
    expect(find(css.normal, ".cv-inline-spinner-text", "gap")).toContain(
      "gap: var(--space-inset-sm)",
    );
    expect(find(css.normal, ".cv-inline-spinner-text__label", "overflow-wrap")).toContain(
      "min-width: 0",
    );
  });

  it("forced colours: CanvasText words, the arc currentColor of CanvasText", () => {
    const body = find(css.forced, ".cv-inline-spinner-text__status > .cv-spinner", "color");
    expect(body).toContain("color: CanvasText");
    expect(css.forced).not.toMatch(/forced-color-adjust/);
  });
});
