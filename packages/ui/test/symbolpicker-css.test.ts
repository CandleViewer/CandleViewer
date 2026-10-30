import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("symbolpicker.css");
const TRIGGER = ".cv-symbolpicker__trigger";

describe("symbolpicker.css contract (CMP-219, E08-D05 B02)", () => {
  itIsTokenOnlyAndStatic(css);

  it("the trigger: a hairline border.default edge, radius.control, text.primary; the value type.num.base, whole", () => {
    const trigger = find(css.normal, TRIGGER, "border");
    expect(trigger).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(trigger).toContain("border-radius: var(--radius-control)");
    expect(trigger).toContain("color: var(--color-text-primary)");
    expect(trigger).toContain("padding-inline: var(--space-inset-sm)");
    const value = find(css.normal, ".cv-symbolpicker__value", "font");
    expect(value).toContain("var(--type-num-base-font-family)");
    expect(value).toContain("white-space: nowrap");
    expect(value).toContain("flex: none");
    expect(css.all).not.toMatch(/ellipsis|font\.mono|--font-mono/);
  });

  it("hover tints; a press and the expanded state take the selected fill (B02)", () => {
    expect(find(css.normal, `${TRIGGER}:hover`, "background")).toContain(
      "var(--color-surface-hover)",
    );
    for (const state of [`${TRIGGER}:active`, `${TRIGGER}[aria-expanded="true"]`])
      expect(find(css.normal, state, "background")).toContain("var(--color-surface-selected)");
  });

  it("comfortable widens the padding to inset.md, here or on an ancestor; the root's own compact wins", () => {
    expect(find(css.normal, `[data-density="comfortable"] ${TRIGGER}`, "padding-inline")).toContain(
      "var(--space-inset-md)",
    );
    expect(
      find(css.normal, `.cv-symbolpicker[data-density="compact"] ${TRIGGER}`, "padding-inline"),
    ).toContain("var(--space-inset-sm)");
  });

  it("delisted: the value struck in the delisted text; the chip's ⊘ in the delisted indicator", () => {
    const value = find(css.normal, `${TRIGGER}[data-delisted] .cv-symbolpicker__value`, "color");
    expect(value).toContain("color: var(--color-data-confidence-delisted-text)");
    expect(value).toContain("text-decoration: line-through");
    expect(
      find(
        css.normal,
        '.cv-symbolpicker__chip[data-marker="delisted"] .cv-symbolpicker__glyph',
        "color",
      ),
    ).toContain("var(--color-data-confidence-delisted-indicator)");
  });

  it("the chip: caption type in text.secondary; the dot an 8 px circle, hollow, filled while recording", () => {
    const chip = find(css.normal, ".cv-symbolpicker__chip", "font");
    expect(chip).toContain("var(--type-ui-caption-font-size)");
    expect(chip).toContain("color: var(--color-text-secondary)");
    const dot = find(css.normal, ".cv-symbolpicker__dot", "border");
    expect(dot).toContain("inline-size: var(--space-inset-sm)");
    expect(dot).toContain("border-radius: var(--radius-circle)");
    expect(dot).toContain("solid currentcolor");
    expect(dot).not.toMatch(/background/);
    expect(
      find(
        css.normal,
        '.cv-symbolpicker__chip[data-marker="recording"] .cv-symbolpicker__dot',
        "background",
      ),
    ).toContain("background: currentcolor");
  });

  it("forced colours: ButtonText on ButtonFace, expanded Highlight, a CanvasText dot; no token colour survives", () => {
    expect(find(css.forced, `${TRIGGER}:active`, "background")).toContain("background: ButtonFace");
    const expanded = find(css.forced, `${TRIGGER}[aria-expanded="true"]`, "background");
    expect(expanded).toContain("background: Highlight");
    expect(expanded).toContain("color: HighlightText");
    expect(
      find(
        css.forced,
        '.cv-symbolpicker__chip[data-marker="recording"] .cv-symbolpicker__dot',
        "background",
      ),
    ).toContain("background: CanvasText");
    expect(find(css.forced, ".cv-symbolpicker__chevron", "color")).toContain("color: inherit");
    expect(css.forced).not.toMatch(/var\(--/);
  });
});
