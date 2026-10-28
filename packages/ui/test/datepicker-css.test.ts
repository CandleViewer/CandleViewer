import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("datepicker.css");
const BUTTON = ".cv-datepicker .cv-field > .cv-icon-button";
const DAY = ".cv-datepicker__day";

describe("datepicker.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("sets the value in type.num.base", () => {
    expect(find(css.normal, ".cv-datepicker .cv-field__input", "font")).toContain(
      "var(--type-num-base-font-family)",
    );
  });

  it("the calendar button sits flush with the well's end, under its boundary", () => {
    const button = find(css.normal, BUTTON, "margin-block");
    expect(button).toContain("margin-block: calc(var(--cv-field-bw) * -1)");
    expect(button).toContain("margin-inline-end: calc(var(--cv-field-bw) * -1)");
    expect(button).toContain("background-clip: padding-box");
  });

  it("pads the dialog space.inset.md over the popover surface", () => {
    expect(find(css.normal, ".cv-popover.cv-datepicker__dialog", "padding")).toContain(
      "var(--space-inset-md)",
    );
  });

  it("day cells are size.control.height squares with numbers in type.num.base", () => {
    const day = find(css.normal, DAY, "width");
    expect(day).toContain("width: var(--size-control-height)");
    expect(day).toContain("height: var(--size-control-height)");
    expect(day).toContain("var(--type-num-base-font-size)");
  });

  it("today is a 1px text.tertiary ring; selected is the selected role", () => {
    expect(find(css.normal, `${DAY}[data-today]`, "box-shadow")).toContain(
      "var(--border-hairline) * 1px) var(--color-text-tertiary)",
    );
    const selected = find(css.normal, `${DAY}[data-selected]`, "background");
    expect(selected).toContain("var(--color-action-selected)");
    expect(selected).toContain("var(--border-thick) * 1px) var(--color-border-selected)");
  });

  it("out of range is opacity.disabled, never the T2 look", () => {
    expect(find(css.normal, `${DAY}[aria-disabled]`, "opacity")).toContain(
      "var(--opacity-disabled)",
    );
  });

  it("weekdays are caption text in text.tertiary; the caption is text.secondary", () => {
    expect(find(css.normal, ".cv-datepicker__weekday", "color")).toContain(
      "var(--color-text-tertiary)",
    );
    expect(find(css.normal, ".cv-datepicker__caption", "color")).toContain(
      "var(--color-text-secondary)",
    );
  });

  it("forced colours: today a CanvasText border, selected Highlight, out of range GrayText", () => {
    expect(find(css.forced, `${DAY}[data-today]`, "border")).toContain("CanvasText");
    const selected = find(css.forced, `${DAY}[data-selected]`, "background");
    expect(selected).toContain("Highlight");
    expect(selected).toContain("HighlightText");
    expect(find(css.forced, `${DAY}[aria-disabled]`, "color")).toContain("GrayText");
    expect(find(css.forced, DAY, "forced-color-adjust")).toContain("none");
    expect(find(css.forced, BUTTON, "color")).toContain("ButtonText");
    expect(css.forced).not.toContain("var(--color");
  });
});
