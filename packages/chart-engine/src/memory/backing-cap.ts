// The backing-store cap (26 §6, §11; threat model F-12, BQ-S15-13). Pure: clamps a requested
// backing store to what the context can hold, so a huge container or dpr cannot ask the GPU or the
// browser for an unbounded canvas. The GL limit per axis is the probed
// `min(MAX_TEXTURE_SIZE, MAX_RENDERBUFFER_SIZE, MAX_VIEWPORT_DIMS)`; the Canvas2D backend has no
// probe, so it uses the browser's canvas limits below (BQ-P2-06, 26 §7 table). Not wired yet:
// PR-2b applies it in the main-thread BackingSizer with the limits from `ready`.

/** Chromium's canvas side limit, px per axis (BQ-P2-06; to be verified in the Electron build). */
export const CANVAS2D_MAX_SIDE_PX = 32_767;
/** Chromium's canvas area limit, px (16,384², BQ-P2-06; to be verified in the Electron build). */
export const CANVAS2D_MAX_AREA_PX = 268_435_456;

/** The probed GL limits the cap reads (recorded, not floors). */
export interface GlBackingLimits {
  readonly maxTextureSize: number;
  readonly maxRenderbufferSize: number;
  readonly maxViewportDims: readonly [number, number];
}

export interface BackingCap {
  readonly width: number;
  readonly height: number;
  /** True when either axis was reduced. */
  readonly clamped: boolean;
}

/** A positive integer limit, or 1 for a missing / non-finite / non-positive probe value. */
const limit = (v: number): number => (Number.isFinite(v) && v >= 1 ? Math.floor(v) : 1);
/** A requested side: a finite size floored to whole px, 0 for anything else. */
const side = (v: number): number => (Number.isFinite(v) && v > 0 ? Math.floor(v) : 0);

/**
 * Clamps `[width, height]` (device px). `gl` null is the Canvas2D backend: each axis to
 * CANVAS2D_MAX_SIDE_PX, then the area to CANVAS2D_MAX_AREA_PX, scaling both axes by the same
 * factor so the aspect ratio holds. A 0 side stays 0 (a hidden container, BQ-147).
 */
export function capBackingStore(
  width: number,
  height: number,
  gl: GlBackingLimits | null,
): BackingCap {
  const w = side(width);
  const h = side(height);
  let maxW: number;
  let maxH: number;
  if (gl === null) {
    maxW = CANVAS2D_MAX_SIDE_PX;
    maxH = CANVAS2D_MAX_SIDE_PX;
  } else {
    const common = Math.min(limit(gl.maxTextureSize), limit(gl.maxRenderbufferSize));
    maxW = Math.min(common, limit(gl.maxViewportDims[0]));
    maxH = Math.min(common, limit(gl.maxViewportDims[1]));
  }
  let cw = Math.min(w, maxW);
  let ch = Math.min(h, maxH);
  if (gl === null && cw * ch > CANVAS2D_MAX_AREA_PX) {
    const k = Math.sqrt(CANVAS2D_MAX_AREA_PX / (cw * ch));
    cw = Math.floor(cw * k);
    ch = Math.floor(ch * k);
    // Float rounding can leave the product one row over: trim the longer side until it fits.
    while (cw * ch > CANVAS2D_MAX_AREA_PX) {
      if (cw >= ch) cw -= 1;
      else ch -= 1;
    }
  }
  return { width: cw, height: ch, clamped: cw < w || ch < h };
}
