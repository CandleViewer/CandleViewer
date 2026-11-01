/**
 * Moving a node without dragging (WCAG 2.5.7; 05 §3.4 item 8; E47-S03 Gherkin 2, BQ-05): a
 * focused node moves by a discrete step per key press, a larger step with Shift, and the new
 * position is announced. The second non-drag path is the node's "Move node..." menu entry with
 * numeric X / Y fields (`moveTo`). Positions are canvas units, clamped to the canvas bounds and
 * rounded to whole units, so no key press can carry a node off the canvas or onto a fraction.
 */
import { copy, type Direction } from "./copy.js";

/** PROPOSED step sizes, pending E37-D04's keyboard authoring map. */
export const NUDGE_STEP = 8;
export const NUDGE_LARGE_STEP = 32;

export interface Point {
  readonly x: number;
  readonly y: number;
}

export interface Bounds {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

export interface Moved {
  readonly position: Point;
  /** True when the bounds stopped the move short of the full step (or held it in place). */
  readonly clamped: boolean;
  readonly text: string;
}

const DELTA: Readonly<Record<Direction, Point>> = {
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  up: { x: 0, y: -1 },
  down: { x: 0, y: 1 },
};

const finite = (v: number, fallback: number): number => (Number.isFinite(v) ? v : fallback);

function clamp(value: number, min: number, max: number): number {
  const lo = Math.min(min, max);
  const hi = Math.max(min, max);
  return Math.min(hi, Math.max(lo, Math.round(finite(value, lo))));
}

const clampPoint = (p: Point, b: Bounds): Point => ({
  x: clamp(p.x, b.minX, b.maxX),
  y: clamp(p.y, b.minY, b.maxY),
});

/** One nudge of the node named `name` from `from` in `dir`; `large` is the Shift step. */
export function nudge(
  name: string,
  from: Point,
  dir: Direction,
  large: boolean,
  bounds: Bounds,
): Moved {
  const start = clampPoint(from, bounds);
  const step = large ? NUDGE_LARGE_STEP : NUDGE_STEP;
  const d = DELTA[dir];
  const wanted = { x: start.x + d.x * step, y: start.y + d.y * step };
  const position = clampPoint(wanted, bounds);
  const clamped = position.x !== wanted.x || position.y !== wanted.y;
  const text = clamped
    ? copy.atEdge(name, position.x, position.y)
    : copy.moved(name, dir, step, position.x, position.y);
  return { position, clamped, text };
}

/** The "Move node..." path: an exact position typed in, clamped and rounded the same way. */
export function moveTo(name: string, to: Point, bounds: Bounds): Moved {
  const position = clampPoint(to, bounds);
  const clamped = position.x !== to.x || position.y !== to.y;
  const text = clamped
    ? copy.atEdge(name, position.x, position.y)
    : copy.movedTo(name, position.x, position.y);
  return { position, clamped, text };
}
