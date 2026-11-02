// The accessibility window (E11-S13 PR-1; E06-D03 D1, D7, D9): which bars the DOM mirror holds,
// which bars are visible and where the selected cursor is, computed in the render worker from
// the engine's own state. Pure: no DOM, no I/O, no allocation per call (C-2.16). The mirror that
// renders it is PR-2's; this file is the canvas's presentation-free query surface only.

/** E06-D03 D9: the footprint and candle tiers of 26 §3.6, reported separately (D7). */
export type FootprintTier = "L0" | "L1" | "L2" | "L3";
export type CandleTier = "L0" | "L1" | "L2";
/** E06-D03 D9: who moved the cursor; `pointer` is a click only, hover never reaches a11y (D6). */
export type CursorOrigin = "pointer" | "keyboard" | "table" | "data";

/** E06-D03 D9 `A11yWindow`; bar positions are absolute in the loaded series. */
export interface A11yWindow {
  /** The mirror window: centred on the cursor (D1), not the visible range; empty is 0, -1. */
  readonly firstBar: number;
  readonly lastBar: number;
  /** The visible range, exposed separately (D1); empty is 0, -1. */
  readonly viewFirstBar: number;
  readonly viewLastBar: number;
  /** Derived from `cursorTime` when posted; -1 with no bars. */
  readonly cursorBar: number;
  /** The selected cursor itself, µs; it survives prependHistory, resize and zoom. NaN: none. */
  readonly cursorTime: number;
  readonly footprintTier: FootprintTier;
  readonly candleTier: CandleTier;
  /** 1 unless `candleTier` is L2 (bars per device-px column, 26 §3.6). */
  readonly barsPerColumn: number;
}

export type MutableA11yWindow = { -readonly [K in keyof A11yWindow]: A11yWindow[K] };

/** E06-D03 D1: the default window is 60 rows, configurable up to the 200-row cap. */
export const A11Y_WINDOW_ROWS = 60;
export const A11Y_WINDOW_ROWS_MAX = 200;

const FOOTPRINT_TIERS: readonly FootprintTier[] = ["L0", "L1", "L2", "L3"];
const CANDLE_TIERS: readonly CandleTier[] = ["L0", "L1", "L2"];

export const EMPTY_A11Y_WINDOW: A11yWindow = Object.freeze({
  firstBar: 0,
  lastBar: -1,
  viewFirstBar: 0,
  viewLastBar: -1,
  cursorBar: -1,
  cursorTime: Number.NaN,
  footprintTier: "L0",
  candleTier: "L0",
  barsPerColumn: 1,
});

/** The bar index <-> time map the window reads (`IndexTimeMap` fits it structurally). */
export interface A11yBars {
  readonly length: number;
  indexToTime(i: number): number;
  timeToIndex(t: number): number;
}

/** The viewport fields the visible range and the L2 column width come from. */
export interface A11yView {
  readonly leftIndex: number;
  readonly barSpacing: number;
  readonly plotWidth: number;
  readonly dpr: number;
}

/**
 * Writes the window into `out` and returns it. `cursorTime` NaN follows the latest bar (the
 * auto-follow cursor, 05 §3.2 `End`); a time in a gap or before the first bar resolves to the
 * last bar at or before it, else bar 0. `rows` is clamped to [1, A11Y_WINDOW_ROWS_MAX].
 */
export function computeA11yWindow(
  out: MutableA11yWindow,
  bars: A11yBars,
  view: A11yView,
  cursorTime: number,
  lod: { readonly candles: number; readonly footprint: number },
  rows: number = A11Y_WINDOW_ROWS,
): MutableA11yWindow {
  const n = bars.length;
  out.footprintTier = FOOTPRINT_TIERS[lod.footprint] ?? "L0";
  out.candleTier = CANDLE_TIERS[lod.candles] ?? "L0";
  const px = view.barSpacing * view.dpr;
  out.barsPerColumn = out.candleTier === "L2" && px > 0 ? Math.max(1, Math.ceil(1 / px)) : 1;
  if (n <= 0) {
    out.firstBar = 0;
    out.lastBar = -1;
    out.viewFirstBar = 0;
    out.viewLastBar = -1;
    out.cursorBar = -1;
    out.cursorTime = Number.NaN;
    return out;
  }
  const cursor = Number.isNaN(cursorTime) ? n - 1 : Math.max(0, bars.timeToIndex(cursorTime));
  out.cursorBar = Math.min(n - 1, cursor);
  out.cursorTime = Number.isNaN(cursorTime) ? bars.indexToTime(out.cursorBar) : cursorTime;
  const size = Math.min(n, Math.max(1, Math.min(A11Y_WINDOW_ROWS_MAX, Math.floor(rows) || 1)));
  out.firstBar = Math.min(n - size, Math.max(0, out.cursorBar - Math.floor(size / 2)));
  out.lastBar = out.firstBar + size - 1;
  const from = Math.max(0, Math.floor(view.leftIndex));
  const to = view.barSpacing > 0 ? view.leftIndex + view.plotWidth / view.barSpacing : from;
  const last = Math.min(n - 1, Math.ceil(to) - 1);
  out.viewFirstBar = last >= from ? from : 0;
  out.viewLastBar = last >= from ? last : -1;
  return out;
}

const CURSOR_KEYS = [
  "firstBar",
  "lastBar",
  "cursorBar",
  "footprintTier",
  "candleTier",
  "barsPerColumn",
] as const;

/** The cursor window (everything but the visible range) is the same; NaN equals NaN. */
export function sameCursorWindow(a: A11yWindow, b: A11yWindow): boolean {
  // An indexed loop: this runs every rendered frame, so no iterator is created (rule 31).
  for (let i = 0; i < CURSOR_KEYS.length; i += 1) {
    const k = CURSOR_KEYS[i] as (typeof CURSOR_KEYS)[number];
    if (a[k] !== b[k]) return false;
  }
  return Object.is(a.cursorTime, b.cursorTime);
}

/** Copies `src` into `out` field by field (no `Object.assign`, no allocation; rule 31). */
export function copyA11yWindow(out: MutableA11yWindow, src: A11yWindow): void {
  out.firstBar = src.firstBar;
  out.lastBar = src.lastBar;
  out.viewFirstBar = src.viewFirstBar;
  out.viewLastBar = src.viewLastBar;
  out.cursorBar = src.cursorBar;
  out.cursorTime = src.cursorTime;
  out.footprintTier = src.footprintTier;
  out.candleTier = src.candleTier;
  out.barsPerColumn = src.barsPerColumn;
}

export const sameView = (a: A11yWindow, b: A11yWindow): boolean =>
  a.viewFirstBar === b.viewFirstBar && a.viewLastBar === b.viewLastBar;

const ORIGINS: ReadonlySet<unknown> = new Set(["pointer", "keyboard", "table", "data"]);
const int = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= -1;

/** One decoded `a11y` message: the window, its origin and the visible range's times. */
export interface A11yUpdate {
  readonly window: A11yWindow;
  readonly origin: CursorOrigin;
  readonly viewTimeStart: number;
  readonly viewTimeEnd: number;
}

/**
 * Reads the window out of an `a11y` message on the main thread. Version-safe: a message from an
 * older worker (only `cursorSummary`) or a malformed one returns null and the caller keeps its
 * cache. Never throws.
 */
export function readA11yUpdate(msg: unknown): A11yUpdate | null {
  if (typeof msg !== "object" || msg === null) return null;
  const m = msg as Record<string, unknown>;
  const [first, last, vFirst, vLast, cursor] = [
    m["firstBar"],
    m["lastBar"],
    m["viewFirstBar"],
    m["viewLastBar"],
    m["cursorBar"],
  ];
  const ok =
    int(first) &&
    int(last) &&
    int(vFirst) &&
    int(vLast) &&
    int(cursor) &&
    // Empty is exactly (0, -1); any other pair is a non-inverted range (an inverted empty
    // window such as first 5, last -1 is malformed).
    (vLast === -1 ? vFirst === 0 : vLast >= vFirst) &&
    (last === -1 ? first === 0 : last >= first) &&
    last - first + 1 <= A11Y_WINDOW_ROWS_MAX &&
    (cursor === -1 ? last === -1 : cursor >= first && cursor <= last) &&
    typeof m["cursorTime"] === "number" &&
    FOOTPRINT_TIERS.includes(m["footprintTier"] as FootprintTier) &&
    CANDLE_TIERS.includes(m["candleTier"] as CandleTier) &&
    int(m["barsPerColumn"]) &&
    (m["barsPerColumn"] as number) >= 1 &&
    ORIGINS.has(m["origin"]) &&
    typeof m["viewTimeStart"] === "number" &&
    typeof m["viewTimeEnd"] === "number";
  if (!ok) return null;
  return {
    window: {
      firstBar: first,
      lastBar: last,
      viewFirstBar: vFirst,
      viewLastBar: vLast,
      cursorBar: cursor,
      cursorTime: m["cursorTime"] as number,
      footprintTier: m["footprintTier"] as FootprintTier,
      candleTier: m["candleTier"] as CandleTier,
      barsPerColumn: m["barsPerColumn"] as number,
    },
    origin: m["origin"] as CursorOrigin,
    viewTimeStart: m["viewTimeStart"] as number,
    viewTimeEnd: m["viewTimeEnd"] as number,
  };
}
