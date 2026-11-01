// E11-T04: the pattern / encoding registry and the dash vocabulary, E11-D05 §7 / §7.2 as data.
// A pattern marks estimated, absent or a status, never a side or direction (E25-D05 §9.5,
// PROPOSED; binding through `16` §6 rules 1 and 5 and `26` §5 rules 3–4). Ids and indices are
// append-only: never renamed, never reordered (D05 §7). Geometry is CSS px before device snapping.

import type { ThemeSlot } from "./slots.js";

export type DashId = "dash.4-4" | "dash.2-6" | "dash.2-2" | "dash.4-3" | "dash.3-3";

export interface DashDef {
  readonly id: DashId;
  readonly index: number;
  readonly onPx: number;
  readonly offPx: number;
}

/** D05 §7.2's ids (PROPOSED there, adopted here as the dash-pattern index). */
export const DASHES: readonly DashDef[] = Object.freeze(
  (
    [
      ["dash.4-4", 4, 4],
      ["dash.2-6", 2, 6],
      ["dash.2-2", 2, 2],
      ["dash.4-3", 4, 3],
      ["dash.3-3", 3, 3],
    ] as const
  ).map(([id, onPx, offPx], index) => Object.freeze({ id, index, onPx, offPx })),
);

export type PatternId =
  | "pattern.hatch.estimated"
  | "pattern.dashed.estimated"
  | "pattern.hatch.gap"
  | "pattern.hatch.absent"
  | "pattern.dashed.tested"
  | "pattern.outline.imbalance"
  | "glyph.notch.delta"
  | "indicator.reduced-detail";

export type PatternKind = "hatch" | "dash" | "outline" | "glyph" | "dom";

/**
 * Where the ink comes from: a theme slot, or one of the mark's own colours — `fill` (none of its
 * own: over the present fill), `mark` (the mark's own hue), `side` (the side hue at muted opacity),
 * `delta` (the cell's delta colour) — or `dom` (drawn by the host, not the engine).
 */
export type PatternInk = ThemeSlot | "fill" | "mark" | "side" | "delta" | "dom";

export type PatternMeaning = "estimated" | "gap" | "absent" | "tested" | "imbalance" | "delta-sign";

export interface PatternDef {
  readonly id: PatternId;
  readonly index: number;
  readonly kind: PatternKind;
  readonly meaning: PatternMeaning | "reduced-detail";
  readonly ink: PatternInk;
  readonly opacity: number;
  /** Hatches: line angle (degrees), line width and pitch in px; 0 where not a hatch. */
  readonly angleDeg: number;
  readonly lineWidthPx: number;
  readonly pitchPx: number;
  /** A dashed stroke or a hatch's dashed edges; null when solid or none. */
  readonly dash: DashId | null;
  /** A hatch's edge ink (`pattern.hatch.gap`), else null. */
  readonly edgeInk: ThemeSlot | null;
}

const def = (
  id: PatternId,
  kind: PatternKind,
  meaning: PatternDef["meaning"],
  ink: PatternInk,
  opacity: number,
  hatch: readonly [angleDeg: number, lineWidthPx: number, pitchPx: number],
  dash: DashId | null = null,
  edgeInk: ThemeSlot | null = null,
): Omit<PatternDef, "index"> => ({
  id,
  kind,
  meaning,
  ink,
  opacity,
  angleDeg: hatch[0],
  lineWidthPx: hatch[1],
  pitchPx: hatch[2],
  dash,
  edgeInk,
});

const NO_HATCH = [0, 0, 0] as const;
const BOUNDARY: ThemeSlot = "color.chart.boundary";

/**
 * D05 §7's eight rows, in registry order. E06-D01 §3 states the estimated hatch's 2 px pitch but
 * not its line width: 1 px (a hairline) is this registry's reading, noted under Deviations.
 */
export const PATTERNS: readonly PatternDef[] = Object.freeze(
  [
    def("pattern.hatch.estimated", "hatch", "estimated", "fill", 0.3, [45, 1, 2]),
    def("pattern.dashed.estimated", "dash", "estimated", "mark", 1, [0, 1, 0], "dash.4-3"),
    def(
      "pattern.hatch.gap",
      "hatch",
      "gap",
      "color.chart.hatch.texture",
      1,
      [45, 1, 6],
      "dash.4-4",
      BOUNDARY,
    ),
    def("pattern.hatch.absent", "hatch", "absent", BOUNDARY, 1, [45, 1, 6]),
    def("pattern.dashed.tested", "dash", "tested", "side", 0.7, [0, 1, 0], "dash.4-3"),
    def(
      "pattern.outline.imbalance",
      "outline",
      "imbalance",
      "color.footprint.imbalance",
      1,
      [0, 1.5, 0],
    ),
    def("glyph.notch.delta", "glyph", "delta-sign", "delta", 1, [0, 1, 0]),
    def("indicator.reduced-detail", "dom", "reduced-detail", "dom", 1, NO_HATCH),
  ].map((p, index) => Object.freeze({ ...p, index })),
);

const BY_ID: ReadonlyMap<string, PatternDef> = new Map(PATTERNS.map((p) => [p.id, p]));

/** The registered pattern for `id`, or undefined: an unregistered encoding is never drawn. */
export function patternById(id: string): PatternDef | undefined {
  return BY_ID.get(id);
}
