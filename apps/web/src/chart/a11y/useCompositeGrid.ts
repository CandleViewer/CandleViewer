/**
 * The thin React host of `compositeGrid` (E47-S02, #1358): spreads `gridProps` on the `role="grid"` element,
 * `rowProps(row)` on each drawn row and `cellProps(row, col)` on each cell. Keys the model knows move the one Tab stop
 * and focus follows; every other key (Enter, letters, chords) is left to the host. Focus moves only on a user key, or
 * back to the stop when churn removed the focused row while focus was in the grid (`05` §3.4.3: never stolen).
 */
import { useReducer, useRef, useLayoutEffect, useState } from "react";
import type { FocusEvent, KeyboardEvent, RefObject } from "react";
import {
  createGridState,
  gridMoveOf,
  reduceGrid,
  tabIndexAt,
  windowOf,
  type GridAction,
  type GridAxis,
  type GridPos,
  type GridState,
} from "./compositeGrid";

export interface UseCompositeGridOptions {
  readonly rows: number;
  readonly cols: number;
  readonly page?: GridAxis;
  readonly homeEnd?: GridAxis;
  readonly pageRows?: number;
  /** Rows materialised around the stop; the surrogate never draws more (`a11y_surrogate_nodes`). */
  readonly windowRows?: number;
  /** Row identity (a ladder row's price): keep the array's identity stable between data changes. */
  readonly rowKeys?: readonly string[];
  readonly initial?: Partial<GridPos>;
}

export interface CompositeGrid {
  readonly state: GridState;
  readonly window: { readonly first: number; readonly last: number };
  readonly gridProps: {
    readonly ref: RefObject<HTMLDivElement>;
    readonly role: "grid";
    readonly "aria-rowcount": number;
    readonly "aria-colcount": number;
    readonly onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
    readonly onFocus: (event: FocusEvent<HTMLElement>) => void;
    readonly onBlur: (event: FocusEvent<HTMLElement>) => void;
  };
  readonly rowProps: (row: number) => { role: "row"; "aria-rowindex": number };
  readonly cellProps: (
    row: number,
    col: number,
  ) => {
    role: "gridcell";
    tabIndex: 0 | -1;
    "aria-colindex": number;
    "data-cg-row": number;
    "data-cg-col": number;
  };
}

export const DEFAULT_WINDOW_ROWS = 40;
export const DEFAULT_PAGE_ROWS = 10;

interface Step {
  readonly action: GridAction;
  readonly keys: readonly string[] | undefined;
}
const step = (s: GridState, { action, keys }: Step): GridState => reduceGrid(s, action, keys);

const cellIn = (root: HTMLElement | null, pos: GridPos): HTMLElement | null =>
  root?.querySelector<HTMLElement>(`[data-cg-row="${pos.row}"][data-cg-col="${pos.col}"]`) ?? null;

const placeOf = (target: EventTarget | null): GridPos | null => {
  const cell = target instanceof Element ? target.closest("[data-cg-row]") : null;
  if (cell === null) return null;
  return {
    row: Number(cell.getAttribute("data-cg-row")),
    col: Number(cell.getAttribute("data-cg-col")),
  };
};

export function useCompositeGrid(options: UseCompositeGridOptions): CompositeGrid {
  const { rows, cols, rowKeys } = options;
  const config = {
    rows,
    cols,
    page: options.page ?? "row",
    homeEnd: options.homeEnd ?? "row",
    pageRows: options.pageRows ?? DEFAULT_PAGE_ROWS,
    windowRows: options.windowRows ?? DEFAULT_WINDOW_ROWS,
  } as const;
  const [state, dispatch] = useReducer(step, undefined, () =>
    createGridState(config, options.initial, rowKeys),
  );
  // Churn is folded in during render (React's "adjust state on a prop change"), so no commit ever shows a stop on a
  // row that has gone, and the restore below sees the settled stop.
  const [seen, setSeen] = useState({ rows, cols, rowKeys });
  if (seen.rows !== rows || seen.cols !== cols || seen.rowKeys !== rowKeys) {
    setSeen({ rows, cols, rowKeys });
    dispatch({ action: { type: "data", rows, cols, rowKeys }, keys: rowKeys });
  }

  const ref = useRef<HTMLDivElement>(null);
  const wantFocus = useRef(false);
  /** The element focus is on while it is in the grid. */
  const held = useRef<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const restore =
      held.current !== null &&
      !held.current.isConnected &&
      (document.activeElement === null || document.activeElement === document.body);
    if (!wantFocus.current && !restore) return;
    wantFocus.current = false;
    cellIn(ref.current, state.focus)?.focus({ preventScroll: true });
  });

  const onKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    if (event.defaultPrevented || placeOf(event.target) === null) return;
    const move = gridMoveOf(event);
    if (move === null) return; // the host's key
    event.preventDefault();
    wantFocus.current = true;
    dispatch({ action: { type: "move", move }, keys: rowKeys });
  };

  const onFocus = (event: FocusEvent<HTMLElement>): void => {
    const at = placeOf(event.target);
    if (at === null) return;
    if (event.target instanceof HTMLElement) held.current = event.target;
    if (at.row !== state.focus.row || at.col !== state.focus.col)
      dispatch({ action: { type: "focus", ...at }, keys: rowKeys });
  };

  const onBlur = (event: FocusEvent<HTMLElement>): void => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) held.current = null;
  };

  return {
    state,
    window: windowOf(state),
    gridProps: {
      ref,
      role: "grid",
      "aria-rowcount": rows,
      "aria-colcount": cols,
      onKeyDown,
      onFocus,
      onBlur,
    },
    rowProps: (row) => ({ role: "row", "aria-rowindex": row + 1 }),
    cellProps: (row, col) => ({
      role: "gridcell",
      tabIndex: tabIndexAt(state, row, col),
      "aria-colindex": col + 1,
      "data-cg-row": row,
      "data-cg-col": col,
    }),
  };
}
