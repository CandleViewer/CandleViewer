/**
 * The one composite-grid focus model (E47-S02, #1358; `05` §3.4.2, the WAI-ARIA APG grid): one Tab stop, arrow keys
 * move it, `PageUp`/`PageDown` and `Home`/`End` jump, `Ctrl+Home`/`Ctrl+End` reach the corners, and the stop survives
 * data churn by following its row's key. Pure and framework-free: `useCompositeGrid` is its thin React host, and the
 * footprint, DOM-ladder and profile surrogates consume it (15 §11.3: the pattern is specified once).
 *
 * The window helpers (`clampIndex`, `drawnRange`, `needsRecentre`) are SCR-045's windowing (ChartDataTable, E47-S01)
 * moved here so both surfaces draw the same buffer around the cursor. CMP-049 keeps its own 2-D arrows (packages/ui);
 * this module is for surrogates that are not a CMP-049 table.
 */

export interface GridPos {
  readonly row: number;
  readonly col: number;
}

/** An axis of the grid: rows (price levels, ladder rows) or columns (footprint bars). */
export type GridAxis = "row" | "col";

export interface GridConfig {
  /** Every row the surface has, not the drawn window. */
  readonly rows: number;
  readonly cols: number;
  /** `PageUp`/`PageDown`: by `pageRows` rows (the ladder), or by one column (the footprint's "by bar"). */
  readonly page: GridAxis;
  readonly pageRows: number;
  /** `Home`/`End`: the ends of the row (APG), or of the column (the footprint: the bar's first and last cell). */
  readonly homeEnd: GridAxis;
  /** Rows materialised around the focus (`05` §6.1: the mirror is windowed). */
  readonly windowRows: number;
}

export interface GridState extends GridConfig {
  readonly focus: GridPos;
  /** The focused row's key, so the stop follows its row through churn; null without keys. */
  readonly key: string | null;
  /** The first materialised row. */
  readonly first: number;
}

export type GridMove =
  "up" | "down" | "left" | "right" | "pageUp" | "pageDown" | "home" | "end" | "first" | "last";

export type GridAction =
  | { readonly type: "move"; readonly move: GridMove }
  /** Focus landed on a cell by pointer or by the AT: the stop follows it. */
  | { readonly type: "focus"; readonly row: number; readonly col: number }
  /** Data churn: a new row count (and keys, for row identity), or new columns. */
  | {
      readonly type: "data";
      readonly rows: number;
      readonly cols: number;
      readonly rowKeys?: readonly string[] | undefined;
    };

export const clampIndex = (v: number, lo: number, hi: number): number =>
  Math.min(Math.max(v, lo), hi);

/** The drawn rows: the host's in-view rows plus `buffer` either side, inside the list (SCR-045's window). */
export function drawnRange(
  view: { readonly first: number; readonly last: number },
  total: number,
  buffer: number,
): { first: number; last: number } {
  const end = Math.max(total - 1, 0);
  return {
    first: clampIndex(view.first - buffer, 0, end),
    last: clampIndex(view.last + buffer, 0, end),
  };
}

/** Focus within half a buffer of a drawn edge recentres the window, so keyboard travel never leaves the drawn rows. */
export function needsRecentre(
  row: number,
  drawn: { readonly first: number; readonly last: number },
  buffer: number,
): boolean {
  return row - drawn.first < buffer / 2 || drawn.last - row < buffer / 2;
}

/** The smallest scroll of a `size`-row window starting at `first` that keeps `row` inside it. */
export function scrollToShow(first: number, size: number, row: number, total: number): number {
  let next = first;
  if (row < next) next = row;
  else if (row > next + size - 1) next = row - size + 1;
  return clampIndex(next, 0, Math.max(total - size, 0));
}

const PLAIN_MOVES: ReadonlyMap<string, GridMove> = new Map([
  ["ArrowUp", "up"],
  ["ArrowDown", "down"],
  ["ArrowLeft", "left"],
  ["ArrowRight", "right"],
  ["PageUp", "pageUp"],
  ["PageDown", "pageDown"],
  ["Home", "home"],
  ["End", "end"],
]);

/** The grid key a keyboard event names; null leaves the event to the host (Enter, letters, Shift and Alt chords). */
export function gridMoveOf(event: {
  readonly key: string;
  readonly ctrlKey: boolean;
  readonly shiftKey: boolean;
  readonly altKey: boolean;
  readonly metaKey: boolean;
}): GridMove | null {
  if (event.altKey || event.metaKey || event.shiftKey) return null;
  if (event.ctrlKey) {
    if (event.key === "Home") return "first";
    if (event.key === "End") return "last";
    return null;
  }
  return PLAIN_MOVES.get(event.key) ?? null;
}

const lastRow = (s: GridConfig): number => Math.max(s.rows - 1, 0);
const lastCol = (s: GridConfig): number => Math.max(s.cols - 1, 0);

function moved(s: GridState, move: GridMove): GridPos {
  const { row, col } = s.focus;
  const rowEnds = s.homeEnd === "row";
  switch (move) {
    case "up":
      return { row: row - 1, col };
    case "down":
      return { row: row + 1, col };
    case "left":
      return { row, col: col - 1 };
    case "right":
      return { row, col: col + 1 };
    case "pageUp":
      return s.page === "row" ? { row: row - s.pageRows, col } : { row, col: col - 1 };
    case "pageDown":
      return s.page === "row" ? { row: row + s.pageRows, col } : { row, col: col + 1 };
    case "home":
      return rowEnds ? { row, col: 0 } : { row: 0, col };
    case "end":
      return rowEnds ? { row, col: lastCol(s) } : { row: lastRow(s), col };
    case "first":
      return { row: 0, col: 0 };
    case "last":
      return { row: lastRow(s), col: lastCol(s) };
  }
}

/** Places the stop (clamped into the grid) and scrolls the window to show it. */
function place(s: GridState, to: GridPos, key: string | null): GridState {
  const focus = { row: clampIndex(to.row, 0, lastRow(s)), col: clampIndex(to.col, 0, lastCol(s)) };
  return { ...s, focus, key, first: scrollToShow(s.first, s.windowRows, focus.row, s.rows) };
}

export function createGridState(
  config: GridConfig,
  start: Partial<GridPos> = {},
  rowKeys?: readonly string[],
): GridState {
  const base: GridState = { ...config, focus: { row: 0, col: 0 }, key: null, first: 0 };
  const row = clampIndex(start.row ?? 0, 0, lastRow(config));
  return place(base, { row, col: start.col ?? 0 }, rowKeys?.[row] ?? null);
}

/**
 * The reducer. A key the row keys no longer hold (the price scrolled off the book) clamps to the nearest row; a key
 * that moved keeps the stop on its row, wherever the row went.
 */
export function reduceGrid(
  s: GridState,
  action: GridAction,
  rowKeys?: readonly string[],
): GridState {
  switch (action.type) {
    case "move": {
      const to = moved(s, action.move);
      const row = clampIndex(to.row, 0, lastRow(s));
      return place(s, to, rowKeys?.[row] ?? (row === s.focus.row ? s.key : null));
    }
    case "focus":
      return place(s, { row: action.row, col: action.col }, rowKeys?.[action.row] ?? null);
    case "data": {
      const next: GridState = { ...s, rows: action.rows, cols: action.cols };
      const keys = action.rowKeys;
      const found = s.key === null || keys === undefined ? -1 : keys.indexOf(s.key);
      const row = found >= 0 ? found : s.focus.row;
      const clamped = clampIndex(row, 0, lastRow(next));
      return place(next, { row, col: s.focus.col }, keys?.[clamped] ?? null);
    }
  }
}

/** The materialised rows: `[first, last]`, never more than `windowRows`. */
export function windowOf(s: GridState): { first: number; last: number } {
  const first = clampIndex(s.first, 0, lastRow(s));
  return { first, last: Math.min(first + s.windowRows - 1, lastRow(s)) };
}

/** Roving `tabindex`: the stop is 0, every other cell -1. */
export const tabIndexAt = (s: GridState, row: number, col: number): 0 | -1 =>
  s.focus.row === row && s.focus.col === col ? 0 : -1;
