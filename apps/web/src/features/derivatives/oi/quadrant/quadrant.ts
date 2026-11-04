// E24-S02 (#777) slice 1: the OI/price quadrant lookup. The classification is the server's (`/market/metrics`
// `oi_price_quadrant`, #5341; 24 §7.2): this module only maps the wire enum to how it is drawn and worded.
// It never infers a quadrant from a price or OI change (BQ-4, and the negative test). One table, one place:
// CMP-186's own prop names (`long_build`, `short_cover`, D03 §15.1) are mapped here and nowhere else.

/** The wire enum, as `MetricPoint.v` carries it for `oi_price_quadrant` (#5341). */
export type QuadrantWire = "long_buildup" | "short_covering" | "short_buildup" | "long_unwind";

/** CMP-186's `OiPoint.quadrant` prop spelling (D03 §15.1), kept to this table. */
export type QuadrantProp = "long_build" | "short_cover" | "short_build" | "long_unwind";

export interface QuadrantStyle {
  readonly prop: QuadrantProp;
  /** In words, for the key row, the crosshair readout and the table (never colour alone). */
  readonly words: string;
  /** D03 S54-10 key row: price, then OI. */
  readonly glyphs: "▲▲" | "▲▼" | "▼▲" | "▼▼";
  readonly priceWord: "up" | "down";
  readonly oiWord: "up" | "down";
  /** D03 §4: OI up above the zero line, OI down below. */
  readonly side: "above" | "below";
  /** D03 §4: price up a full-width bar, price down a half-width bar. */
  readonly width: "full" | "half";
  /** D03 §4: colour reinforces the price direction only, the candle slots. */
  readonly token: "color.candle.up" | "color.candle.down";
}

export const QUADRANT_STYLE: Readonly<Record<QuadrantWire, QuadrantStyle>> = {
  long_buildup: {
    prop: "long_build",
    words: "long build-up",
    glyphs: "▲▲",
    priceWord: "up",
    oiWord: "up",
    side: "above",
    width: "full",
    token: "color.candle.up",
  },
  short_covering: {
    prop: "short_cover",
    words: "short covering",
    glyphs: "▲▼",
    priceWord: "up",
    oiWord: "down",
    side: "below",
    width: "full",
    token: "color.candle.up",
  },
  short_buildup: {
    prop: "short_build",
    words: "short build-up",
    glyphs: "▼▲",
    priceWord: "down",
    oiWord: "up",
    side: "above",
    width: "half",
    token: "color.candle.down",
  },
  long_unwind: {
    prop: "long_unwind",
    words: "long unwind",
    glyphs: "▼▼",
    priceWord: "down",
    oiWord: "down",
    side: "below",
    width: "half",
    token: "color.candle.down",
  },
};

/**
 * BQ-4: `null` (unclassified) is a first-class key of the lookup, not a missing one. D03 §4 / S54-16: no
 * bar, the column hatched `pattern.hatch.absent` in `color.chart.boundary`, and excluded from classification.
 * The plot (#534's styled histogram) reads it; the DOM says it in words.
 */
export const NO_QUADRANT_STYLE = {
  words: "unclassified",
  hatch: "pattern.hatch.absent",
  ink: "color.chart.boundary",
} as const;

/** The one lookup the renderer reads: the served enum, or `null` for the neutral hatch. */
export function styleFor(q: QuadrantWire | null): QuadrantStyle | typeof NO_QUADRANT_STYLE {
  return q === null ? NO_QUADRANT_STYLE : QUADRANT_STYLE[q];
}

/** The key row's order (D03 S54-10): ▲▲, ▲▼, ▼▲, ▼▼. */
export const QUADRANT_ORDER: readonly QuadrantWire[] = [
  "long_buildup",
  "short_covering",
  "short_buildup",
  "long_unwind",
];

/** Narrow a served `v`; anything that is not one of the four (null, a decimal, a new value) is unclassified. */
export function quadrantOf(v: unknown): QuadrantWire | null {
  return typeof v === "string" && Object.hasOwn(QUADRANT_STYLE, v) ? (v as QuadrantWire) : null;
}

/** D03 §6 crosshair form: "long build-up (▲ price ▲ OI)". */
export function quadrantReading(q: QuadrantWire): string {
  const s = QUADRANT_STYLE[q];
  const arrow = (w: "up" | "down"): string => (w === "up" ? "▲" : "▼");
  return `${s.words} (${arrow(s.priceWord)} price ${arrow(s.oiWord)} OI)`;
}

/**
 * Q12 (PROPOSED, stamped for E24-S02; D03 S54-15): the pattern floor in one place. Lane height D03 §4 (16 px).
 * Rungs, by pixels per bar: tips on from 10, the width step from 6 (half = 3 px), then the LOD step
 * `1 bar = 2 bars` from 4, below that the price-direction ribbon (a 2 px strip in the candle slots).
 */
export const LANE_HEIGHT_PX = 16;
export const RIBBON_HEIGHT_PX = 2;
export const FLOOR_PX = { tips: 10, width: 6, lod: 4 } as const;
export type FloorRung = "tips" | "width" | "lod" | "ribbon";

export function floorRung(pxPerBar: number): FloorRung {
  if (pxPerBar >= FLOOR_PX.tips) return "tips";
  if (pxPerBar >= FLOOR_PX.width) return "width";
  if (pxPerBar >= FLOOR_PX.lod) return "lod";
  return "ribbon";
}
