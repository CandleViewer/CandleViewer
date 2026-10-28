import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("card.css");
const { normal, forced } = css;

describe("card.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("surface: raised fill, radius.card, elevation.card, a transparent 1px box for forced colours", () => {
    const card = find(normal, ".cv-card", "background");
    expect(card).toContain("background: var(--color-surface-raised)");
    expect(card).toContain("border-radius: var(--radius-card)");
    expect(card).toContain("box-shadow: var(--elevation-card)");
    expect(card).toContain("border: calc(var(--border-hairline) * 1px) solid transparent");
  });

  it("flat: the border.default hairline and no shadow", () => {
    const flat = find(normal, '.cv-card[data-surface="flat"]', "border-color");
    expect(flat).toContain("border-color: var(--color-border-default)");
    expect(flat).toContain("box-shadow: none");
  });

  it("header: control-height minimum, actions inset.xs apart, the title wraps first", () => {
    const header = find(normal, ".cv-card__header", "min-height");
    expect(header).toContain("min-height: var(--size-control-height)");
    expect(find(normal, ".cv-card__actions", "gap")).toContain("gap: var(--space-inset-xs)");
    expect(find(normal, ".cv-card__actions", "flex")).toContain("flex: none");
    const title = find(normal, ".cv-card__title", "font");
    expect(title).toContain("--type-ui-heading-sm-font-size");
    expect(title).toContain("color: var(--color-text-primary)");
    expect(title).toContain("min-width: 0");
    expect(title).toContain("margin: 0");
  });

  it("body: panel padding, stack.sm under the header, none at Padding=none", () => {
    expect(find(normal, ".cv-card__body", "padding")).toContain(
      "padding: var(--space-panel-padding)",
    );
    expect(find(normal, ".cv-card__header + .cv-card__body", "padding-block-start")).toContain(
      "var(--space-stack-sm)",
    );
    expect(find(normal, '.cv-card[data-padding="none"] > .cv-card__body', "padding")).toContain(
      "padding: 0",
    );
  });

  it("not interactive: no hover, focus or opacity of its own", () => {
    expect(css.all).not.toMatch(/:hover|focus|opacity|cursor/);
  });

  it("forced colours: a CanvasText 1px border in both surfaces, the title CanvasText", () => {
    expect(find(forced, ".cv-card", "border-color")).toContain("border-color: CanvasText");
    expect(find(forced, '.cv-card[data-surface="flat"]', "border-color")).toContain("CanvasText");
    expect(find(forced, ".cv-card__title", "color")).toContain("CanvasText");
  });
});
