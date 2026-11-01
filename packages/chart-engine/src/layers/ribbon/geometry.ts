// The line-family geometry twin (E12-S07 PR B, E12-D06 §3.2, §5.5, R-2): the one float64 CPU
// copy of what the `ribbon` shader draws, for the 2D painter, hit-testing and the tests. Per
// frame it reduces bar spacing and DPR to `u_geom`; per instance it places one triangle-strip
// corner exactly as the shader does, through the pane block and `projectRel` (BQ-114). No DOM.
import { hairlineDevicePx } from "../../viewport/pixels.js";
import { projectRel } from "../../viewport/transform.js";
import { RIBBON_PALETTE } from "../candle/palette.js";
import { FLAG_GAP_BEFORE } from "../candle/seams.js";

/**
 * `u_batch.x` of a `ribbon` batch. `stroke`: the segment from bar i to bar i + 1, butt caps;
 * `join`: a disc of half the stroke at bar i (the round join); `last`: the last bar's disc;
 * `fill`: the area under the segment to the plot's bottom edge; `above` / `below`: the baseline
 * fills between the segment and base B, split exactly at a crossing; `base`: B's hairline.
 */
export const RIBBON_PART = {
  stroke: 0,
  join: 1,
  last: 2,
  fill: 3,
  above: 4,
  below: 5,
  base: 6,
} as const;
export const RIBBON_PART_NAMES = ["stroke", "join", "last", "fill", "above", "below", "base"];

/**
 * `u_geom` (two vec4 rows): stroke, join radius, last-disc radius and hairline in device px;
 * then the DPR, the L2 flag (1: x snaps to the device-pixel column), `spare` (unused, 0), spacing
 * (CSS px).
 */
export const RIBBON_GEOM = {
  stroke: 0,
  join: 1,
  disc: 2,
  hair: 3,
  dpr: 4,
  l2: 5,
  spare: 6,
  spacing: 7,
};
export const RIBBON_GEOM_FLOATS = 8;
/** D06 §3.2: a 2 px line, a 3.5 px last-point disc. */
export const LINE_STROKE_CSS = 2;
export const LAST_DISC_CSS = 3.5;
/** D06 §5.1 / §5.5: below 1.5 CSS px a bar (L2), one vertex per device-pixel column. */
export const RIBBON_L2_BELOW = 1.5;
/** A disc's quad reaches this many device px past its radius (the fragment cuts the circle). */
export const DISC_MARGIN = 1;

/**
 * D06 §2: the stroke is a "2 px bar", `2 × floor(dpr)` device px (rule 3), so the round join is
 * a hairline radius; the last disc is 3.5 CSS px × dpr; the base line one hairline.
 */
export function ribbonGeometry(spacingCss: number, dpr: number, out: Float32Array): void {
  const s = spacingCss > 0 ? spacingCss : 0;
  const hair = hairlineDevicePx(dpr);
  const d = dpr > 0 ? dpr : 1;
  out[RIBBON_GEOM.stroke] = LINE_STROKE_CSS * hair;
  out[RIBBON_GEOM.join] = (LINE_STROKE_CSS * hair) / 2;
  out[RIBBON_GEOM.disc] = LAST_DISC_CSS * d;
  out[RIBBON_GEOM.hair] = hair;
  out[RIBBON_GEOM.dpr] = d;
  out[RIBBON_GEOM.l2] = s < RIBBON_L2_BELOW ? 1 : 0;
  out[RIBBON_GEOM.spare] = 0;
  out[RIBBON_GEOM.spacing] = s;
}

/** The palette row a part is drawn in (`RIBBON_PALETTE`): the shader's choice, line for line. */
export function ribbonRow(part: number): number {
  if (part <= RIBBON_PART.last) return RIBBON_PALETTE.line;
  if (part === RIBBON_PART.fill) return RIBBON_PALETTE.area;
  if (part === RIBBON_PART.above) return RIBBON_PALETTE.above;
  return part === RIBBON_PART.below ? RIBBON_PALETTE.below : RIBBON_PALETTE.base;
}

/** True for the parts drawn once per segment i → i + 1 (broken at a gap, R-2). */
export const isSegment = (part: number): boolean =>
  part === RIBBON_PART.stroke || (part >= RIBBON_PART.fill && part <= RIBBON_PART.below);

/** Bar `index`'s x in `u_viewport` px: its slot centre, at L2 its device-pixel column's centre. */
export function ribbonX(
  index: number,
  k: ArrayLike<number>,
  indexBase: number,
  l2: boolean,
): number {
  const x = (index - indexBase + 0.5 - (k[3] ?? 0)) * (k[0] ?? 0); // the shader's order
  return l2 ? Math.floor(x) + 0.5 : x;
}

/**
 * Corner `vid` (0..3, `x = vid & 1`, `y = vid >> 1`) of instance `index` of `part`, into out[0],
 * out[1] in `u_viewport` px, y down; false when the instance collapses (past the last bar, a
 * segment into a `gap_before` bar, or a baseline fill with nothing on its side). `c0` / `c1`:
 * bar `index`'s and the next bar's closes; `nextFlags` the next bar's meta word; `base`: B for
 * the baseline parts, the last close for `last` (`u_base`). `n` the bars held. `k`, `indexBase`,
 * `tickBase`: the pane block (k[4], k[5] the viewport, the fill's bottom edge).
 */
export function ribbonCorner(
  part: number,
  vid: number,
  index: number,
  n: number,
  c0: number,
  c1: number,
  nextFlags: number,
  base: number,
  k: ArrayLike<number>,
  indexBase: number,
  tickBase: number,
  geom: ArrayLike<number>,
  out: Float64Array,
): boolean {
  const single = part === RIBBON_PART.last || part === RIBBON_PART.base;
  const i = single ? n - 1 : index;
  const seg = isSegment(part);
  if (i < 0 || i >= n || (seg && (i + 1 >= n || (nextFlags & FLAG_GAP_BEFORE) !== 0))) {
    return false;
  }
  const cx = vid & 1;
  const cy = vid >> 1;
  const l2 = (geom[RIBBON_GEOM.l2] ?? 0) > 0.5;
  const x0 = ribbonX(i, k, indexBase, l2);
  if (part === RIBBON_PART.join || part === RIBBON_PART.last) {
    const r = geom[part === RIBBON_PART.join ? RIBBON_GEOM.join : RIBBON_GEOM.disc] ?? 0;
    const y = projectRel(k, (part === RIBBON_PART.last ? base : c0) - tickBase);
    const m = r + DISC_MARGIN;
    out[0] = x0 + (cx * 2 - 1) * m;
    out[1] = y + (cy * 2 - 1) * m;
    return true;
  }
  if (part === RIBBON_PART.base) {
    const h = geom[RIBBON_GEOM.hair] ?? 1;
    out[0] = cx * (k[4] ?? 0); // the pane scissor clips it to the plot (one pane, E11-S09)
    out[1] = Math.floor(projectRel(k, base - tickBase) - h * 0.5 + 0.5) + cy * h;
    return true;
  }
  const y0 = projectRel(k, c0 - tickBase);
  const x1 = ribbonX(i + 1, k, indexBase, l2);
  const y1 = projectRel(k, c1 - tickBase);
  if (part === RIBBON_PART.stroke) {
    const vx = x1 - x0 + 1e-6;
    const vy = y1 - y0;
    const len = Math.hypot(vx, vy);
    const w = (geom[RIBBON_GEOM.stroke] ?? 0) * 0.5 * (cy * 2 - 1);
    out[0] = x0 + (x1 - x0) * cx + (-vy / len) * w;
    out[1] = y0 + (y1 - y0) * cx + (vx / len) * w;
    return true;
  }
  // The fills: corner y 0 on the line (clamped to its side of B), 1 on the edge it closes to.
  const yb = part === RIBBON_PART.fill ? (k[5] ?? 0) : projectRel(k, base - tickBase);
  const s = part === RIBBON_PART.below ? -1 : 1;
  const in0 = part === RIBBON_PART.fill || (yb - y0) * s >= 0;
  const in1 = part === RIBBON_PART.fill || (yb - y1) * s >= 0;
  if (!in0 && !in1) return false;
  const dy = y1 - y0;
  const xc = dy !== 0 ? x0 + ((x1 - x0) * (yb - y0)) / dy : x0; // the exact crossing
  const ex = cx === 0 ? (in0 ? x0 : xc) : in1 ? x1 : xc;
  const ey = cx === 0 ? (in0 ? y0 : yb) : in1 ? y1 : yb;
  out[0] = ex;
  out[1] = cy === 0 ? ey : yb;
  return true;
}

const CORNER = new Float64Array(2);

/**
 * The four strip corners of one instance into out[0..8) (x, y per corner, `vid` order); false
 * when it collapses. The 2D painter and the tests read it; a disc's centre is their mean.
 */
export function ribbonQuad(
  part: number,
  index: number,
  n: number,
  c0: number,
  c1: number,
  nextFlags: number,
  base: number,
  k: ArrayLike<number>,
  indexBase: number,
  tickBase: number,
  geom: ArrayLike<number>,
  out: Float64Array,
): boolean {
  for (let v = 0; v < 4; v += 1) {
    const ok = ribbonCorner(
      part,
      v,
      index,
      n,
      c0,
      c1,
      nextFlags,
      base,
      k,
      indexBase,
      tickBase,
      geom,
      CORNER,
    );
    if (!ok) return false;
    out[v * 2] = CORNER[0] as number;
    out[v * 2 + 1] = CORNER[1] as number;
  }
  return true;
}

/** The distance from (px, py) to the segment a → b (device px). */
export function segmentDistance(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const vx = bx - ax;
  const vy = by - ay;
  const ll = vx * vx + vy * vy;
  const t = ll > 0 ? Math.min(1, Math.max(0, ((px - ax) * vx + (py - ay) * vy) / ll)) : 0;
  return Math.hypot(px - (ax + vx * t), py - (ay + vy * t));
}
