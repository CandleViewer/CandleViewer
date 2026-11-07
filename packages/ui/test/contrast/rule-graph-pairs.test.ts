import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The rule graph's contrast pairs (E37-D03 §9.1, §9.4): the 14 rows D03 proposes (P7, P14 to P20,
// P22 to P24 and P31 to P33) and the six aliases (TP-1 to TP-6) under their own names. Each row is
// registered in tools/contrast/pairs.mjs (the contrast gate), and the token values are held here per
// theme, as fuzzylist-pairs does. Plain .mjs tooling loads untyped, as in select-option-reason.

type Theme = Record<string, { $value: unknown } | undefined>;
type Row = { fg: string; bg: string; threshold: number };
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const gate = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/pairs.mjs" as string
)) as {
  PAIRS: readonly Row[];
};
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();
const dark = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../../tokens/semantic-dark.tokens.json"), "utf-8"),
) as Record<string, { $description?: string } | undefined>;

function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`rule-graph-pairs: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

/** [foreground, background, bar]: text 4.5:1 (WCAG 1.4.3), an edge, a port or a ring 3:1 (1.4.11). */
type Pair = readonly [string, string, number];

const CANVAS = "color.surface.canvas";
const RAISED = "color.surface.raised";
/** P16 to P20: border.selected on the canvas, the card, the minimap well, the marquee's tint, a hovered node. */
const OUTLINED = [
  CANVAS,
  RAISED,
  "color.surface.sunken",
  "color.action.selected",
  "color.surface.hover",
];
/** D03 §9.4's 14 rows, P7 to P33 in order: an outline straddles the card edge, checked on both sides. */
const D03_ROWS: readonly Pair[] = [
  ["color.text.primary", "color.surface.sunken", 4.5],
  ["color.focus.ring", "color.status.warning.subtle", 3],
  ["color.focus.ring", "color.status.danger.subtle", 3],
  ...OUTLINED.map((bg): Pair => ["color.border.selected", bg, 3]),
  ...["condition", "action", "logic"].map((n): Pair => [`color.node.${n}`, RAISED, 3]),
  ["color.status.danger.default", CANVAS, 3],
  ["color.status.danger.default", RAISED, 3],
  ["color.status.warning.default", CANVAS, 3],
];
/** TP-1 to TP-6: the edges on the canvas, the ports on the canvas and on the card. */
const ALIASES = {
  "color.edge.default": "TP-1",
  "color.edge.selected": "TP-2",
  "color.edge.invalid": "TP-3",
  "color.port.ring": "TP-4",
  "color.port.compatible": "TP-5",
  "color.port.incompatible": "TP-6",
} as const;
const ALIAS_ROWS: readonly Pair[] = Object.keys(ALIASES).flatMap((fg) =>
  (fg.startsWith("color.edge.") ? [CANVAS] : [CANVAS, RAISED]).map((bg): Pair => [fg, bg, 3]),
);

describe("the rule graph's contrast pairs (E37-D03 §9.1, §9.4)", () => {
  it("registers D03's 14 rows and the 9 alias rows in the contrast gate", () => {
    expect(D03_ROWS).toHaveLength(14);
    expect(ALIAS_ROWS).toHaveLength(9);
    for (const [fg, bg, threshold] of [...D03_ROWS, ...ALIAS_ROWS]) {
      expect(gate.PAIRS, `${fg} on ${bg}`).toContainEqual({ fg, bg, threshold });
    }
  });

  it.each(["dark", "light", "high-contrast"])("%s: every row meets its bar", (name) => {
    const theme = themes[name] as Theme;
    for (const [fg, bg, bar] of [...D03_ROWS, ...ALIAS_ROWS]) {
      const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
      expect(Math.floor(ratio * 1000) / 1000, `${fg} on ${bg}`).toBeGreaterThanOrEqual(bar);
    }
  });

  it("describes each alias with the D03 pair it names", () => {
    for (const [name, id] of Object.entries(ALIASES)) {
      expect(dark[name]?.$description, name).toContain(`E37-D03 ${id}`);
    }
  });
});
