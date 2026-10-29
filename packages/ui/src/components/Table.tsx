import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Icon } from "../icons/Icon.js";
import { Checkbox } from "./Checkbox.js";
import { EmptyState } from "./EmptyState.js";
import { ErrorState } from "./ErrorState.js";
import { IconButton } from "./IconButton.js";
import { Menu, type MenuItem } from "./Menu.js";
import { Skeleton } from "./Skeleton.js";
import { Spinner } from "./Spinner.js";
import { NumericText, type NumericFormat } from "./Typography.js";

export type TableSortDirection = "ascending" | "descending";

/** The applied sort: one column and its direction. */
export interface TableSort {
  readonly columnId: string;
  readonly direction: TableSortDirection;
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
}

/** A text column: the cell truncates with an ellipsis and keeps its full text in the DOM. */
export interface TableTextColumn<T> extends TableColumnBase {
  readonly cell: (row: T) => ReactNode;
  readonly numeric?: undefined;
  readonly precision?: never;
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
}

export type TableColumn<T> = TableTextColumn<T> | TableNumericColumn<T>;

/** The error state: CandleViewer's own words and a Retry. */
export interface TableError {
  readonly message: string;
  readonly onRetry: () => void;
}

export interface TableProps<T> {
  readonly columns: readonly TableColumn<T>[];
  /** The rows, in display order: the consumer sorts. v0 renders every row; above 200 it warns in development. */
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
  /**
   * Renders the trailing actions column: an IconButton "Actions for {row}" opening a CMP-041 menu of these items;
   * `Shift+F10` or the Menu key on a focused row opens the same items as a context menu at the row.
   */
  readonly rowActions?: ((row: T) => readonly MenuItem[]) | undefined;
  /**
   * The row's name in "Select {row}" and "Actions for {row}". Default: the first column's value when it is text or a
   * number, else the row's key.
   */
  readonly rowLabel?: ((row: T) => string) | undefined;
}

/** The v0 bound (#266 out of scope: no virtualised rendering). */
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

const rowsWord = (n: number): string => (n === 0 ? "No rows" : n === 1 ? "1 row" : `${n} rows`);

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

/** What a cell holds: a built-in control focused in its place, plain content, or a consumer's controls. */
type CellKind = "widget" | "cell" | "interactive";

/** The grid cell an event happened in (its own node or inside it), or null outside this table's cells. */
const cellOf = (table: HTMLElement | null, target: EventTarget | null): HTMLElement | null => {
  if (table === null || !(target instanceof Element)) return null;
  const cell = target.closest<HTMLElement>("[data-cv-c]");
  return cell !== null && table.contains(cell) ? cell : null;
};

const placeOf = (cell: HTMLElement): CellAt => ({
  r: Number(cell.dataset["cvR"]),
  c: Number(cell.dataset["cvC"]),
});

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
 * stop, in order (arrow navigation needs a layout of rows and columns).
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
  rowActions,
  rowLabel,
}: TableProps<T>): JSX.Element {
  const captionId = useId();
  const shell = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const region = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const tbody = useRef<HTMLTableSectionElement>(null);
  const state = loading
    ? "loading"
    : error !== undefined
      ? "error"
      : rows.length === 0
        ? "empty"
        : "populated";
  const selectable = onRowSelect !== undefined;
  const gridColumns: readonly GridColumn<T>[] = [
    ...(selectable ? [{ kind: "select" } as const] : []),
    ...columns.map((column, index) => ({ kind: "data", column, index }) as const),
    ...(rowActions === undefined ? [] : [{ kind: "actions" } as const]),
  ];
  const gridMode =
    grid ||
    selectable ||
    rowActions !== undefined ||
    columns.some((column) => column.interactive === true);
  const scrolls = useScrolls(region, `${state}:${rows.length}:${gridColumns.length}`);
  const stacked = useStacked(
    shell,
    probe,
    columns.reduce((sum, column) => sum + (column.minWidthEm ?? DEFAULT_MIN_WIDTH_EM), 0) +
      (gridColumns.length - columns.length) * CONTROL_COLUMN_EM,
  );
  /** Arrow navigation and one Tab stop: grid mode, laid out as rows and columns. */
  const roving = gridMode && !stacked;
  // Explicit roles: `grid` / `gridcell` while roving; while stacked, the table roles, because `display: block`
  // strips native table semantics in some engines.
  const role = (name: "table" | "rowgroup" | "row" | "columnheader" | "cell"): { role?: string } =>
    roving && name === "table"
      ? { role: "grid" }
      : roving && name === "cell"
        ? { role: "gridcell" }
        : stacked
          ? { role: name }
          : {};
  const selection = selected ?? new Set<string>();
  const keys = state === "populated" ? rows.map(rowKey) : [];
  const { line, retryStarted, nonce, say } = useResultLine({
    columns,
    rowCount: rows.length,
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
  useTamedControls(tableRef, roving);

  // The remembered cell (the Tab stop), clamped to the grid as rows come and go; at first the first body cell.
  const [active, setActive] = useState<CellAt | undefined>(undefined);
  const bodyRows = state === "populated" ? rows.length : 0;
  const lastC = gridColumns.length - 1;
  const wanted = active ?? { r: bodyRows > 0 ? 1 : 0, c: 0 };
  const stop: CellAt = {
    r: Math.min(Math.max(wanted.r, 0), bodyRows),
    c: Math.min(Math.max(wanted.c, 0), lastC),
  };
  // The context menu's row: the remembered body row (the header row keeps the last; the keys open it from the body).
  const activeRow = state === "populated" ? rows[Math.max(stop.r, 1) - 1] : undefined;
  // The context menu is controlled so its items are asked for only while it is open.
  const [contextOpen, setContextOpen] = useState(false);

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
  const tabFor = (r: number, c: number): 0 | -1 | undefined =>
    roving ? (stop.r === r && stop.c === c ? 0 : -1) : undefined;
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

  const onGridFocus = (event: FocusEvent<HTMLTableElement>): void => {
    if (!gridMode) return;
    const cell = cellOf(tableRef.current, event.target);
    if (cell === null) return;
    const place = placeOf(cell);
    if (active?.r !== place.r || active.c !== place.c) setActive(place);
    // `nearest` honours the cell's `scroll-margin-top`, so it is never left under the sticky header.
    if (roving && event.target === focusTargetOf(cell))
      cell.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  };

  /**
   * A press on a cell makes it the remembered cell before any `contextmenu`: a right-click opens the pressed row's
   * menu, not the last focused one's. While roving, a press beside a cell's built-in control (the select or actions
   * cell's padding, the box's plate) focuses that control instead of losing focus to the page.
   */
  const onGridMouseDown = (event: MouseEvent<HTMLTableElement>): void => {
    const cell = cellOf(tableRef.current, event.target);
    if (cell === null) return;
    const place = placeOf(cell);
    if (active?.r !== place.r || active.c !== place.c) setActive(place);
    const target = focusTargetOf(cell);
    if (!roving || !(event.target instanceof Node) || target.contains(event.target)) return;
    event.preventDefault();
    target.focus({ preventScroll: true });
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
    let next: CellAt;
    if (event.ctrlKey) {
      if (event.key === "Home") next = { r: 0, c: 0 };
      else if (event.key === "End") next = { r: bodyRows, c: lastC };
      else return;
    } else if (event.key === "ArrowUp") next = { r: Math.max(r - 1, 0), c };
    else if (event.key === "ArrowDown") next = { r: Math.min(r + 1, bodyRows), c };
    else if (event.key === "ArrowLeft") next = { r, c: Math.max(c - 1, 0) };
    else if (event.key === "ArrowRight") next = { r, c: Math.min(c + 1, lastC) };
    else if (event.key === "Home") next = { r, c: 0 };
    else if (event.key === "End") next = { r, c: lastC };
    else if (event.key === "PageUp")
      next = { r: Math.max(r - pageRows(region.current, cell), 0), c };
    else if (event.key === "PageDown")
      next = { r: Math.min(r + pageRows(region.current, cell), bodyRows), c };
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
        r >= 1 &&
        !cell.hasAttribute("data-cv-widget")
      ) {
        // A widget cell's own Space (the box, a button) acts natively.
        event.preventDefault();
        const row = rows[r - 1];
        if (row !== undefined) setRow(rowKey(row), !selection.has(rowKey(row)));
      }
      return;
    }
    // A handled key never scrolls the region itself: focus moves, and the cell scrolls into view.
    event.preventDefault();
    const target = tableRef.current?.querySelector<HTMLElement>(
      `[data-cv-r="${next.r}"][data-cv-c="${next.c}"]`,
    );
    if (target != null) focusTargetOf(target).focus({ preventScroll: true });
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
        >
          <Checkbox
            label={`Select ${labelOf(row)}`}
            checked={selection.has(key)}
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
        data-numeric={column.numeric === undefined ? undefined : ""}
        data-heading={index === 0 ? "" : undefined}
        {...role("cell")}
        {...at(r, c, interactive ? "interactive" : "cell")}
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
    body = rows.map((row, i) => {
      const key = rowKey(row);
      return (
        <tr
          key={key}
          className="cv-table__row"
          aria-rowindex={i + 2}
          aria-selected={selectable ? selection.has(key) : undefined}
          {...role("row")}
        >
          {gridColumns.map((gc, c) => bodyCell(row, key, i + 1, gc, c))}
        </tr>
      );
    });
  }

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
        >
          <Checkbox
            label="Select all rows"
            checked={allOn}
            indeterminate={someOn}
            disabled={empty}
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
        >
          <span className="cv-visually-hidden">Actions</span>
        </th>
      );
    }
    const { column } = gc;
    const sortable = column.sortable === true && onSortChange !== undefined;
    const direction = sort?.columnId === column.id ? sort.direction : undefined;
    const pending = sortable && sortPending === column.id;
    return (
      <th
        key={column.id}
        scope="col"
        className={`cv-table__header${sortable ? "" : ring}`}
        data-numeric={column.numeric === undefined ? undefined : ""}
        aria-sort={sortable ? (direction ?? "none") : undefined}
        {...role("columnheader")}
        {...at(0, c, sortable ? "widget" : "cell")}
      >
        {sortable ? (
          <button
            type="button"
            className="cv-table__sort cv-focus-ring cv-focus-ring--inset"
            aria-busy={pending ? true : undefined}
            tabIndex={tabFor(0, c)}
            onClick={() => press(column)}
          >
            <span className="cv-table__label">{column.header}</span>
            <SortGlyph direction={direction} pending={pending} />
          </button>
        ) : (
          <span className="cv-table__label">{column.header}</span>
        )}
      </th>
    );
  };

  const rowCount = state === "loading" ? -1 : state === "populated" ? rows.length + 1 : 2;

  return (
    <div
      ref={shell}
      className="cv-table"
      data-cmp="CMP-049"
      data-density={density}
      data-state={state}
      data-mode={gridMode ? "grid" : undefined}
      data-layout={stacked ? "stacked" : undefined}
    >
      <span ref={probe} className="cv-table__em-probe" aria-hidden="true" />
      <div
        ref={region}
        className="cv-table__region"
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
          aria-multiselectable={roving && selectable ? true : undefined}
          {...role("table")}
          // Grid mode only: the grid's keys while it roves (role="grid"), and the remembered cell (which the
          // stacked layout's context menu reads too). A table-mode table listens to nothing.
          {...(roving ? { onKeyDown: onGridKeyDown } : {})}
          {...(gridMode ? { onFocus: onGridFocus, onMouseDown: onGridMouseDown } : {})}
        >
          <caption className="cv-table__caption">
            <span id={captionId} className={captionHidden ? "cv-visually-hidden" : undefined}>
              {caption}
            </span>
            {loading ? <span className="cv-table__loading">{loadingText}</span> : null}
          </caption>
          <thead {...role("rowgroup")}>
            <tr aria-rowindex={1} {...role("row")}>
              {gridColumns.map(headerCell)}
            </tr>
          </thead>
          <tbody ref={tbody} {...role("rowgroup")}>
            {body}
          </tbody>
        </table>
      </div>
      {rowActions !== undefined && activeRow !== undefined ? (
        <Menu
          contextTarget={tbody}
          aria-label={`Actions for ${labelOf(activeRow)}`}
          open={contextOpen}
          onOpenChange={setContextOpen}
          items={contextOpen ? rowActions(activeRow) : []}
          announceReason={say}
        />
      ) : null}
      <div
        className="cv-visually-hidden cv-table__live"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {/* Re-keyed per `say`, so the same reason pressed twice is said twice. */}
        <span key={nonce}>{line}</span>
      </div>
    </div>
  );
}
