/**
 * SCR-045, the chart's data-table alternative (E47-S01 C1/C2, #1316): CMP-049 in grid mode over the series the
 * chart is given (`ChartTableSeries`), windowed so only the drawn window (plus a buffer) is in the DOM at 100k bars.
 * Keys: CMP-049's grid keys (arrows, `Home`/`End` within the row, `Ctrl+Home`/`Ctrl+End`, `PageUp`/`PageDown`) and
 * E11-D04 §17.1's own: `Enter` (or `→` on the time cell) expands the bar's footprint levels as grid rows beneath it
 * (one bar at a time), `←` on the time cell or `Enter` again collapses; `Esc` clears the selection,
 * then collapses, then returns to the chart (`onExit`); `Space` toggles a row's selection, `Shift+↑/↓` extends it
 * from the cursor row, `Ctrl+A` selects every loaded bar, `Ctrl+C` copies the selection, or the cursor row, as TSV
 * through an injectable clipboard writer.
 */
import { useCallback, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FocusEvent, JSX, KeyboardEvent } from "react";
import { Table, type TableColumn, type TableRowContext } from "@candleviewer/ui";
import {
  BAR_HEADERS,
  EXPANDER_HEADER,
  LEVEL_HEADERS,
  NOT_AVAILABLE,
  NO_FOOTPRINT,
  SAY,
  collapseName,
  expandName,
  levelPosition,
  tableCaption,
} from "./copy";
import {
  displayDecimal,
  formatBarTime,
  formatBarTimeFull,
  signedDecimal,
  type BarFields,
} from "./format";
import {
  barCount,
  barFields,
  cvdAt,
  cvdPrefix,
  levelCount,
  levelsOf,
  type ChartTableSeries,
  type LevelFields,
} from "./series";
import { politeToShell } from "./politeWriter";
import { buildTsv } from "./tsv";
import "./chartTable.css";

/** Rows kept drawn beyond the cursor on each side: the "small buffer" (Gherkin 5). */
export const WINDOW_BUFFER = 30;

/** A drawn row: a bar, or one footprint level of the expanded bar. */
type Item =
  | { readonly kind: "bar"; readonly bar: number }
  | { readonly kind: "level"; readonly bar: number; readonly level: number };

/** Where a key asked focus to go once its row is drawn: a bar's or a level's cell in data column `col`. */
interface FocusRequest {
  readonly bar: number;
  readonly level: number | null;
  readonly col: number;
}

export interface ChartDataTableProps {
  /**
   * The series the chart draws. Keep its identity stable between data changes: a new object recomputes the CVD
   * prefix, one O(footprint cells) pass (code lens r1 m4).
   */
  readonly series: ChartTableSeries;
  /** "BTCUSDT 1m": the caption's head. */
  readonly title: string;
  /** The bar the table opens on (the chart's cursor bar); default the latest. */
  readonly initialBar?: number;
  /** Move focus to the initial bar's row on mount: Alt+T, a user action, moves focus into the table. */
  readonly focusOnOpen?: boolean;
  readonly writeClipboard?: (text: string) => Promise<void>;
  /** The table's polite lines; default the shell announcer. */
  readonly say?: (text: string) => void;
  /** `Esc` with nothing selected or expanded: back to the chart (E11-D04 §17.1's last step). */
  readonly onExit?: () => void;
}

const defaultClipboard = (text: string): Promise<void> => navigator.clipboard.writeText(text);
const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi);
/** The time column: `→` here expands, `←` collapses (E11-D04 §17.1). */
const TIME_COL = 1;

/** A value the series cannot show exactly (a tick finer than the price digits) reads "not available". */
function orNotAvailable<T>(read: () => T, fallback: T): T {
  try {
    return read();
  } catch (error) {
    if (error instanceof RangeError) return fallback;
    throw error;
  }
}

/** The data column of the cell an event came from (CMP-049's `data-cv-c`). */
const colOf = (target: EventTarget): number => {
  const cell = target instanceof Element ? target.closest("[data-cv-c]") : null;
  return Number(cell?.getAttribute("data-cv-c") ?? 0);
};

export function ChartDataTable(props: ChartDataTableProps): JSX.Element {
  const { series, title, focusOnOpen = false, onExit } = props;
  const say = props.say ?? politeToShell;
  const writeClipboard = props.writeClipboard ?? defaultClipboard;
  const n = barCount(series);
  const lastBar = Math.max(n - 1, 0);
  const cvd = useMemo(() => orNotAvailable(() => cvdPrefix(series), null), [series]);
  const baseId = useId();
  const [expandedState, setExpanded] = useState<number | null>(null);
  const [selectedState, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [cursorState, setCursor] = useState(() => clamp(props.initialBar ?? n - 1, 0, lastBar));
  // A series that shrank leaves no index past its end (code lens r1 m6): clamp and prune on read.
  const cursor = clamp(cursorState, 0, lastBar);
  const expanded =
    expandedState !== null && expandedState < n && levelCount(series, expandedState) > 0
      ? expandedState
      : null;
  const selected = useMemo(() => {
    let stale = false;
    for (const bar of selectedState) if (bar >= n) stale = true;
    return stale ? new Set([...selectedState].filter((bar) => bar < n)) : selectedState;
  }, [selectedState, n]);
  const levels = useMemo(
    () => (expanded === null ? [] : orNotAvailable(() => levelsOf(series, expanded), [])),
    [series, expanded],
  );
  const levelRows = levels.length;
  /** Shift+↑/↓ extends from here; it follows the cursor on every move that is not an extension. */
  const anchor = useRef(cursor);
  const extending = useRef(false);
  /** The column `Enter` (or the button) expanded from: collapse returns there (a11y lens r1 m2). */
  const expandCol = useRef(0);
  const [view, setView] = useState(() => ({ first: cursor, last: cursor }));
  const shell = useRef<HTMLDivElement>(null);
  const focusNext = useRef<FocusRequest | null>(
    focusOnOpen ? { bar: cursor, level: null, col: TIME_COL } : null,
  );
  /** Alt+T's arrival line is said once, when the opening focus lands. */
  const arrival = useRef(focusOnOpen);

  const total = n + levelRows;
  const itemAt = (abs: number): Item => {
    if (expanded === null || abs <= expanded) return { kind: "bar", bar: abs };
    if (abs <= expanded + levelRows)
      return { kind: "level", bar: expanded, level: abs - expanded - 1 };
    return { kind: "bar", bar: abs - levelRows };
  };
  const absOf = (bar: number): number =>
    expanded !== null && bar > expanded ? bar + levelRows : bar;
  const first = clamp(view.first - WINDOW_BUFFER, 0, Math.max(total - 1, 0));
  const last = clamp(view.last + WINDOW_BUFFER, 0, Math.max(total - 1, 0));
  const rows: Item[] = [];
  for (let abs = first; abs <= last && abs < total; abs++) rows.push(itemAt(abs));
  const levelRowId = (level: number): string => `${baseId}-level-${level}`;
  /** The expander controls the level rows that exist: no idref ever dangles. */
  const drawnLevelIds = rows
    .filter((item) => item.kind === "level")
    .map((item) => levelRowId(item.level))
    .join(" ");

  const onRowsInView = useCallback((from: number, to: number): void => {
    setView((v) => (v.first === from && v.last === to ? v : { first: from, last: to }));
  }, []);

  // Focus requested by a key (expand, collapse, extend, Alt+T) lands in the commit that draws its row. The request
  // lives for that one pass: a row that is not drawn never pulls focus on a later, unrelated render (§3.4.3).
  useLayoutEffect(() => {
    const want = focusNext.current;
    if (want === null) return;
    focusNext.current = null;
    const row =
      want.level === null
        ? `tr[data-bar="${want.bar}"][data-kind="bar"]`
        : `tr[data-bar="${want.bar}"][data-level="${want.level}"]`;
    const tr = shell.current?.querySelector<HTMLElement>(row);
    const target =
      tr?.querySelector<HTMLElement>(`[data-cv-c="${want.col}"]`) ??
      tr?.querySelector<HTMLElement>("[data-cv-c]");
    target?.focus();
    extending.current = false;
    if (arrival.current && target !== undefined && target !== null)
      say(SAY.tableRow(want.bar + 1, n));
    arrival.current = false;
  });

  const expand = (bar: number, fromCol: number): void => {
    const count = levelCount(series, bar);
    if (count === 0) return;
    expandCol.current = fromCol;
    setExpanded(bar);
    // In the new order the bar keeps its index and its levels follow it, so they are drawn and focus can land.
    setView({ first: bar, last: bar + 1 });
    focusNext.current = { bar, level: 0, col: TIME_COL };
    say(SAY.expanded(count));
  };

  /** Collapses the open bar; focus returns to it only when focus was on it or its levels. */
  const collapse = (refocus: boolean): void => {
    if (expanded === null) return;
    setExpanded(null);
    if (refocus) focusNext.current = { bar: expanded, level: null, col: expandCol.current };
    say(SAY.collapsed);
  };

  const toggleSelected = (bar: number): void => {
    const next = new Set(selected);
    if (next.has(bar)) next.delete(bar);
    else next.add(bar);
    anchor.current = bar;
    setSelected(next);
    say(next.has(bar) ? SAY.selected(next.size) : SAY.deselected);
  };

  const extendTo = (bar: number, col: number): void => {
    const lo = Math.min(anchor.current, bar);
    const hi = Math.max(anchor.current, bar);
    const next = new Set<number>();
    for (let i = lo; i <= hi; i++) next.add(i);
    setSelected(next);
    extending.current = true;
    focusNext.current = { bar, level: null, col };
    setView({ first: absOf(bar), last: absOf(bar) });
    say(SAY.selected(next.size));
  };

  /** `Ctrl+C` on any body row: the grid's copy key (E11-D04 §17.1). */
  const onCopyKey = (event: KeyboardEvent<HTMLTableRowElement>): boolean => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "c")
      return false;
    // A text selection inside a cell copies that text, as the browser's Ctrl+C does (E11-D04 §8.3).
    if ((window.getSelection()?.toString() ?? "") !== "") return true;
    event.preventDefault();
    const bars = selected.size > 0 ? [...selected].sort((a, b) => a - b) : [cursor];
    const tsv = orNotAvailable(() => buildTsv(series, bars, expanded, cvd), null);
    if (tsv === null) {
      say(SAY.copyFailed);
      return true;
    }
    void writeClipboard(tsv.text).then(
      () =>
        say(
          tsv.capped ? SAY.copiedCapped(tsv.rows, bars.length) : SAY.copied(tsv.rows, tsv.columns),
        ),
      () => say(SAY.copyFailed), // the OS refused: nothing was copied, and the user hears so
    );
    return true;
  };

  /** `Ctrl+A`: every loaded bar (the copy takes the first `TSV_ROW_CAP`). */
  const onSelectAllKey = (event: KeyboardEvent<HTMLTableRowElement>): boolean => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "a")
      return false;
    event.preventDefault();
    const all = new Set<number>();
    for (let i = 0; i < n; i++) all.add(i);
    setSelected(all);
    say(SAY.selected(n));
    return true;
  };

  /** On a level row, `Esc` (or `←` on its price cell) collapses back to the column the levels opened from. */
  const onLevelKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
    const plain = !event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey;
    if (plain && event.key === "Escape") {
      event.preventDefault();
      collapse(true);
    } else if (plain && event.key === "ArrowLeft" && colOf(event.target) === TIME_COL) {
      // The level's price cell sits in the time column: ← there leaves the levels for their bar.
      event.preventDefault();
      collapse(true);
    }
  };

  const onRowKeyDown = (item: Item, event: KeyboardEvent<HTMLTableRowElement>): void => {
    if (onCopyKey(event) || onSelectAllKey(event) || event.altKey || event.metaKey) return;
    if (item.kind === "level") {
      onLevelKeyDown(event);
      return;
    }
    const plain = !event.ctrlKey && !event.shiftKey;
    const col = colOf(event.target);
    const open = expanded === item.bar;
    /** Collapsing from the open bar's own row keeps focus on the cell the key came from. */
    const collapseHere = (): void => {
      expandCol.current = col;
      collapse(true);
    };
    if (plain && event.key === "Enter") {
      event.preventDefault();
      if (open) collapseHere();
      else expand(item.bar, col);
    } else if (plain && event.key === "ArrowRight" && col === TIME_COL && !open) {
      if (levelCount(series, item.bar) === 0) return; // nothing to expand: → moves on, as in any grid
      event.preventDefault();
      expand(item.bar, col);
    } else if (plain && event.key === "ArrowLeft" && col === TIME_COL && open) {
      event.preventDefault();
      collapseHere();
    } else if (plain && event.key === " ") {
      event.preventDefault();
      toggleSelected(item.bar);
    } else if (
      event.shiftKey &&
      !event.ctrlKey &&
      (event.key === "ArrowUp" || event.key === "ArrowDown")
    ) {
      event.preventDefault();
      extendTo(clamp(item.bar + (event.key === "ArrowUp" ? -1 : 1), 0, lastBar), col);
    } else if (plain && event.key === "Escape") {
      event.preventDefault();
      if (selected.size > 0) {
        setSelected(new Set());
        say(SAY.deselected);
      } else if (expanded !== null) {
        // From another bar's row, collapsing leaves focus where the user is (code lens r1 m1).
        if (open) collapseHere();
        else collapse(false);
      } else {
        onExit?.();
      }
    }
  };

  // The cursor follows focus; the window recentres on it so keyboard travel never leaves the drawn rows. Any move
  // that is not a Shift extension carries the selection anchor with it (code lens r1 M1).
  const onFocus = (event: FocusEvent<HTMLTableRowElement>): void => {
    const tr = (event.target as Element).closest?.("tr[data-bar]");
    if (tr === null || tr === undefined) return;
    const bar = Number(tr.getAttribute("data-bar"));
    if (bar !== cursor) setCursor(bar);
    if (!extending.current) anchor.current = bar;
    // `aria-rowindex` counts the header row and from 1: the body's first row is 2.
    const abs = Number(tr.getAttribute("aria-rowindex")) - 2;
    if (abs - first < WINDOW_BUFFER / 2 || last - abs < WINDOW_BUFFER / 2)
      setView({ first: abs, last: abs });
  };

  const columns: TableColumn<Item>[] = [EXPANDER_HEADER, ...BAR_HEADERS].map((header, i) => ({
    id: header,
    header,
    cell: () => "",
    minWidthEm: i === 0 ? 3 : 6,
    ...(i >= 2 ? { align: "end" as const } : {}),
  }));

  const renderRow = (item: Item, grid: TableRowContext): JSX.Element => {
    if (item.kind === "level") {
      const fields = levels[item.level];
      return (
        <LevelRow
          item={item}
          grid={grid}
          id={levelRowId(item.level)}
          describedById={`${levelRowId(item.level)}-at`}
          fields={fields}
          levels={levelRows}
          barTime={formatBarTimeFull(series.candles.time[item.bar] ?? 0)}
          onKeyDown={onRowKeyDown}
          onFocus={onFocus}
        />
      );
    }
    const i = item.bar;
    const f: BarFields | null = orNotAvailable(() => barFields(series, i), null);
    const timeUs = series.candles.time[i] ?? 0;
    const count = levelCount(series, i);
    const open = expanded === i;
    const isSelected = selected.has(i);
    const cvdText = f === null ? undefined : orNotAvailable(() => cvdAt(series, cvd, i), undefined);
    const num = (k: number, text: string): JSX.Element => (
      <td {...grid.cellProps(k, { numeric: true })}>
        {grid.label(k)}
        {text}
      </td>
    );
    const price = (pick: (bar: BarFields) => string): string =>
      f === null ? NOT_AVAILABLE : displayDecimal(pick(f));
    const signed = (value: string | undefined): string =>
      value === undefined ? NOT_AVAILABLE : signedDecimal(value);
    return (
      <tr
        {...grid.rowProps}
        data-bar={i}
        data-kind="bar"
        aria-selected={isSelected}
        aria-current={cursor === i ? "true" : undefined}
        onKeyDown={(e) => onRowKeyDown(item, e)}
        onFocus={onFocus}
      >
        <td {...grid.cellProps(0)}>
          {count > 0 ? (
            <button
              type="button"
              tabIndex={-1}
              className="cv-chart-table__expander cv-focus-ring"
              aria-label={open ? collapseName(count) : expandName(count)}
              aria-expanded={open}
              aria-controls={open && drawnLevelIds !== "" ? drawnLevelIds : undefined}
              onClick={() => (open ? collapse(true) : expand(i, 0))}
            >
              <span aria-hidden="true">{`${isSelected ? "✓" : ""}${open ? "⌄" : "›"}`}</span>
            </button>
          ) : (
            <>
              <span aria-hidden="true">{`${isSelected ? "✓" : ""}${NOT_AVAILABLE}`}</span>
              <span className="cv-visually-hidden">{NO_FOOTPRINT}</span>
            </>
          )}
        </td>
        <th {...grid.cellProps(TIME_COL, { header: true })}>
          <span aria-hidden="true">{formatBarTime(timeUs, series.intervalMs)}</span>
          <span className="cv-visually-hidden">{formatBarTimeFull(timeUs)}</span>
        </th>
        {num(
          2,
          price((b) => b.open),
        )}
        {num(
          3,
          price((b) => b.high),
        )}
        {num(
          4,
          price((b) => b.low),
        )}
        {num(
          5,
          price((b) => b.close),
        )}
        {num(
          6,
          price((b) => b.volume),
        )}
        {num(7, signed(f?.delta))}
        {num(8, signed(cvdText))}
      </tr>
    );
  };

  return (
    <div ref={shell} className="cv-chart-table" data-scr="SCR-045">
      <Table<Item>
        columns={columns}
        rows={rows}
        rowKey={(item) => (item.kind === "bar" ? `bar:${item.bar}` : `level:${item.level}`)}
        caption={tableCaption(title, n)}
        grid
        reflow="grid"
        rowWindow={{ offset: first, total }}
        onRowsInView={onRowsInView}
        renderRow={renderRow}
        announce={say}
      />
    </div>
  );
}

interface LevelRowProps {
  readonly item: Extract<Item, { kind: "level" }>;
  readonly grid: TableRowContext;
  readonly id: string;
  readonly describedById: string;
  readonly fields: LevelFields | undefined;
  readonly levels: number;
  readonly barTime: string;
  readonly onKeyDown: (item: Item, event: KeyboardEvent<HTMLTableRowElement>) => void;
  readonly onFocus: (event: FocusEvent<HTMLTableRowElement>) => void;
}

/**
 * One footprint level of the expanded bar as its own grid row (E11-D04 §6.1): the `05` §6.3 columns price (the row
 * header, in the time column), bid, ask, delta and imbalance, each cell led by its column's name because the bar
 * columns' headers do not name them. The row's first cell says "Level k of N, bar <time>" and describes the price
 * cell. No `aria-level`: ARIA allows it on treegrid rows only, and CMP-049 draws a grid (a recorded deviation until
 * CMP-049 offers a treegrid role).
 */
function LevelRow(props: LevelRowProps): JSX.Element {
  const { item, grid, id, describedById, fields, levels, barTime, onKeyDown, onFocus } = props;
  const [priceH, bidH, askH, deltaH, imbalanceH] = LEVEL_HEADERS;
  const cell = (label: string, text: string): JSX.Element[] => [
    <span key="l" className="cv-chart-table__level-label">
      {label}
    </span>,
    <span key="v">{` ${text}`}</span>,
  ];
  const show = (pick: (l: LevelFields) => string, signed = false): string =>
    fields === undefined
      ? NOT_AVAILABLE
      : signed
        ? signedDecimal(pick(fields))
        : displayDecimal(pick(fields));
  return (
    <tr
      {...grid.rowProps}
      className={`${grid.rowProps.className} cv-chart-table__level`}
      id={id}
      data-bar={item.bar}
      data-kind="level"
      data-level={item.level}
      onKeyDown={(e) => onKeyDown(item, e)}
      onFocus={onFocus}
    >
      <td {...grid.cellProps(0)}>
        <span id={describedById} className="cv-visually-hidden">
          {levelPosition(item.level + 1, levels, barTime)}
        </span>
      </td>
      <th {...grid.cellProps(TIME_COL, { header: true, describedBy: describedById })}>
        {cell(
          priceH,
          show((l) => l.price),
        )}
      </th>
      <td {...grid.cellProps(2, { numeric: true })}>
        {cell(
          bidH,
          show((l) => l.bid),
        )}
      </td>
      <td {...grid.cellProps(3, { numeric: true })}>
        {cell(
          askH,
          show((l) => l.ask),
        )}
      </td>
      <td {...grid.cellProps(4, { numeric: true })}>
        {cell(
          deltaH,
          show((l) => l.delta, true),
        )}
      </td>
      <td {...grid.cellProps(5, { span: 4 })}>
        {cell(imbalanceH, fields === undefined ? NOT_AVAILABLE : fields.imbalance)}
      </td>
    </tr>
  );
}
