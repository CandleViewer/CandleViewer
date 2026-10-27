import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  componentName,
  iconSources,
  OUTPUT_DIR,
  parseIconSource,
} from "../../scripts/build-icons.mjs";
import { ICON_COMPONENTS } from "../../src/icons/generated/components.js";
import { ICONS, type IconName } from "../../src/icons/registry.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
const CATEGORIES = ["navigation", "action", "status", "chart", "trading", "rule-graph"];

/**
 * The base set: E05-D02's 47 `icon/{name}` glyphs, with `locked` named `lock` as the merged specs
 * name it, and `unlock`, which the interface slice added. The trading glyphs join it later.
 */
const BASE_SET = [
  "arrow-down",
  "arrow-up",
  "arrow-up-down",
  "calendar",
  "cancelled",
  "check",
  "chevron-down",
  "chevron-left",
  "chevron-right",
  "chevron-up",
  "chevrons-up-down",
  "close",
  "copy",
  "crosshair",
  "danger",
  "delete",
  "disconnected",
  "download",
  "drag-handle",
  "edit",
  "error",
  "external-link",
  "filter",
  "help",
  "hide",
  "info",
  "lock",
  "maximize",
  "minimize",
  "minus",
  "more-horizontal",
  "more-vertical",
  "notifications",
  "pending",
  "pin",
  "plus",
  "redo",
  "refresh",
  "search",
  "settings",
  "show",
  "success",
  "undo",
  "unlock",
  "upload",
  "warning",
  "zoom-in",
  "zoom-out",
];

describe("the icon registry (src/icons/registry.ts)", () => {
  it("registers the whole base set, under the names the merged specs use", () => {
    expect(NAMES).toEqual(BASE_SET);
  });

  it("gives every name exactly one component, and every component exactly one name", () => {
    expect(Object.keys(ICON_COMPONENTS)).toEqual(NAMES);
    expect(new Set(Object.values(ICON_COMPONENTS)).size).toBe(NAMES.length);
    expect(NAMES.map((name) => ICON_COMPONENTS[name].name)).toEqual(NAMES.map(componentName));
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
});
