import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/densitytoggle.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");

/** The declarations of the rule whose selector list includes `selector`. */
const rule = (selector: string): string | undefined => {
  for (const m of CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = (m[1] ?? "").split(",").map((s) => s.replace(/\s+/g, " ").trim());
    if (selectors.includes(selector)) return m[2] ?? "";
  }
  return undefined;
};

describe("densitytoggle.css contract", () => {
  it("stacks CMP-003's group above its reason line with a token gap", () => {
    const root = rule(".cv-density-toggle");
    expect(root).toContain("display: inline-grid");
    expect(root).toContain("gap: var(--space-stack-xs)");
    expect(rule(".cv-density-toggle[data-full-width]")).toContain("justify-items: stretch");
  });

  it("adds no anatomy of its own: no colour, no size, no motion", () => {
    expect(CSS).not.toMatch(/#[0-9a-fA-F]{3,8}\b|color|background|border|height|width:/);
    expect(CSS).not.toMatch(/transition|animation/);
  });

  it("is concatenated into components.css by the Storybook theme bundle", () => {
    const bundles = readFileSync(
      resolve(import.meta.dirname, "../.storybook/theme-bundles.ts"),
      "utf-8",
    );
    expect(bundles).toContain('import "../src/components/densitytoggle.css";');
  });
});
