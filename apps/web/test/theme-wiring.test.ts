// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src");

/**
 * #3139: `@candleviewer/ui`'s theme runtime is the only writer of `data-theme`, `data-density`,
 * `data-motion` and `data-text-scale`, and the legacy `--cv-font-scale`, `data-reduced-motion`,
 * `data-high-contrast` and `data-contrast` are gone. Reads (`getAttribute`, an observer's
 * `attributeFilter`) are fine: the runtime's attributes are the contract.
 */
const FORBIDDEN: readonly { readonly rule: string; readonly pattern: RegExp }[] = [
  {
    rule: "writes a runtime attribute with (set|remove|toggle)Attribute",
    pattern:
      /\b(?:set|remove|toggle)Attribute\(\s*["'`]data-(?:theme|density|motion|text-scale)["'`]/,
  },
  {
    rule: "writes a runtime attribute through dataset",
    pattern: /\.dataset(?:\.|\[\s*["'`])(?:theme|density|motion|textScale)\b/,
  },
  { rule: "mentions the legacy --cv-font-scale", pattern: /--cv-font-scale/ },
  {
    rule: "mentions a retired attribute",
    pattern:
      /\bdata-(?:reduced-motion|high-contrast|contrast)\b|\.dataset(?:\.|\[\s*["'`])(?:reducedMotion|highContrast|contrast)\b/,
  },
];

function violationsIn(source: string): string[] {
  return FORBIDDEN.filter(({ pattern }) => pattern.test(source)).map(({ rule }) => rule);
}

function sourceFiles(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .filter((file) => /\.tsx?$/.test(file))
    .map((file) => join(SRC, file));
}

describe("one writer: apps/web does not write the theme runtime's root attributes", () => {
  it("finds no write of a runtime attribute, the legacy font-scale or a retired attribute in src", () => {
    const found = sourceFiles().flatMap((file) =>
      violationsIn(readFileSync(file, "utf8")).map((rule) => `${file}: ${rule}`),
    );
    expect(found).toStrictEqual([]);
  });

  it("scans the whole source tree (the check is not vacuous)", () => {
    const files = sourceFiles().map((file) => file.replaceAll("\\", "/"));
    expect(files.length).toBeGreaterThan(40);
    expect(files.some((file) => file.endsWith("/shell/bootstrap/preferencesApply.ts"))).toBe(true);
    expect(
      files.some((file) => file.endsWith("/features/a11y-preferences/PreferencesContext.tsx")),
    ).toBe(true);
  });

  it.each([
    ['root.setAttribute("data-theme", "dark")', "writes a runtime attribute with"],
    ["root.setAttribute('data-density', d)", "writes a runtime attribute with"],
    ["root.setAttribute(`data-motion`, m)", "writes a runtime attribute with"],
    ['root.removeAttribute("data-text-scale")', "writes a runtime attribute with"],
    ['root.toggleAttribute(\n  "data-theme", true)', "writes a runtime attribute with"],
    ['r.dataset["theme"] = "dark"', "writes a runtime attribute through dataset"],
    ["r.dataset.density = d", "writes a runtime attribute through dataset"],
    ["r.dataset.textScale = '125'", "writes a runtime attribute through dataset"],
    ['root.style.setProperty("--cv-font-scale", "1.25")', "mentions the legacy --cv-font-scale"],
    ['root.setAttribute("data-reduced-motion", "true")', "mentions a retired attribute"],
    ['[data-high-contrast="true"] { }', "mentions a retired attribute"],
    ['r.dataset["contrast"] = "more"', "mentions a retired attribute"],
    ["r.dataset.reducedMotion = 'true'", "mentions a retired attribute"],
  ])("flags %s", (snippet, rule) => {
    expect(violationsIn(snippet).some((found) => found.startsWith(rule))).toBe(true);
  });

  it.each([
    'root.getAttribute("data-theme")',
    'root.setAttribute("data-palette", "cvd-safe")',
    'root.setAttribute("data-convention", "inverted")',
    'attributeFilter: ["data-theme", "data-palette"]',
    'r.dataset["focusRing"] = "thick"',
    'r.dataset["keyboardOnly"] = "true"',
    'const DATA_THEME_ATTR = "data-theme"',
  ])("allows %s", (snippet) => {
    expect(violationsIn(snippet)).toStrictEqual([]);
  });
});

describe("the app entry imports the theme CSS by export name", () => {
  const entry = readFileSync(join(SRC, "main.tsx"), "utf8");
  const cssImports = [...entry.matchAll(/^import\s+["']([^"']+\.css)["'];?\s*$/gm)].map(
    (match) => match[1],
  );

  it("imports the three token files, then theme.css, so the runtime styles override the tokens", () => {
    expect(cssImports).toStrictEqual([
      "@candleviewer/ui/tokens.dark.css",
      "@candleviewer/ui/tokens.light.css",
      "@candleviewer/ui/tokens.high-contrast.css",
      "@candleviewer/ui/theme.css",
    ]);
  });

  it("never reaches into the package's build output or sources by path", () => {
    expect(entry).not.toMatch(/@candleviewer\/ui\/(?:build|dist|src)\//);
    expect(entry).not.toMatch(/packages\/ui\//);
  });
});
