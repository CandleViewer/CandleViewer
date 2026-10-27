// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, loadCss } from "./css-contract.js";

const { all, normal, forced } = loadCss("popover.css");

describe("popover.css contract (CMP-017)", () => {
  it("binds tokens only: no raw colour, raw px only for forced-colours edges", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(forced).not.toMatch(/\d+px/);
  });

  it("is the floating surface of conventions 30: overlay fill, popover elevation, card radius, default edge", () => {
    const surface = find(normal, ".cv-popover", "background");
    expect(surface).toContain("background: var(--color-surface-overlay)");
    expect(surface).toContain("box-shadow: var(--elevation-popover)");
    expect(surface).toContain("border-radius: var(--radius-card)");
    expect(surface).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(surface).toContain("padding: var(--space-inset-sm)");
    expect(surface).toContain("gap: var(--space-stack-sm)");
    expect(surface).toContain("color: var(--color-text-primary)");
    expect(surface).toContain("position: fixed");
  });

  it("is at least as wide as its trigger and capped at the room to the viewport edge", () => {
    const surface = find(normal, ".cv-popover", "min-width");
    expect(surface).toContain("min-width: var(--cv-anchor-width, auto)");
    expect(surface).toContain("max-width: calc(100vw - 2 * var(--space-inset-xs))");
    expect(surface).toContain(
      "max-height: var(--cv-available-height, calc(100vh - 2 * var(--space-inset-xs)))",
    );
  });

  it("Overflow=scrolls: the body scrolls between a fixed heading and footer", () => {
    const body = find(normal, ".cv-popover__body", "overflow");
    expect(body).toContain("overflow: auto");
    expect(body).toContain("min-height: 0");
    expect(find(normal, ".cv-popover__heading", "flex")).toContain("flex: none");
    expect(find(normal, ".cv-popover__footer", "flex")).toContain("flex: none");
  });

  it("heading in type.ui.body-strong; footer end-aligned, space.inset.sm apart, wrapping", () => {
    expect(find(normal, ".cv-popover__heading", "font")).toContain(
      "var(--type-ui-body-strong-font-size)",
    );
    const footer = find(normal, ".cv-popover__footer", "justify-content");
    expect(footer).toContain("justify-content: flex-end");
    expect(footer).toContain("gap: var(--space-inset-sm)");
    expect(footer).toContain("flex-wrap: wrap");
  });

  it("appears at once (it takes focus): no enter transition; transparent, never invisible, until placed", () => {
    expect(find(normal, ".cv-popover", "transition")).toBe("");
    expect(all).not.toMatch(/@starting-style|@keyframes|animation|transform/);
    const unplaced = find(normal, ".cv-popover:not([data-positioned])", "opacity");
    expect(unplaced).toContain("opacity: 0");
    expect(all).not.toMatch(/visibility:\s*hidden/);
  });

  it("the exit fades over fast / accelerate with no pointer events, and hides", () => {
    const exit = find(normal, ".cv-popover[hidden]", "transition");
    expect(exit).toContain("display: none");
    expect(exit).toContain("pointer-events: none");
    expect(exit).toContain("opacity var(--motion-duration-fast) var(--motion-easing-accelerate)");
  });

  it("reduced motion: the in-app override and the OS preference both cut the exit", () => {
    expect(find(all, ':root[data-motion="reduce"] .cv-popover[hidden]', "transition")).toContain(
      "transition: none",
    );
    const os = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?\}\s*)\}/.exec(all)?.[1];
    expect(find(os ?? "", ":root:not([data-motion]) .cv-popover[hidden]", "transition")).toContain(
      "transition: none",
    );
  });

  it("forced colours: a CanvasText 1 px edge on Canvas, CanvasText text, system colours only", () => {
    const surface = find(forced, ".cv-popover", "border-color");
    expect(surface).toContain("border-color: CanvasText");
    expect(surface).toContain("background: Canvas");
    expect(surface).toContain("color: CanvasText");
    expect(find(forced, ".cv-popover__heading", "color")).toContain("color: CanvasText");
    expect(forced).not.toMatch(/var\(--/);
  });
});
