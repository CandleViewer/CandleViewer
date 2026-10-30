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

/** One pane's vertical mapping: float64 ticks from the series' `priceOrigin` (BQ-71). */
export interface PaneTransform {
  priceLow: number;
  priceHigh: number;
  /** BQ-72: log, percent and inverted are E11-S05's alternative `priceToScreen`. */
  readonly scaleMode: "linear";
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
