import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/tag.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

const find = (css: string, selector: string, prop: string): string | undefined => {
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim());
    if (selectors.includes(selector) && new RegExp(`${prop}\\s*:`).test(m[2] ?? "")) return m[2];
  }
  return undefined;
};

describe("tag.css contract", () => {
  it("tokens only: no hex, rgb or hsl colour, and the only raw px is the 1px hairline", () => {
    expect(CSS).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    for (const px of CSS.match(/-?\d+(\.\d+)?px/g) ?? []) expect(px).toMatch(/^-?1px$/);
  });

  it("shape and type: pill, control height minimum, caption type, inset padding and gap", () => {
    const base = find(normal, ".cv-tag", "border-radius");
    expect(base).toContain("var(--radius-badge)");
    expect(base).toContain("min-height: var(--size-control-height)");
    expect(base).toContain("padding-inline: var(--space-inset-sm)");
    expect(base).toContain("gap: var(--space-inset-xs)");
    expect(base).toContain("--type-ui-caption-font-size");
    expect(base).toContain("white-space: nowrap");
  });

  it("neutral: subtle fill, default border, secondary label", () => {
    expect(find(normal, ".cv-tag", "background")).toContain("--color-neutral-subtle");
    expect(find(normal, ".cv-tag", "color")).toContain("color: var(--color-text-secondary)");
    expect(find(normal, '.cv-tag[data-variant="neutral"]', "border-color")).toContain(
      "--color-border-default",
    );
  });

  it.each(["info", "warning", "danger"])(
    "%s: status subtle fill, text.primary label, .strong glyph",
    (tone) => {
      const body = find(normal, `.cv-tag[data-variant="${tone}"]`, "background");
      expect(body).toContain(`--color-status-${tone}-subtle`);
      expect(body).toContain("color: var(--color-text-primary)");
      expect(body).toContain(`--cv-tag-glyph: var(--color-status-${tone}-strong)`);
    },
  );

  it("removable (E7): an 8px inset.sm gap and inset.xs end padding", () => {
    const body = find(normal, ".cv-tag[data-removable]", "gap");
    expect(body).toContain("gap: var(--space-inset-sm)");
    expect(body).toContain("padding-inline-end: var(--space-inset-xs)");
  });

  it("no second ring, no dimming of its own (conv. 20)", () => {
    expect(CSS).not.toMatch(/focus|outline|opacity/);
  });

  it("no motion: no transition or animation, so reduced motion has nothing to stop", () => {
    expect(CSS).not.toMatch(/transition|animation|@keyframes/);
  });

  it("forced colours: CanvasText border and label on Canvas, glyph currentColor", () => {
    const body = find(forced, ".cv-tag[data-variant]", "border-color");
    expect(body).toContain("border-color: CanvasText");
    expect(body).toContain("background: Canvas");
    expect(body).toContain("color: CanvasText");
    expect(find(forced, ".cv-tag__glyph", "color")).toContain("currentcolor");
    expect(forced).not.toMatch(/forced-color-adjust/);
  });
});
