// Scene-graph dirty flags, deferral classes and layer order (E11-S01, 26 §3.1, 06 §4.4).

export const Dirty = { NONE: 0, DATA: 1, LAYOUT: 2, STYLE: 4, TRANSFORM: 8 } as const;

export type DirtyFlags = number; // a bitwise OR of `Dirty` bits
export const DIRTY_ALL: DirtyFlags = 15; // a new node has never been collected

/**
 * 06 §4.4's shedding ladder, relaxed from rung 1 to rung 4; `NONE` is never deferred and is the
 * only class a `critical` node may have. Ruling BQ-S5 maps the ticket's rungs: non-focused pane
 * redraw is `BACKGROUND_PANES`, bubble clustering is `FOOTPRINT_TEXT`.
 */
export const DeferClass = {
  NONE: 0,
  HEATMAP_CADENCE: 1,
  FOOTPRINT_TEXT: 2,
  INDICATOR_COALESCE: 3,
  BACKGROUND_PANES: 4,
} as const;

export type DeferClass = (typeof DeferClass)[keyof typeof DeferClass];

/** A rung mask for `SceneGraph.frame`: bit `r` defers rung `r`; bit 0 (`NONE`) is never honoured. */
export const SHED_ALL = 0b11110;
export const shedUpTo = (rung: DeferClass): number => ((1 << (rung + 1)) - 2) & SHED_ALL;

/** The fixed per-pane layer order, bottom to top. Not configurable. */
export const LAYER_ORDER = [
  "background",
  "heatmap",
  "series",
  "overlays",
  "drawings",
  "foreground",
] as const;

export type LayerName = (typeof LAYER_ORDER)[number];
