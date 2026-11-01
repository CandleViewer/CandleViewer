/**
 * Moving a node without dragging (WCAG 2.5.7; 05 §3.4 item 8; E47-S03 Gherkin 2, BQ-05): a
 * focused node moves by a discrete step per key press, a larger step with Shift, and the new
 * position is announced. The second non-drag path is the node's "Move node..." menu entry with
 * numeric X / Y fields (`moveTo`). Positions are canvas units, clamped to the canvas bounds and
 * rounded to whole units, so no key press can carry a node off the canvas or onto a fraction.
 * Bounds come from the canvas and are trusted to be finite; a NaN bound would yield NaN.
 *
 * Announcements, one per settled move (05 §6.2, E37-D02 §14: never per keystroke): the nudge keys
 * keep `ignoreRepeat: false` so a held key keeps moving the node, and `settledNudge` builds the one
 * sentence for a burst ("Moved AND 40 right, now x 280, y 120."). `nudge(...).text` is for a single
 * press only. Carried rows, hard gates for the wiring PR (E37-S05 #1071, with the window constant
 * from E37-D04 #949):
 * - N-1: while a nudge key repeats, nothing is announced; on keyup (or after the settle window)
 *   the wiring announces `settledNudge` once, politely. Landing without this is a 05 §6.2 failure.
 * - N-2: macOS takes Ctrl+arrows for Mission Control and Spaces before the browser sees them, so
 *   on a Mac the "Move node..." dialog (`moveTo`) is the stated keyboard path until E37-D04 picks a
 *   Mac chord (Option+arrows is the candidate); the cheat sheet says so.
 * - N-3: `rules.add_node` Ctrl+Shift+N is taken by Chrome and Edge (new private window) before the
 *   page sees it, so it works in the desktop app only; in the browser the keyboard path is the
 *   palette (search, Enter to add) and the header's visible Add node control, and the cheat sheet
 *   marks the key "desktop app only" (E47-S08 #1322).
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
  // `+ 0` turns a -0 (Math.round(-0.4)) into 0, so a position is never negative zero.
  return Math.min(hi, Math.max(lo, Math.round(finite(value, lo)))) + 0;
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

/**
 * The one announcement for a burst of nudges of the node named `name` that started at `from` and
 * ended at `last` (the final `nudge` result): the net move per axis, then where it stopped.
 */
export function settledNudge(name: string, from: Point, last: Moved, bounds: Bounds): string {
  const start = clampPoint(from, bounds);
  const { x, y } = last.position;
  const dx = x - start.x;
  const dy = y - start.y;
  const parts = [
    ...(dx === 0 ? [] : [copy.distance(Math.abs(dx), dx > 0 ? "right" : "left")]),
    ...(dy === 0 ? [] : [copy.distance(Math.abs(dy), dy > 0 ? "down" : "up")]),
  ];
  if (parts.length === 0) return last.clamped ? copy.atEdge(name, x, y) : copy.movedTo(name, x, y);
  return copy.movedBy(name, parts, x, y) + (last.clamped ? copy.stoppedAtEdge() : "");
}
