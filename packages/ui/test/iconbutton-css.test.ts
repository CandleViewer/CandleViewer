import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/iconbutton.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

const find = (
  css: string,
  selector: string,
  prop: string,
): { body: string; index: number } | undefined => {
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim());
    if (selectors.includes(selector) && new RegExp(`${prop}\\s*:`).test(m[2] ?? ""))
      return { body: m[2] ?? "", index: m.index };
  }
  return undefined;
};

describe("iconbutton.css contract", () => {
  it("the box is the density-owned control height, square, at every size", () => {
    const box = find(normal, ".cv-icon-button", "width");
    expect(box?.body).toContain("width: var(--size-control-height)");
    expect(box?.body).toContain("height: var(--size-control-height)");
    expect(CSS).not.toMatch(/data-size/);
  });

  it("gated: glyph text.primary on every variant, out-specifying them, outline kept off the plate", () => {
    const gated = find(normal, ".cv-icon-button[data-gated][data-variant]", "color");
    expect(gated?.body).toContain("color: var(--color-text-primary)");
    const primary = find(normal, '.cv-icon-button[data-variant="primary"]', "color");
    expect(gated?.index).toBeGreaterThan(primary?.index ?? Infinity);
    expect(find(normal, ".cv-icon-button[data-gated]::before", "opacity")?.body).toContain(
      "--opacity-disabled",
    );
  });

  it("ghost glyph: text.secondary at rest, text.primary on hover and active, pressed and gated kept primary", () => {
    const rest = find(normal, '.cv-icon-button[data-variant="ghost"]', "color");
    expect(rest?.body).toContain("color: var(--color-text-secondary)");
    for (const state of ["hover", "active"]) {
      const sel = `.cv-icon-button[data-variant="ghost"]:${state}:not(:disabled, [aria-disabled])`;
      expect(find(normal, sel, "color")?.body).toContain("color: var(--color-text-primary)");
    }
    const pressed = find(normal, '.cv-icon-button[aria-pressed="true"]', "color");
    expect(pressed?.body).toContain("color: var(--color-text-primary)");
    expect(pressed?.index).toBeGreaterThan(rest?.index ?? Infinity);
    const gated = find(normal, ".cv-icon-button[data-gated][data-variant]", "color");
    expect(gated?.body).toContain("color: var(--color-text-primary)");
  });

  it("pressed: selected fill and a border.thick inner outline, unchanged on hover and active", () => {
    const hover =
      '.cv-icon-button[aria-pressed="true"][data-variant]:hover:not(:disabled, [aria-disabled])';
    const pressed = find(normal, hover, "box-shadow");
    expect(pressed?.body).toContain("--color-action-selected");
    expect(pressed?.body).toContain("--color-border-selected");
    expect(pressed?.body).toContain("--border-thick");
    expect(find(normal, hover.replace(":hover", ":active"), "box-shadow")).toBeDefined();
  });

  it("forced colours: ghost hover and active keep the ButtonText glyph", () => {
    for (const state of ["hover", "active"]) {
      const rule = find(
        forced,
        `.cv-icon-button[data-variant="ghost"]:${state}:not(:disabled, [aria-disabled])`,
        "color",
      );
      expect(rule?.body).toContain("color: ButtonText");
    }
  });

  it("forced colours: ButtonText, Highlight pressed, GrayText plain disabled, ButtonText gated", () => {
    expect(find(forced, ".cv-icon-button[data-variant]", "color")?.body).toContain(
      "color: ButtonText",
    );
    expect(find(forced, '.cv-icon-button[aria-pressed="true"]', "color")?.body).toContain(
      "color: HighlightText",
    );
    expect(find(forced, ".cv-icon-button[data-variant]:disabled", "color")?.body).toContain(
      "GrayText",
    );
    const gated = find(forced, ".cv-icon-button[data-gated][data-variant]", "color");
    expect(gated?.body).toContain("color: ButtonText");
    const both = find(forced, '.cv-icon-button[data-gated][aria-pressed="true"]', "border");
    expect(both?.body).toContain("2px solid ButtonText");
    expect(both?.index).toBeGreaterThan(gated?.index ?? Infinity);
    expect(find(forced, ".cv-icon-button__badge", "color")?.body).toContain("ButtonText");
  });
});
