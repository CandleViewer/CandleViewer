import { describe, expect, it } from "vitest";
import { contrastRatio, parseHex } from "../../src/components/internal/contrast.js";

// BQ-17: CMP-228's ported ratio stays in parity with the E05-T05 gate's `color-math.mjs` over every
// colour pair of every resolved theme (text tokens on surface tokens). Plain .mjs tooling loads untyped,
// as in colorswatch-glyph.test.ts.
type Theme = Record<string, { $value: unknown } | undefined>;
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();

const hexes = (theme: Theme, prefix: string): string[] =>
  Object.entries(theme)
    .filter(([name, t]) => name.startsWith(prefix) && typeof t?.$value === "string")
    .map(([, t]) => String(t?.$value))
    .filter((v) => /^#[0-9A-Fa-f]{6}$/.test(v));

describe("CMP-228 contrast ratio parity with tools/contrast", () => {
  for (const [name, theme] of Object.entries(themes)) {
    it(`${name}: every color.text.* on every color.surface.* matches to 1e-9`, () => {
      const texts = hexes(theme, "color.text.");
      const surfaces = hexes(theme, "color.surface.");
      expect(texts.length * surfaces.length).toBeGreaterThan(0);
      for (const fg of texts)
        for (const bg of surfaces)
          expect(contrastRatio(fg, bg)).toBeCloseTo(math.contrastRatio(fg, bg), 9);
    });
  }

  it("reads #RGB shorthand and rejects non-hex values", () => {
    expect(parseHex("#fff")).toEqual([255, 255, 255]);
    expect(contrastRatio("#000", "#FFFFFF")).toBeCloseTo(21, 9);
    expect(contrastRatio("var(--x)", "#fff")).toBeNull();
    expect(contrastRatio("#ffffff80", "#fff")).toBeNull();
  });
});
