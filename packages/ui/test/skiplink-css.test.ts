import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/skiplink.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

/** The declarations of the rule whose selector list includes `selector`. */
const rule = (css: string, selector: string): string | undefined => {
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = (m[1] ?? "").split(",").map((s) => s.replace(/\s+/g, " ").trim());
    if (selectors.includes(selector)) return m[2] ?? "";
  }
  return undefined;
};

describe("skiplink.css contract", () => {
  it("unfocused: visually hidden by the clip pattern, never display:none (it stays in the Tab order)", () => {
    const hidden = rule(normal, ".cv-skip-link");
    expect(hidden).toContain("clip-path: inset(50%)");
    expect(hidden).toContain("width: 1px");
    expect(hidden).toContain("position: absolute");
    expect(CSS).not.toMatch(/display:\s*none|visibility:\s*hidden/);
  });

  it("focused: the primary pill at the control height with the CMP-039 ring", () => {
    const shown = rule(normal, ".cv-skip-link:focus");
    expect(shown).toContain("clip-path: none");
    expect(shown).toContain("min-height: var(--size-control-height)");
    expect(shown).toContain("padding-inline: var(--space-button-paddingX)");
    expect(shown).toContain("border-radius: var(--radius-control)");
    expect(shown).toContain("background: var(--color-action-primary-default)");
    expect(shown).toContain("color: var(--color-text-on-action)");
    expect(shown).toContain("--type-ui-label-font-size");
    expect(shown).toMatch(
      /outline: calc\(var\(--border-focus\) \* 1px\) solid var\(--color-focus-ring\)/,
    );
    expect(rule(normal, ".cv-skip-link:focus:hover")).toContain("--color-action-primary-hover");
  });

  it("the target keeps the ring while it holds the moved focus", () => {
    expect(rule(normal, "[data-cv-skip-target]:focus")).toContain("var(--color-focus-ring)");
  });

  it("no motion: no transition or animation in either mode", () => {
    expect(CSS).not.toMatch(/transition|animation/);
  });

  it("uses tokens only: no hex colour", () => {
    expect(CSS).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it("forced colours: LinkText on Canvas with a CanvasText border; Highlight rings", () => {
    const pill = rule(forced, ".cv-skip-link:focus");
    expect(pill).toContain("color: LinkText");
    expect(pill).toContain("background: Canvas");
    expect(pill).toContain("border-color: CanvasText");
    expect(pill).toContain("outline-color: Highlight");
    expect(rule(forced, ".cv-skip-link:focus:hover")).toBe(pill);
    expect(rule(forced, "[data-cv-skip-target]:focus")).toContain("outline-color: Highlight");
  });
});
