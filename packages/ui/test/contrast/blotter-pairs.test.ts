import { describe, expect, it } from "vitest";

// The pairs E29-S01's blotter stylesheets bind (E29-D04 §5): CMP-116's digits and accent bar on the row fills,
// CMP-129's word on the group header, and CMP-105's filter list on the CMP-017 panel. The token values are held here
// per theme, as fuzzylist-pairs and select-option-reason do; CMP-055 and CMP-057 draw only CMP-001, CMP-002 and
// CMP-011, whose pairs are theirs. Plain .mjs tooling loads untyped.

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
    throw new Error(`blotter-pairs: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

/** [foreground, background, bar]: text 4.5:1 (WCAG 1.4.3); a bar, a box edge, a glyph or a ring 3:1 (1.4.11). */
type Pair = readonly [string, string, number];

/** The data row's fills (E29-D04 §2.1) and the story canvas. */
const ROWS = ["color.surface.raised", "color.surface.hover", "color.surface.selected"];
const BARS = ["color.buy.default", "color.sell.default", "color.neutral.default"];

/** The filter list's active row: hover, but selected in light, where hover equals the overlay (Q-21). */
function pairsOf(name: string): Pair[] {
  const active = name === "light" ? "color.surface.selected" : "color.surface.hover";
  const panel = ["color.surface.overlay", active];
  return [
    // CMP-116: neutral digits on every row fill; the accent bar on every row fill and the canvas.
    ...[...ROWS, "color.surface.app"].map((bg): Pair => ["color.text.primary", bg, 4.5]),
    ...BARS.flatMap((fg) => [...ROWS, "color.surface.app"].map((bg): Pair => [fg, bg, 3])),
    // CMP-116's provisional tag (E29-S04; E29-D02:252): its words on the pending tag's fill, a pair the gate
    // registers among the notice tints (tools/contrast/pairs.mjs).
    ["color.text.primary", "color.status.info.subtle", 4.5],
    // CMP-129 display: the word on the account group header.
    ["color.text.primary", "color.surface.canvas", 4.5],
    // CMP-105: the option text, the plate's edge, the chosen plate and the active row's inset ring.
    ...panel.map((bg): Pair => ["color.text.primary", bg, 4.5]),
    ...panel.map((bg): Pair => ["color.text.tertiary", bg, 3]),
    ...panel.map((bg): Pair => ["color.action.primary.default", bg, 3]),
    ["color.focus.ring", active, 3],
    ["color.text.on-action", "color.action.primary.default", 3],
  ];
}

/**
 * CMP-099 PrintExportBar (E29-S04; E29-D04 §2.8.9): each format is a CMP-001 secondary button, its label
 * color.text.primary on the secondary fill (label-on-fill.json's `secondary` role registers it for the gate), and the
 * running arc takes the label's colour, because CMP-038's own arc colour would fail there.
 */
describe("CMP-099's contrast pairs (E29-S04)", () => {
  it.each(["dark", "light", "high-contrast"])(
    "%s: the label, and the running arc in its colour, on the secondary fill",
    (name) => {
      const theme = themes[name] as Theme;
      const ratio = math.contrastRatio(
        hexOf(theme, "color.text.primary"),
        hexOf(theme, "color.action.secondary.default"),
      );
      expect(Math.floor(ratio * 1000) / 1000).toBeGreaterThanOrEqual(4.5);
    },
  );

  it("CMP-038's own arc colour would fail on the secondary fill in dark, so the arc takes the label's", () => {
    const dark = themes["dark"] as Theme;
    const ratio = math.contrastRatio(
      hexOf(dark, "color.action.primary.default"),
      hexOf(dark, "color.action.secondary.default"),
    );
    expect(ratio).toBeLessThan(3);
  });
});

describe("the blotter components' contrast pairs (E29-D04 §5)", () => {
  it.each(["dark", "light", "high-contrast"])(
    "%s: every opaque pair the stylesheets bind",
    (name) => {
      const theme = themes[name] as Theme;
      for (const [fg, bg, bar] of pairsOf(name)) {
        const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
        expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
      }
    },
  );

  it("matches E29-D04 §5's measured closest margin: the sell bar on a selected dark row, 3.13:1", () => {
    const dark = themes["dark"] as Theme;
    const ratio = math.contrastRatio(
      hexOf(dark, "color.sell.default"),
      hexOf(dark, "color.surface.selected"),
    );
    expect(Math.round(ratio * 100) / 100).toBe(3.13);
  });
});

/**
 * E29-S04's atoms (E29-D04 §2.3, §2.8.9, §2.9): CMP-011's toggle at rest, hovered and pressed, its ring on the pressed
 * fill and on the toolbar surfaces; CMP-116's provisional tag; CMP-099's secondary buttons, whose running arc takes the
 * label's colour.
 */
const ATOMS: readonly Pair[] = [
  ["color.text.secondary", "color.neutral.subtle", 4.5],
  ["color.text.primary", "color.action.secondary.hover", 4.5],
  ["color.text.primary", "color.action.selected", 4.5],
  ["color.border.selected", "color.action.selected", 3],
  ...["color.surface.app", "color.surface.canvas", "color.surface.raised"].map((bg): Pair => [
    "color.border.selected",
    bg,
    3,
  ]),
  ["color.text.primary", "color.status.info.subtle", 4.5],
  ["color.text.primary", "color.action.secondary.default", 4.5],
];

describe("the Fills tab and SCR-078 atoms' contrast pairs (E29-S04)", () => {
  it.each(["dark", "light", "high-contrast"])("%s: every opaque pair the atoms bind", (name) => {
    const theme = themes[name] as Theme;
    for (const [fg, bg, bar] of ATOMS) {
      const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
      expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
    }
  });

  it.each(["dark", "light", "high-contrast"])(
    "%s: hover moves a resting toggle's fill visibly (1.54:1 dark and high contrast, 1.35:1 light)",
    (name) => {
      const theme = themes[name] as Theme;
      const ratio = math.contrastRatio(
        hexOf(theme, "color.action.secondary.hover"),
        hexOf(theme, "color.neutral.subtle"),
      );
      expect(ratio).toBeGreaterThanOrEqual(1.3);
    },
  );

  it.each(["dark", "light", "high-contrast"])(
    "%s: a pressed toggle's fill alone is within 1.2:1 of the rest fill, so its ring carries the state",
    (name) => {
      const theme = themes[name] as Theme;
      for (const fill of ["color.action.selected", "color.surface.selected"]) {
        const ratio = math.contrastRatio(hexOf(theme, fill), hexOf(theme, "color.neutral.subtle"));
        expect(ratio, fill).toBeLessThan(1.21);
      }
    },
  );

  it("CMP-038's own arc colour would fail on the secondary fill in dark (2.58:1), so the arc takes the label's", () => {
    const dark = themes["dark"] as Theme;
    const ratio = math.contrastRatio(
      hexOf(dark, "color.action.primary.default"),
      hexOf(dark, "color.action.secondary.default"),
    );
    expect(Math.round(ratio * 100) / 100).toBe(2.58);
  });
});
