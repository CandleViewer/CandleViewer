// The candle geometry twin (E12-S06, E12-D06 §2-§4 at L0): the one float64 CPU copy of what the
// `candle` shader draws, for the 2D painter and the tests (hit-testing joins in PR 2). Per frame
// it reduces bar spacing and DPR to four numbers (`u_geom`); per bar it places a part's rect
// exactly as the shader does, through the pane block and `projectRel` (BQ-114). No DOM.
import { hairlineDevicePx } from "../../viewport/pixels.js";
import { projectRel } from "../../viewport/transform.js";
import { CANDLE_DIR } from "./ring.js";

/** `u_geom` slots: body width and hairline in device px, OHLC tick in device px, spacing in CSS px. */
export const GEOM = { body: 0, hair: 1, tick: 2, spacing: 3 } as const;

/**
 * Body: clamp(roundHalfUp(0.7 s), 1, 35) CSS px, odd from 4, then device px; from 4 device px
 * its parity is the hairline's, so it centres on the wick exactly. Hairline max(1, floor(dpr));
 * OHLC tick clamp(floor(body / 2), 1, floor((s - 3) / 2)).
 */
export function candleGeometry(spacingCss: number, dpr: number, out: Float32Array): void {
  const s = spacingCss > 0 ? spacingCss : 0;
  let css = Math.min(35, Math.max(1, Math.floor(0.7 * s + 0.5)));
  if (css >= 4 && css % 2 === 0) css -= 1;
  const hair = hairlineDevicePx(dpr);
  let body = Math.max(hair, Math.round(css * dpr));
  if (body >= 4 && (body - hair) % 2 !== 0) body -= 1;
  const tick = Math.max(1, Math.min(Math.floor(css / 2), Math.floor((s - 3) / 2)));
  out[GEOM.body] = body;
  out[GEOM.hair] = hair;
  out[GEOM.tick] = Math.max(hair, Math.round(tick * dpr));
  out[GEOM.spacing] = s;
}

/**
 * Part `part` (0 wick, 1 body) of bar `index` (logical) as [x, y, w, h] in `u_viewport` px, y
 * down: the shader's arithmetic in float64. `k` is the pane block's floats (`u_k`, `u_log`),
 * `tickBase` / `indexBase` its ints; `dir` the ring's classification.
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
): void {
  const hair = geom[GEOM.hair] ?? 1;
  const body = geom[GEOM.body] ?? 1;
  // The body's left edge snapped to a device pixel; every part is centred on it from there.
  const left = Math.floor((index - indexBase + 0.5 - (k[3] ?? 0)) * (k[0] ?? 0) - body * 0.5 + 0.5);
  let w: number;
  let y0: number;
  let y1: number;
  if (part === 0) {
    w = dir === CANDLE_DIR.down ? 2 * hair : hair;
    y0 = projectRel(k, l - tickBase);
    y1 = projectRel(k, h - tickBase);
  } else {
    w = body;
    y0 = projectRel(k, o - tickBase);
    y1 = projectRel(k, c - tickBase);
    if (dir === CANDLE_DIR.doji || dir === CANDLE_DIR.zeroRange) {
      const tall = (geom[GEOM.spacing] ?? 0) < 8 ? hair : 2 * hair;
      if (dir === CANDLE_DIR.zeroRange) w = Math.max(w, 3 * hair);
      y0 = Math.floor(y0 - tall * 0.5 + 0.5);
      y1 = y0 + tall;
    }
  }
  const top = Math.min(y0, y1);
  const bottom = Math.max(Math.max(y0, y1), top + hair);
  out[0] = left + Math.floor((body - w) * 0.5);
  out[1] = top;
  out[2] = w;
  out[3] = bottom - top;
}
