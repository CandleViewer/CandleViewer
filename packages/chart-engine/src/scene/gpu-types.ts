// The shapes the scene and the layers hand to a backend (E11-S02 / E12-S06), DOM- and GL-free:
// a ring's slots as the GPU reads them, the int attributes a VAO binds and a batch's own
// uniforms. They live here, not in src/gl, so src/layers and src/scene never import src/gl
// (dependency-cruiser `chart-engine-core-no-gl`, C-2.16); src/gl re-exports them.

/** A store's ring as the GPU sees it; read on every upload, so getters over a store fit. */
export interface VertexSource {
  /** The ring's backing floats; a new identity means it was reallocated. */
  readonly data: Float32Array;
  /** The physical slot of logical index 0. */
  readonly head: number;
  /** Floats per slot; the capacity is `data.length / stride`. */
  readonly stride: number;
}

/** E12-S06: int instance attributes a node's VAO binds (`INSTANCE_LAYOUTS` rows read as int). */
export interface AttributeLayout {
  /** Floats (4-byte words) per instance. */
  readonly stride: number;
  /** [location, word offset, components] per `in` the shader declares with `layout(location)`. */
  readonly ints: readonly (readonly [location: number, offset: number, size: number])[];
}

/**
 * A batch's own uniforms (E12-S06): `u_batch` ints (the candle part and the ring's head, mask and
 * length), `u_geom` and `u_palette`. Retained per node and rewritten in place: no allocation.
 */
export interface BatchUniforms {
  readonly ints: Int32Array;
  readonly geom: Float32Array;
  readonly palette: Float32Array;
  /** Strip vertices per instance; 0 takes `PROGRAM_VERTICES`. */
  vertices: number;
  /** The draw-trace label (`series.candle.wick`, `series.ohlc.ticks`, …); the node id if absent. */
  readonly label?: string;
  /** Instances to draw this frame; below 0 (or absent) the batch's count. 0 skips the draw. */
  instances?: number;
}
