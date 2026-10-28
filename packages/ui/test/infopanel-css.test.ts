// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("infopanel.css");

describe("infopanel.css contract (CMP-069)", () => {
  itIsTokenOnlyAndStatic(css);

  it("the inline form: a decorative default hairline above it, padded space.inset.sm (conventions 44)", () => {
    const inline = find(css.normal, '.cv-info-panel[data-variant="inline"]', "border-top");
    expect(inline).toContain(
      "border-top: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(inline).toContain("padding: var(--space-inset-sm)");
  });

  it("the title is type.ui.heading-sm and the body type.ui.body, in color.text.primary", () => {
    expect(find(css.normal, ".cv-info-panel__title", "font")).toContain(
      "var(--type-ui-heading-sm-font-size)",
    );
    const panel = find(css.normal, ".cv-info-panel", "font");
    expect(panel).toContain("var(--type-ui-body-font-size)");
    expect(panel).toContain("color: var(--color-text-primary)");
  });

  it("forced colours: the inline hairline is CanvasText", () => {
    expect(find(css.forced, '.cv-info-panel[data-variant="inline"]', "border-top-color")).toContain(
      "border-top-color: CanvasText",
    );
    expect(css.forced).not.toMatch(/var\(--color/);
  });
});
