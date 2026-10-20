import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  componentName,
  iconSources,
  OUTPUT_DIR,
  parseIconSource,
} from "../../scripts/build-icons.mjs";
import * as ui from "../../src/index.js";
import { ICON_COMPONENTS } from "../../src/icons/generated/components.js";
import * as icons from "../../src/icons/index.js";
import { ICONS, type IconName } from "../../src/icons/registry.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
const CATEGORIES = ["navigation", "action", "status", "chart", "trading", "rule-graph"];
/** The component exports of a module: every `<Name>Icon` function. */
const componentsOf = (module: object) =>
  Object.entries(module).filter(([key]) => /^[A-Z]\w*Icon$/.test(key));
const render = (name: IconName) => renderToStaticMarkup(createElement(ICON_COMPONENTS[name]));
/** A module specifier naming the grid, `src/icons/IconSvg.tsx`: `"../icons/IconSvg.js"`. */
const GRID_MODULE = /(["'`])[^"'`\s]*\/IconSvg(?:\.[jt]sx?)?\1/;

describe("the icon registry (src/icons/registry.ts)", () => {
  it("gives every name exactly one component, and every component exactly one name", () => {
    expect(Object.keys(ICON_COMPONENTS)).toEqual(NAMES);
    expect(new Set(Object.values(ICON_COMPONENTS)).size).toBe(NAMES.length);
    const exported = componentsOf(icons);
    expect(exported.map(([key]) => key).sort()).toEqual(NAMES.map(componentName).sort());
    for (const name of NAMES) {
      // componentName returns a string; the barrel's keys are those names (the line above).
      expect(icons[componentName(name) as keyof typeof icons], name).toBe(ICON_COMPONENTS[name]);
      expect(render(name)).toContain(` data-icon="${name}"`);
    }
  });

  it("generates each component in its own module, from its own source", () => {
    const modules = readdirSync(path.join(PACKAGE, OUTPUT_DIR)).filter((f) => f.endsWith(".tsx"));
    expect(modules.sort()).toEqual(NAMES.map((name) => `${componentName(name)}.tsx`).sort());
    expect(iconSources().map(({ name }) => name)).toEqual(NAMES);
  });

  it("names where each glyph comes from: its origin and, for Lucide, the upstream glyph", () => {
    // A source's provenance: `lucide/<glyph its class names>`, or its origin alone (`custom`).
    const provenance = iconSources().map(({ name, origin, file }) => {
      const { glyph } = parseIconSource(readFileSync(path.join(PACKAGE, file), "utf-8"), file);
      return [name, glyph === null ? origin : `${origin}/${glyph}`];
    });
    const registered = NAMES.map((name) => [
      name,
      ICONS[name].source.replace(/^custom\/.*/, "custom"),
    ]);
    expect(provenance).toEqual(registered);
  });

  it("keeps a diff-comparable format: sorted kebab-case names, one-sentence descriptions", () => {
    expect(NAMES).toEqual([...NAMES].sort());
    const descriptions = new Set<string>();
    for (const name of NAMES) {
      const { category, description } = ICONS[name];
      expect(name).toMatch(/^[a-z][\da-z]*(?:-[\da-z]+)*$/);
      expect(CATEGORIES, name).toContain(category);
      expect(description, name).toMatch(/^[A-Z][^\n]{0,98}\.$/);
      descriptions.add(description);
    }
    expect(descriptions.size).toBe(NAMES.length);
  });

  it("draws no glyph twice under two names", () => {
    const geometry = NAMES.map((name) => render(name).replace(/^<svg[^>]*>/, ""));
    expect(new Set(geometry).size).toBe(NAMES.length);
  });

  it("is part of the package's public surface", () => {
    expect(ui.ICONS).toBe(ICONS);
    expect(ui.ICON_SIZES).toEqual(["sm", "md", "lg"]);
    expect(
      componentsOf(ui)
        .map(([key]) => key)
        .sort(),
    ).toEqual(NAMES.map(componentName).sort());
  });

  it("keeps its grid behind it: only the generated modules reach IconSvg, by any route", () => {
    // eslint.config.mjs fences static imports and re-exports; this reads what ESLint does not:
    // an import() call, and the MDX docs pages. Apps never see the grid at all.
    const reachers = ["src", ".storybook"].flatMap((root) =>
      readdirSync(path.join(PACKAGE, root), { recursive: true, encoding: "utf-8" })
        .filter((file) => /\.(?:tsx?|mdx)$/.test(file))
        .map((file) => path.posix.join(root, file.split(path.sep).join("/")))
        .filter((file) => GRID_MODULE.test(readFileSync(path.join(PACKAGE, file), "utf-8"))),
    );
    expect(reachers.filter((file) => !file.startsWith(`${OUTPUT_DIR}/`))).toEqual([
      "src/icons/index.ts",
    ]);
    expect(ui).not.toHaveProperty("IconSvg");
    expect(icons).not.toHaveProperty("IconSvg");
  });
});
