// Device-pixel helpers (E11-S10, README BQ-143 to BQ-145, BQ-151): engine math stays in CSS px and
// DPR is applied once, in `writePaneUniforms` (BQ-74, BQ-142); these snap CSS px to the device grid.
// DOM-free and internal: S06 (axis rules), S07 (crosshair) and E21 (heatmap) consume them.

/** The heatmap layer's DPR ceiling (26 §3.4): a 3× display must not triple its textures. */
export const HEATMAP_DPR_CAP = 2;

/** A layer's effective ratio under its cap: `layerDpr(3, HEATMAP_DPR_CAP)` is 2. */
export const layerDpr = (dpr: number, cap = Number.POSITIVE_INFINITY): number => Math.min(dpr, cap);

/**
 * A hairline's width in device px, `max(1, floor(dpr))` (E11-D02 §4.4): one device pixel at 1,
 * 1.25 and 1.5, two at 2 and 3 at 3. Dash lengths scale by the same `floor(dpr)`.
 */
export const hairlineDevicePx = (dpr: number): number => Math.max(1, Math.floor(dpr));

/**
 * The ticket's half-pixel rule: the CSS px whose device position is a device-pixel centre nearest
 * `vCssPx`, so a 1-device-px stroke there covers exactly one pixel column, with no fringe.
 */
export const snapHairline = (vCssPx: number, dpr: number): number =>
  (Math.round(vCssPx * dpr - 0.5) + 0.5) / dpr;

/**
 * A `widthDevicePx`-wide stroke's centre in CSS px: odd widths sit on a pixel centre, even widths
 * on a pixel edge, so the stroke covers exactly `widthDevicePx` whole device pixels.
 */
export function snapStroke(vCssPx: number, dpr: number, widthDevicePx: number): number {
  if (Math.round(widthDevicePx) % 2 === 1) return snapHairline(vCssPx, dpr);
  return Math.round(vCssPx * dpr) / dpr;
}

/**
 * One axis of the backing store (BQ-145): the browser's device-pixel-content-box size when it
 * reports one, otherwise `round(cssPx * dpr)`. The canvas's CSS box is then `backing / dpr`, so
 * CSS px map to device px by exactly `dpr` and a snapped hairline stays on the grid. `cap` is the
 * seam for threat model F-12's size cap (E11-S15 sets it; G-34); uncapped here.
 */
export function backingPx(
  cssPx: number,
  dpr: number,
  devicePx?: number,
  cap = Number.POSITIVE_INFINITY,
): number {
  const px =
    devicePx !== undefined && Number.isFinite(devicePx) && devicePx >= 0
      ? Math.round(devicePx)
      : Math.max(0, Math.round(cssPx * dpr));
  return Math.min(px, cap);
}
