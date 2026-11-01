// The candle geometry twin (E12-S06, E12-D06 §2-§4 and §9 at L0): the one float64 CPU copy of
// what the `candle` shader draws, for the 2D painter, hit-testing and the tests. Per frame it
// reduces bar spacing and DPR to four numbers (`u_geom`); per bar it places a part's rect exactly
// as the shader does, through the pane block and `projectRel` (BQ-114). No DOM.
import { hairlineDevicePx } from "../../viewport/pixels.js";
import { projectRel } from "../../viewport/transform.js";
import { PALETTE } from "./palette.js";
import { CANDLE_DIR } from "./ring.js";

/**
 * `u_batch.x`: what a batch draws. Candles: the wick and the body. OHLC bars (D06 §3.2): the stem
 * and the open / close ticks (a 10-vertex strip, two quads joined by degenerate bridges, BQ-15).
 * The gap seam (BQ-8): one hairline at the left edge of each `gap_before` bar's slot.
 */
export const CANDLE_PART = { wick: 0, body: 1, ticks: 2, stem: 3, seam: 4 } as const;
/** Strip vertices per instance: 4 for a quad, 10 for the two ticks (BQ-15). */
export const PART_VERTICES: readonly number[] = [4, 4, 10, 4, 4];
/** D06 §3.2: OHLC ticks are drawn from 5 CSS px; below it the bar draws the candle mark. */
export const OHLC_TICKS_FROM = 5;

/**
 * `u_geom` (two vec4 rows): body width, hairline and OHLC tick in device px, spacing in CSS px;
 * then the DPR (the up outline's CSS-px threshold, D06 §3.2). Floats per block: `GEOM_FLOATS`.
 */
export const GEOM = { body: 0, hair: 1, tick: 2, spacing: 3, dpr: 4 } as const;
export const GEOM_FLOATS = 8;
/** D06 §3.2: an up body is outlined on every side once it is ≥ 3 CSS px wide. */
export const FULL_OUTLINE_CSS = 3;

/**
 * E12-D06 §3.1 / E12-D12 §5.2: body = clamp(roundHalfUp(0.7 s), 1, 35) CSS px, forced odd from
 * 4 px: an even width takes the next odd value when it is ≤ s − 1, else the previous one (the
 * ladder 9 / 5 / 2 at s = 12 / 6 / 3, the 35 cap from s = 48). Then device px; from 4 device px
 * its parity is the hairline's, so it centres on the wick exactly. Hairline max(1, floor(dpr));
 * OHLC tick clamp(floor(body / 2), 1, floor((s - 3) / 2)).
 */
export function candleGeometry(spacingCss: number, dpr: number, out: Float32Array): void {
  const s = spacingCss > 0 ? spacingCss : 0;
  let css = Math.min(35, Math.max(1, Math.floor(0.7 * s + 0.5)));
  if (css >= 4 && css % 2 === 0) css = css + 1 <= s - 1 ? css + 1 : css - 1;
  const hair = hairlineDevicePx(dpr);
  let body = Math.max(hair, Math.round(css * dpr));
  if (body >= 4 && (body - hair) % 2 !== 0) body -= 1;
  const tick = Math.max(1, Math.min(Math.floor(css / 2), Math.floor((s - 3) / 2)));
  out[GEOM.body] = body;
  out[GEOM.hair] = hair;
  out[GEOM.tick] = Math.max(hair, Math.round(tick * dpr));
  out[GEOM.spacing] = s;
  out[GEOM.dpr] = dpr > 0 ? dpr : 1;
}

/** D06 §3.2: a `w` device-px up body gets the full outline from 3 CSS px, else top and bottom. */
export const fullOutline = (w: number, geom: ArrayLike<number>): boolean =>
  w >= FULL_OUTLINE_CSS * (geom[GEOM.dpr] ?? 1);

/** The palette row a part of a `dir` bar is drawn in (the shader's choice, line for line). */
export function partColor(part: number, dir: number): number {
  if (part === CANDLE_PART.wick || part === CANDLE_PART.seam || dir >= CANDLE_DIR.doji) {
    return PALETTE.wick; // D06 §9: doji and zero-range marks are neutral; R-6
  }
  return dir === CANDLE_DIR.up ? PALETTE.up : PALETTE.down;
}

/**
 * Part `part` (`CANDLE_PART`) of bar `index` (logical) as [x, y, w, h] in `u_viewport` px, y
 * down: the shader's arithmetic in float64. `k` is the pane block's floats (`u_k`, `u_viewport`,
 * `u_log`), `tickBase` / `indexBase` its ints; `dir` the ring's classification. `sub` picks the
 * OHLC tick (0 open, 1 close); a part with nothing to draw gets w = 0.
 */
export function candleRect(
  part: number,
  index: number,
  o: number,
  h: number,
  l: number,
  c: number,
  dir: number,
  k: ArrayLike<number>,
  indexBase: number,
  tickBase: number,
  geom: ArrayLike<number>,
  out: Float64Array,
  sub = 0,
): void {
  const hair = geom[GEOM.hair] ?? 1;
  const body = geom[GEOM.body] ?? 1;
  const kx = k[0] ?? 0;
  const centre = (index - indexBase + 0.5 - (k[3] ?? 0)) * kx; // the shader's evaluation order
  if (part === CANDLE_PART.seam) {
    // BQ-8: the slot's left edge, a hairline over the whole pane.
    out[0] = Math.floor(centre - kx * 0.5 - hair * 0.5 + 0.5);
    out[1] = 0;
    out[2] = hair;
    out[3] = k[5] ?? 0;
    return;
  }
  // The body's left edge snapped to a device pixel; every part is centred on it from there.
  const left = Math.floor(centre - body * 0.5 + 0.5);
  // D06 §3.1 / §3.2: 1 hairline up, 2 down; doji and zero-range marks keep one.
  const weight = dir === CANDLE_DIR.down ? 2 * hair : hair;
  const stem = left + Math.floor((body - hair) * 0.5);
  let x = stem;
  let w = weight;
  let y0: number;
  let y1: number;
  if (part === CANDLE_PART.ticks) {
    const tick = geom[GEOM.tick] ?? 1;
    if (dir === CANDLE_DIR.zeroRange)
      w = 0; // the stem draws the zero-range mark
    else {
      x = sub === 0 ? stem - tick : stem + weight;
      w = tick;
    }
    y0 = Math.floor(projectRel(k, (sub === 0 ? o : c) - tickBase) - weight * 0.5 + 0.5);
    y1 = y0 + weight;
  } else if (
    part === CANDLE_PART.body ||
    (part === CANDLE_PART.stem && dir === CANDLE_DIR.zeroRange)
  ) {
    w = body;
    y0 = projectRel(k, o - tickBase);
    y1 = projectRel(k, c - tickBase);
    if (dir === CANDLE_DIR.doji || dir === CANDLE_DIR.zeroRange) {
      // D06 §9: a doji is 2 hairlines tall (1 below 8 px); a zero-range bar 2 hairlines always,
      // max(body, roundHalfUp(3 dpr)) wide.
      const zero = dir === CANDLE_DIR.zeroRange;
      const tall = zero || (geom[GEOM.spacing] ?? 0) >= 8 ? 2 * hair : hair;
      if (zero) w = Math.max(w, Math.floor(3 * (geom[GEOM.dpr] ?? 1) + 0.5));
      y0 = Math.floor(y0 - tall * 0.5 + 0.5);
      y1 = y0 + tall;
    }
    x = left + Math.floor((body - w) * 0.5);
  } else {
    // The wick (candles) or the stem (OHLC): high → low on the centre column.
    y0 = projectRel(k, l - tickBase);
    y1 = projectRel(k, h - tickBase);
  }
  const top = Math.min(y0, y1);
  const bottom = Math.max(Math.max(y0, y1), top + hair);
  out[0] = x;
  out[1] = top;
  out[2] = w;
  out[3] = bottom - top;
}
