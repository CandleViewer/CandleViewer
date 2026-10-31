import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The pairs the watchlist stylesheets bind (E08-D07 §7.2: CMP-049's grid additions, CMP-161, CMP-239's compact chip):
// the token values held per theme, as fuzzylist-pairs does. The opaque pairs are registered in
// tools/contrast/pairs.mjs (the contrast gate); §7.3 item 1's Disconnected fallback (text.primary at opacity.muted,
// on the text alone) has an alpha the gate cannot express, so it is composited and held here (§7.2 row 28).

type Theme = Record<string, { $value: unknown } | undefined>;
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();
const primitives = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../../tokens/primitives.tokens.json"), "utf-8"),
) as Record<string, { $value: unknown } | undefined>;
const MUTED = Number(primitives["opacity.muted"]?.$value);

function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`watchlist-pairs: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

/** `fg` at `alpha` over `bg`, composited per channel in sRGB (E08-D07 §7.2's method). */
function over(fg: string, alpha: number, bg: string): string {
  const channel = (hex: string, i: number): number => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return `#${[0, 1, 2]
    .map((i) => Math.round(channel(fg, i) * alpha + channel(bg, i) * (1 - alpha)))
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("")}`;
}

/** [foreground, background, bar]: text 4.5:1 (WCAG 1.4.3), a glyph, a bar or an edge 3:1 (1.4.11). */
type Pair = readonly [string, string, number];

const ROW_FILLS = ["color.surface.raised", "color.surface.hover", "color.surface.selected"];
const PAIRS: readonly Pair[] = [
  // A stale row's demoted text on the active row's fill (§7.2 row 6; its own tint is registered already).
  ["color.data-confidence.stale.text", "color.surface.selected", 4.5],
  // The T2 age chip (row 8).
  ["color.text.inverse", "color.data-confidence.stale.indicator", 4.5],
  // A delisted row's symbol, lock and merged cell on the grid body (row 11).
  ["color.data-confidence.delisted.text", "color.surface.raised", 4.5],
  // A T2 sort header's label and lock on the header row (row 30).
  ["color.text.tertiary", "color.surface.hover", 4.5],
  // DS-CR-2's fallback: ▲/▼ alone in buy or sell, on every row fill (row 26).
  ...ROW_FILLS.flatMap((bg): Pair[] => [
    ["color.buy.default", bg, 3],
    ["color.sell.default", bg, 3],
  ]),
  // A stale column's ⚠ on the header row; the T1 chip's edge on its own fill (rows 18-19).
  ["color.data-confidence.stale.indicator", "color.surface.hover", 3],
  ["color.data-confidence.stale.indicator", "color.status.warning.subtle", 3],
  // The merged delisted cell's glyph on the grid body (row 23).
  ["color.data-confidence.delisted.indicator", "color.surface.raised", 3],
  // Rec's ⚠ on every row fill (§7.1 "REC").
  ...ROW_FILLS.map((bg): Pair => ["color.status.warning.strong", bg, 3]),
];

describe("the watchlist's contrast pairs (E08-D07 §7.2)", () => {
  it.each(["dark", "light", "high-contrast"])(
    "%s: every opaque pair the stylesheets bind",
    (name) => {
      const theme = themes[name] as Theme;
      for (const [fg, bg, bar] of PAIRS) {
        const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
        expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
      }
    },
  );

  it.each(["dark", "light", "high-contrast"])(
    "%s: Disconnected's fallback, text.primary at opacity.muted on surface.sunken, holds 4.5:1",
    (name) => {
      const theme = themes[name] as Theme;
      const sunken = hexOf(theme, "color.surface.sunken");
      const text = over(hexOf(theme, "color.text.primary"), MUTED, sunken);
      expect(math.contrastRatio(text, sunken)).toBeGreaterThanOrEqual(4.5);
    },
  );
});
