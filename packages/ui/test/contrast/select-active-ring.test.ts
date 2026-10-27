import { describe, expect, it } from "vitest";

// CMP-009's active option rings itself with CMP-039's inset ring (`color.focus.ring`) over the overlay, on top of
// `color.surface.hover` (design ruling #264 issuecomment-6443627262). WCAG 1.4.11 wants 3:1 for a focus indicator;
// axe does not measure it, so the token values are held here, per theme. Plain .mjs tooling loads untyped through a
// string specifier, as in label-on-fill.test.ts.

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
    throw new Error(`select-active-ring: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

describe("select active-option ring contrast (WCAG 1.4.11)", () => {
  it.each(["light", "dark", "high-contrast"])(
    "%s: the ring holds 3:1 on the overlay and on the hover fill",
    (name) => {
      const theme = themes[name] as Theme;
      const ring = hexOf(theme, "color.focus.ring");
      const overlay = hexOf(theme, "color.surface.overlay");
      const hover = hexOf(theme, "color.surface.hover");
      const onOverlay = math.contrastRatio(ring, overlay);
      const onHover = math.contrastRatio(ring, hover);
      console.log(`ring ${name}: ${onOverlay.toFixed(2)}:1 overlay, ${onHover.toFixed(2)}:1 hover`);
      expect(Math.floor(onOverlay * 1000) / 1000).toBeGreaterThanOrEqual(3);
      expect(Math.floor(onHover * 1000) / 1000).toBeGreaterThanOrEqual(3);
    },
  );
});
