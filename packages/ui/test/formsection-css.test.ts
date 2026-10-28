import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("formsection.css");

describe("formsection.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the fieldset draws no border or padding of its own", () => {
    const root = find(css.normal, ".cv-formsection", "border");
    expect(root).toContain("border: 0");
    expect(root).toContain("padding: 0");
  });

  it("fields space.stack.md apart; sections space.stack.lg apart", () => {
    expect(find(css.normal, ".cv-formsection__body", "gap")).toContain(
      "gap: var(--space-stack-md)",
    );
    expect(find(css.normal, ".cv-formsection + .cv-formsection", "margin-block-start")).toContain(
      "var(--space-stack-lg)",
    );
  });

  it("heading in text.primary; description and notice type.ui.caption in text.secondary", () => {
    expect(find(css.normal, ".cv-formsection__heading", "color")).toContain(
      "var(--color-text-primary)",
    );
    const caption = find(css.normal, ".cv-formsection__notice", "font");
    expect(caption).toContain("--type-ui-caption-font-size");
    expect(caption).toContain("color: var(--color-text-secondary)");
    expect(caption).toContain("padding-block-start: var(--space-stack-xs)");
  });

  it("the disclosure button spans the heading line at least size.control.height tall", () => {
    expect(find(css.normal, ".cv-formsection__toggle", "min-height")).toContain(
      "var(--size-control-height)",
    );
  });

  it("errors within: the danger glyph in status.danger.strong, never colour alone", () => {
    expect(find(css.normal, ".cv-formsection__glyph", "color")).toContain(
      "var(--color-status-danger-strong)",
    );
    expect(find(css.normal, ".cv-formsection__errors", "color")).toContain(
      "var(--color-text-primary)",
    );
  });

  it("a collapsed body leaves the layout (and with it the Tab order)", () => {
    expect(find(css.normal, ".cv-formsection__body[hidden]", "display")).toContain("display: none");
  });

  it("never dims: T2 is not opacity, and plain disabled dims through the fields", () => {
    expect(css.all).not.toContain("opacity");
  });

  it("forced colours: heading, notice and errors CanvasText; glyphs currentcolor; no token colour", () => {
    expect(find(css.forced, ".cv-formsection__heading", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-formsection__notice", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-formsection__toggle", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-formsection__glyph", "color")).toContain("currentcolor");
    expect(css.forced).not.toContain("var(--color");
  });
});
