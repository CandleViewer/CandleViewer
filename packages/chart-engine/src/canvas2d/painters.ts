// The per-program 2D painters (E11-T05, README BQ-87): each adds one instance's geometry to the
// current path, reading the instance where `INSTANCE_LAYOUTS` puts it and projecting with exactly
// its shader's affine (src/gl/shaders), so both backends place an instance on the same pixels.
// The pane block (`PaneUniforms`, E11-S03) is the only projection used: no price or time maths here.
import type { BatchUniforms } from "../gl/submit.js";
import { candleRect, GEOM } from "../layers/candle/geometry.js";
import { CANDLE_STRIDE } from "../layers/candle/ring.js";
import { attributeOffset, PROGRAM } from "../scene/instance-layout.js";
import { projectRel, type PaneUniforms } from "../viewport/transform.js";
import type { Ctx2DLike } from "./ctx2d.js";

/** One instance to paint: its ring floats (and their int32 view) at `at`, in a w × h store. */
export interface PaintArgs {
  data: Float32Array;
  ints: Int32Array;
  at: number;
  /** The batch's pane block; null draws `line` / `quad` in backing-store px (no block bound). */
  block: PaneUniforms | null;
  /** E12-S06: a candle batch's own block, and the sub-rect (0 the part, 1 an up body's tint). */
  batch?: BatchUniforms | null;
  sub?: number;
  w: number;
  h: number;
}

const SEG = attributeOffset(PROGRAM.line, "a_segment");
const RECT = attributeOffset(PROGRAM.quad, "a_rect");
const CELL = attributeOffset(PROGRAM.barCell, "a_cell");
const SIZE = attributeOffset(PROGRAM.barCell, "a_size");

/** `u_viewport` → backing store: the shaders' `p / u_viewport * 2 - 1` then the GL viewport. */
const scaleX = (a: PaintArgs): number => {
  const v = a.block?.floats[4] ?? a.w;
  return v > 0 ? a.w / v : 0;
};
const scaleY = (a: PaintArgs): number => {
  const v = a.block?.floats[5] ?? a.h;
  return v > 0 ? a.h / v : 0;
};

/** `line`: the segment p0 → p1, y up (the shader's NDC); the bucket strokes it. */
export function paintLine(ctx: Ctx2DLike, a: PaintArgs): void {
  const d = a.data;
  const i = a.at + SEG;
  const sx = scaleX(a);
  const sy = scaleY(a);
  ctx.moveTo((d[i] ?? 0) * sx, a.h - (d[i + 1] ?? 0) * sy);
  ctx.lineTo((d[i + 2] ?? 0) * sx, a.h - (d[i + 3] ?? 0) * sy);
}

/** `quad`: the rect (x, y, w, h), y up; the bucket fills it. */
export function paintQuad(ctx: Ctx2DLike, a: PaintArgs): void {
  const d = a.data;
  const i = a.at + RECT;
  const sx = scaleX(a);
  const sy = scaleY(a);
  const top = (d[i + 1] ?? 0) + (d[i + 3] ?? 0);
  ctx.rect((d[i] ?? 0) * sx, a.h - top * sy, (d[i + 2] ?? 0) * sx, (d[i + 3] ?? 0) * sy);
}

/**
 * `bar-cell`, colour only (S4: no text): the shader's `x = (rel.x + 0.5 - k.w + (c.x - 0.5) *
 * size.x) * k.x` and its y through `projectRel` (E11-S05 BQ-114, every scale mode), `rel` the
 * exact int difference from the block's bases (BQ-75), at the corners c = (0, 0) and (1, 1); y
 * grows down (its NDC flip).
 */
export function paintBarCell(ctx: Ctx2DLike, a: PaintArgs): void {
  const b = a.block;
  if (b === null) return; // the submit loop skips these and counts them
  const k = b.floats;
  const rx = (a.ints[a.at + CELL] ?? 0) - (b.ints[0] ?? 0) + 0.5 - (k[3] ?? 0);
  const ry = (a.ints[a.at + CELL + 1] ?? 0) - (b.ints[1] ?? 0);
  const half = (a.data[a.at + SIZE] ?? 0) * 0.5;
  const sx = scaleX(a) * (k[0] ?? 0);
  const sy = scaleY(a);
  const x0 = (rx - half) * sx;
  const x1 = (rx + half) * sx;
  const y0 = projectRel(k, ry) * sy;
  const y1 = projectRel(k, ry + (a.data[a.at + SIZE + 1] ?? 0)) * sy;
  ctx.rect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
}

const RECT_OUT = new Float64Array(4);

/**
 * `candle` (E12-S06): the part's rect from the geometry twin (the shader's arithmetic), in
 * `u_viewport` px then scaled to the backing store. `sub` 1 is an up body's tint: the rect inset
 * by a hairline on every side from 3 hairlines wide, else top and bottom only.
 */
export function paintCandle(ctx: Ctx2DLike, a: PaintArgs): void {
  const b = a.block;
  const blk = a.batch ?? null;
  if (b === null || blk === null) return; // the submit loop skips these and counts them
  const at = a.at;
  const i = (at / CANDLE_STRIDE - (blk.ints[1] ?? 0)) & (blk.ints[2] ?? 0);
  const v = a.ints;
  const o = v[at] ?? 0;
  const hi = v[at + 1] ?? 0;
  const lo = v[at + 2] ?? 0;
  const c = v[at + 3] ?? 0;
  const dir = ((v[at + 4] ?? 0) >> 4) & 3;
  const r = RECT_OUT;
  candleRect(
    blk.ints[0] ?? 0,
    i,
    o,
    hi,
    lo,
    c,
    dir,
    b.floats,
    b.ints[0] ?? 0,
    b.ints[1] ?? 0,
    blk.geom,
    r,
  );
  let [x, y, w, h] = [r[0] ?? 0, r[1] ?? 0, r[2] ?? 0, r[3] ?? 0];
  if (a.sub === 1) {
    const hair = blk.geom[GEOM.hair] ?? 1;
    if (w >= 3 * hair) [x, w] = [x + hair, w - 2 * hair];
    [y, h] = [y + hair, h - 2 * hair];
    if (w <= 0 || h <= 0) return;
  }
  const sx = scaleX(a);
  const sy = scaleY(a);
  ctx.rect(x * sx, y * sy, w * sx, h * sy);
}

/** Indexed by `PROGRAM`; `sdf-text` has none: the 2D path cannot rebuild strings (BQ-88). */
export const PAINTERS: readonly (((ctx: Ctx2DLike, a: PaintArgs) => void) | null)[] = [
  paintLine,
  paintQuad,
  null,
  paintBarCell,
  paintCandle,
];
