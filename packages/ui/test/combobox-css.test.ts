import { describe, expect, it } from "vitest";
import { find, loadCss } from "./css-contract.js";

const { normal, forced } = loadCss("combobox.css");

describe("combobox.css contract (CMP-048)", () => {
  it("binds tokens only: no raw colour, and raw px only as a token multiplier", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(forced).not.toMatch(/\d+px/);
  });

  it("is the popup of conventions 26: overlay fill, popover elevation, card radius, default edge", () => {
    const popup = find(normal, ".cv-combobox__popup", "background");
    expect(popup).toContain("background: var(--color-surface-overlay)");
    expect(popup).toContain("box-shadow: var(--elevation-popover)");
    expect(popup).toContain("border-radius: var(--radius-card)");
    expect(popup).toContain("border: var(--cv-combobox-edge) solid var(--color-border-default)");
    expect(popup).toContain("min-width: var(--cv-anchor-width, auto)");
    expect(find(normal, ".cv-combobox__popup:not([data-positioned])", "opacity")).toContain(
      "opacity: 0",
    );
  });

  it("caps the list at ten rows, then scrolls, and never past the room on its side", () => {
    const list = find(normal, ".cv-combobox__list", "max-height");
    expect(list).toContain("10 * var(--size-row-height)");
    expect(list).toContain("var(--cv-available-height, 100vh)");
    expect(list).toContain("overflow-y: auto");
  });

  it("the match is weight, not colour; status rows are secondary words", () => {
    const match = find(normal, ".cv-combobox__match", "font");
    expect(match).toContain("var(--type-ui-body-strong-font-weight)");
    expect(match).not.toMatch(/color/);
    expect(find(normal, ".cv-combobox__status", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
  });

  it("fades in over fast / decelerate, with the reduced-motion pair in the file", () => {
    expect(find(normal, ".cv-combobox__popup", "transition")).toContain(
      "transition: opacity var(--motion-duration-fast) cubic-bezier(var(--motion-easing-decelerate))",
    );
    for (const scope of [':root[data-motion="reduce"] *', ":root:not([data-motion]) *"]) {
      const pair = find(normal, scope, "transition-duration");
      expect(pair).toContain("transition-duration: 0.01ms !important");
      expect(pair).toContain("transition-delay: 0s !important");
    }
  });

  it("forced colours: the popup on Canvas with a CanvasText edge, adjust none; status CanvasText", () => {
    const popup = find(forced, ".cv-combobox__popup", "background");
    expect(popup).toContain("border-color: CanvasText");
    expect(popup).toContain("background: Canvas");
    expect(popup).toContain("color: CanvasText");
    expect(popup).toContain("forced-color-adjust: none");
    expect(find(forced, ".cv-combobox__status", "color")).toContain("color: CanvasText");
    expect(forced).not.toMatch(/var\(--/);
  });
});
