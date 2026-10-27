import { describe, expect, it } from "vitest";

// CMP-009's reason line (`color.text.secondary`) and a T2 option's label and lock (`color.text.tertiary`) sit on the
// overlay, and on the hover fill when active. axe skips aria-disabled options, so it never measures them: the token
// values are held here, per theme (D02F a11y audit §4). Plain .mjs tooling loads untyped, as in select-active-ring.

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
    throw new Error(`select-option-reason: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

describe("select option reason and T2 label contrast (WCAG 1.4.3)", () => {
  it.each(["light", "dark", "high-contrast"])(
    "%s: 4.5:1 on the overlay and the hover fill",
    (name) => {
      const theme = themes[name] as Theme;
      for (const text of ["color.text.secondary", "color.text.tertiary"]) {
        for (const surface of ["color.surface.overlay", "color.surface.hover"]) {
          const ratio = math.contrastRatio(hexOf(theme, text), hexOf(theme, surface));
          expect(Math.floor(ratio * 1000) / 1000, `${text} on ${surface}`).toBeGreaterThanOrEqual(
            4.5,
          );
        }
      }
    },
  );
});
