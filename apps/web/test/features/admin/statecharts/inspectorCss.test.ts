/**
 * E42-S08 (#1137) §4.4: the drawing's stylesheet as text (jsdom resolves no `forced-colors` media
 * and paints nothing, so the real browser's computed values are the e2e's). Every base rule that
 * fills or strokes a mark has its forced-colours twin, the same selector setting a system colour,
 * so no base rule outranks the forced block (A-1137-03); and no stroke is `border.default`, which
 * reads 1.4 to 1.6 : 1 on the page: the outlines are `text.tertiary`, as the edges are, the pair
 * `packages/ui/test/contrast/inspector-pairs.test.ts` pins at 3:1 in every theme (A-1137-04). The
 * kind counters' headers wrap there too, never cut (A-1137-d05).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SHEET = resolve(
  import.meta.dirname,
  "../../../../src/features/admin/statecharts/inspector.css",
);
const FORCED = "@media (forced-colors: active)";
const SYSTEM = new Set(["Canvas", "CanvasText", "Highlight", "HighlightText", "GrayText"]);

interface Rule {
  readonly selectors: readonly string[];
  readonly declarations: ReadonlyMap<string, string>;
}

/** The flat rules of a block of CSS (no nesting), comments removed. */
function rulesOf(css: string): Rule[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectors = "", body = ""]) => ({
    selectors: selectors
      .split(",")
      .map((selector) => selector.trim())
      .filter((selector) => selector !== ""),
    declarations: new Map(
      body
        .split(";")
        .map((declaration) => declaration.trim())
        .filter((declaration) => declaration.includes(":"))
        .map((declaration): [string, string] => {
          const colon = declaration.indexOf(":");
          return [declaration.slice(0, colon).trim(), declaration.slice(colon + 1).trim()];
        }),
    ),
  }));
}

const text = readFileSync(SHEET, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const at = text.indexOf(FORCED);
const base = rulesOf(text.slice(0, at));
const forced = rulesOf(text.slice(text.indexOf("{", at) + 1, text.lastIndexOf("}")));

/** Each selector of a base rule that sets `property`, with its value. */
const setting = (rules: readonly Rule[], property: string): [string, string][] =>
  rules.flatMap((rule) => {
    const value = rule.declarations.get(property);
    return value === undefined ? [] : rule.selectors.map((s): [string, string] => [s, value]);
  });

describe("the drawing's stylesheet (inspector.css)", () => {
  it("test_inspector_css_has_its_forced_colours_block_after_the_base_rules", () => {
    expect(at).toBeGreaterThan(0);
    expect(base.length).toBeGreaterThan(0);
    expect(forced.length).toBeGreaterThan(0);
  });

  it.each(["fill", "stroke"])(
    "test_inspector_css_every_base_%s_has_a_forced_colours_twin_in_a_system_colour",
    (property) => {
      const twins = new Map(setting(forced, property));
      const painted = setting(base, property).filter(([, value]) => value !== "none");
      expect(painted.length).toBeGreaterThan(0);
      for (const [selector] of painted) {
        expect(twins.has(selector), `${selector}: no ${property} in ${FORCED}`).toBe(true);
        expect(SYSTEM.has(twins.get(selector) ?? ""), selector).toBe(true);
      }
    },
  );

  it("test_inspector_css_no_stroke_is_border_default", () => {
    const strokes = setting(base, "stroke");
    expect(strokes.length).toBeGreaterThan(0);
    for (const [selector, value] of strokes) {
      expect(value, selector).not.toBe("var(--color-border-default)");
    }
    // The box, final and group outlines are the edges' text.tertiary (D05 §16's 3:1 pair).
    for (const outline of [
      ".cv-inspector-diagram__box",
      ".cv-inspector-diagram__final",
      ".cv-inspector-diagram__group",
    ]) {
      expect(new Map(strokes).get(outline), outline).toBe("var(--color-text-tertiary)");
    }
  });
});

describe("the kind counters' headers (inspector.css)", () => {
  it("test_inspector_css_the_kind_counters_headers_wrap_never_cut", () => {
    // No grid, so no echo: a header too long for its column under 1.4.12 wraps (A-1137-d05).
    const label = base.find((rule) =>
      rule.selectors.includes(".cv-inspector-counters .cv-table__label"),
    );
    expect(label?.declarations.get("white-space")).toBe("normal");
    expect(label?.declarations.get("overflow-wrap")).toBe("anywhere");
  });
});
