import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/indicatorchips.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

const body = (css: string, selector: string): string | undefined => {
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim());
    if (selectors.includes(selector)) return m[2] ?? "";
  }
  return undefined;
};

const OPEN = '.cv-indicator-chips[aria-expanded="true"] .cv-indicator-chips__pill';

describe("indicatorchips.css contract", () => {
  it("the open state keys the house selected fill off aria-expanded, never aria-pressed", () => {
    expect(body(normal, OPEN)).toContain("background: var(--color-surface-selected)");
    expect(CSS).not.toMatch(/aria-pressed/);
  });

  it("forced colours: the open chip keeps a pressed cue in system colours (Highlight / HighlightText)", () => {
    const pill = body(forced, OPEN);
    expect(pill).toMatch(/background:\s*Highlight;/);
    expect(pill).toMatch(/color:\s*HighlightText;/);
    expect(pill).toMatch(/forced-color-adjust:\s*none;/);
    expect(
      body(
        forced,
        '.cv-indicator-chips[aria-expanded="true"] .cv-indicator-chips__glyph[data-kind]',
      ),
    ).toMatch(/color:\s*HighlightText;/);
  });
});
