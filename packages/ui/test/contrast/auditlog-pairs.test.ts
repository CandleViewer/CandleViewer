import { describe, expect, it } from "vitest";

// The pairs the audit log's packages/ui parts bind (E42-D04 §15): the grid row's words on the zebra, hover and selected
// fills, its high-severity rule and the selected row (D2, D14), the T2 look (§12.1) and the diff part (§6). Text 4.5:1
// (WCAG 1.4.3), a glyph, a rule or a ring 3:1 (1.4.11). They are held here per theme, as pageheader-auditrow-pairs
// does; the screens' own pairs (the incident banner, SCR-136's drawer) come with them, and the real-browser proof is
// CI's axe on R-360. Plain .mjs tooling loads untyped, as in fuzzylist-pairs.

type Theme = Record<string, { $value: unknown } | undefined>;
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();
const THEMES = ["dark", "light", "high-contrast"] as const;

function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`auditlog-pairs: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

const ratio = (theme: string, fg: string, bg: string): number =>
  math.contrastRatio(hexOf(themes[theme] as Theme, fg), hexOf(themes[theme] as Theme, bg));

/** [foreground, background, bar]. */
type Pair = readonly [string, string, number];

/** A grid row's fills: CMP-049's zebra (odd canvas, even raised), hover, and the selected record (D14). */
const ROW_SURFACES = [
  "color.surface.canvas",
  "color.surface.raised",
  "color.surface.hover",
  "color.surface.selected",
];

const PAIRS: readonly (readonly [string, readonly Pair[]])[] = [
  [
    "the grid row's words (severity, outcome, actor, meta)",
    ROW_SURFACES.flatMap((bg): Pair[] => [
      ["color.text.primary", bg, 4.5],
      ["color.text.secondary", bg, 4.5],
    ]),
  ],
  [
    "the high rule, the octagon and the triangle (D2)",
    [
      ...ROW_SURFACES.map((bg): Pair => ["color.status.danger.strong", bg, 3]),
      ["color.status.warning.strong", "color.surface.raised", 3],
    ],
  ],
  ["the selected row's check glyph (D14)", [["color.text.primary", "color.surface.selected", 3]]],
  [
    "the LIVE chip's border",
    [
      ["color.env.live", "color.surface.app", 3],
      ["color.env.live", "color.surface.selected", 3],
    ],
  ],
  [
    "T2 (§12.1): the label and lock in text.tertiary, the reason in text.secondary",
    [
      ["color.text.tertiary", "color.surface.raised", 4.5],
      ["color.text.secondary", "color.surface.raised", 4.5],
      ["color.text.secondary", "color.surface.selected", 4.5],
      ["color.text.secondary", "color.surface.overlay", 4.5],
      ["color.text.secondary", "color.surface.app", 4.5],
    ],
  ],
  [
    "the diff part: 'none' in text.tertiary and the lock in text.secondary on the row, hovered too",
    ROW_SURFACES.filter((bg) => bg !== "color.surface.selected").flatMap((bg): Pair[] => [
      ["color.text.tertiary", bg, 4.5],
      ["color.text.secondary", bg, 3],
    ]),
  ],
  [
    "AD-5's line on danger.subtle: its words and the octagon",
    [
      ["color.text.primary", "color.status.danger.subtle", 4.5],
      ["color.status.danger.strong", "color.status.danger.subtle", 3],
    ],
  ],
];

describe("audit log contrast pairs (E42-D04 §15)", () => {
  for (const [name, pairs] of PAIRS) {
    it.each(THEMES)(`%s: ${name}`, (theme) => {
      for (const [fg, bg, bar] of pairs) {
        const value = Math.floor(ratio(theme, fg, bg) * 1000) / 1000;
        expect(value, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
      }
    });
  }

  it("why a selected row's meta is never text.tertiary: it fails on surface.selected in dark (3.98)", () => {
    expect(ratio("dark", "color.text.tertiary", "color.surface.selected")).toBeLessThan(4.5);
    expect(ratio("dark", "color.text.secondary", "color.surface.selected")).toBeGreaterThanOrEqual(
      4.5,
    );
  });
});
