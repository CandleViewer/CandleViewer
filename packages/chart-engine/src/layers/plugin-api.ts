// The DOM-free half of the series-plugin surface (E12-S06, BQ-2, additive; reported to E11-T09):
// the shapes `RenderContext.instances`, `.projection` and `SeriesPlugin.onMutation` read. They
// live here, not in `api/types.ts`, so core code (the host node, the runtime) can use them under
// tsconfig.core.json; `api/types.ts` imports them. The package root re-exports none of them.

/** A store mutation's range in logical bar indices after it (26 §3.3). */
export interface DataRange {
  readonly op: "append" | "patch" | "prepend" | "replace";
  readonly from: number;
  readonly to: number;
  /** How far held indices move: after `prepend`, i += indexShift; after `append`, i -= it. */
  readonly indexShift: number;
}

/** A retained instance ring (`CandleRing`), as `RenderContext.instances` reads it. */
export interface InstanceRing {
  readonly data: Float32Array;
  readonly head: number;
  readonly stride: number;
  readonly length: number;
  /** Physical slots: a draw covers them all, slots past `length` collapse (BQ-14). */
  readonly capacity: number;
}

/** The transform's own functions (G-2), never a second projection. */
export interface SeriesProjection {
  /** The x of bar index i's centre, CSS px (`indexToScreen`). */
  indexToX(index: number): number;
  /** The y of a tick from the series' `priceOrigin`, CSS px (`priceToScreen`). */
  tickToY(tick: number): number;
}
