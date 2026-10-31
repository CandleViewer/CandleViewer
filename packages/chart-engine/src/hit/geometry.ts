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

/** BQ-130: CSS px, shared by bodies and handles; the threshold is `widthPx / 2 + tolerance`. */
export const TOLERANCE_PX = { mouse: 10, pen: 10, touch: 16 } as const;
export type PointerType = keyof typeof TOLERANCE_PX;

export const toleranceFor = (pointer: PointerType): number => TOLERANCE_PX[pointer];
