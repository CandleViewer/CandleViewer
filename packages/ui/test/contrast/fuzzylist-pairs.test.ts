import { describe, expect, it } from "vitest";

// The pairs fuzzylist.css and symbolsearch.css bind (E08-D05 §9.5): the row's text on the overlay, the hover fill and
// the active fill; the header; the active bar; the delisted glyph; the ARMED pill. axe skips aria-disabled options, so
// it never measures a delisted or T2 row: the token values are held here, per theme, until PR C registers the pairs in
// tools/contrast/pairs.mjs. Plain .mjs tooling loads untyped, as in select-option-reason.

type Theme = Record<string, { $value: unknown } | undefined>;
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();

function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`fuzzylist-pairs: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

/** [foreground, background, bar]: text 4.5:1 (WCAG 1.4.3), a glyph or the bar 3:1 (1.4.11). */
type Pair = readonly [string, string, number];

function pairsOf(hover: string): Pair[] {
  const rows = ["color.surface.overlay", hover, "color.surface.selected"];
  const text = [
    "color.text.primary",
    "color.text.secondary",
    "color.data-confidence.delisted.text",
  ];
  return [
    ...text.flatMap((fg) => rows.map((bg): Pair => [fg, bg, 4.5])),
    ...rows.map((bg): Pair => ["color.data-confidence.delisted.indicator", bg, 3]),
    ["color.text.tertiary", "color.surface.overlay", 4.5],
    ["color.border.selected", "color.surface.selected", 3],
    ["color.text.primary", "color.status.warning.subtle", 4.5],
    ["color.status.warning.strong", "color.status.warning.subtle", 3],
  ];
}

describe("FuzzyList and SymbolSearchInput contrast (E08-D05 §9.5)", () => {
  it.each(["light", "dark", "high-contrast"])("%s: every pair the two stylesheets bind", (name) => {
    const theme = themes[name] as Theme;
    // Light's hover equals the overlay, so a hovered row takes the selected fill there (fuzzylist.css).
    const hover = name === "light" ? "color.surface.selected" : "color.surface.hover";
    for (const [fg, bg, bar] of pairsOf(hover)) {
      const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
      expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
    }
  });
});
