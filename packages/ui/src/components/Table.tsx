import {
  useEffect,
  useId,
  useRef,
  useState,
  type JSX,
  type ReactNode,
  type RefObject,
} from "react";
import { Icon } from "../icons/Icon.js";
import { EmptyState } from "./EmptyState.js";
import { ErrorState } from "./ErrorState.js";
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
}

/** A text column: the cell truncates with an ellipsis and keeps its full text in the DOM. */
export interface TableTextColumn<T> extends TableColumnBase {
  readonly cell: (row: T) => ReactNode;
  readonly numeric?: undefined;
  readonly precision?: never;
}

/** A numeric column: the value renders through CMP-020 NumericText, end-aligned in mono, never truncated. */
export interface TableNumericColumn<T> extends TableColumnBase {
  readonly cell: (row: T) => number;
  readonly numeric: NumericFormat;
  /** Decimals; NumericText's default for the format when omitted. */
  readonly precision?: number;
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
}

/** The v0 bound (#266 out of scope: no virtualised rendering). */
const MAX_ROWS = 200;
const SKELETON_ROWS = 5;

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
 * row and column counts) changes, and as the region or its table resizes.
 */
function useScrolls(region: RefObject<HTMLDivElement | null>, content: string): boolean {
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const node = region.current;
    if (node === null) return undefined;
    const measure = (): void => {
      setScrolls(node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    for (const child of node.children) observer.observe(child);
    return () => observer.disconnect();
  }, [region, content]);
  return scrolls;
}

interface ResultInputs<T> {
  readonly columns: readonly TableColumn<T>[];
  readonly rowCount: number;
  readonly sort: TableSort | undefined;
  readonly sortPending: string | undefined;
  readonly loading: boolean;
  readonly error: TableError | undefined;
}

interface ResultLine {
  /** The polite line. */
  readonly line: string;
  /** Call as a Retry starts: clears the line so the next result, even an identical one, is said again. */
  readonly retryStarted: () => void;
}

/**
 * The one polite line for sort and load results (D02F CMP-049): a settled sort, the end of a load (the row
 * count) and an error (its message, G17). Never the first render's state, except an error, which is spoken
 * once after mount. Each result is spoken once. The line clears as a load, a pending sort or a Retry starts,
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
  const retryStarted = (): void => {
    retriedFrom.current = error;
    setLine("");
  };
  return { line, retryStarted };
}

/**
 * CMP-049 Table, table mode (the WAI-ARIA APG Table pattern: static cells, no control in a body row). A native
 * `<table>` named by its caption inside a scroll region that takes a Tab stop when it scrolls, a sticky header
 * whose sortable labels are buttons with `aria-sort`, zebra rows, and one polite region for sort and load
 * results. States: loading (skeleton rows, `aria-busy`), empty and filtered-empty (CMP-026), error (CMP-027 with
 * Retry). The consumer sorts the rows; the table only asks.
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
}: TableProps<T>): JSX.Element {
  const captionId = useId();
  const region = useRef<HTMLDivElement>(null);
  const state = loading
    ? "loading"
    : error !== undefined
      ? "error"
      : rows.length === 0
        ? "empty"
        : "populated";
  const scrolls = useScrolls(region, `${state}:${rows.length}:${columns.length}`);
  const { line, retryStarted } = useResultLine({
    columns,
    rowCount: rows.length,
    sort,
    sortPending,
    loading,
    error,
  });

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

  const stateRow = (content: ReactNode): JSX.Element => (
    <tr className="cv-table__state-row" aria-rowindex={2}>
      <td className="cv-table__state" colSpan={columns.length}>
        {content}
      </td>
    </tr>
  );

  let body: ReactNode;
  if (state === "loading") {
    body = Array.from({ length: SKELETON_ROWS }, (_, i) => (
      <tr key={i} className="cv-table__row" aria-hidden="true">
        {columns.map((column) => (
          <td key={column.id} className="cv-table__cell">
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
    body = rows.map((row, i) => (
      <tr key={rowKey(row)} className="cv-table__row" aria-rowindex={i + 2}>
        {columns.map((column) => (
          <td
            key={column.id}
            className="cv-table__cell"
            data-numeric={column.numeric === undefined ? undefined : ""}
          >
            {column.numeric === undefined ? (
              <span className="cv-table__text">{column.cell(row)}</span>
            ) : (
              <NumericCell column={column} row={row} />
            )}
          </td>
        ))}
      </tr>
    ));
  }

  const rowCount = state === "loading" ? -1 : state === "populated" ? rows.length + 1 : 2;

  return (
    <div className="cv-table" data-cmp="CMP-049" data-density={density} data-state={state}>
      <div
        ref={region}
        className="cv-table__region"
        {...(scrolls ? { role: "region", "aria-labelledby": captionId, tabIndex: 0 } : {})}
      >
        <table
          className="cv-table__table"
          aria-labelledby={captionId}
          aria-rowcount={rowCount}
          aria-busy={loading ? true : undefined}
        >
          <caption className="cv-table__caption">
            <span id={captionId} className={captionHidden ? "cv-visually-hidden" : undefined}>
              {caption}
            </span>
            {loading ? <span className="cv-table__loading">{loadingText}</span> : null}
          </caption>
          <thead>
            <tr aria-rowindex={1}>
              {columns.map((column) => {
                const sortable = column.sortable === true && onSortChange !== undefined;
                const direction = sort?.columnId === column.id ? sort.direction : undefined;
                const pending = sortable && sortPending === column.id;
                return (
                  <th
                    key={column.id}
                    scope="col"
                    className="cv-table__header"
                    data-numeric={column.numeric === undefined ? undefined : ""}
                    aria-sort={sortable ? (direction ?? "none") : undefined}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        className="cv-table__sort cv-focus-ring cv-focus-ring--inset"
                        aria-busy={pending ? true : undefined}
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
              })}
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
      <div className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {line}
      </div>
    </div>
  );
}
