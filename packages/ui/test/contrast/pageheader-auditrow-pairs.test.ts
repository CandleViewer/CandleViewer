import { describe, expect, it } from "vitest";

// The pairs pageheader.css and auditrow.css bind (E42-D03 §15, board 10 rows G and K; E42-D04 D2): the header's
// title and meta lines on the page, and the compact rows' text, glyphs and high-severity rule on an Audit tile
// (`surface.raised`) or on the page (`surface.app`, SCR-122's Recent changes). Text 4.5:1 (WCAG 1.4.3), a glyph or the
// rule 3:1 (1.4.11). The danger and warning inks on `surface.raised` are not registered in tools/contrast/pairs.mjs,
// so they are held here, per theme. Plain .mjs tooling loads untyped, as in fuzzylist-pairs.

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
    throw new Error(
      `pageheader-auditrow-pairs: "${name}" does not resolve to an opaque hex colour`,
    );
  }
  return v;
}

/** [foreground, background, bar]. */
type Pair = readonly [string, string, number];

const HEADER: readonly Pair[] = [
  ["color.text.primary", "color.surface.app", 4.5],
  ["color.text.tertiary", "color.surface.app", 4.5],
];

const ROW_SURFACES = ["color.surface.raised", "color.surface.app"];
const ROW_TEXT = ["color.text.primary", "color.text.secondary", "color.text.tertiary"];
const ROW_INKS = ["color.status.danger.strong", "color.status.warning.strong"];

const ROWS: readonly Pair[] = ROW_SURFACES.flatMap((bg) => [
  ...ROW_TEXT.map((fg): Pair => [fg, bg, 4.5]),
  ...ROW_INKS.map((fg): Pair => [fg, bg, 3]),
]);

describe("PageHeader and compact AuditRow contrast (E42-D03 §15)", () => {
  it.each(["light", "dark", "high-contrast"])("%s: every pair the two stylesheets bind", (name) => {
    const theme = themes[name] as Theme;
    for (const [fg, bg, bar] of [...HEADER, ...ROWS]) {
      const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
      expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
    }
  });
});
