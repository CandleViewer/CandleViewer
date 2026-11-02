import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Checkbox } from "./Checkbox.js";
import { EmptyState } from "./EmptyState.js";
import { ErrorState } from "./ErrorState.js";
import { IconButton } from "./IconButton.js";
import { Menu, type MenuItem } from "./Menu.js";
import { Skeleton } from "./Skeleton.js";
import { Spinner } from "./Spinner.js";
import { NumericText, type NumericFormat } from "./Typography.js";
import { LEAVE_GRACE_MS } from "./Tooltip.js";
import { cx } from "./internal/cx.js";
import { useGatedAnnounce } from "./internal/disabledReason.js";
import { useLayerPortal } from "./internal/layers.js";
import { bodyParts, rowsInView } from "./internal/tableWindow.js";
import { useAnchoredPosition } from "./internal/useAnchoredPosition.js";

export type TableSortDirection = "ascending" | "descending";

/** The applied sort: one column and its direction. */
export interface TableSort {
  readonly columnId: string;
  readonly direction: TableSortDirection;
}

/** A status after a header's label: SCR-100's stale OI Δ column, "⚠" and "stale" (E08-D07 §4.2). */
export interface TableHeaderStatus {
  /** A registry glyph, decorative: the word carries the status. */
  readonly icon: IconName;
  /** The word, visually hidden after the label, so it joins the header's name ("OI Δ 24h % stale"). */
  readonly label: string;
  /** `stale` draws the glyph in `color.data-confidence.stale.indicator`; absent, the header's text colour. */
  readonly tone?: "stale";
}

interface TableColumnBase {
  /** Unique within the table: keys the cells and names the column in `sort` and `sortPending`. */
  readonly id: string;
  /** The header label, and the sort button's name. */
  readonly header: string;
  /** A sort button in the header (with `onSortChange`). */
  readonly sortable?: boolean;
  /**
   * The narrowest the column reads well, in `em` of the table's font size. The table stacks below the sum of
   * its columns' minimums, so the threshold tracks text scale and zoom. Default 8.
   */
  readonly minWidthEm?: number;
  /** The column's width, in `em` of the table's font size (a `<col>`), in the table layout; stacked, it is dropped. */
  readonly widthEm?: number;
  /**
   * The column's sort is gated (T2, E08-D07 §6.6; SCR-100's live sort past the budget, D5): the header keeps its
   * button, label and `aria-sort`, takes `aria-disabled`, the CMP-019 `lock` before the label and this reason as its
   * description (the table's `sortReasonId` note, or a node of its own). A press sorts nothing and re-shows it; a
   * held Enter's repeats say nothing.
   */
  readonly sortDisabledReason?: string;
  /** A glyph and a word after the label (E08-D07 §4.2: a stale column's "⚠", named "stale"). */
  readonly headerStatus?: TableHeaderStatus;
  /**
   * Words visually hidden after the label, in the header's name and in its echo with the label, on hover and focus: a
   * narrow column's unit ("uPnL" "(USDT)", E29-D02 §11.5's name and tooltip).
   */
  readonly headerHint?: string;
}

/** A text column: the cell truncates with an ellipsis and keeps its full text in the DOM. */
export interface TableTextColumn<T> extends TableColumnBase {
  readonly cell: (row: T) => ReactNode;
  readonly numeric?: undefined;
  readonly precision?: never;
  /** `end` aligns the header and the cells as numbers are (a column of preformatted figures, CMP-161's). */
  readonly align?: "start" | "end";
  /**
   * The cell holds controls (an inline control): the table becomes a grid. Its controls leave the Tab order; on the
   * focused cell `Enter` or `F2` moves focus to the first of them and `Esc` brings it back to the cell.
   */
  readonly interactive?: boolean;
}

/** A numeric column: the value renders through CMP-020 NumericText, end-aligned in mono, never truncated. */
export interface TableNumericColumn<T> extends TableColumnBase {
  readonly cell: (row: T) => number;
  readonly numeric: NumericFormat;
  /** Decimals; NumericText's default for the format when omitted. */
  readonly precision?: number;
  readonly interactive?: never;
  readonly align?: never;
}

export type TableColumn<T> = TableTextColumn<T> | TableNumericColumn<T>;

/** The error state: CandleViewer's own words and a Retry. */
export interface TableError {
  readonly message: string;
  readonly onRetry: () => void;
}

/** The host's window of a long list (virtualised rendering): `rows` start `offset` rows into a list of `total`. */
export interface TableRowWindow {
  /** The index, in the whole list, of the first drawn row. */
  readonly offset: number;
  /** The whole list's length. */
  readonly total: number;
}

/**
 * A treegrid row's place in its tree (E29-D04 §2.7, D04H A-6.2 and A-6.5; E29-D05 §5.1, §5.3 F-03), read from the
 * host's model, never from the DOM: a windowed set counts the rows it does not draw.
 */
export interface TableTreeRow {
  /** Its depth, outermost first, from 1 (`aria-level`). */
  readonly level: number;
  /** A row that holds others: whether they are shown (`aria-expanded`). Absent on a leaf. */
  readonly expanded?: boolean | undefined;
  /** Its place among its siblings, from 1 (`aria-posinset`). */
  readonly posinset: number;
  /** Its siblings' count, itself included (`aria-setsize`). */
  readonly setsize: number;
}

/** A row of the host's whole list, found by its key: its data and its absolute index, from 0 (`rowByKey`). */
export interface TableKeptRow<T> {
  readonly row: T;
  readonly index: number;
}

/** How a custom row's cell takes part in the grid (`TableRowContext.cellProps`). */
export interface TableCellOptions {
  /** The row's header: a `th scope="row"` (`rowheader`), as CMP-161's symbol. */
  readonly header?: boolean;
  /** Merges the cell with the next `span - 1` columns: a native `colspan`, one cell to the arrows. */
  readonly span?: number;
  /** A number: end-aligned, never wrapped. */
  readonly numeric?: boolean;
  /**
   * The cell's one control takes focus in its place, as the select box does (CMP-114's row checkbox): the cell takes
   * no `tabindex`, and the control spreads `grid.tabIndexOf(column)`. Its own keys (Space on a box) act natively.
   */
  readonly widget?: boolean;
  /**
   * The cell holds controls, as an `interactive` column's do (CMP-114's CMP-057): they leave the Tab order while
   * the grid roves; `Enter` or `F2` moves focus to the first of them and `Esc` brings it back to the cell.
   */
  readonly interactive?: boolean;
  /**
   * Words the table's one CMP-016 echo shows on hover and, in grid mode, on keyboard focus (`aria-hidden`: the cell
   * already carries them for assistive technology, E09-D09 2b), such as a stale row's "Last update 10:31:02 UTC".
   */
  readonly echo?: string | undefined;
  /**
   * The cell's whole text where the cell may cut it with an ellipsis (CMP-161's symbol): while the cell is cut, the
   * echo shows it on hover and, in grid mode, on keyboard focus (E08-D07 §4.1 pairs every cut with the echo). The
   * cell keeps its whole text in the DOM, so its name is never cut.
   */
  readonly cut?: string | undefined;
  /** The cell's description ids (`aria-describedby`). */
  readonly describedBy?: string | undefined;
  readonly className?: string | undefined;
}

/** Spread on a custom row's cell (`td`, or `th` for the row's header). */
export interface TableCellProps {
  readonly className: string;
  readonly role?: string | undefined;
  readonly scope?: "row" | undefined;
  readonly colSpan?: number | undefined;
  readonly tabIndex?: 0 | -1 | undefined;
  readonly "aria-describedby"?: string | undefined;
  readonly "data-cv-r"?: number | undefined;
  readonly "data-cv-c"?: number | undefined;
  readonly "data-cv-span"?: number | undefined;
  readonly "data-numeric"?: "" | undefined;
  readonly "data-heading"?: "" | undefined;
  readonly "data-cv-echo"?: string | undefined;
  readonly "data-cv-cut"?: string | undefined;
  readonly "data-cv-widget"?: "" | undefined;
  readonly "data-cv-interactive"?: "" | undefined;
  /** A pinned leading column's place among the pinned ones, from 0 (`stickyFirstColumn`). */
  readonly "data-pin-start"?: number | undefined;
  /** The pinned trailing column (`stickyLastColumn`). */
  readonly "data-pin-end"?: "" | undefined;
}

/** Spread on a custom row's `<tr>`. */
export interface TableRowProps {
  readonly className: string;
  readonly role?: string | undefined;
  readonly "aria-rowindex": number;
  /** With `treegrid`, the row's place in its tree (`treeRow`); none on a totals row. */
  readonly "aria-level"?: number | undefined;
  readonly "aria-expanded"?: boolean | undefined;
  readonly "aria-posinset"?: number | undefined;
  readonly "aria-setsize"?: number | undefined;
  /** A totals row's pin below the body (`--cv-table-after`, the totals rows after it). */
  readonly style?: CSSProperties | undefined;
}

/** CMP-049's row contract for a row the host draws (`renderRow`; CMP-161 WatchlistRow). */
export interface TableRowContext {
  /** The row's index in the whole list, from 0. */
  readonly index: number;
  /** For the `<tr>`: its absolute `aria-rowindex` and, stacked, its explicit role. */
  readonly rowProps: TableRowProps;
  /** For the cell of data column `column` (an index into `columns`): its grid place, role and roving `tabindex`. */
  readonly cellProps: (column: number, options?: TableCellOptions) => TableCellProps;
  /** Stacked, the visible header label a cell leads with (none for the first column), hidden from AT. */
  readonly label: (column: number) => ReactNode;
  readonly stacked: boolean;
  /**
   * A T2 key on the row (E08-D07 §6.6, E09-D09 §9.3): call it from the row's key handler after `preventDefault()`,
   * once per press (a held key's repeats are the row's to drop). Nothing changes; `reason` shows in the CMP-016 echo
   * on the focused cell and is said once, politely, through the gated announcement (`GatedAnnounceProvider`).
   */
  readonly refuse: (reason: string) => void;
  /** The roving `tabindex` of a `widget` cell's control (`cellProps(i, { widget: true })`). */
  readonly tabIndexOf: (column: number) => 0 | -1 | undefined;
}

export interface TableProps<T> {
  readonly columns: readonly TableColumn<T>[];
  /**
   * The rows, in display order: the consumer sorts. Without `rowWindow` every row is drawn (above 200 it warns in
   * development); with it, these are the drawn window.
   */
  readonly rows: readonly T[];
  /** A stable, unique key per row. */
  readonly rowKey: (row: T) => string;
  /** Names the table and its scroll region (D02F G12). */
  readonly caption: string;
  /** Visually hides the caption when a heading already names the table; it still names it. */
  readonly captionHidden?: boolean;
  /** The applied sort; its column takes `aria-sort`. */
  readonly sort?: TableSort | undefined;
  /** A header press asks for a sort: ascending first, then descending on the sorted column. */
  readonly onSortChange?: (sort: TableSort) => void;
  /** The column whose requested sort waits on rows: its button is busy and a press changes nothing. */
  readonly sortPending?: string | undefined;
  /** The header row stays; CMP-015 skeleton rows fill the body and the table is `aria-busy`. */
  readonly loading?: boolean;
  /** The caption's loading words. Default "Loading…". */
  readonly loadingText?: string;
  /** The header row stays; CMP-027 with Retry across every column, announced politely by the table's region. */
  readonly error?: TableError;
  /**
   * Shown across every column when there are no rows: a CMP-026 EmptyState (`no-data`, or `filtered-empty`
   * with Clear filters). Default: a `no-data` EmptyState "No rows to show".
   */
  readonly emptyState?: ReactNode;
  /** Emits `data-density` so `theme.css` re-points the row height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
  /**
   * Forces grid mode (the WAI-ARIA APG Grid pattern) on a static table. Grid mode is implied, without it, by any
   * interactive column: `onRowSelect`'s select column, `rowActions`' actions column, or an `interactive` column.
   */
  readonly grid?: boolean;
  /** The selected rows' keys (`rowKey`), with `onRowSelect`. */
  readonly selected?: ReadonlySet<string> | undefined;
  /** Renders the leading select column (a CMP-005 per row and a select-all) and asks for the next selection. */
  readonly onRowSelect?: ((selected: ReadonlySet<string>) => void) | undefined;
  /** The select column is denied (T2, RBAC): its checkboxes are disabled and carry this reason. */
  readonly selectDisabledReason?: string | undefined;
  /**
   * Renders the trailing actions column: an IconButton "Actions for {row}" opening a CMP-041 menu of these items;
   * `Shift+F10` or the Menu key on a focused row opens the same items as a context menu at the row, and on a row with
   * none opens nothing.
   */
  readonly rowActions?: ((row: T) => readonly MenuItem[]) | undefined;
  /**
   * The row's name in "Select {row}" and "Actions for {row}". Default: the first column's value when it is text or a
   * number, else the row's key.
   */
  readonly rowLabel?: ((row: T) => string) | undefined;
  /**
   * The host's window of a long list (grid mode; SCR-100 windows past 60 rows, E08-D07 D6): `rows` are the drawn
   * rows. Spacer rows hold the others' height, `aria-rowcount` counts the whole list and each row's `aria-rowindex`
   * is absolute. A key that moves focus past the window asks for its row through `onRowsInView`; focus lands once
   * the host draws it, and the one Tab stop stays on a drawn row meanwhile.
   */
  readonly rowWindow?: TableRowWindow | undefined;
  /**
   * The absolute rows the scroll region shows below the sticky header, first and last inclusive, once per change:
   * as it scrolls or resizes, and for the row a key moves focus to outside the window. The host draws a window that
   * holds them.
   */
  readonly onRowsInView?: ((first: number, last: number) => void) | undefined;
  /**
   * Draws each body row itself (CMP-161 WatchlistRow): the `<tr>` and its cells spread the row contract `grid` gives
   * (`rowProps`, `cellProps`), one cell per column. The table then draws no select or actions column: `rowActions`
   * opens as the context menu alone.
   */
  readonly renderRow?: ((row: T, grid: TableRowContext) => ReactNode) | undefined;
  /**
   * The host's polite region says the table's lines (sort, load and selection results, a row menu's re-shown reason)
   * and the table renders none: SCR-100 owns no live region (E08-D07 D17). A T2 sort header's or row key's reason is
   * the gated announcement's (`GatedAnnounceProvider`, #5135), said once, never here as well.
   */
  readonly announce?: ((text: string) => void) | undefined;
  /** The host's note every T2 sort header points at (E09-D09 §2.2: one notice, many pointers). */
  readonly sortReasonId?: string | undefined;
  /**
   * What a grid becomes when it stacks: `table` (the default), a table whose controls are each a Tab stop; `grid`,
   * one card per row that keeps the grid's roles, its one Tab stop and its keys (SCR-100 at 200 %, E08-D07 D30).
   */
  readonly reflow?: "table" | "grid";
  /**
   * The WAI-ARIA APG Treegrid pattern (E29-D04 §2.7, D04H A-6.2 to A-6.5), which implies grid mode: rows nest by
   * `treeRow`'s `level`, outermost first; `→` on a collapsed row's first cell expands it and on an expanded one
   * moves to its first child, `←` collapses an expanded row and otherwise moves from a row's first cell to its
   * parent (`onExpandedChange` asks; the host shows or hides the children). A treegrid does not stack, the reading
   * taken pending OQ-19 (E29-D03 C-19, E29-D05 C-13: `16` §3 rule 4's stacked reflow, at risk here): its region
   * scrolls sideways under its pinned columns instead (E29-D02 §11.5, board 19).
   */
  readonly treegrid?: boolean;
  /** Each body row's place in its tree, from the host's model (with `treegrid`; F-03: never counted in the DOM). */
  readonly treeRow?: ((row: T) => TableTreeRow) | undefined;
  /** `→` or `←` on a row that holds others asks to show or hide them; the host passes the next `rows`. */
  readonly onExpandedChange?: ((row: T, expanded: boolean) => void) | undefined;
  /**
   * The host's custom rows carry their own `aria-selected` (CMP-114 owns its selection, which reaches rows outside
   * the window): the grid is `aria-multiselectable`.
   */
  readonly multiselectable?: boolean;
  /**
   * Finds any row of the host's whole list by key (E29-D05 §5.3 G-01): with `rowWindow`, the remembered cell's row
   * stays mounted when it leaves the window, at its absolute `aria-rowindex`, the one drawn row outside it, so focus
   * and the one Tab stop stay on it (a re-sort that moves it away included). `undefined` when the row has gone.
   */
  readonly rowByKey?: ((key: string) => TableKeptRow<T> | undefined) | undefined;
  /**
   * Pins leading columns while the region scrolls sideways (E29-D04 §2.7): `true` the first, a number that many, at
   * most four (SCR-063's select, Env, Account and Symbol), the select column counted. A focused cell scrolls clear
   * of them (`scroll-margin-inline-start`, E29-D05 §6.2 F-01). A merged cell is pinned only within them.
   */
  readonly stickyFirstColumn?: boolean | number;
  /** Pins the last column (an actions column) to the region's end; focused cells scroll clear of it too. */
  readonly stickyLastColumn?: boolean;
  /**
   * Totals rows (D04H A-6.4, A-6.5): a trailing rowgroup after every body row, pinned to the region's bottom, each
   * led by its rowheader ("LIVE total"), drawn by `renderRow` or else by the columns. They take the rows after the
   * body's in `aria-rowindex` and `aria-rowcount`; `↓` reaches them from the last row, and focused body cells scroll
   * clear of them. Never selectable, and no row menu.
   */
  readonly totalRows?: readonly T[] | undefined;
}

/** The pinned leading columns a table supports (SCR-063's select, Env, Account and Symbol). */
const MAX_PINNED = 4;

/** The v0 bound of a table drawn whole (#266); a longer list takes the host's window (`rowWindow`). */
const MAX_ROWS = 200;
const SKELETON_ROWS = 5;
/** A column's `minWidthEm` when it gives none: room for a short label or an 8-digit number. */
const DEFAULT_MIN_WIDTH_EM = 8;
/** The select and the actions columns' share of the reflow threshold. */
const CONTROL_COLUMN_EM = 3;
/** Page Up / Page Down's step when nothing is laid out to measure a page by. */
const FALLBACK_PAGE_ROWS = 10;
/** What a control inside an `interactive` cell looks like: these leave the Tab order while the grid roves. */
const TABBABLE = "a[href], button, input, select, textarea, [tabindex]";

/** The load result's words (the table's polite line): a host's own result line says a count the same way. */
export const rowsWord = (n: number): string =>
  n === 0 ? "No rows" : n === 1 ? "1 row" : `${n} rows`;

function NumericCell<T>({ column, row }: { column: TableNumericColumn<T>; row: T }): JSX.Element {
  const value = column.cell(row);
  const precision = column.precision === undefined ? {} : { precision: column.precision };
  return column.numeric === "pnl" ? (
    <NumericText value={value} format="pnl" signDisplay="always" {...precision} />
  ) : (
    <NumericText value={value} format={column.numeric} {...precision} />
  );
}

/** The sort glyph: the direction's arrow, a neutral one when sortable and unsorted, a spinner while pending. */
function SortGlyph({
  direction,
  pending,
}: {
  direction: TableSortDirection | undefined;
  pending: boolean;
}): JSX.Element {
  if (pending) return <Spinner size="sm" />;
  return (
    <span className="cv-table__sort-glyph">
      <Icon
        name={
          direction === "ascending"
            ? "arrow-up"
            : direction === "descending"
              ? "arrow-down"
              : "arrow-up-down"
        }
      />
    </span>
  );
}

/**
 * Whether the region scrolls, so it takes a Tab stop (WCAG 2.1.1). Measured when `content` (the state and the
 * row and column counts) changes, and as the region or its table resizes. With ResizeObserver the first measure
 * is its initial callback, after the browser's own layout, so a mount forces no synchronous reflow (the frame
 * budget); without it, the effect measures once.
 */
function useScrolls(region: RefObject<HTMLDivElement | null>, content: string): boolean {
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const node = region.current;
    if (node === null) return undefined;
    const measure = (): void => {
      setScrolls(node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth);
    };
    if (typeof ResizeObserver === "undefined") {
      measure();
      return undefined;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    for (const child of node.children) observer.observe(child);
    return () => observer.disconnect();
  }, [region, content]);
  return scrolls;
}

/**
 * The stacked reflow (`16` §3 rule 4): true while the shell's content width is narrower than `thresholdEm`
 * times its computed font size. A CSS container query cannot sum dynamic column minimums, so a ResizeObserver
 * watches the shell (its width) and a 1 em probe inside it (a font-size change at a fixed width: root zoom or
 * text scale). A width of 0 (the shell is not laid out) keeps the last layout. Without ResizeObserver the
 * table stays a table.
 */
function useStacked(
  shell: RefObject<HTMLDivElement | null>,
  probe: RefObject<HTMLSpanElement | null>,
  thresholdEm: number,
): boolean {
  const [stacked, setStacked] = useState(false);
  useEffect(() => {
    const node = shell.current;
    if (node === null || typeof ResizeObserver === "undefined") return undefined;
    let width = 0;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) if (entry.target === node) width = entry.contentRect.width;
      if (width <= 0) return;
      const fontPx = parseFloat(getComputedStyle(node).fontSize);
      if (!Number.isFinite(fontPx) || fontPx <= 0) return;
      setStacked(width < thresholdEm * fontPx);
    });
    observer.observe(node);
    if (probe.current !== null) observer.observe(probe.current);
    return () => observer.disconnect();
  }, [shell, probe, thresholdEm]);
  return stacked;
}

interface ResultInputs<T> {
  readonly columns: readonly TableColumn<T>[];
  readonly rowCount: number;
  readonly sort: TableSort | undefined;
  readonly sortPending: string | undefined;
  readonly loading: boolean;
  readonly error: TableError | undefined;
  /**
   * The count of selected keys among the rows, or `undefined` without a select column or rows (loading, empty,
   * error): an undefined count says nothing and keeps the last one, so a reload with the same selection is silent.
   */
  readonly selectedCount: number | undefined;
}

interface ResultLine {
  /** The polite line. */
  readonly line: string;
  /** Call as a Retry starts: clears the line so the next result, even an identical one, is said again. */
  readonly retryStarted: () => void;
  /** Re-keys the line on each call, so the same text (a T2 reason pressed twice) is said again. */
  readonly nonce: number;
  /** Says a row menu's re-shown T2 reason (CMP-041 `announceReason`), once per press. */
  readonly say: (text: string) => void;
}

/**
 * The one polite line for sort, selection and load results (D02F CMP-049): a settled sort, a changed selection
 * count ("2 selected"), the end of a load (the row count) and an error (its message, G17). Never the first
 * render's state, except an error, which is spoken once after mount. Each result is spoken once. The line clears as a load, a pending sort or a Retry starts,
 * so a result identical to the last one (the same row count after a reload, the same failure after a Retry)
 * changes the region and is said again.
 */
function useResultLine<T>({
  columns,
  rowCount,
  sort,
  sortPending,
  loading,
  error,
  selectedCount,
}: ResultInputs<T>): ResultLine {
  const settled = sort !== undefined && sortPending === undefined ? sort : undefined;
  const sortKey = settled === undefined ? undefined : `${settled.columnId}:${settled.direction}`;
  // The derived line (its header label), not the columns or sort objects: an inline `columns` or `sort`
  // must not re-run the effect.
  const sortLine =
    settled === undefined
      ? undefined
      : `Sorted by ${columns.find((c) => c.id === settled.columnId)?.header ?? settled.columnId}, ${settled.direction}`;
  const busy = loading || sortPending !== undefined;
  const prev = useRef<{
    sortKey: string | undefined;
    loading: boolean;
    busy: boolean;
    error: TableError | undefined;
  }>({ sortKey, loading, busy, error: undefined });
  // The error a Retry was pressed on; the next error that is not this object is a fresh result.
  const retriedFrom = useRef<TableError | undefined>(undefined);
  const [line, setLine] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = { sortKey, loading, busy, error };
    if (busy && !before.busy) setLine("");
    if (loading) return;
    if (error !== undefined) {
      const retried = retriedFrom.current !== undefined && error !== retriedFrom.current;
      if (error.message !== before.error?.message || before.loading || retried) {
        retriedFrom.current = undefined;
        setLine(error.message);
      }
      return;
    }
    retriedFrom.current = undefined;
    if (before.loading) {
      setLine(rowsWord(rowCount));
      return;
    }
    if (sortLine !== undefined && sortKey !== before.sortKey) setLine(sortLine);
  }, [sortKey, sortLine, busy, loading, error, rowCount]);
  // A selection change is said once per new count (never the first render's count).
  const lastCount = useRef(selectedCount);
  useEffect(() => {
    if (selectedCount === undefined || selectedCount === lastCount.current) return;
    const first = lastCount.current === undefined;
    lastCount.current = selectedCount;
    if (!first) setLine(`${selectedCount} selected`);
  }, [selectedCount]);
  const [nonce, setNonce] = useState(0);
  const retryStarted = (): void => {
    retriedFrom.current = error;
    setLine("");
  };
  const say = (text: string): void => {
    setLine(text);
    setNonce((n) => n + 1);
  };
  return { line, retryStarted, nonce, say };
}

/** One column of the grid: the select column, a data column, or the actions column. */
type GridColumn<T> =
  | { readonly kind: "select" }
  | { readonly kind: "data"; readonly column: TableColumn<T>; readonly index: number }
  | { readonly kind: "actions" };

/** A cell's place: `r` 0 is the header row, 1… the body rows; `c` indexes the grid columns. */
interface CellAt {
  readonly r: number;
  readonly c: number;
}

/** The remembered cell: its last place and, on a drawn body row, that row's key. */
interface Remembered extends CellAt {
  readonly key?: string | undefined;
}

/** What a cell holds: a built-in control focused in its place, plain content, or a consumer's controls. */
type CellKind = "widget" | "cell" | "interactive";

/** The grid cell an event happened in (its own node or inside it), or null outside this table's cells. */
const cellOf = (table: HTMLElement | null, target: EventTarget | null): HTMLElement | null => {
  if (table === null || !(target instanceof Element)) return null;
  const cell = target.closest<HTMLElement>("[data-cv-c]");
  return cell !== null && table.contains(cell) ? cell : null;
};

/**
 * Table mode's cells carry no grid place: the header or body cell of this table an event happened in, or null. The
 * one echo reads it (a cut header label, a cell's `cut` or `echo` words), as `cellOf` serves grid mode.
 */
const tableCellOf = (table: HTMLElement | null, target: EventTarget | null): HTMLElement | null => {
  if (table === null || !(target instanceof Element)) return null;
  const cell = target.closest<HTMLElement>("th, td");
  return cell !== null && table.contains(cell) ? cell : null;
};

const placeOf = (cell: HTMLElement): CellAt => ({
  r: Number(cell.dataset["cvR"]),
  c: Number(cell.dataset["cvC"]),
});

/** The columns a cell covers: 1, or a merged cell's span. */
const spanOf = (cell: HTMLElement): number => Math.max(1, Number(cell.dataset["cvSpan"] ?? 1) || 1);

/** The drawn cell of row `r` that covers column `c` (a merged cell covers its span), or null. */
const cellCovering = (table: HTMLElement | null, r: number, c: number): HTMLElement | null => {
  if (table === null) return null;
  for (const cell of table.querySelectorAll<HTMLElement>(`[data-cv-r="${r}"]`)) {
    const start = Number(cell.dataset["cvC"]);
    if (c >= start && c < start + spanOf(cell)) return cell;
  }
  return null;
};

/** Keyboard focus shows a cell's echo at once; an engine without `:focus-visible` counts every focus. */
const focusVisible = (element: Element): boolean => {
  try {
    return element.matches(":focus-visible");
  } catch {
    return true;
  }
};

/** One step of layout's own precision (a `LayoutUnit`, 1/64 px): a difference of one step is rounding, not overflow. */
const LAYOUT_STEP = 1 / 64;

/** A computed length in px: "8px" is 8, and the empty string of an unstyled node (jsdom) is 0. */
const pixels = (length: string): number => Number.parseFloat(length) || 0;

/**
 * How wide `node`'s line is, to the fraction, which no whole-pixel property reads: the union of the boxes and text runs
 * of its in-flow content. An absolutely positioned descendant, a visually hidden note, takes no room in the line, so it
 * and what it holds are skipped. `undefined` where the engine has no geometry for a `Range` (jsdom).
 */
function lineWidth(node: HTMLElement): number | undefined {
  const range = node.ownerDocument.createRange();
  if (typeof range.getClientRects !== "function") return undefined;
  let start = Infinity;
  let end = -Infinity;
  const take = (rects: Iterable<DOMRect>): void => {
    for (const rect of rects) {
      start = Math.min(start, rect.left);
      end = Math.max(end, rect.right);
    }
  };
  const walker = node.ownerDocument.createTreeWalker(
    node,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    (child) =>
      child instanceof Element && ["absolute", "fixed"].includes(getComputedStyle(child).position)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  );
  for (let child = walker.nextNode(); child !== null; child = walker.nextNode()) {
    if (child instanceof Element) {
      take(child.getClientRects());
    } else {
      range.selectNodeContents(child);
      take(range.getClientRects());
    }
  }
  return end - start;
}

/** `node`'s content width, to the fraction: its border box less its padding and borders. */
function contentWidth(node: HTMLElement): number {
  const style = getComputedStyle(node);
  return (
    node.getBoundingClientRect().width -
    pixels(style.paddingLeft) -
    pixels(style.paddingRight) -
    pixels(style.borderLeftWidth) -
    pixels(style.borderRightWidth)
  );
}

/**
 * Whether `node` draws an ellipsis. `scrollWidth` and `clientWidth` are whole pixels: they read a cut of a pixel or
 * more, but a text 0.4 px wider than its box reads as none while the ellipsis is still drawn (E08-D07 §4.1 pairs every
 * cut with the echo). So the line is also measured to the fraction against the box's content width, within one
 * layout step.
 */
const isCut = (node: HTMLElement): boolean => {
  if (node.scrollWidth > node.clientWidth) return true;
  const line = lineWidth(node);
  return line !== undefined && line - contentWidth(node) > LAYOUT_STEP;
};

/**
 * A cut text's whole words in `cell` (E08-D07 §4.1 pairs every cut with the echo): the cell's own `cut` text or its
 * header label's, while that box is narrower than its text, to the fraction of a pixel (`isCut`). Read on focus and
 * hover only, never per render.
 */
const cutWords = (cell: HTMLElement): string | undefined => {
  const node = cell.hasAttribute("data-cv-cut")
    ? cell
    : cell.querySelector<HTMLElement>("[data-cv-cut]");
  const words = node?.dataset["cvCut"]?.trim();
  if (node == null || words === undefined || words === "") return undefined;
  return isCut(node) ? words : undefined;
};

/** What a cell's echo shows on focus and hover: its own words, else a cut text's whole words. */
const echoWords = (cell: HTMLElement): string | undefined => {
  const own = cell.dataset["cvEcho"];
  return own !== undefined && own !== "" ? own : cutWords(cell);
};

/** Where focus goes for a cell: its built-in control (checkbox, sort or actions button), else the cell. */
const focusTargetOf = (cell: HTMLElement): HTMLElement =>
  cell.hasAttribute("data-cv-widget")
    ? (cell.querySelector<HTMLElement>("input, button") ?? cell)
    : cell;

/** The default row name: the first column's value when it is text or a number, else the row's key. */
function defaultRowLabel<T>(columns: readonly TableColumn<T>[], row: T, key: string): string {
  const first = columns[0];
  if (first === undefined) return key;
  const value: unknown = first.cell(row);
  return typeof value === "string" || typeof value === "number" ? String(value) : key;
}

/** A column's T2 sort reason, trimmed; none when blank (a blank reason would show nothing and read nothing). */
const reasonOf = (column: TableColumnBase): string | undefined => {
  const reason = column.sortDisabledReason?.trim();
  return reason === undefined || reason === "" ? undefined : reason;
};

/**
 * A held Enter repeats its keydown, and each repeat clicks a native button: a T2 sort header swallows the repeats, so
 * its reason is said once per press (E09-D09 §9.3), never once per repeat.
 */
const swallowHeldEnter = (event: KeyboardEvent<HTMLElement>): void => {
  if (event.key === "Enter" && event.repeat) event.preventDefault();
};

/** Numbers, and text columns of preformatted figures, end-align under an end-aligned header. */
const endAligned = <T,>(column: TableColumn<T>): boolean =>
  column.numeric !== undefined || column.align === "end";

/**
 * One page of rows for Page Up / Page Down: the rows that fit the visible part of the scroll region (or of the
 * window, when the region grows with the page), less the sticky header; a fixed step when nothing is laid out.
 */
function pageRows(region: HTMLElement | null, cell: HTMLElement): number {
  const rowHeight = cell.closest("tr")?.getBoundingClientRect().height ?? 0;
  const view = Math.min(region?.clientHeight ?? 0, window.innerHeight);
  if (rowHeight <= 0 || view <= 0) return FALLBACK_PAGE_ROWS;
  return Math.max(1, Math.floor(view / rowHeight) - 1);
}

/**
 * Takes an `interactive` cell's controls out of the Tab order while the grid roves (one Tab stop), and gives them
 * back their own `tabindex` when it stops (the stacked layout). Runs after every render: a control may mount late.
 */
function useTamedControls(table: RefObject<HTMLTableElement | null>, roving: boolean): void {
  useEffect(() => {
    const node = table.current;
    if (node === null) return;
    for (const cell of node.querySelectorAll<HTMLElement>("[data-cv-interactive]")) {
      for (const control of cell.querySelectorAll<HTMLElement>(TABBABLE)) {
        const tamed = control.getAttribute("data-cv-tamed");
        if (roving && tamed === null) {
          control.setAttribute("data-cv-tamed", control.getAttribute("tabindex") ?? "");
          control.tabIndex = -1;
        } else if (!roving && tamed !== null) {
          control.removeAttribute("data-cv-tamed");
          if (tamed === "") control.removeAttribute("tabindex");
          else control.setAttribute("tabindex", tamed);
        }
      }
    }
  });
}

interface RowsInViewHandle {
  /** Measures the region and reports a changed view. */
  readonly measure: () => void;
  /** Asks the host for absolute row `index`, outside the window, and forgets the last view reported. */
  readonly want: (index: number) => void;
}

/** The custom properties `usePinOffsets` writes on the shell; the stylesheet reads them (`table.css`). */
const PIN_PROPERTIES = [
  ...Array.from({ length: MAX_PINNED - 1 }, (_, i) => `--cv-table-pin-${String(i + 1)}`),
  "--cv-table-pin-start",
  "--cv-table-pin-end",
];

/**
 * The pinned columns' offsets (`stickyFirstColumn`, `stickyLastColumn`; E29-D05 §6.2 F-01), measured from the header
 * row's cells, which carry their columns' widths: `--cv-table-pin-<n>` is where the n-th pinned column starts (the
 * widths before it), `--cv-table-pin-start` the pinned leading columns' width and `--cv-table-pin-end` the pinned last
 * column's, set on the shell from a ResizeObserver's callbacks, after the browser's own layout: a mount forces no
 * synchronous reflow and a resize re-renders nothing. One row is measured, never one per body row. Without
 * ResizeObserver nothing is measured, and the first pinned column still sticks at 0.
 */
function usePinOffsets(
  shell: RefObject<HTMLDivElement | null>,
  table: RefObject<HTMLTableElement | null>,
  pinStart: number,
  pinEnd: boolean,
  layout: string,
): void {
  useEffect(() => {
    const host = shell.current;
    const header = table.current?.querySelector("thead tr");
    if (host == null || header == null || (pinStart === 0 && !pinEnd)) return undefined;
    if (typeof ResizeObserver === "undefined") return undefined;
    const cells = [...header.children];
    const widthOf = (cell: Element | undefined): number => cell?.getBoundingClientRect().width ?? 0;
    const measure = (): void => {
      let start = 0;
      for (let c = 0; c < pinStart; c += 1) {
        if (c > 0) host.style.setProperty(`--cv-table-pin-${String(c)}`, `${String(start)}px`);
        start += widthOf(cells[c]);
      }
      host.style.setProperty("--cv-table-pin-start", `${String(start)}px`);
      const end = pinEnd ? widthOf(cells[cells.length - 1]) : 0;
      host.style.setProperty("--cv-table-pin-end", `${String(end)}px`);
    };
    const observer = new ResizeObserver(measure);
    for (const cell of cells) observer.observe(cell);
    return () => {
      observer.disconnect();
      for (const name of PIN_PROPERTIES) host.style.removeProperty(name);
    };
  }, [shell, table, pinStart, pinEnd, layout]);
}

/**
 * The rows the region shows, reported once per change: on scroll (the region's `onScroll`), as the region resizes
 * and after a mount. Measured from layout (`rowsInView`): the body's top, the sticky header's and one drawn row's
 * height. Nothing is reported while no row has a height.
 */
function useRowsInView(
  region: RefObject<HTMLDivElement | null>,
  tbody: RefObject<HTMLTableSectionElement | null>,
  total: number,
  onRowsInView: ((first: number, last: number) => void) | undefined,
): RowsInViewHandle {
  const report = useRef(onRowsInView);
  report.current = onRowsInView;
  const count = useRef(total);
  count.current = total;
  const said = useRef("");
  const measure = useCallback((): void => {
    const box = region.current;
    const body = tbody.current;
    if (report.current === undefined || box === null || body === null) return;
    const view = rowsInView({
      scrollTop: box.scrollTop,
      viewHeight: box.clientHeight,
      bodyTop: body.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop,
      headerHeight: box.querySelector("thead")?.getBoundingClientRect().height ?? 0,
      rowHeight: body.querySelector("tr[aria-rowindex]")?.getBoundingClientRect().height ?? 0,
      total: count.current,
    });
    if (view === undefined) return;
    const key = `${view.first}:${view.last}`;
    if (key === said.current) return;
    said.current = key;
    report.current(view.first, view.last);
  }, [region, tbody]);
  const watching = onRowsInView !== undefined;
  useEffect(() => {
    const box = region.current;
    if (!watching || box === null) return undefined;
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [region, watching, measure]);
  const want = useCallback((index: number): void => {
    said.current = "";
    report.current?.(index, index);
  }, []);
  return { measure, want };
}

/** The table's one echo: its words, the cell it sits on, and a count that re-mounts it on every show. */
interface EchoState {
  readonly text: string;
  readonly anchor: HTMLElement;
  readonly n: number;
}

/** The hover delay of a cell's echo, as CMP-016's; keyboard focus shows it at once. */
const ECHO_DELAY_MS = 300;

/** The pointer on a shown echo (it stays, WCAG 1.4.13 hoverable) and off it (CMP-016's leave grace starts). */
interface EchoHover {
  readonly onPointerEnter: () => void;
  readonly onPointerLeave: () => void;
}

/** One shown echo: positioned on its anchor cell by CMP-016's primitive while it is mounted. */
function EchoSurface({
  echo,
  hover,
}: {
  readonly echo: EchoState;
  readonly hover: EchoHover;
}): JSX.Element {
  const surface = useRef<HTMLDivElement>(null);
  const anchor = useRef<HTMLElement | null>(echo.anchor);
  useAnchoredPosition({ open: true, reference: anchor, floating: surface, side: "top" });
  return (
    <div
      ref={surface}
      role="tooltip"
      className="cv-tooltip cv-table__echo"
      data-cmp="CMP-016"
      data-mode="echo"
      aria-hidden="true"
      onPointerEnter={hover.onPointerEnter}
      onPointerLeave={hover.onPointerLeave}
    >
      {echo.text}
    </div>
  );
}

/**
 * The table's one CMP-016 echo (E09-D09 2b; E08-D07 §6.6): a cell's words on keyboard focus and hover, or a T2
 * reason on a refused press. `aria-hidden`: the cell's own text and description carry the words, so nothing is read
 * twice. One node per table, however many cells have words: no extra DOM per cell. A hover echo stays while the
 * pointer is on its cell or on the echo, and goes CMP-016's leave grace after it leaves both.
 */
function TableEcho({
  echo,
  hover,
}: {
  readonly echo: EchoState | null;
  readonly hover: EchoHover;
}): JSX.Element | null {
  const root = useLayerPortal();
  if (root === null) return null;
  return createPortal(
    echo === null ? (
      <div
        role="tooltip"
        className="cv-tooltip cv-table__echo"
        data-cmp="CMP-016"
        data-mode="echo"
        aria-hidden="true"
        hidden
      />
    ) : (
      <EchoSurface key={echo.n} echo={echo} hover={hover} />
    ),
    root,
  );
}

interface RowMenuProps {
  /** The row's items, asked for only while its menu is open (a closed menu renders an empty, hidden surface). */
  readonly items: () => readonly MenuItem[];
  readonly label: string;
  readonly tabIndex: 0 | -1 | undefined;
  readonly announceReason: (reason: string) => void;
  readonly onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

/** A row's actions: the CMP-002 "Actions for {row}" button opening the CMP-041 row menu. */
function RowMenu({ items, label, tabIndex, announceReason, onKeyDown }: RowMenuProps): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <Menu
      open={open}
      onOpenChange={setOpen}
      items={open ? items() : []}
      announceReason={announceReason}
      trigger={
        <IconButton
          icon="more-horizontal"
          variant="ghost"
          label={`Actions for ${label}`}
          tabIndex={tabIndex}
          // ↑ / ↓ move between rows here, before the menu button takes them as "open" (APG Menu Button).
          onKeyDown={(event) => {
            if (event.key === "ArrowUp" || event.key === "ArrowDown") onKeyDown(event);
          }}
        />
      }
    />
  );
}

/**
 * CMP-049 Table. Table mode (the default; the WAI-ARIA APG Table pattern: static cells, no control in a body row): a
 * native `<table>` named by its caption inside a scroll region that takes a Tab stop when it scrolls, a sticky header
 * whose sortable labels are buttons with `aria-sort`, zebra rows, and one polite region for sort, selection and load
 * results. States: loading (skeleton rows, `aria-busy`), empty and filtered-empty (CMP-026), error (CMP-027 with
 * Retry). The consumer sorts the rows; the table only asks. Grid mode (the APG Grid pattern), implied by any
 * interactive column (`onRowSelect`'s select column, `rowActions`' actions column, an `interactive` column) or forced
 * by `grid`: `role="grid"` with one Tab stop that remembers the last focused cell; the arrows move by cell (the
 * header row included), Home / End to the row's ends, Ctrl+Home / Ctrl+End to the grid's corners, Page Up / Page
 * Down by a page of rows; a cell's built-in control (the select box, a sort or actions button) takes focus in its
 * place; an `interactive` cell takes `Enter` or `F2` into its controls and `Esc` back; `Space` toggles the focused
 * row's selection; `Shift+F10` or the Menu key opens the row's actions as a context menu. A focused cell scrolls
 * below the sticky header (`scroll-margin-top`). Reflow: below the sum of the columns' `minWidthEm` (at its own font
 * size, so at 200 % zoom too) it stacks, one block per row: the first data cell is the heading line, the others
 * header–value pairs, with explicit table roles kept; a grid then degrades to a table whose controls are each a Tab
 * stop, in order (arrow navigation needs a layout of rows and columns), unless `reflow="grid"` keeps it a grid of
 * cards (E08-D07 D30). E08-D07's grid additions (§5, D16): a host's window of a long list (`rowWindow`, absolute
 * `aria-rowcount` / `aria-rowindex`, spacer rows, `onRowsInView`, keys that cross the window); custom rows over the
 * row contract (`renderRow`: CMP-161) with row headers and merged cells, one cell to the arrows; a T2 sort header
 * and a T2 key on a row, which change nothing and re-show the reason in the table's one CMP-016 echo, said once; a
 * cell's words in that echo on keyboard focus and hover (a hover echo stays while the pointer is on it), and a cut
 * header label's or `cut` text's whole words, in table mode too (on hover, and on a sort button's keyboard focus); a
 * held Enter on a T2 sort header says its reason once; focus kept through a commit: a reorder leaves it on the moved
 * row, and a removed row hands it to the next row, else the previous (E08-D07 §6.3); `announce` for a host that owns
 * the live region. E29-D04 §2.7's treegrid (D04H A-6.2 to A-6.5): `treegrid` with each row's `treeRow` (`aria-level`,
 * `aria-expanded`, `aria-posinset` and `aria-setsize` from the host's model), `→` / `←` on a row's first cell to
 * expand, collapse, or move to the first child or the parent; the remembered row kept mounted outside the window
 * (`rowByKey`, E29-D05 §5.3 G-01); pinned leading and last columns that focused cells scroll clear of (F-01); and a
 * trailing, pinned totals rowgroup (`totalRows`), each row led by its rowheader.
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  caption,
  captionHidden = false,
  sort,
  onSortChange,
  sortPending,
  loading = false,
  loadingText = "Loading…",
  error,
  emptyState,
  density,
  grid = false,
  selected,
  onRowSelect,
  selectDisabledReason,
  rowActions,
  rowLabel,
  rowWindow,
  onRowsInView,
  renderRow,
  announce,
  sortReasonId,
  reflow = "table",
  treegrid = false,
  treeRow,
  onExpandedChange,
  multiselectable = false,
  rowByKey,
  stickyFirstColumn = false,
  stickyLastColumn = false,
  totalRows,
}: TableProps<T>): JSX.Element {
  const captionId = useId();
  const reasonBase = useId();
  const announceGated = useGatedAnnounce();
  const shell = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const region = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const tbody = useRef<HTMLTableSectionElement>(null);
  // The whole list and the drawn window of it: without `rowWindow` the window is every row.
  const total = Math.max(0, rowWindow?.total ?? rows.length);
  const offset = Math.min(Math.max(0, rowWindow?.offset ?? 0), total);
  const drawnCount = Math.min(rows.length, total - offset);
  const state = loading
    ? "loading"
    : error !== undefined
      ? "error"
      : total === 0
        ? "empty"
        : "populated";
  const custom = renderRow !== undefined;
  // T2 sort headers (E08-D07 §6.6): each distinct reason; without the host's note each has a hidden node to point at.
  const gatedReasons =
    onSortChange === undefined
      ? []
      : [...new Set(columns.filter((c) => c.sortable === true).flatMap((c) => reasonOf(c) ?? []))];
  const sortReasonIdOf = (reason: string): string =>
    `${reasonBase}-sort-${gatedReasons.indexOf(reason)}`;
  // A custom row draws the data cells alone: no select column, and the row menu opens as the context menu only.
  const selectable = onRowSelect !== undefined && !custom;
  const gridColumns: readonly GridColumn<T>[] = [
    ...(selectable ? [{ kind: "select" } as const] : []),
    ...columns.map((column, index) => ({ kind: "data", column, index }) as const),
    ...(rowActions === undefined || custom ? [] : [{ kind: "actions" } as const]),
  ];
  const gridMode =
    grid ||
    treegrid ||
    selectable ||
    rowActions !== undefined ||
    columns.some((column) => column.interactive === true);
  const scrolls = useScrolls(region, `${state}:${rows.length}:${gridColumns.length}`);
  // A treegrid does not stack, the reading taken pending OQ-19 (E29-D05 C-13): a zero threshold keeps it a grid at
  // every width.
  const stacked = useStacked(
    shell,
    probe,
    treegrid
      ? 0
      : columns.reduce((sum, column) => sum + (column.minWidthEm ?? DEFAULT_MIN_WIDTH_EM), 0) +
          (gridColumns.length - columns.length) * CONTROL_COLUMN_EM,
  );
  /** Arrow navigation and one Tab stop: grid mode laid out as rows and columns, or stacked as cards (`reflow`). */
  const roving = gridMode && (!stacked || reflow === "grid");
  // Explicit roles: `grid` (or `treegrid`) / `gridcell` while roving; while stacked, the table roles, because
  // `display: block` strips native table semantics in some engines.
  const role = (
    name: "table" | "rowgroup" | "row" | "columnheader" | "rowheader" | "cell",
  ): { role?: string } =>
    roving && name === "table"
      ? { role: treegrid ? "treegrid" : "grid" }
      : roving && name === "cell"
        ? { role: "gridcell" }
        : stacked
          ? { role: name }
          : {};
  const selection = selected ?? new Set<string>();
  const keys = state === "populated" ? rows.map(rowKey) : [];
  const { line, retryStarted, nonce, say } = useResultLine({
    columns,
    rowCount: total,
    sort,
    sortPending,
    loading,
    error,
    // Only the keys among the rows: a stale key (a row gone since) is not counted.
    selectedCount:
      selectable && state === "populated"
        ? keys.filter((key) => selection.has(key)).length
        : undefined,
  });
  // With `announce` the host's region says each line, and the table renders none (E08-D07 D17).
  const announceRef = useRef(announce);
  announceRef.current = announce;
  useEffect(() => {
    if (line !== "") announceRef.current?.(line);
  }, [line, nonce]);
  useTamedControls(tableRef, roving);
  const view = useRowsInView(region, tbody, total, onRowsInView);

  // The remembered cell (the Tab stop), clamped to the grid as rows come and go; at first the first body cell.
  // Body rows are numbered in the whole list: `r` 1 is its first row, whether drawn or not. A drawn body row is
  // remembered by its key too, so a reorder carries the Tab stop with its row (E08-D07 §6.3: a re-rank keeps focus
  // on the same symbol); a row gone leaves its place, clamped: the next row, else the previous. Totals rows follow
  // the body (`totalRows`), always drawn.
  const [active, setActive] = useState<Remembered | undefined>(undefined);
  const bodyRows = state === "populated" ? total : 0;
  const footer = state === "populated" ? (totalRows ?? []) : [];
  const footerKeys = footer.map(rowKey);
  const lastR = bodyRows + footer.length;
  const firstDrawn = offset + 1;
  const lastDrawn = offset + drawnCount;
  const inWindow = (r: number): boolean => r >= firstDrawn && r <= lastDrawn;
  // G-01 (E29-D05 §5.3): the remembered row, outside the window, stays drawn through the host's lookup.
  const remembered = active?.key;
  const kept =
    rowByKey === undefined ||
    remembered === undefined ||
    keys.includes(remembered) ||
    footerKeys.includes(remembered)
      ? undefined
      : rowByKey(remembered);
  const keptR =
    kept !== undefined && kept.index >= 0 && kept.index < bodyRows && !inWindow(kept.index + 1)
      ? kept.index + 1
      : undefined;
  const isFooter = (r: number): boolean => r > bodyRows && r <= lastR;
  const drawn = (r: number): boolean => r === 0 || inWindow(r) || r === keptR || isFooter(r);
  const lastC = gridColumns.length - 1;
  const keyAt = (r: number): string | undefined =>
    inWindow(r)
      ? keys[r - firstDrawn]
      : r === keptR
        ? remembered
        : isFooter(r)
          ? footerKeys[r - bodyRows - 1]
          : undefined;
  /** The body row drawn at `r` (in the window, or the kept row); never a totals row. */
  const bodyRowAt = (r: number): T | undefined =>
    inWindow(r) ? rows[r - firstDrawn] : r === keptR ? kept?.row : undefined;
  const moved = remembered === undefined ? -1 : keys.indexOf(remembered);
  const movedFooter = remembered === undefined ? -1 : footerKeys.indexOf(remembered);
  const wanted: CellAt =
    active === undefined
      ? { r: bodyRows > 0 ? firstDrawn : 0, c: 0 }
      : moved >= 0 && moved < drawnCount
        ? { r: firstDrawn + moved, c: active.c }
        : keptR !== undefined
          ? { r: keptR, c: active.c }
          : movedFooter >= 0
            ? { r: bodyRows + 1 + movedFooter, c: active.c }
            : active;
  /** Remembers the cell at `place`, with its row's key while that row is drawn. */
  const remember = (place: CellAt): void => {
    const key = keyAt(place.r);
    if (active?.r === place.r && active.c === place.c && active.key === key) return;
    setActive({ r: place.r, c: place.c, key });
  };
  const stop: CellAt = {
    r: Math.min(Math.max(wanted.r, 0), lastR),
    c: Math.min(Math.max(wanted.c, 0), lastC),
  };
  // The Tab stop is always drawn: a remembered row outside the window lends it to the nearest drawn row.
  const tabStop: CellAt = drawn(stop.r)
    ? stop
    : drawnCount > 0
      ? { r: Math.min(Math.max(stop.r, firstDrawn), lastDrawn), c: stop.c }
      : { r: 0, c: stop.c };
  // The context menu's row: the remembered body row (the header row keeps the last; the keys open it from the body).
  // A totals row has none.
  const menuR = inWindow(stop.r) || stop.r === keptR || isFooter(stop.r) ? stop.r : firstDrawn;
  const activeRow = state === "populated" && drawnCount > 0 ? bodyRowAt(menuR) : undefined;
  // Pinned columns (`stickyFirstColumn`, `stickyLastColumn`): none while stacked, whose cells are blocks.
  const pinStart = stacked
    ? 0
    : Math.min(
        MAX_PINNED,
        gridColumns.length,
        stickyFirstColumn === true ? 1 : Math.max(0, Math.trunc(Number(stickyFirstColumn) || 0)),
      );
  const pinEnd = !stacked && stickyLastColumn && gridColumns.length > pinStart;
  /** A cell's pin: a leading cell pinned only within the pinned columns, the end only as the last column alone. */
  const pinOf = (c: number, span = 1): { "data-pin-start"?: number; "data-pin-end"?: "" } => ({
    ...(c + span <= pinStart ? { "data-pin-start": c } : {}),
    ...(pinEnd && c === lastC && span === 1 ? { "data-pin-end": "" as const } : {}),
  });
  usePinOffsets(shell, tableRef, pinStart, pinEnd, `${columns.map((c) => c.id).join()}:${lastC}`);
  // The context menu is controlled so its items are asked for only while it is open, for the row the render holds
  // (a press remembers its cell before its `contextmenu`). A row with no actions (a group header before its own menu
  // mounts) shows nothing, never an empty menu, and its request is dropped at once, so it never opens later on another.
  const [contextOpen, setContextOpen] = useState(false);
  const contextItems =
    contextOpen && activeRow !== undefined ? (rowActions?.(activeRow) ?? []) : [];
  const contextShown = contextItems.length > 0;
  useLayoutEffect(() => {
    if (contextOpen && !contextShown) setContextOpen(false);
  }, [contextOpen, contextShown]);
  // A cell a key moves focus to outside the window: focused once the host draws it.
  const pending = useRef<CellAt | null>(null);
  useLayoutEffect(() => {
    const want = pending.current;
    if (want === null || !drawn(want.r)) return;
    pending.current = null;
    const target = cellCovering(tableRef.current, want.r, want.c);
    if (target !== null) focusTargetOf(target).focus({ preventScroll: true });
  });
  // A windowed list's spacers are counted in its drawn rows' measured height (`size.row.height` until laid out),
  // measured again as the window, the density or the layout changes.
  const [rowPx, setRowPx] = useState(0);
  const windowed = rowWindow !== undefined;
  useLayoutEffect(() => {
    if (!windowed) return;
    const height =
      tbody.current?.querySelector("tr[aria-rowindex]")?.getBoundingClientRect().height ?? 0;
    if (height > 0 && Math.abs(height - rowPx) > 0.5) setRowPx(height);
  }, [windowed, rowPx, offset, drawnCount, stacked, density]);

  // The element that holds focus in the grid, from focus landing there until focus leaves the table.
  const held = useRef<HTMLElement | null>(null);
  const lastTotal = useRef(total);
  // After each commit (E08-D07 §6.3): a reorder keeps focus on the moved row (React gives a moved node its focus
  // back) and the Tab stop follows its key; a removal (`Del`) unmounts the focused cell, so focus goes to the
  // clamped Tab-stop cell: the next row, else the previous. A windowed list also unmounts a row scrolled out of its
  // window: only a list that shrank restores. Focus elsewhere on purpose is never taken back.
  useLayoutEffect(() => {
    const was = lastTotal.current;
    lastTotal.current = total;
    const element = held.current;
    const table = tableRef.current;
    if (element === null || table === null || element.isConnected) return;
    held.current = null;
    const now = document.activeElement;
    if (!roving || (now !== null && now !== document.body) || (windowed && total >= was)) return;
    const target = cellCovering(table, tabStop.r, tabStop.c);
    if (target !== null) focusTargetOf(target).focus({ preventScroll: true });
  });

  // The one echo (CMP-016): a cell's words on keyboard focus and hover, a T2 reason on a refused press.
  const [echo, setEcho] = useState<EchoState | null>(null);
  const echoRef = useRef<EchoState | null>(null);
  echoRef.current = echo;
  const echoCount = useRef(0);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const showEcho = (anchor: HTMLElement, text: string): void => {
    clearTimeout(leaveTimer.current);
    echoCount.current += 1;
    setEcho({ text, anchor, n: echoCount.current });
  };
  const hideEcho = (): void => {
    clearTimeout(leaveTimer.current);
    setEcho((shown) => (shown === null ? shown : null));
  };
  /**
   * The pointer left a hover echo's cell, or the echo: it goes after CMP-016's leave grace unless the pointer reaches
   * the echo or its cell first (WCAG 1.4.13, Tooltip's own rule). Keyboard focus on its cell keeps it.
   */
  const leaveEcho = (): void => {
    const shown = echoRef.current;
    if (shown === null || shown.anchor.contains(document.activeElement)) return;
    clearTimeout(leaveTimer.current);
    leaveTimer.current = setTimeout(hideEcho, LEAVE_GRACE_MS);
  };
  const echoHover: EchoHover = {
    onPointerEnter: () => clearTimeout(leaveTimer.current),
    onPointerLeave: leaveEcho,
  };
  useEffect(
    () => () => {
      clearTimeout(hoverTimer.current);
      clearTimeout(leaveTimer.current);
    },
    [],
  );
  // `Esc` hides a shown echo and stops there, focus kept, as CMP-016's own does; the next `Esc` is the host's.
  useLayoutEffect(() => {
    if (echo === null) return undefined;
    const onKeyDown = (event: globalThis.KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setEcho(null);
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [echo]);
  /**
   * A T2 press (E09-D09 §9.3): nothing changes; the reason shows in the echo at the point of action and is said once,
   * through the gated announcement the ui atoms use (#5135), never the table's own line as well.
   */
  const refuse = (reason: string, at?: Element | null): void => {
    const text = reason.trim();
    if (text === "") return;
    const anchor =
      at instanceof HTMLElement ? at : cellOf(tableRef.current, document.activeElement);
    if (anchor !== null) showEcho(anchor, text);
    announceGated(text);
  };

  useEffect(() => {
    if (!import.meta.env?.DEV || rows.length <= MAX_ROWS) return;
    console.warn(
      `Table: ${rows.length} rows exceed the v0 bound of ${MAX_ROWS}; v0 renders every row and is not virtualised (#266)`,
    );
  }, [rows.length]);

  const press = (column: TableColumn<T>): void => {
    if (sortPending === column.id || onSortChange === undefined) return;
    const direction: TableSortDirection =
      sort?.columnId === column.id && sort.direction === "ascending" ? "descending" : "ascending";
    onSortChange({ columnId: column.id, direction });
  };

  const labelOf = (row: T): string => rowLabel?.(row) ?? defaultRowLabel(columns, row, rowKey(row));
  const setRow = (key: string, on: boolean): void => {
    const next = new Set(selection);
    if (on) next.add(key);
    else next.delete(key);
    onRowSelect?.(next);
  };
  const allOn = keys.length > 0 && keys.every((key) => selection.has(key));
  const someOn = !allOn && keys.some((key) => selection.has(key));
  const selectAll = (): void => {
    const next = new Set(selection);
    for (const key of keys) {
      if (allOn) next.delete(key);
      else next.add(key);
    }
    onRowSelect?.(next);
  };

  /** A cell's grid attributes: its place, what it holds, and its roving `tabindex` (a widget carries its own). */
  const tabFor = (r: number, c: number, span = 1): 0 | -1 | undefined =>
    roving ? (tabStop.r === r && tabStop.c >= c && tabStop.c < c + span ? 0 : -1) : undefined;
  const at = (r: number, c: number, kind: CellKind): Record<string, string | number | undefined> =>
    gridMode
      ? {
          "data-cv-r": r,
          "data-cv-c": c,
          "data-cv-widget": kind === "widget" ? "" : undefined,
          "data-cv-interactive": kind === "interactive" ? "" : undefined,
          tabIndex: kind === "widget" ? undefined : tabFor(r, c),
        }
      : {};
  const ring = roving ? " cv-focus-ring cv-focus-ring--inset" : "";

  /** The cell whose words the echo shows for an event: a grid's placed cell, or a table-mode header or body cell. */
  const echoCellOf = (target: EventTarget | null): HTMLElement | null =>
    gridMode ? cellOf(tableRef.current, target) : tableCellOf(tableRef.current, target);

  /** Keyboard focus on a cell or its control shows the cell's words in the echo at once; any other cell's echo goes. */
  const echoOnFocus = (cell: HTMLElement, target: EventTarget): void => {
    const words = echoWords(cell);
    const by = target instanceof Element ? target : cell;
    if (words !== undefined && focusVisible(by)) showEcho(cell, words);
    else if (echoRef.current?.anchor !== cell) hideEcho();
  };

  const onGridFocus = (event: FocusEvent<HTMLTableElement>): void => {
    if (!gridMode) return;
    // Focus that lands in the grid supersedes a key's wait for an undrawn row: it never jumps there later.
    pending.current = null;
    const cell = cellOf(tableRef.current, event.target);
    if (cell === null) return;
    remember(placeOf(cell));
    if (roving && event.target instanceof HTMLElement) held.current = event.target;
    // `nearest` honours the cell's `scroll-margin-top`, so it is never left under the sticky header.
    if (roving && event.target === focusTargetOf(cell))
      cell.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    echoOnFocus(cell, event.target);
  };

  /** Table mode: a sort button is the one thing that takes focus; its keyboard focus shows a cut label whole. */
  const onTableFocus = (event: FocusEvent<HTMLTableElement>): void => {
    const cell = tableCellOf(tableRef.current, event.target);
    if (cell !== null) echoOnFocus(cell, event.target);
  };

  /** Focus leaving the table takes the echo with it, and leaves nothing for a later commit to restore. */
  const onGridBlur = (event: FocusEvent<HTMLTableElement>): void => {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    held.current = null;
    hideEcho();
  };

  /**
   * Hover shows a cell's words (or a cut text's whole words) after CMP-016's delay; a hover echo goes CMP-016's leave
   * grace after the pointer leaves its cell, unless it reaches the echo or comes back. Grid and table mode alike.
   */
  const onGridPointerOver = (event: PointerEvent<HTMLTableElement>): void => {
    const cell = echoCellOf(event.target);
    if (cell !== null && echoRef.current?.anchor === cell) {
      clearTimeout(leaveTimer.current);
      return;
    }
    clearTimeout(hoverTimer.current);
    leaveEcho();
    const words = cell === null ? undefined : echoWords(cell);
    if (cell === null || words === undefined) return;
    hoverTimer.current = setTimeout(() => showEcho(cell, words), ECHO_DELAY_MS);
  };
  const onGridPointerLeave = (): void => {
    clearTimeout(hoverTimer.current);
    leaveEcho();
  };

  /**
   * A press on a cell makes it the remembered cell before any `contextmenu`: a right-click opens the pressed row's
   * menu, not the last focused one's. While roving, a press beside a cell's built-in control (the select or actions
   * cell's padding, the box's plate) focuses that control instead of losing focus to the page.
   */
  const onGridMouseDown = (event: MouseEvent<HTMLTableElement>): void => {
    // A press supersedes a key's wait for an undrawn row, as focus moving does.
    pending.current = null;
    const cell = cellOf(tableRef.current, event.target);
    if (cell === null) return;
    remember(placeOf(cell));
    const target = focusTargetOf(cell);
    if (!roving || !(event.target instanceof Node) || target.contains(event.target)) return;
    event.preventDefault();
    target.focus({ preventScroll: true });
  };

  /**
   * A click on a treegrid row's first cell, outside any control in it, opens or closes a row that holds others: the
   * pointer twin of → and ← (a group header row's one wide cell, E29-D04 §2.1).
   */
  const onTreeClick = (event: MouseEvent<HTMLTableElement>): void => {
    const cell = cellOf(tableRef.current, event.target);
    if (cell === null || placeOf(cell).c !== 0) return;
    const control = event.target instanceof Element ? event.target.closest(TABBABLE) : null;
    if (control !== null && control !== cell) return;
    const row = bodyRowAt(placeOf(cell).r);
    const tree = row === undefined ? undefined : treeRow?.(row);
    if (row === undefined || tree?.expanded === undefined) return;
    onExpandedChange?.(row, !tree.expanded);
  };

  /**
   * Focus to the cell covering (r, c). A row outside the window is asked of the host (`onRowsInView`); focus lands
   * once it is drawn, and meanwhile the Tab stop stays on a drawn row.
   */
  const moveTo = (next: CellAt): void => {
    if (drawn(next.r)) {
      const target = cellCovering(tableRef.current, next.r, next.c);
      if (target !== null) focusTargetOf(target).focus({ preventScroll: true });
      return;
    }
    if (onRowsInView === undefined) return;
    pending.current = next;
    setActive(next);
    view.want(next.r - 1);
  };

  /** An expanded row's next row is its first child, unless a drawn next row sits at its own level or above. */
  const hasChildAfter = (r: number, tree: TableTreeRow): boolean => {
    if (r + 1 > bodyRows) return false;
    const below = bodyRowAt(r + 1);
    return below === undefined || (treeRow?.(below).level ?? 1) > tree.level;
  };

  /**
   * A row's parent: the nearest drawn row above it at a lower level; past the drawn rows, `posinset` rows up, which
   * is exact when its earlier siblings show no children (SCR-063's two levels).
   */
  const parentOf = (r: number, tree: TableTreeRow): number => {
    for (let p = r - 1; p >= 1 && (inWindow(p) || p === keptR); p -= 1) {
      const above = bodyRowAt(p);
      if (above !== undefined && (treeRow?.(above).level ?? 1) < tree.level) return p;
    }
    return Math.max(1, r - Math.max(1, tree.posinset));
  };

  const onGridKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    if (!roving || event.defaultPrevented || event.altKey || event.metaKey || event.shiftKey)
      return;
    const cell = cellOf(tableRef.current, event.target);
    if (cell === null) return;
    if (event.target !== cell && !cell.hasAttribute("data-cv-widget")) {
      // Focus is inside an interactive cell's control: the control owns its keys, Esc gives focus back to the cell.
      if (event.key === "Escape" && !event.ctrlKey) {
        event.preventDefault();
        cell.focus();
      }
      return;
    }
    const { r, c } = placeOf(cell);
    // A treegrid row's first cell takes → and ← for its tree (APG Treegrid; E29-D04 §2.7); other cells move by cell.
    const treeAt = treegrid && c === 0 ? bodyRowAt(r) : undefined;
    const tree = treeAt === undefined ? undefined : treeRow?.(treeAt);
    let next: CellAt;
    if (event.ctrlKey) {
      if (event.key === "Home") next = { r: 0, c: 0 };
      else if (event.key === "End") next = { r: lastR, c: lastC };
      else return;
    } else if (
      treeAt !== undefined &&
      tree?.expanded !== undefined &&
      (event.key === "ArrowRight" || event.key === "ArrowLeft") &&
      (event.key === "ArrowRight") !== tree.expanded
    ) {
      // → on a collapsed row expands it, ← on an expanded row collapses it: focus stays; the host redraws.
      event.preventDefault();
      hideEcho();
      onExpandedChange?.(treeAt, !tree.expanded);
      return;
    } else if (event.key === "ArrowRight" && tree?.expanded === true && hasChildAfter(r, tree))
      next = { r: r + 1, c: 0 };
    else if (event.key === "ArrowLeft" && tree !== undefined && tree.level > 1)
      next = { r: parentOf(r, tree), c: 0 };
    else if (event.key === "ArrowUp") next = { r: Math.max(r - 1, 0), c };
    else if (event.key === "ArrowDown") next = { r: Math.min(r + 1, lastR), c };
    else if (event.key === "ArrowLeft") next = { r, c: Math.max(c - 1, 0) };
    // A merged cell is one cell: → leaves it past its span.
    else if (event.key === "ArrowRight") next = { r, c: Math.min(c + spanOf(cell), lastC) };
    else if (event.key === "Home") next = { r, c: 0 };
    else if (event.key === "End") next = { r, c: lastC };
    else if (event.key === "PageUp")
      next = { r: Math.max(r - pageRows(region.current, cell), 0), c };
    else if (event.key === "PageDown")
      next = { r: Math.min(r + pageRows(region.current, cell), lastR), c };
    else {
      if (
        (event.key === "Enter" || event.key === "F2") &&
        cell.hasAttribute("data-cv-interactive")
      ) {
        const control = cell.querySelector<HTMLElement>(TABBABLE);
        if (control !== null) {
          event.preventDefault();
          control.focus();
        }
      } else if (
        event.key === " " &&
        selectable &&
        selectDisabledReason === undefined &&
        r >= 1 &&
        r <= bodyRows &&
        !cell.hasAttribute("data-cv-widget")
      ) {
        // A widget cell's own Space (the box, a button) acts natively.
        event.preventDefault();
        const row = bodyRowAt(r);
        if (row !== undefined) setRow(rowKey(row), !selection.has(rowKey(row)));
      }
      return;
    }
    // A handled key never scrolls the region itself: focus moves, and the cell scrolls into view.
    event.preventDefault();
    hideEcho();
    moveTo(next);
  };

  const stateRow = (content: ReactNode): JSX.Element => (
    <tr className="cv-table__state-row" aria-rowindex={2} {...role("row")}>
      <td className="cv-table__state" colSpan={gridColumns.length} {...role("cell")}>
        {content}
      </td>
    </tr>
  );

  const bodyCell = (row: T, key: string, r: number, gc: GridColumn<T>, c: number): JSX.Element => {
    if (gc.kind === "select") {
      return (
        <td
          key="cv-select"
          className="cv-table__cell cv-table__select"
          {...role("cell")}
          {...at(r, c, "widget")}
          {...pinOf(c)}
        >
          <Checkbox
            label={`Select ${labelOf(row)}`}
            checked={selection.has(key)}
            {...(selectDisabledReason === undefined
              ? {}
              : { disabled: true, disabledReason: selectDisabledReason })}
            onChange={(on) => setRow(key, on)}
            tabIndex={tabFor(r, c)}
          />
        </td>
      );
    }
    if (gc.kind === "actions") {
      return (
        <td
          key="cv-actions"
          className="cv-table__cell cv-table__actions"
          {...role("cell")}
          {...at(r, c, "widget")}
          {...pinOf(c)}
        >
          <RowMenu
            items={() => rowActions?.(row) ?? []}
            label={labelOf(row)}
            tabIndex={tabFor(r, c)}
            announceReason={say}
            onKeyDown={onGridKeyDown}
          />
        </td>
      );
    }
    const { column, index } = gc;
    const interactive = column.interactive === true;
    return (
      <td
        key={column.id}
        className={`cv-table__cell${ring}`}
        data-numeric={endAligned(column) ? "" : undefined}
        data-heading={index === 0 ? "" : undefined}
        {...role("cell")}
        {...at(r, c, interactive ? "interactive" : "cell")}
        {...pinOf(c)}
      >
        {/* Stacked: a visible header label on every data cell but the heading line; hidden from AT, which
            already reads the cell's columnheader in table navigation (browse mode reads values alone). */}
        {stacked && index > 0 ? (
          <span className="cv-table__cell-label" aria-hidden="true">
            {column.header}
          </span>
        ) : null}
        {column.numeric === undefined ? (
          <span className="cv-table__text">{column.cell(row)}</span>
        ) : (
          <NumericCell column={column} row={row} />
        )}
      </td>
    );
  };

  /**
   * A totals row's cell drawn from the columns (`totalRows` without `renderRow`): its first data cell is the row's
   * header (a `th scope="row"`), the select and actions cells are empty and plain.
   */
  const totalCell = (row: T, r: number, gc: GridColumn<T>, c: number): JSX.Element => {
    if (gc.kind !== "data") {
      return (
        <td
          key={`cv-${gc.kind}`}
          className={`cv-table__cell${ring}`}
          {...role("cell")}
          {...at(r, c, "cell")}
          {...pinOf(c)}
        />
      );
    }
    const { column, index } = gc;
    const Cell = index === 0 ? "th" : "td";
    return (
      <Cell
        key={column.id}
        className={`cv-table__cell${ring}`}
        data-numeric={endAligned(column) ? "" : undefined}
        {...(index === 0 ? { scope: "row" as const, ...role("rowheader") } : role("cell"))}
        {...at(r, c, "cell")}
        {...pinOf(c)}
      >
        {column.numeric === undefined ? (
          <span className="cv-table__text">{column.cell(row)}</span>
        ) : (
          <NumericCell column={column} row={row} />
        )}
      </Cell>
    );
  };

  /** A treegrid body row's `aria-level`, `aria-expanded`, `aria-posinset` and `aria-setsize`, from `treeRow`. */
  const treeAttrsOf = (row: T, r: number): Partial<TableRowProps> => {
    const tree = treegrid && r <= bodyRows ? treeRow?.(row) : undefined;
    return tree === undefined
      ? {}
      : {
          "aria-level": tree.level,
          "aria-expanded": tree.expanded,
          "aria-posinset": tree.posinset,
          "aria-setsize": tree.setsize,
        };
  };

  /** A totals row's pin: the region's bottom, above the totals rows after it (`--cv-table-after` of them). */
  const pinnedBelow = (r: number): CSSProperties =>
    ({ "--cv-table-after": lastR - r }) as CSSProperties;

  /** The row contract a custom row spreads (`renderRow`): its place, its cells' roles and the roving tabindex. */
  const contextOf = (row: T, r: number): TableRowContext => ({
    index: r - 1,
    rowProps: {
      className: isFooter(r) ? "cv-table__row cv-table__total-row" : "cv-table__row",
      "aria-rowindex": r + 1,
      ...role("row"),
      ...treeAttrsOf(row, r),
      ...(isFooter(r) ? { style: pinnedBelow(r) } : {}),
    },
    cellProps: (column, options = {}) => {
      const index = Math.min(Math.max(Math.trunc(column), 0), columns.length - 1);
      const span = Math.max(1, Math.min(Math.trunc(options.span ?? 1), columns.length - index));
      const words = options.echo?.trim();
      const cut = options.cut?.trim();
      const widget = options.widget === true;
      return {
        className: cx(
          "cv-table__cell",
          roving && "cv-focus-ring cv-focus-ring--inset",
          options.className,
        ),
        ...(options.header === true
          ? { scope: "row" as const, ...role("rowheader") }
          : role("cell")),
        colSpan: span > 1 ? span : undefined,
        "aria-describedby": options.describedBy,
        "data-numeric": options.numeric === true ? "" : undefined,
        "data-heading": index === 0 ? "" : undefined,
        "data-cv-echo": words === undefined || words === "" ? undefined : words,
        "data-cv-cut": cut === undefined || cut === "" ? undefined : cut,
        ...pinOf(index, span),
        ...(gridMode
          ? {
              "data-cv-r": r,
              "data-cv-c": index,
              "data-cv-span": span > 1 ? span : undefined,
              "data-cv-widget": widget ? "" : undefined,
              "data-cv-interactive": options.interactive === true ? "" : undefined,
              tabIndex: widget ? undefined : tabFor(r, index, span),
            }
          : {}),
      };
    },
    label: (column) =>
      stacked && column > 0 ? (
        <span className="cv-table__cell-label" aria-hidden="true">
          {columns[column]?.header}
        </span>
      ) : null,
    stacked,
    refuse: (reason) => refuse(reason),
    tabIndexOf: (column) =>
      tabFor(r, Math.min(Math.max(Math.trunc(column), 0), columns.length - 1)),
  });

  let body: ReactNode;
  if (state === "loading") {
    body = Array.from({ length: SKELETON_ROWS }, (_, i) => (
      <tr key={i} className="cv-table__row" aria-hidden="true" {...role("row")}>
        {gridColumns.map((gc, c) => (
          <td key={c} className="cv-table__cell" {...role("cell")}>
            <Skeleton shape="text" count={1} />
          </td>
        ))}
      </tr>
    ));
  } else if (state === "error" && error !== undefined) {
    body = stateRow(
      <ErrorState
        form="panel"
        live="off"
        message={error.message}
        retry={{
          label: "Retry",
          onClick: () => {
            retryStarted();
            error.onRetry();
          },
        }}
      />,
    );
  } else if (state === "empty") {
    body = stateRow(emptyState ?? <EmptyState title="No rows to show" />);
  } else {
    // The undrawn rows' height, in their measured height once laid out (`size.row.height` before).
    const rowsTall = (count: number): string =>
      rowPx > 0 ? `${count * rowPx}px` : `calc(${count} * var(--size-row-height))`;
    const spacer = (key: string, count: number): JSX.Element => (
      <tr key={key} className="cv-table__spacer" aria-hidden="true">
        <td colSpan={gridColumns.length} style={{ blockSize: rowsTall(count) }} />
      </tr>
    );
    const bodyRow = (row: T, r: number): JSX.Element => {
      const key = rowKey(row);
      if (renderRow !== undefined)
        return <Fragment key={key}>{renderRow(row, contextOf(row, r))}</Fragment>;
      return (
        <tr
          key={key}
          className="cv-table__row"
          aria-rowindex={r + 1}
          aria-selected={selectable ? selection.has(key) : undefined}
          {...role("row")}
          {...treeAttrsOf(row, r)}
        >
          {gridColumns.map((gc, c) => bodyCell(row, key, r, gc, c))}
        </tr>
      );
    };
    // The window's rows and, outside it, the kept row (G-01), at their absolute places: spacers hold the rest and
    // an empty pad keeps each drawn row on its absolute row's zebra (`bodyParts`).
    const drawnRs = Array.from({ length: drawnCount }, (_, i) => offset + i + 1);
    if (keptR !== undefined) drawnRs.push(keptR);
    drawnRs.sort((a, b) => a - b);
    body = bodyParts(drawnRs, total).map((part) => {
      if (part.kind === "pad")
        return <tr key={part.key} className="cv-table__spacer" aria-hidden="true" />;
      if (part.kind === "spacer") return spacer(part.key, part.rows);
      const row = bodyRowAt(part.r);
      return row === undefined ? null : bodyRow(row, part.r);
    });
  }
  // The trailing totals rowgroup (D04H A-6.4): after the body in the grid's order, each row led by its rowheader.
  const totals =
    footer.length === 0
      ? null
      : footer.map((row, i) => {
          const r = bodyRows + 1 + i;
          const key = footerKeys[i] ?? String(i);
          if (renderRow !== undefined)
            return <Fragment key={key}>{renderRow(row, contextOf(row, r))}</Fragment>;
          return (
            <tr
              key={key}
              className="cv-table__row cv-table__total-row"
              aria-rowindex={r + 1}
              style={pinnedBelow(r)}
              {...role("row")}
            >
              {gridColumns.map((gc, c) => totalCell(row, r, gc, c))}
            </tr>
          );
        });

  const headerCell = (gc: GridColumn<T>, c: number): JSX.Element => {
    if (gc.kind === "select") {
      const empty = keys.length === 0;
      return (
        <th
          key="cv-select"
          scope="col"
          className={`cv-table__header cv-table__select${empty ? ring : ""}`}
          {...role("columnheader")}
          {...at(0, c, empty ? "cell" : "widget")}
          {...pinOf(c)}
        >
          <Checkbox
            label="Select all rows"
            checked={allOn}
            indeterminate={someOn}
            disabled={empty || selectDisabledReason !== undefined}
            {...(selectDisabledReason === undefined
              ? {}
              : { disabledReason: selectDisabledReason })}
            onChange={selectAll}
            tabIndex={empty ? undefined : tabFor(0, c)}
          />
        </th>
      );
    }
    if (gc.kind === "actions") {
      return (
        <th
          key="cv-actions"
          scope="col"
          className={`cv-table__header cv-table__actions${ring}`}
          {...role("columnheader")}
          {...at(0, c, "cell")}
          {...pinOf(c)}
        >
          <span className="cv-visually-hidden">Actions</span>
        </th>
      );
    }
    const { column } = gc;
    const sortable = column.sortable === true && onSortChange !== undefined;
    const direction = sort?.columnId === column.id ? sort.direction : undefined;
    const pending = sortable && sortPending === column.id;
    const gated = sortable ? reasonOf(column) : undefined;
    // A block that ellipsises when the column is narrower than its words; in a grid the echo shows them whole.
    const hint = column.headerHint?.trim();
    const label = (
      <span className="cv-table__label" data-cv-cut={column.header}>
        {column.header}
        {hint === undefined || hint === "" ? null : (
          <span className="cv-visually-hidden"> {hint}</span>
        )}
      </span>
    );
    const status =
      column.headerStatus === undefined ? null : (
        <span className="cv-table__header-status" data-tone={column.headerStatus.tone}>
          <Icon name={column.headerStatus.icon} />
          <span className="cv-visually-hidden"> {column.headerStatus.label}</span>
        </span>
      );
    return (
      <th
        key={column.id}
        scope="col"
        className={`cv-table__header${sortable ? "" : ring}`}
        data-numeric={endAligned(column) ? "" : undefined}
        data-cv-echo={hint === undefined || hint === "" ? undefined : `${column.header} ${hint}`}
        aria-sort={sortable ? (direction ?? "none") : undefined}
        {...role("columnheader")}
        {...at(0, c, sortable ? "widget" : "cell")}
        {...pinOf(c)}
      >
        {sortable ? (
          <button
            type="button"
            className="cv-table__sort cv-focus-ring cv-focus-ring--inset"
            aria-busy={pending ? true : undefined}
            aria-disabled={gated === undefined ? undefined : true}
            aria-describedby={
              gated === undefined ? undefined : (sortReasonId ?? sortReasonIdOf(gated))
            }
            tabIndex={tabFor(0, c)}
            onClick={(event) =>
              gated === undefined ? press(column) : refuse(gated, event.currentTarget.closest("th"))
            }
            onKeyDown={gated === undefined ? undefined : swallowHeldEnter}
          >
            {gated === undefined ? null : (
              <span className="cv-table__lock">
                <Icon name="lock" decorative={false} label="Not available" />
              </span>
            )}
            {label}
            {status}
            <SortGlyph direction={direction} pending={pending} />
          </button>
        ) : status === null ? (
          label
        ) : (
          <span className="cv-table__head">
            {label}
            {status}
          </span>
        )}
      </th>
    );
  };

  const rowCount = state === "loading" ? -1 : state === "populated" ? lastR + 1 : 2;
  // A grid and a table with a T2 sort header keep the echo's node; any other table mounts it while it shows a cut
  // header label's or a cell's words, and has none otherwise.
  const echoes = gridMode || gatedReasons.length > 0 || echo !== null;

  return (
    <div
      ref={shell}
      className="cv-table"
      data-cmp="CMP-049"
      data-density={density}
      data-state={state}
      data-mode={gridMode ? "grid" : undefined}
      data-layout={stacked ? "stacked" : undefined}
      // Focused body cells scroll clear of the pinned totals rows (E29-D05 §6.2 F-01: `scroll-margin-bottom`).
      style={
        footer.length === 0 || stacked
          ? undefined
          : ({ "--cv-table-totals": footer.length } as CSSProperties)
      }
    >
      <span ref={probe} className="cv-table__em-probe" aria-hidden="true" />
      <div
        ref={region}
        className="cv-table__region"
        onScroll={onRowsInView === undefined ? undefined : view.measure}
        {...(scrolls
          ? { role: "region", "aria-labelledby": captionId, ...(roving ? {} : { tabIndex: 0 }) }
          : {})}
      >
        <table
          ref={tableRef}
          className="cv-table__table"
          aria-labelledby={captionId}
          aria-rowcount={rowCount}
          aria-colcount={gridMode ? gridColumns.length : undefined}
          aria-busy={loading ? true : undefined}
          aria-multiselectable={roving && (selectable || multiselectable) ? true : undefined}
          {...role("table")}
          // Grid mode: the grid's keys while it roves (role="grid"), and the remembered cell (which the stacked
          // layout's context menu reads too), the cells' echo on focus and hover, focus leaving it (the echo goes;
          // nothing is restored). Table mode: the echo alone, for a cut header label or a cell's words on hover and
          // a sort button's keyboard focus (E08-D07 §4.1), and a shown echo's blur.
          {...(roving ? { onKeyDown: onGridKeyDown } : {})}
          {...(gridMode
            ? {
                onFocus: onGridFocus,
                onMouseDown: onGridMouseDown,
                onPointerOver: onGridPointerOver,
                onPointerLeave: onGridPointerLeave,
                ...(treegrid ? { onClick: onTreeClick } : {}),
              }
            : {
                onFocus: onTableFocus,
                onPointerOver: onGridPointerOver,
                onPointerLeave: onGridPointerLeave,
              })}
          {...(gridMode || echo !== null ? { onBlur: onGridBlur } : {})}
        >
          <caption className="cv-table__caption">
            <span id={captionId} className={captionHidden ? "cv-visually-hidden" : undefined}>
              {caption}
            </span>
            {loading ? <span className="cv-table__loading">{loadingText}</span> : null}
          </caption>
          {/* Column widths in `em` of the table's own font (a `<col>` inherits it), in the table layout. */}
          {columns.some((column) => column.widthEm !== undefined) ? (
            <colgroup>
              {gridColumns.map((gc, c) => (
                <col
                  key={c}
                  style={
                    gc.kind === "data" && gc.column.widthEm !== undefined
                      ? { width: `${gc.column.widthEm}em` }
                      : undefined
                  }
                />
              ))}
            </colgroup>
          ) : null}
          <thead {...role("rowgroup")}>
            <tr aria-rowindex={1} {...role("row")}>
              {gridColumns.map(headerCell)}
            </tr>
          </thead>
          <tbody ref={tbody} {...role("rowgroup")}>
            {body}
          </tbody>
          {totals === null ? null : (
            <tbody className="cv-table__totals" {...role("rowgroup")}>
              {totals}
            </tbody>
          )}
        </table>
      </div>
      {rowActions !== undefined && activeRow !== undefined ? (
        <Menu
          contextTarget={tbody}
          aria-label={`Actions for ${labelOf(activeRow)}`}
          open={contextShown}
          onOpenChange={setContextOpen}
          items={contextItems}
          announceReason={say}
        />
      ) : null}
      {sortReasonId === undefined
        ? gatedReasons.map((reason) => (
            <span key={reason} id={sortReasonIdOf(reason)} className="cv-visually-hidden">
              {reason}
            </span>
          ))
        : null}
      {echoes ? <TableEcho echo={echo} hover={echoHover} /> : null}
      {announce === undefined ? (
        <div
          className="cv-visually-hidden cv-table__live"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {/* Re-keyed per `say`, so the same reason pressed twice is said twice. */}
          <span key={nonce}>{line}</span>
        </div>
      ) : null}
    </div>
  );
}
