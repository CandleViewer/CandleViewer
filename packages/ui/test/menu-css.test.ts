// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, loadCss } from "./css-contract.js";

const { all, normal, forced } = loadCss("menu.css");

describe("menu.css contract (CMP-041)", () => {
  it("binds tokens only: no raw colour; px only as a token multiplier (the ring's width and inset)", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px|\* -2px/g, "")).not.toMatch(/\d+px/);
    expect(forced).not.toMatch(/\d+px/);
  });

  it("is the floating surface of conventions 30, at least as wide as its trigger, capped, scrolling", () => {
    const surface = find(normal, ".cv-menu", "background");
    expect(surface).toContain("background: var(--color-surface-overlay)");
    expect(surface).toContain("box-shadow: var(--elevation-popover)");
    expect(surface).toContain("border-radius: var(--radius-card)");
    expect(surface).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(surface).toContain("padding-block: var(--space-inset-xs)");
    expect(surface).toContain("min-width: var(--cv-anchor-width, auto)");
    expect(surface).toContain(
      "max-height: var(--cv-available-height, calc(100vh - 2 * var(--space-inset-xs)))",
    );
    expect(surface).toContain("overflow: auto");
    expect(surface).toContain("position: fixed");
  });

  it("items: size.row.height minimum, space.inset.sm inline, space.inset.xs gap", () => {
    const item = find(normal, ".cv-menu__row", "min-block-size");
    expect(item).toContain("min-block-size: var(--size-row-height)");
    expect(item).toContain("padding-inline: var(--space-inset-sm)");
    expect(item).toContain("gap: var(--space-inset-xs)");
  });

  it("hover and focus on surface.hover; the inset ring (H8) on focus-visible; active on surface.selected", () => {
    expect(find(normal, ".cv-menu__row:hover", "background")).toContain(
      "background: var(--color-surface-hover)",
    );
    const ring = find(normal, ".cv-menu__row:has(.cv-menu__item:focus-visible)", "outline");
    expect(ring).toContain(
      "outline: calc(var(--border-focus) * 1px) solid var(--color-focus-ring)",
    );
    expect(ring).toContain("outline-offset: calc(var(--border-focus) * -2px)");
    expect(find(normal, ".cv-menu__row:active", "background")).toContain(
      "background: var(--color-surface-selected)",
    );
  });

  it("disabled dims; T2 is tertiary, never opacity.disabled; danger's glyph is status.danger.strong", () => {
    expect(find(normal, '.cv-menu__row[data-state="disabled"]', "opacity")).toContain(
      "opacity: var(--opacity-disabled)",
    );
    const gated = find(normal, '.cv-menu__row[data-state="gated"] .cv-menu__item', "color");
    expect(gated).toContain("color: var(--color-text-tertiary)");
    expect(gated).not.toContain("opacity");
    expect(find(normal, ".cv-menu__row[data-danger] .cv-menu__lead", "color")).toContain(
      "color: var(--color-status-danger-strong)",
    );
    expect(find(normal, ".cv-menu__second", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
    expect(find(normal, ".cv-menu__kbd", "color")).toContain("color: var(--color-text-tertiary)");
  });

  it("separators: a 1 px border.default rule with space.inset.xs above and below", () => {
    const rule = find(normal, ".cv-menu__separator", "border-top");
    expect(rule).toContain(
      "border-top: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(rule).toContain("margin-block: var(--space-inset-xs)");
  });

  it("opens at once (no enter transition); the exit fades over fast with no pointer events", () => {
    expect(find(normal, ".cv-menu", "transition")).toBe("");
    expect(all).not.toMatch(/@starting-style|@keyframes|animation|transform/);
    const exit = find(normal, ".cv-menu[hidden]", "transition");
    expect(exit).toContain("display: none");
    expect(exit).toContain("pointer-events: none");
    expect(exit).toContain("opacity var(--motion-duration-fast) var(--motion-easing-accelerate)");
    expect(find(normal, ".cv-menu:not([data-positioned])", "opacity")).toContain("opacity: 0");
  });

  it("reduced motion: the in-app override and the OS preference both cut the exit", () => {
    expect(find(all, ':root[data-motion="reduce"] .cv-menu[hidden]', "transition")).toContain(
      "transition: none",
    );
    const os = all.split("@media (prefers-reduced-motion: reduce)")[1] ?? "";
    expect(find(os, ":root:not([data-motion]) .cv-menu[hidden]", "transition")).toContain(
      "transition: none",
    );
  });

  it("forced colours: CanvasText edge on Canvas, a Highlight focused item, T2 never GrayText", () => {
    const surface = find(forced, ".cv-menu", "border-color");
    expect(surface).toContain("border-color: CanvasText");
    expect(surface).toContain("background: Canvas");
    const focusedItem = find(forced, ".cv-menu__row:has(.cv-menu__item:focus)", "background");
    expect(focusedItem).toContain("forced-color-adjust: none");
    expect(focusedItem).toContain("background: Highlight");
    expect(focusedItem).toContain("color: HighlightText");
    expect(
      find(forced, ".cv-menu__row:has(.cv-menu__item:focus) .cv-menu__second", "color"),
    ).toContain("color: HighlightText");
    expect(find(forced, '.cv-menu__row[data-state="gated"] .cv-menu__item', "color")).toContain(
      "color: CanvasText",
    );
    expect(find(forced, ".cv-menu__separator", "border-top-color")).toContain(
      "border-top-color: CanvasText",
    );
    expect(forced).not.toMatch(/var\(--/);
  });

  it("submenus: sized by their items, the open item's row on surface.hover, a secondary chevron", () => {
    expect(find(normal, ".cv-menu--submenu", "min-width")).toContain("min-width: 0");
    expect(normal).toMatch(/\.cv-menu__row\[data-expanded\],\s*\.cv-menu__row:has/);
    expect(find(normal, ".cv-menu__chevron", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
    expect(find(forced, ".cv-menu__row[data-expanded]", "outline")).toContain(
      "outline: thin solid CanvasText",
    );
    expect(
      find(forced, ".cv-menu__row:has(.cv-menu__item:focus) .cv-menu__chevron", "color"),
    ).toContain("color: HighlightText");
  });
});
