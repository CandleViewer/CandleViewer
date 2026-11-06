// Precise hit tests (E11-S08, 26 §3.9): distances in CSS px from a point to each pickable shape,
// over plain numbers. A non-finite result is +Infinity, so a degenerate projection never picks.

const fin = (d: number): number => (d >= 0 && d < Number.POSITIVE_INFINITY ? d : Infinity);

/** Distance from (px, py) to the point a + t(b - a), t clamped to [0, hi]. */
function along(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
  hi: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 > 0 ? Math.min(hi, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  return fin(Math.hypot(px - (ax + t * dx), py - (ay + t * dy)));
}

/** The segment a-b; a zero-length segment is its point. */
export const distToSegment = (
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number => along(px, py, ax, ay, bx, by, 1);

/** The ray from a through b, unbounded past b. */
export const distToRay = (
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number => along(px, py, ax, ay, bx, by, Infinity);

/** 0 inside the box spanned by the two corners (the fill), else the distance to its edge. */
export function distToRect(
  px: number,
  py: number,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): number {
  const dx = Math.max(Math.min(x0, x1) - px, 0, px - Math.max(x0, x1));
  const dy = Math.max(Math.min(y0, y1) - py, 0, py - Math.max(y0, y1));
  return fin(Math.hypot(dx, dy));
}

/** 0 inside the disc, else the distance to its rim. */
export const distToCircle = (px: number, py: number, cx: number, cy: number, r: number): number =>
  fin(Math.max(0, Math.hypot(px - cx, py - cy) - r));

/**
 * E14-T04: 0 inside the ellipse inscribed in the box of the two corners, else the distance to
 * the rim along the ray from its centre: never less than the true distance, so a pick is never
 * looser than drawn. A flat box is its segment.
 */
export function distToEllipse(
  px: number,
  py: number,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): number {
  const rx = Math.abs(x1 - x0) / 2;
  const ry = Math.abs(y1 - y0) / 2;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  if (!(rx > 0 && ry > 0)) return distToSegment(px, py, x0, y0, x1, y1);
  const dx = px - cx;
  const dy = py - cy;
  const q = Math.hypot(dx / rx, dy / ry);
  if (q <= 1) return 0;
  return fin(Math.hypot(dx - dx / q, dy - dy / q));
}

/**
 * E14-T04 (ticket Technical notes): the part a + t(b - a), t in [lo, hi], inside the box
 * [x0, x1] × [y0, y1] (Liang–Barsky), written to `out` as [ax, ay, bx, by]; false when none is.
 * A ray is [0, ∞), an extended line (-∞, ∞): an infinite extension costs one clip.
 */
export function clipToBox(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  lo: number,
  hi: number,
  box: readonly [number, number, number, number],
  out: Float64Array,
): boolean {
  const dx = bx - ax;
  const dy = by - ay;
  T[0] = lo;
  T[1] = hi;
  const inside =
    edge(-dx, ax - box[0]) &&
    edge(dx, box[2] - ax) &&
    edge(-dy, ay - box[1]) &&
    edge(dy, box[3] - ay);
  const t0 = T[0] as number;
  const t1 = T[1] as number;
  if (!inside || !Number.isFinite(t0) || !Number.isFinite(t1)) return false; // a point off the box
  out[0] = ax + t0 * dx;
  out[1] = ay + t0 * dy;
  out[2] = ax + t1 * dx;
  out[3] = ay + t1 * dy;
  return true;
}

/** The clip's [t0, t1], reused: a pick allocates nothing. */
const T = new Float64Array(2);

/** One Liang–Barsky edge: narrows T; false when the part leaves the box. */
function edge(p: number, q: number): boolean {
  if (p === 0) return q >= 0;
  const r = q / p;
  if (p < 0) T[0] = Math.max(T[0] as number, r);
  else T[1] = Math.min(T[1] as number, r);
  return (T[0] as number) <= (T[1] as number);
}

/** BQ-130: CSS px, shared by bodies and handles; the threshold is `widthPx / 2 + tolerance`. */
export const TOLERANCE_PX = { mouse: 10, pen: 10, touch: 16 } as const;
export type PointerType = keyof typeof TOLERANCE_PX;

export const toleranceFor = (pointer: PointerType): number => TOLERANCE_PX[pointer];
