// The crosshair model (E11-S07, CMP-190; E11-D01 D3, E11-D02 §7.3, E11-D06 §5.3): pure state and
// maths, DOM-free, no allocation. The vertical line snaps to the bar centre through the shared
// transform (`screenToIndex`, then `indexToScreen`); the horizontal one is free (the nearest tick)
// unless the magnet is on. `weak` snaps to the nearest O/H/L/C within 12 px of screen y and holds
// that snap until 14 px (2 px release hysteresis); `strong` always snaps to the nearest of the
// four. The public event is edge-triggered on the bar alone (BQ-10). Key stepping is a pure
// function here; no key handling is wired to it yet (BQ-7 pending).
import { indexToScreen, priceToScreen, screenToIndex, screenToPrice } from "../viewport/index.js";
import type { ViewportState } from "../viewport/index.js";

export type MagnetMode = "off" | "weak" | "strong";
export type SnapField = "open" | "high" | "low" | "close" | null;
export type CrosshairDriver = "pointer" | "key" | "none";

/** E11-D01 D3: the weak magnet's radius in CSS px (not the ticket's 8 px; BQ-8, C-row). */
export const WEAK_RADIUS = 12;
/** E11-D06 §5.3: a weak snap holds until the pointer is this much past the radius. */
export const RELEASE_HYSTERESIS = 2;
/** E06-D03 D6: the ±10-bar step (`Shift+←/→` and the `PageUp/PageDown` alias). */
export const BIG_STEP = 10;

/** The bar columns the magnet reads, in ticks from `priceOrigin`; `BarView` fits structurally. */
export interface OhlcColumns {
  readonly open: ArrayLike<number>;
  readonly high: ArrayLike<number>;
  readonly low: ArrayLike<number>;
  readonly close: ArrayLike<number>;
  readonly length: number;
}

export interface CrosshairState {
  driver: CrosshairDriver;
  visible: boolean;
  /** The intersection in CSS px: the bar centre and the line's y (free or snapped). */
  x: number;
  y: number;
  /** The bar under the line, unclamped (a cursor right of the data has no bar data); -1 none. */
  bar: number;
  /** The price in ticks from `priceOrigin`: an integer, or NaN while there is none. */
  tick: number;
  snap: SnapField;
  /** The bar the last public event carried (BQ-10); -1 before the first. */
  emittedBar: number;
}

export const createCrosshair = (): CrosshairState => ({
  driver: "none",
  visible: false,
  x: Number.NaN,
  y: Number.NaN,
  bar: -1,
  tick: Number.NaN,
  snap: null,
  emittedBar: -1,
});

/** Pointer left the plot: hidden, the last bar kept, no event (BQ-10). */
export function hideCrosshair(s: CrosshairState): void {
  s.visible = false;
  s.driver = "none";
  s.snap = null;
}

/** The bar centre's x for the bar under `x` (BQ-68: floor, then the centre). */
export function snapBarX(vp: ViewportState, x: number): number {
  return indexToScreen(vp, screenToIndex(vp, x));
}

const FIELDS = ["open", "high", "low", "close"] as const;

const columnOf = (bars: OhlcColumns, f: (typeof FIELDS)[number]): ArrayLike<number> => bars[f];

/** The field of bar `i` nearest screen `y` (first of O, H, L, C on a tie), and its distance. */
function nearest(
  vp: ViewportState,
  pane: number,
  bars: OhlcColumns,
  i: number,
  y: number,
  out: Nearest,
): void {
  out.field = null;
  out.dist = Number.POSITIVE_INFINITY;
  for (let k = 0; k < FIELDS.length; k += 1) {
    const f = FIELDS[k] as (typeof FIELDS)[number];
    const t = columnOf(bars, f)[i];
    if (t === undefined || !Number.isFinite(t)) continue;
    const d = Math.abs(priceToScreen(vp, pane, t) - y);
    if (d < out.dist) {
      out.dist = d;
      out.field = f;
      out.tick = t;
    }
  }
}
interface Nearest {
  field: SnapField;
  dist: number;
  tick: number;
}
const NEAR: Nearest = { field: null, dist: 0, tick: 0 };

/**
 * Resolves the pointer at (x, y) into `s` (CSS px, plot-relative): the bar and its centre, then
 * the price by `mode`. A weak snap is held while the pointer stays within `WEAK_RADIUS +
 * RELEASE_HYSTERESIS` px of the same field on the same bar (released at that distance, entered
 * at `WEAK_RADIUS` or less). Values are read at the bar, never interpolated between bars.
 */
export function resolvePointer(
  s: CrosshairState,
  vp: ViewportState,
  pane: number,
  bars: OhlcColumns | null,
  x: number,
  y: number,
  mode: MagnetMode,
): void {
  const bar = screenToIndex(vp, x);
  const held = s.visible && s.bar === bar ? s.snap : null;
  s.driver = "pointer";
  s.visible = true;
  s.bar = bar;
  s.x = indexToScreen(vp, bar);
  s.snap = null;
  if (mode !== "off" && bars !== null && bar >= 0 && bar < bars.length) {
    nearest(vp, pane, bars, bar, y, NEAR);
    let field = NEAR.field;
    let tick = NEAR.tick;
    if (mode === "weak") {
      const heldTick = held === null ? Number.NaN : (columnOf(bars, held)[bar] ?? Number.NaN);
      const heldDist = Math.abs(priceToScreen(vp, pane, heldTick) - y);
      if (heldDist < WEAK_RADIUS + RELEASE_HYSTERESIS && NEAR.dist >= heldDist) {
        field = held;
        tick = heldTick;
      } else if (NEAR.dist > WEAK_RADIUS) {
        field = null;
      }
    }
    if (field !== null) {
      s.snap = field;
      s.tick = tick;
      s.y = priceToScreen(vp, pane, tick);
      return;
    }
  }
  s.tick = Math.round(screenToPrice(vp, pane, y));
  s.y = y;
}

/**
 * The public event's edge (BQ-10): true once per bar change while the crosshair is visible, and
 * the bar is recorded as emitted. Price-only moves and a pointer leaving never fire.
 */
export function takeBarEdge(s: CrosshairState): boolean {
  if (!s.visible || s.bar === s.emittedBar) return false;
  s.emittedBar = s.bar;
  return true;
}

/** A key step (E11-D02 §7.3, E06-D03 D6), as plain codes; no key wiring yet (BQ-7). */
export const STEP = {
  barPrev: 1,
  barNext: 2,
  pagePrev: 3,
  pageNext: 4,
  levelUp: 5,
  levelDown: 6,
  first: 7,
  last: 8,
} as const;
export type StepCode = (typeof STEP)[keyof typeof STEP];

export interface StepResult {
  bar: number;
  /** Ticks; NaN while unseeded (the caller seeds it, e.g. with the bar's close). */
  tick: number;
  /** -1 on the first loaded bar, 1 on the last, else 0 (the edge is announced once, D5). */
  edge: -1 | 0 | 1;
  /** True when a bar step was refused at the loaded edge (no move happened). */
  clamped: boolean;
  /** Bars the view must scroll so the cursor bar stays fully visible (signed; 0 when it is). */
  follow: number;
}

export const createStepResult = (): StepResult => ({
  bar: -1,
  tick: Number.NaN,
  edge: 0,
  clamped: false,
  follow: 0,
});

/**
 * One key step from (`bar`, `tick`) over `length` loaded bars: ±1 or ±10 bars clamped to the
 * data, ±`levelTicks` in price, or the first / last bar. With no cursor placed (`bar` < 0) any
 * bar step lands on the last fully visible bar. `follow` is how far the view must move to keep
 * the landing bar inside [first, last] fully visible bars of `vp`. Writes `out`; no allocation.
 */
export function stepCursor(
  vp: ViewportState,
  length: number,
  bar: number,
  tick: number,
  code: StepCode,
  levelTicks: number,
  out: StepResult,
): StepResult {
  const lastBar = length - 1;
  const firstVisible = Math.ceil(vp.leftIndex);
  const lastVisible = Math.floor(vp.leftIndex + vp.plotWidth / vp.barSpacing) - 1;
  let b = bar;
  let t = tick;
  out.clamped = false;
  if (length <= 0) {
    out.bar = -1;
    out.tick = Number.NaN;
    out.edge = 0;
    out.follow = 0;
    return out;
  }
  if (b < 0 || b > lastBar) b = Math.min(lastBar, Math.max(0, lastVisible));
  else if (code === STEP.levelUp || code === STEP.levelDown) {
    t = Number.isFinite(t) ? t + (code === STEP.levelUp ? levelTicks : -levelTicks) : t;
  } else {
    let next = b;
    if (code === STEP.barPrev) next = b - 1;
    else if (code === STEP.barNext) next = b + 1;
    else if (code === STEP.pagePrev) next = b - BIG_STEP;
    else if (code === STEP.pageNext) next = b + BIG_STEP;
    else if (code === STEP.first) next = 0;
    else next = lastBar;
    const clampedNext = Math.min(lastBar, Math.max(0, next));
    out.clamped = clampedNext === b && next !== b;
    b = clampedNext;
  }
  out.bar = b;
  out.tick = t;
  out.edge = b === 0 ? -1 : b === lastBar ? 1 : 0;
  out.follow = b < firstVisible ? b - firstVisible : b > lastVisible ? b - lastVisible : 0;
  return out;
}

/** Places a key-driven cursor in `s` from a step (the price line at the tick, the bar centre). */
export function applyStep(
  s: CrosshairState,
  vp: ViewportState,
  pane: number,
  r: Readonly<StepResult>,
): void {
  s.driver = "key";
  s.visible = r.bar >= 0;
  s.bar = r.bar;
  s.tick = r.tick;
  s.snap = null;
  s.x = indexToScreen(vp, r.bar);
  s.y = Number.isFinite(r.tick) ? priceToScreen(vp, pane, r.tick) : Number.NaN;
}
