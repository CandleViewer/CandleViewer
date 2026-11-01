/**
 * SCR-100's live window (E08-D07 D6, §4.6): which rows of the shown list the panel claims live within its budget (40
 * less the distinct symbols the other panes hold). A list within the budget is wholly live. A longer list takes the
 * focused row and a block of rows around the rows in view, re-centred on the view; a budget smaller than the rows in
 * view takes the focused row, then the rows in view from the top. The window moves only when a row in view (or the
 * focused row) falls outside it, `SETTLE_MS` after scrolling settles; the ticker hub decides when the move may start.
 * Pure: indices into the shown list, no layout, no clock.
 */

/** A move waits for scrolling (or typing in the filter) to settle this long (DJ). */
export const SETTLE_MS = 300;

/** The rows the scroll region shows, first and last inclusive, as indices into the shown list. */
export interface ViewRange {
  readonly first: number;
  readonly last: number;
}

const range = (from: number, to: number): number[] =>
  to < from ? [] : Array.from({ length: to - from + 1 }, (_, i) => from + i);

/** The row's distance from the view: 0 inside it. */
const distance = (row: number, view: ViewRange): number =>
  row < view.first ? view.first - row : row > view.last ? row - view.last : 0;

/** The rows of a list of `count` the window covers, ascending. */
export function liveWindow(
  count: number,
  budget: number,
  view: ViewRange | null,
  focused: number | null,
): readonly number[] {
  const size = Math.min(Math.max(0, Math.trunc(budget)), Math.max(0, count));
  if (size === 0) return [];
  if (count <= size) return range(0, count - 1);
  const focus = focused !== null && focused >= 0 && focused < count ? focused : null;
  const shown: ViewRange = view ?? { first: 0, last: Math.min(count, size) - 1 };
  const first = Math.max(0, Math.min(shown.first, count - 1));
  const last = Math.max(first, Math.min(shown.last, count - 1));
  const inView = range(first, last);
  const needed = new Set(inView);
  if (focus !== null) needed.add(focus);
  if (size < needed.size) {
    // The focused row, then the rows in view from the top, as many as the budget allows.
    const picked = focus === null ? [] : [focus];
    for (const row of inView) {
      if (picked.length >= size) break;
      if (row !== focus) picked.push(row);
    }
    return picked.sort((a, b) => a - b);
  }
  const centre = (first + last) / 2;
  const start = Math.min(Math.max(0, Math.round(centre - (size - 1) / 2)), count - size);
  const block = range(start, start + size - 1);
  if (focus === null || block.includes(focus)) return block;
  // The focused row replaces the block's row farthest from the view (the later one on a tie).
  let drop = -1;
  for (const row of block) {
    if (drop < 0 || distance(row, { first, last }) >= distance(drop, { first, last })) drop = row;
  }
  return [...block.filter((row) => row !== drop), focus].sort((a, b) => a - b);
}

/** Whether the window holds every row in view and the focused row: if not, the window moves. */
export function coversView(
  window: ReadonlySet<number>,
  view: ViewRange,
  focused: number | null,
): boolean {
  for (let row = view.first; row <= view.last; row += 1) if (!window.has(row)) return false;
  return focused === null || window.has(focused);
}
