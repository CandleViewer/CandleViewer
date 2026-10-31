import { describe, expect, it } from "vitest";
import { find, loadCss, recipeSafe } from "./css-contract.js";

const { all, normal, forced } = loadCss("toast.css");

describe("toast.css contract (CMP-045)", () => {
  it("binds tokens only: no raw colour, raw px only for forced-colours edges", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(forced.replace(/\b[12]px\b/g, "")).not.toMatch(/\d+px/);
  });

  it("the only raw length is the 360 px width, in rem, capped by the viewport less inset.lg each side", () => {
    const rems = [...normal.matchAll(/(\d+(?:\.\d+)?)rem/g)].map((m) => m[1]);
    expect(new Set(rems)).toEqual(new Set(["22.5"]));
    expect(find(normal, ".cv-toast", "width")).toContain(
      "width: min(22.5rem, calc(100vw - 2 * var(--space-inset-lg)))",
    );
  });

  it("one floating surface (H6): overlay, popover elevation, card radius, inset.md, a default hairline", () => {
    const box = find(normal, ".cv-toast", "background");
    expect(box).toContain("background: var(--color-surface-overlay)");
    expect(box).toContain("box-shadow: var(--elevation-popover)");
    expect(box).toContain("border-radius: var(--radius-card)");
    expect(box).toContain("padding: var(--space-inset-md)");
    expect(box).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
  });

  it("a 2 px border.thick start edge in the tone's .default, the glyph in its .strong", () => {
    const box = find(normal, ".cv-toast", "border-inline-start");
    expect(box).toContain(
      "border-inline-start: calc(var(--border-thick) * 1px) solid var(--cv-toast-edge)",
    );
    expect(box).toContain("--cv-toast-edge: var(--color-status-info-default)");
    expect(find(normal, ".cv-toast__glyph", "color")).toContain("var(--cv-toast-strong)");
  });

  it.each(["success", "warning", "danger"])(
    "%s binds its own .default edge and .strong glyph",
    (tone) => {
      const body = find(normal, `.cv-toast[data-tone="${tone}"]`, "--cv-toast-edge");
      expect(body).toContain(`--cv-toast-edge: var(--color-status-${tone}-default)`);
      expect(body).toContain(`--cv-toast-strong: var(--color-status-${tone}-strong)`);
      expect(all).not.toMatch(/-subtle/);
    },
  );

  it("type: kicker caption, title body-strong on one line, body clamped, meta num.sm tertiary", () => {
    expect(find(normal, ".cv-toast__kicker", "font")).toContain("--type-ui-caption-font-size");
    const title = find(normal, ".cv-toast__title", "font");
    expect(title).toContain("--type-ui-body-strong-font-size");
    expect(title).toContain("white-space: nowrap");
    expect(title).toContain("text-overflow: ellipsis");
    expect(find(normal, ".cv-toast__body", "font")).toContain("color: var(--color-text-secondary)");
    expect(find(normal, ".cv-toast__body", "line-clamp")).toContain("-webkit-line-clamp: 2");
    expect(find(normal, '[data-density="comfortable"] .cv-toast__body', "line-clamp")).toContain(
      "-webkit-line-clamp: 3",
    );
    const meta = find(normal, ".cv-toast__meta", "font");
    expect(meta).toContain("--type-num-sm-font-size");
    expect(meta).toContain("color: var(--color-text-tertiary)");
  });

  it("the stack: inset.lg from the corner, stack.sm apart, no z-index of its own", () => {
    const region = find(normal, ".cv-toast-region", "position");
    expect(region).toContain("position: fixed");
    expect(region).toContain("inset-block-end: var(--space-inset-lg)");
    expect(find(normal, ".cv-toast-region__list", "gap")).toContain("gap: var(--space-stack-sm)");
    expect(all).not.toMatch(/z-index/);
  });

  it("no countdown bar: nothing animates but the entrance", () => {
    expect(all).not.toMatch(/transition/);
    expect([...all.matchAll(/animation:/g)]).toHaveLength(1);
  });

  it("motion: slides in over the toast-in recipe (fast / decelerate); reduce resolves it to none (G-1)", () => {
    expect(find(normal, ".cv-toast", "animation")).toContain(
      "animation: var(--cv-recipe-toast-in)",
    );
    expect(recipeSafe("toast-in")).toBe(
      "cv-toast-in var(--motion-duration-fast) cubic-bezier(var(--motion-easing-decelerate))",
    );
    expect(all).toContain("transform: translateY(var(--space-inset-sm))");
    expect(all).not.toMatch(/prefers-reduced-motion: no-preference/);
  });

  it("forced colours: a CanvasText border and edge on Canvas; glyph and words CanvasText", () => {
    const box = find(forced, ".cv-toast[data-tone]", "border");
    expect(box).toContain("border: 1px solid CanvasText");
    expect(box).toContain("border-inline-start: 2px solid CanvasText");
    expect(box).toContain("background: Canvas");
    expect(find(forced, ".cv-toast__glyph", "color")).toContain("CanvasText");
    expect(find(forced, ".cv-toast__kicker", "color")).toContain("CanvasText");
  });
});
