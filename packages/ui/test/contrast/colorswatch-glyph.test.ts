import { describe, expect, it } from "vitest";

// CMP-031's glyph rule (catalogue Tokens line, D02 C12): the `check` and the `lock` badge take
// `color.text.inverse` or `color.text.on-action`, whichever is at least 3:1 on the swatch. The swatch
// defaults to `inverse`; this pins that default against the two shipped drawing colours in every theme
// (the a11y audit's 8.98 / 10.42, 4.01 / 3.45 and 8.98 / 10.42) and the two story stand-ins, and shows
// why `on-action` cannot be the default (it fails both drawing colours in dark). Plain .mjs tooling loads untyped, as in label-on-fill.test.ts.

type Theme = Record<string, { $value: unknown } | undefined>;
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();

const GLYPH = 3;
// The two drawing colours, plus the two stand-ins the stories borrow (Violet, Grey) until A5's palette.
const SWATCHES = [
  "color.drawing.default",
  "color.drawing.selected",
  "color.node.logic",
  "color.neutral.default",
];
const DRAWING = SWATCHES.slice(0, 2);

function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`colorswatch-glyph: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

describe("CMP-031 glyph contrast on the swatch", () => {
  it("covers the three themes", () => {
    expect(Object.keys(themes).sort()).toEqual(["dark", "high-contrast", "light"]);
  });

  for (const [name, theme] of Object.entries(themes)) {
    for (const swatch of SWATCHES) {
      it(`${name}: text.inverse is at least 3:1 on ${swatch}`, () => {
        const ratio = math.contrastRatio(hexOf(theme, "color.text.inverse"), hexOf(theme, swatch));
        expect(ratio).toBeGreaterThanOrEqual(GLYPH);
      });
    }
  }

  it("dark: text.on-action is below 3:1 on both drawing colours, so it is never the default", () => {
    const dark = themes["dark"] as Theme;
    for (const swatch of DRAWING) {
      expect(
        math.contrastRatio(hexOf(dark, "color.text.on-action"), hexOf(dark, swatch)),
        `dark text.on-action on ${swatch} now reaches 3:1: the reason ColorSwatch defaults glyphTone to ` +
          `"inverse" no longer holds, so revisit that default and the catalogue's glyph rule (C12)`,
      ).toBeLessThan(GLYPH);
    }
  });
});
