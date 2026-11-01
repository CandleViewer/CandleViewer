// E11-T04 (BQ-T04-03, BQ-T04-07): the colour slots the engine reads, as data. The engine owns the
// list so it never imports the design system (C-2.16); the names mirror E11-D05 §4.1 (chart chrome),
// §4.1b (engine-chrome aliases) and §4.2 / §5.3 (series and ramp stops). The order is the packed
// order (`packTheme`) and is append-only: a slot is never renamed or reordered.
//
// Not here: the ten `color.cvd.heatmap.*` stops (no engine route until G16's prefix lands) and
// `color.chart.line` / `.baseline` (E12-D09's, PROPOSED there).

export const THEME_SLOTS = [
  // §4.1 chart chrome
  "color.chart.axis",
  "color.chart.grid.major",
  "color.chart.grid.minor",
  "color.chart.crosshair",
  "color.chart.watermark",
  "color.chart.pane.bg.default",
  "color.chart.pane.bg.focused",
  "color.chart.replay.border",
  // §4.1b engine-chrome aliases
  "color.chart.boundary",
  "color.chart.rule",
  "color.chart.hatch.texture",
  "color.chart.pill.bg",
  "color.chart.pill.border",
  "color.chart.pill.text.default",
  "color.chart.pill.text.inverse",
  "color.chart.pill.text.on-marker",
  "color.chart.marker.goto",
  "color.chart.focus.ring",
  // §4.2 series and the delta ramp's ±1 ends
  "color.candle.up",
  "color.candle.down",
  "color.candle.wick",
  "color.buy.default",
  "color.sell.default",
  "color.footprint.imbalance",
  // §5.3 intensity ramp stops (the delta ramp's ±ε stops are bid.1 / ask.1)
  "color.heatmap.zero",
  "color.heatmap.bid.1",
  "color.heatmap.bid.2",
  "color.heatmap.bid.3",
  "color.heatmap.bid.4",
  "color.heatmap.bid.5",
  "color.heatmap.ask.1",
  "color.heatmap.ask.2",
  "color.heatmap.ask.3",
  "color.heatmap.ask.4",
  "color.heatmap.ask.5",
] as const;

export type ThemeSlot = (typeof THEME_SLOTS)[number];

export const SLOT_COUNT = THEME_SLOTS.length;

/** Slot name → its index in `THEME_SLOTS` (and its RGBA quad in `packTheme`'s output). */
export const SLOT_INDEX: Readonly<Record<ThemeSlot, number>> = Object.freeze(
  Object.fromEntries(THEME_SLOTS.map((s, i) => [s, i])) as Record<ThemeSlot, number>,
);

/**
 * How a pair is gated (BQ-T04-07): `text` ≥ 4.5:1, `non-text` ≥ 3:1, `decorative` is listed and
 * exempt by class (E11-D05 Q4: eight decorative slots, measured on the ninth,
 * pane.bg.default), never by silence.
 */
export type PairClass = "text" | "non-text" | "decorative";

export interface SlotPair {
  readonly fg: ThemeSlot;
  readonly bg: ThemeSlot;
  readonly cls: PairClass;
}

const PANE: ThemeSlot = "color.chart.pane.bg.default";
const pair = (fg: ThemeSlot, cls: PairClass, bg: ThemeSlot = PANE): SlotPair =>
  Object.freeze({ fg, bg, cls });

/**
 * Every fg/bg pair the engine draws, with its contrast class (E11-D05 §4.1, §4.1b, §4.2, §10.1).
 * A packages/ui test measures it over the three themes' token build (PR-5); the engine stays free
 * of token values.
 */
export const ENGINE_SLOT_PAIRS: readonly SlotPair[] = Object.freeze([
  pair("color.chart.axis", "text"),
  pair("color.chart.grid.major", "decorative"),
  pair("color.chart.grid.minor", "decorative"),
  pair("color.chart.crosshair", "non-text"),
  pair("color.chart.crosshair", "non-text", "color.chart.grid.major"),
  pair("color.chart.crosshair", "non-text", "color.chart.grid.minor"),
  pair("color.chart.watermark", "decorative"),
  pair("color.chart.pane.bg.focused", "decorative"),
  pair("color.chart.replay.border", "non-text"),
  pair("color.chart.boundary", "non-text"),
  pair("color.chart.rule", "decorative"),
  pair("color.chart.hatch.texture", "decorative"),
  pair("color.chart.pill.bg", "decorative"),
  pair("color.chart.pill.border", "decorative", "color.chart.pill.bg"),
  pair("color.chart.pill.text.default", "text", "color.chart.pill.bg"),
  pair("color.chart.pill.text.inverse", "text", "color.chart.crosshair"),
  pair("color.chart.pill.text.inverse", "text", "color.candle.up"),
  pair("color.chart.pill.text.inverse", "text", "color.candle.down"),
  pair("color.chart.pill.text.on-marker", "text", "color.chart.marker.goto"),
  pair("color.chart.marker.goto", "non-text"),
  pair("color.chart.focus.ring", "non-text"),
  pair("color.candle.up", "non-text"),
  pair("color.candle.down", "non-text"),
  pair("color.candle.wick", "non-text"),
  pair("color.buy.default", "non-text"),
  pair("color.sell.default", "non-text"),
  pair("color.footprint.imbalance", "non-text"),
  pair("color.heatmap.bid.1", "non-text"),
  pair("color.heatmap.bid.2", "non-text"),
  pair("color.heatmap.bid.3", "non-text"),
  pair("color.heatmap.bid.4", "non-text"),
  pair("color.heatmap.bid.5", "non-text"),
  pair("color.heatmap.ask.1", "non-text"),
  pair("color.heatmap.ask.2", "non-text"),
  pair("color.heatmap.ask.3", "non-text"),
  pair("color.heatmap.ask.4", "non-text"),
  pair("color.heatmap.ask.5", "non-text"),
]);
