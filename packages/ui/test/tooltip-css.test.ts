// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, loadCss } from "./css-contract.js";

const css = loadCss("tooltip.css");
const { all, normal, forced } = css;

/** Every block whose selector list includes `selector` (the merged atoms' reading), joined. */
const bodies = (source: string, selector: string): string =>
  [...source.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) =>
      (m[1] ?? "").split(/,(?![^(]*\))/).some((s) => s.replace(/\s+/g, " ").trim() === selector),
    )
    .map((m) => m[2] ?? "")
    .join(";");

describe("tooltip.css contract (CMP-016)", () => {
  it("binds tokens only: no raw colour, raw px only for forced-colours edges", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(forced).not.toMatch(/\d+px/);
  });

  it("is the overlay surface of conventions 30: overlay fill, popover elevation, card radius, default edge", () => {
    const surface = find(normal, ".cv-tooltip", "background");
    expect(surface).toContain("background: var(--color-surface-overlay)");
    expect(surface).toContain("box-shadow: var(--elevation-popover)");
    expect(surface).toContain("border-radius: var(--radius-card)");
    expect(surface).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(surface).toContain("padding-block: var(--space-inset-xs)");
    expect(surface).toContain("padding-inline: var(--space-inset-sm)");
    expect(surface).toContain("color: var(--color-text-primary)");
    expect(surface).toContain("var(--type-ui-caption-font-size)");
  });

  it("is fixed-positioned, wraps inside the 320 px (20rem) maximum and never overflows the viewport", () => {
    const surface = find(normal, ".cv-tooltip", "position");
    expect(surface).toContain("position: fixed");
    expect(surface).toContain("max-width: min(20rem, calc(100vw - 2 * var(--space-inset-xs)))");
    expect(surface).toContain("overflow-wrap: break-word");
    expect(surface).not.toMatch(/white-space:\s*nowrap/);
  });

  it("stays invisible until its first placement, so it never flashes at the origin", () => {
    expect(find(normal, ".cv-tooltip:not([data-positioned])", "visibility")).toContain(
      "visibility: hidden",
    );
  });

  it("motion-safe: fades in over fast / decelerate and out over fast / accelerate, opacity only", () => {
    expect(find(normal, ".cv-tooltip", "transition")).toContain(
      "transition: opacity var(--motion-duration-fast) cubic-bezier(var(--motion-easing-decelerate))",
    );
    const exit = find(normal, ".cv-tooltip[hidden]", "transition");
    expect(exit).toContain(
      "opacity var(--motion-duration-fast) cubic-bezier(var(--motion-easing-accelerate))",
    );
    // The easing tokens are bare lists ("0, 0, 0, 1"): every use is wrapped, or the declaration is invalid.
    expect(all.replace(/cubic-bezier\(var\(--motion-easing-\w+\)\)/g, "")).not.toContain("easing");
    expect(exit).toContain("pointer-events: none");
    expect(exit).toContain("display: none");
    expect(all).toMatch(/@starting-style\s*\{\s*\.cv-tooltip\s*\{\s*opacity: 0;/);
    // Only opacity animates (conventions 35): no transform, no keyframes.
    expect(all).not.toMatch(/transform|@keyframes|animation/);
  });

  it("reduced motion: the in-app override and the OS preference both cut, open and close", () => {
    for (const selector of [".cv-tooltip", ".cv-tooltip[hidden]"]) {
      expect(bodies(all, `:root[data-motion="reduce"] ${selector}`)).toContain("transition: none");
      const os = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?\}\s*)\}/.exec(all)?.[1];
      expect(bodies(os ?? "", `:root:not([data-motion]) ${selector}`)).toContain(
        "transition: none",
      );
    }
  });

  it("reduce rules out-rank the exit rule, and OS reduce yields to an explicit data-motion", () => {
    const osReduce = all.replace(
      /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?\})\s*\}/g,
      "$1",
    );
    const rules = [...osReduce.matchAll(/([^{}]+)\{([^{}]*transition[^{}]*)\}/g)].flatMap((m) =>
      (m[1] ?? "").split(",").map((sel) => [sel.trim(), m[2] ?? ""] as const),
    );
    const node = document.body.appendChild(document.createElement("div"));
    node.className = "cv-tooltip";
    node.hidden = true;
    const root = document.documentElement;
    const reduced = (attr: string | null): boolean => {
      if (attr === null) root.removeAttribute("data-motion");
      else root.setAttribute("data-motion", attr);
      return rules.some(([sel, body]) => node.matches(sel) && body.includes("transition: none"));
    };
    expect(reduced("reduce")).toBe(true);
    expect(reduced(null)).toBe(true);
    expect(reduced("safe")).toBe(false);
    root.removeAttribute("data-motion");
    node.remove();
  });

  it("forced colours: a CanvasText 1 px edge on Canvas, CanvasText text, system colours only", () => {
    const surface = find(forced, ".cv-tooltip", "border-color");
    expect(surface).toContain("border-color: CanvasText");
    expect(surface).toContain("background: Canvas");
    expect(surface).toContain("color: CanvasText");
    expect(forced).not.toMatch(/var\(--/);
  });
});
