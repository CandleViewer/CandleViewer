import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("pageheader.css");
const { normal, forced } = css;

describe("pageheader.css contract (E42-D03 board 10 row G)", () => {
  itIsTokenOnlyAndStatic(css);

  it("frame: space.inset.lg above and below, two columns with the text first", () => {
    const frame = find(normal, ".cv-page-header", "padding-block");
    expect(frame).toContain("padding-block: var(--space-inset-lg)");
    expect(frame).toContain("display: grid");
    // The actions' column is capped at half the width, so several actions wrap, never the title to nothing.
    expect(frame).toContain("grid-template-columns: minmax(0, 1fr) fit-content(50%)");
  });

  it("title: type.ui.heading-md in text.primary, no margin, wrapping before the actions move", () => {
    const title = find(normal, ".cv-page-header__title", "font");
    expect(title).toContain("--type-ui-heading-md-font-size");
    expect(title).toContain("--type-ui-heading-md-font-weight");
    expect(title).toContain("color: var(--color-text-primary)");
    expect(title).toContain("margin: 0");
    expect(title).toContain("min-width: 0");
    expect(title).toContain("overflow-wrap: anywhere");
    expect(title).toContain("grid-column: 1");
  });

  it("meta and marker: type.ui.caption in text.tertiary, space.stack.sm under the line above", () => {
    for (const part of [".cv-page-header__meta", ".cv-page-header__marker"]) {
      const line = find(normal, part, "font");
      expect(line).toContain("--type-ui-caption-font-size");
      expect(line).toContain("color: var(--color-text-tertiary)");
      expect(line).toContain("margin: var(--space-stack-sm) 0 0");
      expect(line).toContain("overflow-wrap: anywhere");
    }
  });

  it("breadcrumb: the full width above the title, space.stack.sm under it", () => {
    const crumb = find(normal, ".cv-page-header__breadcrumb", "grid-column");
    expect(crumb).toContain("grid-column: 1 / -1");
    expect(crumb).toContain("margin-block-end: var(--space-stack-sm)");
  });

  it("actions: the second column, inset.lg clear of the text, inset.xs apart, wrapping", () => {
    const actions = find(normal, ".cv-page-header__actions", "gap");
    expect(actions).toContain("grid-column: 2");
    expect(actions).toContain("gap: var(--space-inset-xs)");
    expect(actions).toContain("flex-wrap: wrap");
    expect(actions).toContain("margin-inline-start: var(--space-inset-lg)");
  });

  it("the actions span exactly the text lines the header counts (data-lines)", () => {
    expect(
      find(normal, '.cv-page-header[data-lines="2"] > .cv-page-header__actions', "grid-row"),
    ).toContain("grid-row: span 2");
    expect(
      find(normal, '.cv-page-header[data-lines="3"] > .cv-page-header__actions', "grid-row"),
    ).toContain("grid-row: span 3");
  });

  it("has no hover, focus, opacity or live styling of its own", () => {
    expect(css.all).not.toMatch(/:hover|focus|opacity|cursor/);
  });

  it("forced colours: the title, the meta and the marker in CanvasText", () => {
    for (const part of [
      ".cv-page-header__title",
      ".cv-page-header__meta",
      ".cv-page-header__marker",
    ]) {
      expect(find(forced, part, "color")).toContain("color: CanvasText");
    }
  });
});
