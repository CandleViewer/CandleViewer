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
import { ICONS, type IconEntry, type IconName } from "../../src/icons/registry.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
const CATEGORIES = ["navigation", "action", "status", "chart", "trading", "rule-graph"];
/** An entry as its type declares it: the `as const` entries differ in which keys they carry. */
const entry = (name: IconName): IconEntry => ICONS[name];

/**
 * The 13 custom trading glyphs of E05-D02 §7.12 (docs/design/E05/E05-D02-rest.md), as its table
 * gives them: the registry description, verbatim (the registry ends each with a full stop), then
 * 16 where the smallest size is "16 px minimum": their detail closes up at 12 px (§6 J24).
 */
const TRADING_SET: Readonly<Record<string, readonly [string, 16?]>> = {
  "chase-limit": ["Limit order that follows the price", 16],
  estimated: ["The value is inferred, not reported by the exchange"],
  "flatten-all": ["Close every position at market", 16],
  "heatmap-convention-swap": ["Swap which side the heatmap colours show as bid and ask", 16],
  "iceberg-order": ["Order shown in visible slices with a hidden remainder", 16],
  "native-sl-shield": ["A native exchange stop-loss protects the position", 16],
  "node-action": ["Rule node: what the rule does"],
  "node-comment": ["Rule node: a note outside the rule"],
  "node-condition": ["Rule node: a comparison that is true or false"],
  "node-logic-gate": ["Rule node: combines inputs (all, any, none, at least n)"],
  "node-trigger": ["Rule node: what starts an evaluation"],
  "one-click-arm": ["One-click trading is armed"],
  twap: ["Order split evenly over a time window", 16],
};

/**
 * The base set: E05-D02's 47 `icon/{name}` glyphs, with `locked` named `lock` as the merged specs
 * name it, and `unlock`, which the interface slice added.
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
  it("registers the whole base set and the 13 trading glyphs, and no other name", () => {
    expect(NAMES).toEqual([...BASE_SET, ...Object.keys(TRADING_SET)].sort());
  });

  it("registers each trading glyph as CandleViewer's own, as E05-D02 §7.12's table gives it", () => {
    for (const [name, [description, minimumPx]] of Object.entries(TRADING_SET)) {
      expect(ICONS[name as IconName], name).toMatchObject({
        source: "custom/E05-T06",
        description: `${description}.`,
      });
      expect(entry(name as IconName).minimumPx, name).toBe(minimumPx);
    }
    const custom = NAMES.filter((name) => ICONS[name].source.startsWith("custom/"));
    expect(custom).toEqual(Object.keys(TRADING_SET));
    // "16 px minimum" marks a trading glyph only: no base glyph carries the mark.
    const marked = NAMES.filter((name) => "minimumPx" in entry(name));
    expect(marked).toEqual(custom.filter((name) => TRADING_SET[name]?.[1] === 16));
  });

  it("gives every name exactly one component, and every component exactly one name", () => {
    expect(Object.keys(ICON_COMPONENTS)).toEqual(NAMES);
    expect(new Set(Object.values(ICON_COMPONENTS)).size).toBe(NAMES.length);
    expect(NAMES.map((name) => ICON_COMPONENTS[name].name)).toEqual(NAMES.map(componentName));
    // A size form (`<name>.<size>.svg`) is a second drawing of its name, never a name of its own.
    const forms = iconSources().flatMap(({ name, forms = {} }) =>
      Object.keys(forms).map((size) => `${componentName(`${name}-${size}`)}.tsx`),
    );
    const modules = readdirSync(path.join(PACKAGE, OUTPUT_DIR)).filter((f) => f.endsWith(".tsx"));
    expect(modules.sort()).toEqual(
      [...NAMES.map((name) => `${componentName(name)}.tsx`), ...forms].sort(),
    );
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
