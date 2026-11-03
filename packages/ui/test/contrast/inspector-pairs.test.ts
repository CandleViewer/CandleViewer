import { describe, expect, it } from "vitest";

// The pairs apps/web's statechart inspector binds that axe cannot see (E42-S08 §4.4, BQ-6; E42-D05 §11 SI-1, SI-4,
// §16): the drawing's SVG strokes and fills, the latch's octagon and the danger banner's text. Each mark sits on a
// leaf box (`surface.raised`) or on the page (`surface.app`, the region and the groups have no fill). A mark that
// carries meaning without words, 3:1 (WCAG 1.4.11): the current state's 3 px border, the edges and their heads, the
// initial dot, the box, final and group outlines (the picture of nesting and of the parallel regions) and the
// octagon. Text 4.5:1 (1.4.3): the labels, the group labels and the banner. Plain .mjs tooling loads untyped, as in
// pageheader-auditrow-pairs.

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
    throw new Error(`inspector-pairs: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

/** [foreground, background, bar]. */
type Pair = readonly [string, string, number];

const SURFACES = ["color.surface.raised", "color.surface.app"];

const PAIRS: readonly Pair[] = [
  // The current state's border (D05 §16 "the diagram's current state"), on a leaf or a group.
  ...SURFACES.map((bg): Pair => ["color.border.selected", bg, 3]),
  // The edges, their heads, the initial dot (D05 §16 "diagram edges") and the box, final and group outlines,
  // across boxes and the page (A-1137-04: `border.default` read 1.4 to 1.6 : 1 there).
  ...SURFACES.map((bg): Pair => ["color.text.tertiary", bg, 3]),
  // The latch's octagon, in a table cell and in a rowless line (D05 §16 "glyphs on raised").
  ...SURFACES.map((bg): Pair => ["color.status.danger.strong", bg, 3]),
  // A leaf's label and its word "current"; a group's label on the page.
  ["color.text.primary", "color.surface.raised", 4.5],
  ["color.text.secondary", "color.surface.app", 4.5],
  // `machine.latched_effect`, CMP-028 danger (D05 §16 "banners").
  ["color.text.primary", "color.status.danger.subtle", 4.5],
];

describe("statechart inspector contrast (E42-S08; E42-D05 §16)", () => {
  it.each(["dark", "light", "high-contrast"])(
    "%s: every pair the drawing and the latch bind",
    (name) => {
      const theme = themes[name] as Theme;
      for (const [fg, bg, bar] of PAIRS) {
        const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
        expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
      }
    },
  );
});
