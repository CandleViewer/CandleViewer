/**
 * SCR-140's recorded-symbols grid (E16-D02 §1, §4, §5, §6.2, §6.3, §9.1, §10; E16-D06 KB-02, FM-01
 * to FM-06, T2-01, T2-02; BQ-9, BQ-10): the symbol search and the FilterBar's chips, then CMP-049 in
 * grid mode over #5146's `renderRow`, one CMP-177 row per symbol, sortable by Symbol, Since and Size,
 * on D02 §1's column plan for its width (the narrow seven below the nine's 72 em). Nothing re-sorts
 * while the page is open: values change in place, a new row joins the end. Stop opens its
 * confirmation; Keep recording (a lingering row, or the Why? popover) and Record again add the symbol
 * at once with its own settings, pessimistically, the action busy meanwhile. Every T2 press, refusal
 * and grid line is said once, politely, through the page's announcer (`say`), which the
 * GatedAnnounceProvider routes the atoms' presses to; a refusal of a row's add shows in the grid's echo
 * at the point of action. A settled search or a chip change says how many rows it shows when that
 * changed, joined with the bar's own sentence; with none shown, CMP-026 `filtered-empty` offers Clear
 * filters.
 */
import { useCallback, useEffect, useRef, useState, type JSX, type RefObject } from "react";
import {
  EmptyState,
  FilterBar,
  GatedAnnounceProvider,
  RecorderStatusRow,
  SearchBox,
  Table,
  recorderStatusColumns,
  type FilterBarFilter,
  type RecorderStatusRowData,
  type TableRowContext,
} from "@candleviewer/ui";
import { reportRecorder } from "./analytics";
import {
  DEFAULT_DEPTH,
  DEFAULT_RETENTION_DAYS,
  DEFAULT_STREAMS,
  FILTER_FIELDS,
  nextOrder,
  rowData,
  rowMatches,
  type GridOrder,
  type GridSort,
  type RowContext,
} from "./grid";
import type { RecorderRow } from "./model";
import type { RecordedSymbol } from "./model/types";
import { fill } from "./copy";
import { PAGE_TEXT } from "./pageCopy";
import {
  recorderApi,
  type AddRecordedSymbolBody,
  type AddedRecordedSymbol,
  type ApiResult,
} from "./recorderApi";
import { refusalText } from "./refusal";
import { StopDialog } from "./StopDialog";
import { useStepUpHost } from "./stepUpHost";

const COLUMNS = recorderStatusColumns();
const NARROW_COLUMNS = recorderStatusColumns({ narrow: true });
const widthEm = (columns: typeof COLUMNS): number =>
  columns.reduce((sum, column) => sum + (column.minWidthEm ?? 0), 0);
/** D02 §1's plans: the nine columns' 72 em (1152 px at 16 px), the narrow seven's 62 em (992 px). */
const WIDE_EM = widthEm(COLUMNS);
const NARROW_EM = widthEm(NARROW_COLUMNS);
/** A query settles this long after its last keystroke (CMP-048's rest, D02F): then the count is said once. */
export const QUERY_SETTLE_MS = 500;

/**
 * D02 §1's column plan for the grid's width (D-5309-03): the nine columns from their 72 em; between that and the
 * narrow seven's 62 em, those seven (Since and Depth are the row detail's); below 62 em the nine again, so CMP-049
 * stacks them into cards that drop no field. Measured in `em` of the host's font (zoom and the in-app text scale),
 * as CMP-049's reflow is; without ResizeObserver, the nine.
 */
function useNarrowPlan(
  host: RefObject<HTMLDivElement>,
  probe: RefObject<HTMLSpanElement>,
): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const node = host.current;
    if (node === null || typeof ResizeObserver === "undefined") return undefined;
    let width = 0;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) if (entry.target === node) width = entry.contentRect.width;
      if (width <= 0) return;
      const fontPx = parseFloat(getComputedStyle(node).fontSize);
      if (!Number.isFinite(fontPx) || fontPx <= 0) return;
      setNarrow(width < WIDE_EM * fontPx && width >= NARROW_EM * fontPx);
    });
    observer.observe(node);
    if (probe.current !== null) observer.observe(probe.current);
    return () => observer.disconnect();
  }, [host, probe]);
  return narrow;
}

/** The query as it rests: `query` once no keystroke has changed it for QUERY_SETTLE_MS. */
function useSettled(query: string): string {
  const [settled, setSettled] = useState(query);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(query), QUERY_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [query]);
  return settled;
}

/** "1 of 5 symbols." (PROPOSED, owner E16-D02); none shown, the deck's filter class, heading then cause. */
const shownLine = (shown: number, total: number): string =>
  shown === 0
    ? `${PAGE_TEXT.noMatch}. ${PAGE_TEXT.noMatchCause}`
    : fill(total === 1 ? PAGE_TEXT.shownOfOne : PAGE_TEXT.shownOf, {
        "{shown}": shown,
        "{total}": total,
      });

/** A 1 em box the plan's observer watches, so a font-size change at the same width measures again. */
const EM_PROBE = {
  position: "absolute",
  inlineSize: "1em",
  blockSize: 0,
  overflow: "hidden",
  visibility: "hidden",
  pointerEvents: "none",
} as const;

/** What a write changed, for the page to merge or read again. */
export type GridWrite =
  | { readonly kind: "added"; readonly row: AddedRecordedSymbol }
  | { readonly kind: "stopped"; readonly symbol: string };

export interface RecorderGridProps {
  /** The model's rows (BQ-8's states), in the server's order. */
  readonly rows: readonly RecorderRow[];
  readonly context: RowContext;
  /** REST's rows by symbol: a write's id and a re-add's streams. */
  readonly listed: ReadonlyMap<string, RecordedSymbol>;
  /** When the newest `recorder` frame was read (a refused stop waits for the next). */
  readonly frameAtMs: number | null;
  readonly filters: readonly FilterBarFilter[];
  readonly onFiltersChange: (next: readonly FilterBarFilter[]) => void;
  readonly query: string;
  readonly onQueryChange: (next: string) => void;
  readonly sort: GridSort | undefined;
  readonly onSortChange: (next: GridSort) => void;
  /** The first reads are in flight: skeleton rows, `aria-busy` (D02 §3.1). */
  readonly loading?: boolean;
  /** The page's announcer: once, politely (E16-D06 SR-14, R-5). */
  readonly say: (text: string) => void;
  readonly onWritten?: (write: GridWrite) => void;
  /** The row detail (#485/#486 BQ-6's `openRowDetail`); without it the symbol is text. */
  readonly onOpenDetail?: ((symbol: string) => void) | undefined;
  /** Reads the list again (a step-up's re-send got no answer). */
  readonly readBack: () => unknown;
}

/** A re-add keeps the row's own settings, so it changes no kept data's retention (`22`: no step-up). */
function againBody(row: RecorderRow, listed: RecordedSymbol | undefined): AddRecordedSymbolBody {
  return {
    symbol: row.symbol,
    streams: listed?.streams ?? [...DEFAULT_STREAMS],
    depth: row.depth ?? DEFAULT_DEPTH,
    pinned: row.pinned,
    retention_days: row.pinned ? null : (row.retentionDays ?? DEFAULT_RETENTION_DAYS),
  };
}

const notListed = (status: number): ApiResult<null> => ({
  ok: false,
  status,
  code: "not_found",
  data: null,
  stepUp: null,
  route: { kind: "t4", code: "not_found", field: null, status },
});

export function RecorderGrid({
  rows,
  context,
  listed,
  frameAtMs,
  filters,
  onFiltersChange,
  query,
  onQueryChange,
  sort,
  onSortChange,
  loading = false,
  say,
  onWritten,
  onOpenDetail,
  readBack,
}: RecorderGridProps): JSX.Element {
  const order = useRef<GridOrder | null>(null);
  order.current = nextOrder(order.current, rows, sort);
  const bySymbol = new Map(rows.map((row) => [row.symbol, row]));
  const shown = order.current.symbols.flatMap((symbol) => {
    const row = bySymbol.get(symbol);
    const data =
      row === undefined || !rowMatches(row, filters, query) ? null : rowData(row, context);
    return data === null ? [] : [data];
  });
  const host = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const narrow = useNarrowPlan(host, probe);

  // The result count (D-5309-02): once per settled query or chip change, when the rows shown changed. The bar's own
  // sentence of a chip change is held for it, so the two are one line and never overwrite each other in the shell's
  // one polite region; a sentence no change follows (a refused press) is said on its own. What "changed" means is
  // judged against the rows as they are when the selection changes (C-5309-d01): the previous selection counted again
  // on today's rows, so rows that loaded or joined since it was counted, the first load included, are in it.
  const settled = useSettled(query);
  const selection = `${settled.trim().toUpperCase()}\n${filters.map((f) => `${f.field}=${f.value}`).join("&")}`;
  const total = rows.filter((row) => row.reason !== null).length;
  const counted = useRef<{
    readonly selection: string;
    readonly query: string;
    readonly filters: readonly FilterBarFilter[];
  } | null>(null);
  const barSaid = useRef<string | null>(null);
  const sayForBar = useCallback(
    (text: string): void => {
      barSaid.current = text;
      queueMicrotask(() => {
        if (barSaid.current !== text) return; // joined with the count by now
        barSaid.current = null;
        say(text);
      });
    },
    [say],
  );
  const latest = useRef({ rows, shown: shown.length, total, say, query, filters });
  latest.current = { rows, shown: shown.length, total, say, query, filters };
  useEffect(() => {
    const now = latest.current;
    const was = counted.current;
    counted.current = { selection, query: now.query, filters: now.filters };
    const sentence = barSaid.current;
    barSaid.current = null;
    const changed =
      was !== null &&
      was.selection !== selection &&
      now.rows.filter((row) => rowMatches(row, was.filters, was.query)).length !== now.shown;
    const words = [sentence, changed ? shownLine(now.shown, now.total) : null].filter(Boolean);
    if (words.length > 0) now.say(words.join(" "));
  }, [selection]);

  const clearFilters = (): void => {
    onFiltersChange([]);
    onQueryChange("");
    // The empty state's button goes with the rows' return: focus to the search, never `<body>`.
    host.current?.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
  };
  const filtering = filters.length > 0 || query.trim() !== "";

  const [stopFor, setStopFor] = useState<RecorderRow | null>(null);
  const stopRow = stopFor === null ? null : (bySymbol.get(stopFor.symbol) ?? stopFor);
  const adding = useRef(new Set<string>());
  /** The rows whose add is in flight: their action is busy (C-5309-13), a second press sends nothing. */
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const stepUp = useStepUpHost(readBack, PAGE_TEXT.grid);

  /** Keep recording and Record again: `addRecordedSymbol`, which gains `manual` (22), one at a time per row. */
  async function addAgain(symbol: string, refuse: (text: string) => void): Promise<void> {
    const row = bySymbol.get(symbol);
    if (row === undefined || adding.current.has(symbol)) return;
    adding.current.add(symbol);
    setBusy(new Set(adding.current));
    await stepUp.start(async () => {
      const res = await recorderApi.add(againBody(row, listed.get(symbol)));
      adding.current.delete(symbol);
      setBusy(new Set(adding.current));
      stepUp.route("addRecordedSymbol", res, (answer) => {
        if (answer.ok && answer.data !== null) onWritten?.({ kind: "added", row: answer.data });
        else if (answer.route !== null) refuse(refusalText(answer.route, "add"));
      });
    });
  }

  /** The stop: by the row's id, read again from the whole list when the frame named a row REST had not. */
  async function stop(row: RecorderRow): Promise<ApiResult<null>> {
    let id = row.id ?? listed.get(row.symbol)?.id ?? null;
    if (id === null) {
      const page = await recorderApi.listAll();
      const items: readonly RecordedSymbol[] = page.data?.items ?? [];
      id = items.find((item) => item.symbol === row.symbol)?.id ?? null;
      if (id === null) return page.ok ? notListed(404) : notListed(page.status);
    }
    return recorderApi.remove(id);
  }

  const actions = (symbol: string, grid: TableRowContext): Partial<RecorderStatusRowData> => ({
    onStop: () => {
      const row = bySymbol.get(symbol);
      if (row !== undefined) setStopFor(row);
    },
    onKeepRecording: () => void addAgain(symbol, grid.refuse),
    onRecordAgain: () => void addAgain(symbol, grid.refuse),
    // D02 §12: a Why? opening is a review of what auto-record added.
    onWhyOpen: () => reportRecorder({ name: "recorder.auto_review_opened", source: "why" }),
    ...(onOpenDetail === undefined ? {} : { onOpenDetail: () => onOpenDetail(symbol) }),
    actionBusy: busy.has(symbol),
  });

  return (
    <GatedAnnounceProvider announce={say}>
      <div ref={host} data-cv-plan="" style={{ position: "relative", minWidth: 0 }}>
        <span ref={probe} aria-hidden="true" style={EM_PROBE} />
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "var(--space-inset-sm)",
            marginBlockEnd: "var(--space-stack-sm)",
          }}
        >
          <SearchBox
            label={PAGE_TEXT.search}
            value={query}
            onChange={(value) => onQueryChange(value)}
            onClear={() => onQueryChange("")}
          />
          <FilterBar
            fields={FILTER_FIELDS}
            value={filters}
            onChange={onFiltersChange}
            announce={sayForBar}
          />
        </div>
        <Table
          columns={narrow ? NARROW_COLUMNS : COLUMNS}
          rows={shown}
          rowKey={(data) => data.symbol}
          caption={PAGE_TEXT.grid}
          captionHidden
          sort={sort}
          onSortChange={onSortChange}
          loading={loading}
          announce={say}
          {...(filtering && total > 0
            ? {
                emptyState: (
                  <EmptyState
                    variant="filtered-empty"
                    title={PAGE_TEXT.noMatch}
                    description={PAGE_TEXT.noMatchCause}
                    actions={[{ label: PAGE_TEXT.clearFilters, onClick: clearFilters }]}
                  />
                ),
              }
            : {})}
          renderRow={(data, grid) => (
            <RecorderStatusRow
              {...data}
              {...actions(data.symbol, grid)}
              variant="table"
              grid={grid}
              narrow={narrow}
            />
          )}
        />
      </div>
      {stepUp.gate}
      <StopDialog
        row={stopRow}
        policy={context.policy}
        frameAtMs={frameAtMs}
        stale={context.stale}
        stop={stop}
        onStopped={(row) => {
          reportRecorder({
            name: "recorder.symbol_stopped",
            symbol: row.symbol,
            reason: row.reason ?? "manual",
          });
          setStopFor(null);
          onWritten?.({ kind: "stopped", symbol: row.symbol });
        }}
        onClose={() => setStopFor(null)}
      />
    </GatedAnnounceProvider>
  );
}
