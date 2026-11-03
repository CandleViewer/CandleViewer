// The per-program 2D painters (E11-T05, README BQ-87): each adds one instance's geometry to the
// current path, reading the instance where `INSTANCE_LAYOUTS` puts it and projecting with exactly
// its shader's affine (src/gl/shaders), so both backends place an instance on the same pixels.
// The pane block (`PaneUniforms`, E11-S03) is the only projection used: no price or time maths here.
import type { BatchUniforms } from "../gl/submit.js";
import {
  CANDLE_PART,
  candleRect,
  fullOutline,
  GEOM,
  MARK_GEOM,
  markRect,
} from "../layers/candle/geometry.js";
import { MARK_BITS } from "../layers/candle/marks.js";
import { BAR_FLAG } from "../model/BarStore.js";
import { CANDLE_STRIDE } from "../layers/candle/ring.js";
import { RIBBON_GEOM, RIBBON_PART, ribbonQuad } from "../layers/ribbon/geometry.js";
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
 * `u_viewport` px then scaled to the backing store. For a body, `sub` 1 is an up body's tint: the
 * rect inset by a hairline on every side from 3 CSS px wide, else top and bottom only; a hollow
 * body's `sub` 1 is its outline alone (E12-S07, D06 §4.2), the same edges, the interior unpainted.
 * For the OHLC ticks `sub` is the tick (0 open, 1 close). A seam or mark instance names its bar's
 * slot; a mark (E12-S10) is the geometry twin's `markRect`, the ring as its dashes (`paintRing`).
 */
export function paintCandle(ctx: Ctx2DLike, a: PaintArgs): void {
  const b = a.block;
  const blk = a.batch ?? null;
  if (b === null || blk === null) return; // the submit loop skips these and counts them
  const at = a.at;
  const part = blk.ints[0] ?? 0;
  const v = a.ints;
  const own = part === CANDLE_PART.seam || part === CANDLE_PART.marks; // entries name a slot
  const slot = own ? (v[at] ?? 0) : at / CANDLE_STRIDE;
  const i = (slot - (blk.ints[1] ?? 0)) & (blk.ints[2] ?? 0);
  if (part === CANDLE_PART.marks) {
    paintMark(ctx, a, blk, i, b);
    return;
  }
  const o = v[at] ?? 0;
  const hi = v[at + 1] ?? 0;
  const lo = v[at + 2] ?? 0;
  const c = v[at + 3] ?? 0;
  const mark = (v[at + 4] ?? 0) >> 4;
  const r = RECT_OUT;
  const sub = part === CANDLE_PART.ticks ? (a.sub ?? 0) : 0;
  const k = b.floats;
  candleRect(part, i, o, hi, lo, c, mark, k, b.ints[0] ?? 0, b.ints[1] ?? 0, blk.geom, r, sub);
  // Scalar locals throughout: a painter runs per bar, per frame (no array per call).
  let x = r[0] ?? 0;
  let y = r[1] ?? 0;
  let w = r[2] ?? 0;
  let h = r[3] ?? 0;
  const sx = scaleX(a);
  const sy = scaleY(a);
  if (part === CANDLE_PART.hollowBody && a.sub === 1) {
    // The shader's discard: the top and bottom edges, the sides too from 3 CSS px wide.
    const hair = blk.geom[GEOM.hair] ?? 1;
    if (w <= 0 || h <= 0) return;
    const e = Math.min(hair, h);
    ctx.rect(x * sx, y * sy, w * sx, e * sy);
    if (h > hair) ctx.rect(x * sx, (y + h - e) * sy, w * sx, e * sy);
    if (fullOutline(w, blk.geom) && h > 2 * hair) {
      ctx.rect(x * sx, (y + hair) * sy, Math.min(hair, w) * sx, (h - 2 * hair) * sy);
      if (w > hair) ctx.rect((x + w - hair) * sx, (y + hair) * sy, hair * sx, (h - 2 * hair) * sy);
    }
    return;
  }
  if (part === CANDLE_PART.body && a.sub === 1) {
    const hair = blk.geom[GEOM.hair] ?? 1;
    if (fullOutline(w, blk.geom)) {
      x += hair;
      w -= 2 * hair;
    }
    y += hair;
    h -= 2 * hair;
  }
  if (w <= 0 || h <= 0) return;
  ctx.rect(x * sx, y * sy, w * sx, h * sy);
}

/** A mark entry ([slot, high, low, open, kind | dir << 4 | heavy]): the square, or the ring. */
function paintMark(
  ctx: Ctx2DLike,
  a: PaintArgs,
  blk: BatchUniforms,
  i: number,
  b: PaneUniforms,
): void {
  const v = a.ints;
  const at = a.at;
  const meta = v[at + 4] ?? 0;
  const k = b.floats;
  const r = RECT_OUT;
  const hi = v[at + 1] ?? 0;
  const lo = v[at + 2] ?? 0;
  const o = v[at + 3] ?? 0;
  markRect(meta & MARK_BITS, i, hi, lo, o, meta, k, b.ints[0] ?? 0, b.ints[1] ?? 0, blk.geom, r);
  const sx = scaleX(a);
  const sy = scaleY(a);
  const x = r[0] ?? 0;
  const y = r[1] ?? 0;
  const w = r[2] ?? 0;
  const h = r[3] ?? 0;
  if ((meta & BAR_FLAG.forming) === 0) ctx.rect(x * sx, y * sy, w * sx, h * sy);
  else paintRing(ctx, x, y, w, h, blk.geom[GEOM.hair] ?? 1, sx, sy);
}

/**
 * The ring's inked pixels as rects, exactly `ringOn`'s set: per band (top, right, bottom, left,
 * the corner priority of the shader), each run of perimeter positions whose dash is on.
 */
function paintRing(
  ctx: Ctx2DLike,
  x: number,
  y: number,
  w: number,
  h: number,
  hair: number,
  sx: number,
  sy: number,
): void {
  const t = MARK_GEOM.ringWeight * hair;
  const d = MARK_GEOM.dash * hair;
  // [along from, along to, perimeter at `from`, +1 / -1, horizontal, fixed offset, fixed length]
  run(ctx, 0, w, 0, 1, true, y, t, x, d, sx, sy);
  run(ctx, t, h, w + t, 1, false, x + w - t, t, y, d, sx, sy);
  run(
    ctx,
    0,
    w - t,
    2 * w + h - 1,
    -1,
    true,
    y + Math.max(t, h - t),
    h - Math.max(t, h - t),
    x,
    d,
    sx,
    sy,
  );
  run(ctx, t, h - t, 2 * w + 2 * h - 1 - t, -1, false, x, Math.min(t, w - t), y, d, sx, sy);
}

/** One band: positions [from, to) along it, perimeter `s0 + dir * (p - from)`, on-runs as rects. */
function run(
  ctx: Ctx2DLike,
  from: number,
  to: number,
  s0: number,
  dir: number,
  horizontal: boolean,
  fixed: number,
  thick: number,
  base: number,
  d: number,
  sx: number,
  sy: number,
): void {
  if (thick <= 0) return;
  let start = -1;
  for (let p = from; p <= to; p += 1) {
    const on = p < to && Math.floor((s0 + dir * (p - from)) / d) % 2 === 0;
    if (on && start < 0) start = p;
    if (on || start < 0) continue;
    if (horizontal) ctx.rect((base + start) * sx, fixed * sy, (p - start) * sx, thick * sy);
    else ctx.rect(fixed * sx, (base + start) * sy, thick * sx, (p - start) * sy);
    start = -1;
  }
}

const QUAD_OUT = new Float64Array(8);
/** A disc's polygon in the 2D path: this many vertices on the twin's circle. */
export const DISC_SIDES = 16;
const COS = Float64Array.from({ length: DISC_SIDES }, (_, j) =>
  Math.cos((2 * Math.PI * j) / DISC_SIDES),
);
const SIN = Float64Array.from({ length: DISC_SIDES }, (_, j) =>
  Math.sin((2 * Math.PI * j) / DISC_SIDES),
);

/**
 * `ribbon` (E12-S07 PR B): instance `a.at` (the bar's logical index) of the batch's part, from
 * the geometry twin (the shader's arithmetic), scaled to the backing store. A strip quad (the
 * stroke, a fill, the base line) is its polygon v0 v1 v3 v2; a disc (a join, the last point) is
 * a `DISC_SIDES`-gon on the twin's circle. Every polygon of a bucket winds the same way, so
 * the nonzero fill unions a stroke with its joins. A collapsed instance paints nothing.
 */
export function paintRibbon(ctx: Ctx2DLike, a: PaintArgs): void {
  const b = a.block;
  const blk = a.batch ?? null;
  if (b === null || blk === null) return; // the submit loop skips these and counts them
  const bi = blk.ints;
  const part = bi[0] ?? 0;
  const head = bi[1] ?? 0;
  const mask = bi[2] ?? 0;
  const n = bi[3] ?? 0;
  const i = a.at;
  const v = a.ints;
  const p0 = ((head + i) & mask) * CANDLE_STRIDE;
  const p1 = ((head + i + 1) & mask) * CANDLE_STRIDE; // the CPU wraps by mask: no guard read
  const q = QUAD_OUT;
  const k = b.floats;
  const c0 = v[p0 + 3] ?? 0;
  const c1 = v[p1 + 3] ?? 0;
  const f1 = v[p1 + 4] ?? 0;
  const base = blk.base ?? 0;
  if (!ribbonQuad(part, i, n, c0, c1, f1, base, k, b.ints[0] ?? 0, b.ints[1] ?? 0, blk.geom, q)) {
    return;
  }
  const sx = scaleX(a);
  const sy = scaleY(a);
  if (part === RIBBON_PART.join || part === RIBBON_PART.last) {
    const r = blk.geom[part === RIBBON_PART.join ? RIBBON_GEOM.join : RIBBON_GEOM.disc] ?? 0;
    const cx = ((q[0] as number) + (q[6] as number)) * 0.5;
    const cy = ((q[1] as number) + (q[7] as number)) * 0.5;
    ctx.moveTo((cx + r) * sx, cy * sy);
    for (let j = 1; j < DISC_SIDES; j += 1) {
      ctx.lineTo((cx + r * (COS[j] as number)) * sx, (cy + r * (SIN[j] as number)) * sy);
    }
    return;
  }
  ctx.moveTo((q[0] as number) * sx, (q[1] as number) * sy);
  ctx.lineTo((q[2] as number) * sx, (q[3] as number) * sy);
  ctx.lineTo((q[6] as number) * sx, (q[7] as number) * sy);
  ctx.lineTo((q[4] as number) * sx, (q[5] as number) * sy);
}

/** Indexed by `PROGRAM`; `sdf-text` has none: the 2D path cannot rebuild strings (BQ-88). */
export const PAINTERS: readonly (((ctx: Ctx2DLike, a: PaintArgs) => void) | null)[] = [
  paintLine,
  paintQuad,
  null,
  paintBarCell,
  paintCandle,
  paintRibbon,
];
