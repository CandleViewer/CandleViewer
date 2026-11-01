/**
 * SCR-045, the chart's data-table alternative (E47-S01 C1/C2, #1316): CMP-049 in grid mode over the series the
 * chart is given (`ChartTableSeries`), windowed so only the drawn window (plus a buffer) is in the DOM at 100k bars.
 * Keys: CMP-049's grid keys (arrows, `Home`/`End` within the row, `Ctrl+Home`/`Ctrl+End`, `PageUp`/`PageDown`) and
 * E11-D04 §17.1's own: `Enter` expands the bar's footprint levels (one bar at a time), `Esc` clears the selection
 * then collapses, `Space` toggles a row's selection, `Shift+↑/↓` extends it, `Ctrl+C` copies the selection, or the
 * cursor row, as TSV through an injectable clipboard writer.
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
  levelsCaption,
  tableCaption,
} from "./copy";
import { displayDecimal, formatBarTime, formatBarTimeFull, signedDecimal } from "./format";
import {
  barCount,
  barFields,
  cvdAt,
  cvdPrefix,
  levelCount,
  levelsOf,
  type ChartTableSeries,
} from "./series";
import { sayToShell } from "./politeWriter";
import { buildTsv } from "./tsv";

/** Rows kept drawn beyond the cursor on each side: the "small buffer" (Gherkin 5). */
export const WINDOW_BUFFER = 30;

type Item = { readonly kind: "bar" | "levels"; readonly bar: number };

export interface ChartDataTableProps {
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
}

const defaultClipboard = (text: string): Promise<void> => navigator.clipboard.writeText(text);
const politeToShell = (text: string): void => sayToShell("polite", text);
const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi);

export function ChartDataTable(props: ChartDataTableProps): JSX.Element {
  const { series, title, focusOnOpen = false } = props;
  const say = props.say ?? politeToShell;
  const writeClipboard = props.writeClipboard ?? defaultClipboard;
  const n = barCount(series);
  const cvd = useMemo(() => cvdPrefix(series), [series]);
  const detailId = useId();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [cursor, setCursor] = useState(() =>
    clamp(props.initialBar ?? n - 1, 0, Math.max(n - 1, 0)),
  );
  const anchor = useRef(cursor);
  const [view, setView] = useState(() => ({ first: cursor, last: cursor }));
  const shell = useRef<HTMLDivElement>(null);
  const focusNext = useRef<{ bar: number; kind: Item["kind"] } | null>(
    focusOnOpen ? { bar: cursor, kind: "bar" } : null,
  );
  /** Alt+T's arrival line is said once, when the opening focus lands. */
  const arrival = useRef(focusOnOpen);

  const total = n + (expanded === null ? 0 : 1);
  const itemAt = (abs: number): Item =>
    expanded === null || abs <= expanded
      ? { kind: "bar", bar: abs }
      : abs === expanded + 1
        ? { kind: "levels", bar: expanded }
        : { kind: "bar", bar: abs - 1 };
  const absOf = (bar: number): number => (expanded !== null && bar > expanded ? bar + 1 : bar);
  const first = clamp(view.first - WINDOW_BUFFER, 0, Math.max(total - 1, 0));
  const last = clamp(view.last + WINDOW_BUFFER, 0, Math.max(total - 1, 0));
  const rows: Item[] = [];
  for (let abs = first; abs <= last && abs < total; abs++) rows.push(itemAt(abs));

  const onRowsInView = useCallback((from: number, to: number): void => {
    setView((v) => (v.first === from && v.last === to ? v : { first: from, last: to }));
  }, []);

  // Focus requested by a key (expand, collapse, Alt+T) lands once its row is drawn.
  useLayoutEffect(() => {
    const want = focusNext.current;
    if (want === null) return;
    const tr = shell.current?.querySelector<HTMLElement>(
      `tr[data-bar="${want.bar}"][data-kind="${want.kind}"]`,
    );
    if (tr === null || tr === undefined) return;
    focusNext.current = null;
    const target = tr.querySelector<HTMLElement>(want.kind === "bar" ? "th" : "td");
    target?.focus();
    if (arrival.current) say(SAY.tableRow(want.bar + 1, n));
    arrival.current = false;
  });

  const toggleExpand = (bar: number): void => {
    if (expanded === bar) {
      setExpanded(null);
      focusNext.current = { bar, kind: "bar" };
      say(SAY.collapsed);
    } else if (levelCount(series, bar) > 0) {
      setExpanded(bar);
      setView({ first: bar, last: bar + 1 }); // the levels row is drawn, so focus can land on it
      focusNext.current = { bar, kind: "levels" };
      say(SAY.expanded(levelCount(series, bar)));
    }
  };

  const toggleSelected = (bar: number): void => {
    const next = new Set(selected);
    if (next.has(bar)) next.delete(bar);
    else next.add(bar);
    anchor.current = bar;
    setSelected(next);
    say(next.has(bar) ? SAY.selected(next.size) : SAY.deselected);
  };

  const extendTo = (bar: number): void => {
    const lo = Math.min(anchor.current, bar);
    const hi = Math.max(anchor.current, bar);
    const next = new Set<number>();
    for (let i = lo; i <= hi; i++) next.add(i);
    setSelected(next);
    focusNext.current = { bar, kind: "bar" };
    setView({ first: absOf(bar), last: absOf(bar) });
    say(SAY.selected(next.size));
  };

  const onRowKeyDown = (item: Item, event: KeyboardEvent<HTMLTableRowElement>): void => {
    if (onCopyKey(event) || event.altKey || event.metaKey) return;
    const plain = !event.ctrlKey && !event.shiftKey;
    if (item.kind === "levels") {
      if (plain && event.key === "Escape") {
        event.preventDefault();
        toggleExpand(item.bar);
      }
      return;
    }
    if (plain && event.key === "Enter") {
      event.preventDefault();
      toggleExpand(item.bar);
    } else if (plain && event.key === " ") {
      event.preventDefault();
      toggleSelected(item.bar);
    } else if (
      event.shiftKey &&
      !event.ctrlKey &&
      (event.key === "ArrowUp" || event.key === "ArrowDown")
    ) {
      event.preventDefault();
      extendTo(clamp(item.bar + (event.key === "ArrowUp" ? -1 : 1), 0, n - 1));
    } else if (plain && event.key === "Escape" && selected.size > 0) {
      event.preventDefault();
      setSelected(new Set());
      say(SAY.deselected);
    } else if (plain && event.key === "Escape" && expanded !== null) {
      event.preventDefault();
      toggleExpand(expanded);
    }
  };

  /** `Ctrl+C` on any body row: the grid's copy key (E11-D04 §17.1). */
  const onCopyKey = (event: KeyboardEvent<HTMLTableRowElement>): boolean => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "c")
      return false;
    // A text selection inside a cell copies that text, as the browser's Ctrl+C does (E11-D04 §8.3).
    if ((window.getSelection()?.toString() ?? "") !== "") return true;
    event.preventDefault();
    const bars = selected.size > 0 ? [...selected].sort((a, b) => a - b) : [cursor];
    const tsv = buildTsv(series, bars, expanded, cvd);
    void writeClipboard(tsv.text).then(
      () =>
        say(
          tsv.capped ? SAY.copiedCapped(tsv.rows, bars.length) : SAY.copied(tsv.rows, tsv.columns),
        ),
      () => undefined, // the OS refused: nothing was copied, nothing is said
    );
    return true;
  };

  // The cursor follows focus; the window recentres on it so keyboard travel never leaves the drawn rows.
  const onFocus = (event: FocusEvent<HTMLTableRowElement>): void => {
    const tr = (event.target as Element).closest?.("tr[data-bar]");
    if (tr === null || tr === undefined) return;
    const bar = Number(tr.getAttribute("data-bar"));
    if (bar !== cursor) setCursor(bar);
    const abs = absOf(bar);
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
    if (item.kind === "levels")
      return (
        <LevelsRow
          item={item}
          grid={grid}
          span={columns.length}
          id={detailId}
          series={series}
          onKeyDown={onRowKeyDown}
          onFocus={onFocus}
        />
      );
    const i = item.bar;
    const f = barFields(series, i);
    const levels = levelCount(series, i);
    const open = expanded === i;
    const isSelected = selected.has(i);
    const cvdText = cvdAt(series, cvd, i);
    const num = (k: number, text: string): JSX.Element => (
      <td {...grid.cellProps(k, { numeric: true })}>
        {grid.label(k)}
        {text}
      </td>
    );
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
          {levels > 0 ? (
            <button
              type="button"
              tabIndex={-1}
              className="cv-chart-table__expander"
              aria-label={open ? collapseName(levels) : expandName(levels)}
              aria-expanded={open}
              aria-controls={open ? detailId : undefined}
              onClick={() => toggleExpand(i)}
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
        <th {...grid.cellProps(1, { header: true })}>
          <span aria-hidden="true">{formatBarTime(f.timeUs, series.intervalMs)}</span>
          <span className="cv-visually-hidden">{formatBarTimeFull(f.timeUs)}</span>
        </th>
        {num(2, displayDecimal(f.open))}
        {num(3, displayDecimal(f.high))}
        {num(4, displayDecimal(f.low))}
        {num(5, displayDecimal(f.close))}
        {num(6, displayDecimal(f.volume))}
        {num(7, f.delta === undefined ? NOT_AVAILABLE : signedDecimal(f.delta))}
        {num(8, cvdText === undefined ? NOT_AVAILABLE : signedDecimal(cvdText))}
      </tr>
    );
  };

  return (
    <div ref={shell} className="cv-chart-table" data-scr="SCR-045">
      <Table<Item>
        columns={columns}
        rows={rows}
        rowKey={(item) => `${item.kind}:${item.bar}`}
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

interface LevelsRowProps {
  readonly item: Item;
  readonly grid: TableRowContext;
  readonly span: number;
  readonly id: string;
  readonly series: ChartTableSeries;
  readonly onKeyDown: (item: Item, event: KeyboardEvent<HTMLTableRowElement>) => void;
  readonly onFocus: (event: FocusEvent<HTMLTableRowElement>) => void;
}

/** The expanded bar's footprint levels: one merged grid cell holding a semantic table (`05` §6.3's columns). */
function LevelsRow({
  item,
  grid,
  span,
  id,
  series,
  onKeyDown,
  onFocus,
}: LevelsRowProps): JSX.Element {
  const levels = levelsOf(series, item.bar);
  const high = levels[0]?.price ?? "0";
  const low = levels[levels.length - 1]?.price ?? "0";
  return (
    <tr
      {...grid.rowProps}
      id={id}
      data-bar={item.bar}
      data-kind="levels"
      onKeyDown={(e) => onKeyDown(item, e)}
      onFocus={onFocus}
    >
      <td {...grid.cellProps(0, { span })}>
        <table className="cv-chart-table__levels">
          <caption>
            {levelsCaption(levels.length, displayDecimal(high), displayDecimal(low))}
          </caption>
          <thead>
            <tr>
              {LEVEL_HEADERS.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {levels.map((l) => (
              <tr key={l.price}>
                <th scope="row">{displayDecimal(l.price)}</th>
                <td>{displayDecimal(l.bid)}</td>
                <td>{displayDecimal(l.ask)}</td>
                <td>{signedDecimal(l.delta)}</td>
                <td>{l.imbalance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </td>
    </tr>
  );
}
