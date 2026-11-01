// The per-program 2D painters (E11-T05, README BQ-87): each adds one instance's geometry to the
// current path, reading the instance where `INSTANCE_LAYOUTS` puts it and projecting with exactly
// its shader's affine (src/gl/shaders), so both backends place an instance on the same pixels.
// The pane block (`PaneUniforms`, E11-S03) is the only projection used: no price or time maths here.
import type { BatchUniforms } from "../gl/submit.js";
import { candleRect, fullOutline, GEOM } from "../layers/candle/geometry.js";
import { CANDLE_STRIDE } from "../layers/candle/ring.js";
import { DASH_LUT } from "../gl/shaders/drawing-line.js";
import { RUN } from "../layers/drawings/labels.js";
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
const A0 = attributeOffset(PROGRAM.drawingLine, "a_anchor0");
const STYLE = attributeOffset(PROGRAM.drawingLine, "a_style");

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
  // Scalar locals throughout: a painter runs per bar, per frame (no array per call).
  let x = r[0] ?? 0;
  let y = r[1] ?? 0;
  let w = r[2] ?? 0;
  let h = r[3] ?? 0;
  if (a.sub === 1) {
    const hair = blk.geom[GEOM.hair] ?? 1;
    if (fullOutline(w, blk.geom)) {
      x += hair;
      w -= 2 * hair;
    }
    y += hair;
    h -= 2 * hair;
    if (w <= 0 || h <= 0) return;
  }
  const sx = scaleX(a);
  const sy = scaleY(a);
  ctx.rect(x * sx, y * sy, w * sx, h * sy);
}

/** `drawing-line`'s anchor `k` (0 or 1) through the block, in `u_viewport` px: the shader's. */
function lineX(a: PaintArgs, b: PaneUniforms, k: number): number {
  const o = a.at + A0 + 4 * k; // the ivec4: int index, int tick, then their fractions' bits
  const rel = (a.ints[o] ?? 0) - (b.ints[0] ?? 0) + (a.data[o + 2] ?? 0);
  return (rel + 0.5 - (b.floats[3] ?? 0)) * (b.floats[0] ?? 0);
}
function lineY(a: PaintArgs, b: PaneUniforms, k: number): number {
  const o = a.at + A0 + 4 * k;
  const rel = (a.ints[o + 1] ?? 0) - (b.ints[1] ?? 0);
  return projectRel(b.floats, rel + (a.data[o + 3] ?? 0));
}

/**
 * `drawing-line` (E14-T03): p0 → p1 as the shader projects them, a ray or an extended line run
 * out as far as the shader's; an extended line starts a whole number of dash periods before p0,
 * so the bucket's dash pattern (which restarts per subpath) lines up with the shader's.
 */
export function paintDrawingLine(ctx: Ctx2DLike, a: PaintArgs): void {
  const b = a.block;
  if (b === null) return;
  const x0 = lineX(a, b, 0);
  const y0 = lineY(a, b, 0);
  const dx = lineX(a, b, 1) - x0;
  const dy = lineY(a, b, 1) - y0;
  const len = Math.hypot(dx, dy);
  const dir = a.data[a.at + STYLE + 3] ?? 0; // 1 horizontal, 2 vertical (hline / vline)
  const ux = dir > 1.5 ? 0 : dir > 0.5 ? 1 : len > 1e-6 ? dx / len : 1;
  const uy = dir > 1.5 ? 1 : dir > 0.5 ? 0 : len > 1e-6 ? dy / len : 0;
  const ext = a.data[a.at + STYLE + 2] ?? 0;
  const far = 2 * (Math.abs(x0) + Math.abs(y0) + (b.floats[4] ?? 0) + (b.floats[5] ?? 0));
  const period = (DASH_LUT[a.data[a.at + STYLE + 1] ?? 0]?.[1] ?? 0) * (a.data[a.at + STYLE] ?? 0);
  const s0 = ext > 1.5 ? -(period > 0 ? Math.ceil(far / period) * period : far) : 0;
  const s1 = ext > 0.5 ? far : len;
  const sx = scaleX(a);
  const sy = scaleY(a);
  ctx.moveTo((x0 + ux * s0) * sx, (y0 + uy * s0) * sy);
  ctx.lineTo((x0 + ux * s1) * sx, (y0 + uy * s1) * sy);
}

/**
 * `drawing-label`'s run (E14-T03 PR 2) at `a.at` in the label ring's run table: its anchor through
 * the block as the shader's `project()`, plus the run's device-px offset, then `fillText` of the
 * record's clamped label at that baseline (text as data: no markup, no CSS from the style).
 */
export function paintDrawingLabel(ctx: Ctx2DLike, a: PaintArgs, text: string): void {
  const b = a.block;
  if (b === null || ctx.fillText === undefined) return;
  const o = a.at + RUN.anchor;
  const rx = (a.ints[o] ?? 0) - (b.ints[0] ?? 0) + (a.data[o + 2] ?? 0);
  const ry = (a.ints[o + 1] ?? 0) - (b.ints[1] ?? 0) + (a.data[o + 3] ?? 0);
  const x = (rx + 0.5 - (b.floats[3] ?? 0)) * (b.floats[0] ?? 0) + (a.data[a.at + RUN.x] ?? 0);
  const y = projectRel(b.floats, ry) + (a.data[a.at + RUN.y] ?? 0);
  ctx.fillText(text, x * scaleX(a), y * scaleY(a));
}

const FA = attributeOffset(PROGRAM.drawingFill, "a_cornerA");
const FSTYLE = attributeOffset(PROGRAM.drawingFill, "a_style");
/** Projected corners A, B, D, C (the quad in edge order), then the inset ones: u_viewport px. */
const QUAD = new Float64Array(8);
const INSET = new Float64Array(8);

/** `drawing-fill`'s corner (0 A, 1 B, 2 C, 3 D = B + C − A) through the block, as the shader. */
function fillCorner(a: PaintArgs, b: PaneUniforms, c: number, out: Float64Array, o: number): void {
  const w = a.at + FA;
  const { ints, data } = a;
  // D sums the ints and the fractions apart, as the shader's ivec arithmetic does.
  const d = c === 3;
  const at = w + 4 * (d ? 1 : c);
  let ii = ints[at] ?? 0;
  let it = ints[at + 1] ?? 0;
  let fi = data[at + 2] ?? 0;
  let ft = data[at + 3] ?? 0;
  if (d) {
    ii += (ints[w + 8] ?? 0) - (ints[w] ?? 0);
    it += (ints[w + 9] ?? 0) - (ints[w + 1] ?? 0);
    fi += (data[w + 10] ?? 0) - (data[w + 2] ?? 0);
    ft += (data[w + 11] ?? 0) - (data[w + 3] ?? 0);
  }
  const ri = ii - (b.ints[0] ?? 0) + fi;
  out[o] = (ri + 0.5 - (b.floats[3] ?? 0)) * (b.floats[0] ?? 0);
  out[o + 1] = projectRel(b.floats, it - (b.ints[1] ?? 0) + ft);
}

/** Moves the quad's edges `hw` inward (toward its centre); false when it would fold over. */
function inset(hw: number): boolean {
  const mx = ((QUAD[0] as number) + (QUAD[4] as number)) / 2;
  const my = ((QUAD[1] as number) + (QUAD[5] as number)) / 2;
  let area = 0;
  for (let v = 0; v < 4; v += 1) {
    // Vertex v is where the inset edges (v - 1, v) and (v, v + 1) meet.
    const p = 2 * ((v + 3) % 4);
    const q = 2 * v;
    const r = 2 * ((v + 1) % 4);
    shift(p, q, mx, my, hw);
    const ax = SHIFT[0] as number;
    const ay = SHIFT[1] as number;
    const ux = SHIFT[2] as number;
    const uy = SHIFT[3] as number;
    shift(q, r, mx, my, hw);
    const bx = SHIFT[0] as number;
    const by = SHIFT[1] as number;
    const wx = SHIFT[2] as number;
    const wy = SHIFT[3] as number;
    const den = ux * wy - uy * wx;
    const t = Math.abs(den) < 1e-12 ? 0 : ((bx - ax) * wy - (by - ay) * wx) / den;
    INSET[q] = ax + ux * t;
    INSET[q + 1] = ay + uy * t;
  }
  for (let v = 0; v < 4; v += 1) {
    const n = 2 * ((v + 1) % 4);
    area += (INSET[2 * v] as number) * (INSET[n + 1] as number);
    area -= (INSET[n] as number) * (INSET[2 * v + 1] as number);
  }
  let was = 0;
  for (let v = 0; v < 4; v += 1) {
    const n = 2 * ((v + 1) % 4);
    was += (QUAD[2 * v] as number) * (QUAD[n + 1] as number);
    was -= (QUAD[n] as number) * (QUAD[2 * v + 1] as number);
  }
  return area * was > 0 && Math.abs(area) > 1e-9;
}
const SHIFT = new Float64Array(4);
/** The edge i → j moved `hw` toward (mx, my), into `SHIFT` as [x, y, dx, dy]. */
function shift(i: number, j: number, mx: number, my: number, hw: number): void {
  const x = QUAD[i] as number;
  const y = QUAD[i + 1] as number;
  const dx = (QUAD[j] as number) - x;
  const dy = (QUAD[j + 1] as number) - y;
  const len = Math.hypot(dx, dy) || 1;
  const side = (mx - x) * -dy + (my - y) * dx < 0 ? -1 : 1; // the normal toward the centre
  SHIFT[0] = x + ((side * -dy) / len) * hw;
  SHIFT[1] = y + ((side * dx) / len) * hw;
  SHIFT[2] = dx;
  SHIFT[3] = dy;
}

/**
 * `drawing-fill` (E14-T03 slice 3), `sub` 0 the fill and 1 an ellipse's ring: the shader's
 * corners; a rect's or band's fill inset half a stroke (its outline is `drawing-line`'s), an
 * ellipse's fill inside its ring; the bucket fills or strokes the path.
 */
export function paintDrawingFill(ctx: Ctx2DLike, a: PaintArgs): void {
  const b = a.block;
  if (b === null) return;
  fillCorner(a, b, 0, QUAD, 0);
  fillCorner(a, b, 1, QUAD, 2);
  fillCorner(a, b, 3, QUAD, 4);
  fillCorner(a, b, 2, QUAD, 6);
  const sx = scaleX(a);
  const sy = scaleY(a);
  const hw = (a.data[a.at + FSTYLE + 1] ?? 0) / 2;
  if ((a.data[a.at + FSTYLE] ?? 0) === 1) {
    const cx = ((QUAD[0] as number) + (QUAD[4] as number)) / 2;
    const cy = ((QUAD[1] as number) + (QUAD[5] as number)) / 2;
    const ring = a.sub === 1;
    const rx = Math.abs((QUAD[4] as number) - (QUAD[0] as number)) / 2 - (ring ? 0 : hw);
    const ry = Math.abs((QUAD[5] as number) - (QUAD[1] as number)) / 2 - (ring ? 0 : hw);
    if (rx <= 0 || ry <= 0 || ctx.ellipse === undefined) return;
    ctx.moveTo((cx + rx) * sx, cy * sy);
    ctx.ellipse(cx * sx, cy * sy, rx * sx, ry * sy, 0, 0, 2 * Math.PI);
    return;
  }
  if (!inset(hw)) return; // narrower than its stroke: the outline covers it
  ctx.moveTo((INSET[0] as number) * sx, (INSET[1] as number) * sy);
  for (let v = 1; v < 4; v += 1)
    ctx.lineTo((INSET[2 * v] as number) * sx, (INSET[2 * v + 1] as number) * sy);
}

/** Indexed by `PROGRAM`; `sdf-text` has none: the 2D path cannot rebuild strings (BQ-88). */
export const PAINTERS: readonly (((ctx: Ctx2DLike, a: PaintArgs) => void) | null)[] = [
  paintLine,
  paintQuad,
  null,
  paintBarCell,
  paintCandle,
  paintDrawingLine,
  paintDrawingFill,
  null, // `drawing-label`: the backend paints its runs' strings (`paintDrawingLabel`), not glyphs
];
