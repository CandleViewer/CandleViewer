// The shared transform's types (E11-S03): apart, so Viewport.ts and transform.ts form no cycle.

/** The monotone bar index <-> µs time map; `BarStore` fits it structurally (BQ-67). */
export interface IndexTimeMap {
  readonly length: number;
  /** The open time of bar i in µs, NaN outside [0, length). */
  indexToTime(i: number): number;
  /** The last bar at or before `t`; -1 before the first. */
  timeToIndex(t: number): number;
  /** Extrapolation step past the loaded range; else the last two bars' delta, else 60 s. */
  readonly barDurationUs?: number;
}

/** E11-S05: the four projections; percent and indexed draw as linear and relabel (BQ-118). */
export type ScaleMode = "linear" | "log" | "percent" | "indexed";
/** Why log cannot be drawn (BQ-120): codes only, the UI owns the copy (C-32). */
export type LogReason = "non-positive" | "no-price-origin";

/** One pane's vertical mapping: float64 ticks from the series' `priceOrigin` (BQ-71). */
export interface PaneTransform {
  priceLow: number;
  priceHigh: number;
  /** The mode drawn (BQ-120): log falls back to linear on the guard and never restores itself. */
  scaleMode: ScaleMode;
  /**
   * The mode asked for, persisted by the app; differs from `scaleMode` after a fallback or while
   * a log request waits for (or is refused on) the data.
   */
  requestedMode: ScaleMode;
  /** Flips the y mapping after the mode's own projection (CPU-only). */
  inverted: boolean;
  /** Auto is the Lock's off state (BQ-119, C-30): never persisted, never synced. */
  autoScale: boolean;
  includeDrawings: boolean;
  /** "Scale price only" (E11-D03): overlay extents are left out of the fit. */
  priceOnly: boolean;
  /** Margins as fractions of the fitted window, each in [0, 0.45] (BQ-117). */
  marginTop: number;
  marginBottom: number;
  /** The main series' price of tick 0 and its tick size (BQ-115); tickSize 0 until known. */
  priceOrigin: number;
  tickSize: number;
  /** Percent and indexed: the close of the left-most fully visible bar, in ticks; NaN if none. */
  anchorTick: number;
  /** Null when log can be drawn. */
  logReason: LogReason | null;
  plotTop: number;
  plotHeight: number;
}

/** What a renderer reads (`FrameCtx.viewport`): the state, never a setter. */
export interface ViewportState {
  /** The fractional bar index at x = 0; bar i spans [i, i + 1) in index space. */
  readonly leftIndex: number;
  readonly barSpacing: number;
  /** CSS px (BQ-74); `dpr` reaches the GPU only through the uniforms. */
  readonly plotWidth: number;
  readonly height: number;
  readonly dpr: number;
  readonly map: IndexTimeMap;
  readonly panes: readonly Readonly<PaneTransform>[];
}
