/**
 * The two tier axes of SCR-082 (E37-D03 §8, implemented verbatim; E37-D05 §7): the node-count tier
 * and the zoom band. The tier is a function of the node count alone and never changes with zoom;
 * a zoom band only toggles the visibility of layers the tier already laid out, so a band change
 * re-lays out nothing. The canvas exposes both as `data-tier` and `data-zoom-band` (hand-off §E).
 */

/** Tier A holds at most this many nodes (D02 §10). */
export const TIER_A_MAX = 60;

/**
 * The provisional soft cap (ADR-0029; E37-K01): above it the graph is Tier C and the canvas shows
 * the over-budget banner. It warns and never blocks: the server's bounds are the real limit, and
 * E37-Q04 lifts or hardens the cap on its measurement.
 */
export const SOFT_CAP = 120;

/** `a` ≤ 60 nodes, `b` 61–120, `c` above the soft cap. */
export type Tier = "a" | "b" | "c";

export function tierOf(nodeCount: number): Tier {
  if (nodeCount <= TIER_A_MAX) return "a";
  return nodeCount <= SOFT_CAP ? "b" : "c";
}

/** Whether the graph shows the over-budget banner (Tier C): a warning, never a block. */
export const isOverBudget = (nodeCount: number): boolean => nodeCount > SOFT_CAP;

/** Z-1 ≥ 75 %, Z-2 50–74 %, Z-3 < 50 % (D03 §8; the starting values E37-Q04 may move). */
export type ZoomBand = "z-1" | "z-2" | "z-3";

/** The band lower bounds, as zoom ratios (1 is 100 %). */
export const ZOOM_BAND_FLOOR = Object.freeze({ "z-1": 0.75, "z-2": 0.5 });

/** The band of a zoom ratio (1 is 100 %); between two whole percents, the lower band. */
export function zoomBandOf(zoom: number): ZoomBand {
  if (zoom >= ZOOM_BAND_FLOOR["z-1"]) return "z-1";
  return zoom >= ZOOM_BAND_FLOOR["z-2"] ? "z-2" : "z-3";
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

/**
 * The node card's box per tier, in canvas units (D02 §10): Tier A's is the minimum, its text box
 * fixed per tier; Tier B and C cards are the compact 120 × 32.
 */
export const NODE_BOX: Readonly<Record<Tier, Size>> = Object.freeze({
  a: Object.freeze({ width: 160, height: 40 }),
  b: Object.freeze({ width: 120, height: 32 }),
  c: Object.freeze({ width: 120, height: 32 }),
});
