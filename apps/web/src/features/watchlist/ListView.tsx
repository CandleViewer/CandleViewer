/**
 * SCR-100's view of one list (E08-D07 §4.1–§4.6, §6): the CMP-049 grid of CMP-161 rows over the list's local-first
 * edits, its footer, its live window and its sort. The panel (`WatchlistPanel`) owns the header, the feed status and
 * the announcer; this view says through it.
 *
 * - Live window (D6): a list within the budget is wholly claimed; a longer one claims the window around the rows in
 *   view, moved only when a row in view (or the focused row) falls outside it, 300 ms after scrolling settles. The
 *   ticker hub decides when a change may start. The adds of one popover opening change it once (D36).
 * - Sort (D5): a pane view setting; a live-column sort re-ranks at most every 2 s and holds while the pointer or focus
 *   is in the grid or its footer ("Sort: 24h % · paused" and "Re-sort"); a list past the live budget has no live sort.
 * - Keys (§6.2): `Enter` activates through the sync-group port, `Del` removes with Undo, `Alt+↑/↓` moves in manual
 *   order, `Ctrl+C` copies, `Ctrl+F` focuses the filter, whose `Esc` clears it and returns to the grid. A T2 key
 *   changes nothing and says its reason once (§6.6), through the panel's gated announcement.
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type FocusEvent,
  type JSX,
} from "react";
import {
  Button,
  ColumnPicker,
  EmptyState,
  Menu,
  SearchBox,
  Table,
  WATCHLIST_DEFAULT_COLUMNS,
  WATCHLIST_OPTIONAL_COLUMNS,
  watchlistColumns,
  type ColumnPickerColumn,
  type MenuItem,
  type TableSort,
} from "@candleviewer/ui";
import { AddSymbolPopover } from "./AddSymbolPopover";
import { reportWatchlist } from "./analytics";
import { COPY, LIST_CAP } from "./copy";
import { isDelisted, type InstrumentFacts } from "./instruments";
import { createListEdits, type Watchlist, type WatchlistSaver } from "./listEdits";
import { coversView, liveWindow, SETTLE_MS, type ViewRange } from "./liveWindow";
import { LiveRow, isStale } from "./LiveRow";
import type { PaneSettingsPort, PanelHostPort, SyncGroupPort } from "./ports";
import { LIVE_SORT_MS, decodeSort, encodeSort, isLiveColumn, ranked } from "./sorting";
import { createStaleEpisode } from "./staleEpisode";
import { secondClock } from "./ticker/secondClock";
import type { HubState, TickerHub } from "./ticker/tickerHub";

/** `14` SCR-100 "Performance": the grid draws a window of the list past 60 rows. */
const VIRTUALIZE_ABOVE = 60;
/** The rows drawn of a windowed list: the rows in view and as many again around them. */
const DRAWN_ROWS = 60;
const OVERSCAN = 20;
/** D36: the adds of one opening change the live window when it closes or this long after the last add. */
const ADDS_SETTLE_MS = 2_000;
const NONE: ReadonlySet<string> = new Set();
const COLUMN_HEADERS = new Map(
  watchlistColumns([...WATCHLIST_DEFAULT_COLUMNS, ...WATCHLIST_OPTIONAL_COLUMNS]).map((c) => [
    c.id,
    c.header,
  ]),
);

const FOOTER: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-2)",
  padding: "var(--space-2) var(--space-panel-padding)",
  background: "var(--color-surface-canvas)",
  borderTop: "calc(var(--border-hairline) * 1px) solid var(--color-border-subtle)",
  color: "var(--color-text-secondary)",
};
const NOTE: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
const COUNT: CSSProperties = { ...NOTE, marginInlineStart: "auto" };
const FILTER: CSSProperties = { inlineSize: "12rem" };

const sameSet = (a: readonly string[], b: ReadonlySet<string>): boolean =>
  a.length === b.size && a.every((s) => b.has(s));

/** `ranking`'s order for the symbols still shown, then any shown since (added or unfiltered), at the end. */
function reconcile(ranking: readonly string[], shown: readonly string[]): readonly string[] {
  const set = new Set(shown);
  const kept = ranking.filter((s) => set.has(s));
  const placed = new Set(kept);
  return [...kept, ...shown.filter((s) => !placed.has(s))];
}

export interface ListViewProps {
  readonly list: Watchlist;
  readonly paneId: string;
  readonly api: WatchlistSaver;
  readonly hub: TickerHub | null;
  readonly hubState: HubState;
  readonly facts: InstrumentFacts;
  /** Disconnected (D4): rows demoted by the panel, no chip, cells described by the status. */
  readonly down: boolean;
  readonly statusId: string;
  /** No `workspaces:write` (D13): every write T2, described by one notice. */
  readonly readOnly: boolean;
  /** The id of that notice: the tabs' "+" points at it too (one notice, many pointers). */
  readonly noticeId: string;
  readonly syncGroup: SyncGroupPort;
  readonly panelHost: PanelHostPort;
  readonly paneSettings: PaneSettingsPort;
  readonly say: (text: string) => void;
  readonly sayAlert: (text: string) => void;
  readonly onCount: (count: number) => void;
  readonly onReload: () => void;
  /** SCR-101 (#4702 PR c): "Import a list" and the manager's other paths. */
  readonly managerHref: string;
}

export function ListView(props: ListViewProps): JSX.Element {
  const { list, paneId, hub, hubState, facts, down, readOnly, say, paneSettings } = props;
  const [edits] = useState(() => createListEdits(list, props.api));
  const state = useSyncExternalStore(edits.subscribe, edits.getState, edits.getState);
  const symbols = state.symbols;
  const name = list.name;
  const columns = state.columns.length > 0 ? state.columns : WATCHLIST_DEFAULT_COLUMNS;
  const ids = {
    notice: props.noticeId,
    cap: useId(),
    sortNote: useId(),
  };
  const root = useRef<HTMLDivElement>(null);

  const { onCount } = props;
  useEffect(() => onCount(symbols.length), [onCount, symbols.length]);

  // The filter (§4.2 Filtered): rows whose symbol holds the text, trimmed and case-insensitive; never saved.
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toUpperCase();
  const filtered = useMemo(
    () => (needle === "" ? symbols : symbols.filter((s) => s.includes(needle))),
    [symbols, needle],
  );
  // The count is said once per settled query (§4.2 Filtered): a change of the list meanwhile says nothing new.
  const countLine = useRef("");
  countLine.current =
    filtered.length === 0
      ? COPY.noMatch(name, filter.trim())
      : COPY.showing(filtered.length, symbols.length);
  useEffect(() => {
    if (needle === "") return undefined;
    const timer = setTimeout(() => say(countLine.current), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [needle, say]);

  // The live budget (D6) and what the hub holds.
  const live = hubState.live;
  const budget = hub?.budgetFor(paneId, symbols) ?? 0;
  const liveCount = symbols.reduce((n, s) => (live.has(s) ? n + 1 : n), 0);
  const wholly = symbols.length <= budget;
  const trading = useMemo(
    () => new Set(facts.snapshot.entries.map((entry) => entry.symbol)),
    [facts.snapshot.entries],
  );

  // Sort (D5): the pane's setting; a list past the live budget has no live sort (until C-11).
  const [sort, setSortState] = useState<TableSort | null>(() =>
    decodeSort(paneSettings.read(paneId).watchlist_sort),
  );
  const setSort = (next: TableSort | null): void => {
    setSortState(next);
    paneSettings.write(paneId, { watchlist_sort: encodeSort(next) });
  };
  const liveSortGated = !wholly;
  const effective = sort !== null && isLiveColumn(sort.columnId) && liveSortGated ? null : sort;
  const liveSort = effective !== null && isLiveColumn(effective.columnId);
  const read = useCallback((symbol: string) => hub?.store.get(symbol), [hub]);

  // The hold: the pointer or focus in the grid or its footer.
  const [pointerIn, setPointerIn] = useState(false);
  const [focusIn, setFocusIn] = useState(false);
  // Disconnected holds the order too (§4.2: "sort and moves held"): no value moves while none arrives.
  const held = pointerIn || focusIn || down;
  const heldRef = useRef(held);
  heldRef.current = held;
  const [ranking, setRanking] = useState<readonly string[] | null>(null);
  const [outOfDate, setOutOfDate] = useState(false);
  const rank = useCallback(() => ranked(filtered, effective, read), [filtered, effective, read]);
  const rankRef = useRef(rank);
  rankRef.current = rank;
  const shownRef = useRef<readonly string[]>([]);
  const liveKey = liveSort ? `${effective.columnId}:${effective.direction}` : "";
  useEffect(() => {
    if (liveKey === "") {
      setRanking(null);
      setOutOfDate(false);
      return undefined;
    }
    setRanking(rankRef.current());
    setOutOfDate(false);
    const timer = setInterval(() => {
      const next = rankRef.current();
      if (!heldRef.current) {
        setRanking(next);
        setOutOfDate(false);
      } else if (next.some((s, i) => shownRef.current[i] !== s)) setOutOfDate(true);
    }, LIVE_SORT_MS);
    return () => clearInterval(timer);
  }, [liveKey]);
  useEffect(() => {
    // The order re-ranks as soon as the hold ends.
    if (held || !outOfDate) return;
    setRanking(rankRef.current());
    setOutOfDate(false);
  }, [held, outOfDate]);
  const ordered = useMemo(
    () =>
      liveSort
        ? reconcile(ranking ?? filtered, filtered)
        : effective !== null
          ? ranked(filtered, effective, read)
          : filtered,
    [liveSort, ranking, filtered, effective, read],
  );
  shownRef.current = ordered;
  const paused = liveSort && held && outOfDate;

  // The rows in view (from the grid), settled 300 ms after the last change, and the focused row.
  const [view, setView] = useState<ViewRange | null>(null);
  const [settled, setSettled] = useState<ViewRange | null>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(settle.current), []);
  const onRowsInView = useCallback((first: number, last: number) => {
    setView({ first, last });
    clearTimeout(settle.current);
    settle.current = setTimeout(() => setSettled({ first, last }), SETTLE_MS);
  }, []);
  const [focusedSymbol, setFocusedSymbol] = useState<string | null>(null);
  const focusedAt = focusedSymbol === null ? -1 : ordered.indexOf(focusedSymbol);
  const focused = focusedAt < 0 ? null : focusedAt;

  // The adds of one popover opening, held out of the window until it closes or 2 s after the last add.
  const [addOpen, setAddOpen] = useState(false);
  const [batch, setBatch] = useState<ReadonlySet<string>>(NONE);
  const batchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(batchTimer.current), []);
  const endBatch = useCallback(() => {
    clearTimeout(batchTimer.current);
    setBatch(NONE);
  }, []);

  // The claim: the whole list within the budget, else the window; only Trading symbols (D27, `23` §5.2).
  const claimed = useRef<ReadonlySet<string>>(NONE);
  // What the claim reads, kept current; the effect runs when one of these facts changes (`claimKey`).
  const claimFacts = { wholly, budget, settled, focused, batch, trading, ordered, symbols, down };
  const facts$ = useRef(claimFacts);
  facts$.current = claimFacts;
  const claimKey = [
    down,
    wholly,
    budget,
    settled?.first,
    settled?.last,
    focused,
    [...batch].join(","),
    trading.size,
    ordered.join(","),
    symbols.join(","),
  ].join(";");
  useEffect(() => {
    const now = facts$.current;
    // Disconnected holds the window (§4.2): it moves, if it must, once the feed is back.
    if (hub === null || now.down) return;
    const wanted = (s: string | undefined): s is string =>
      s !== undefined && now.trading.has(s) && !now.batch.has(s);
    let next: readonly string[];
    if (now.wholly) next = now.symbols.filter(wanted);
    else {
      const at = new Set(now.ordered.flatMap((s, i) => (claimed.current.has(s) ? [i] : [])));
      const shown = now.settled ?? {
        first: 0,
        last: Math.min(now.ordered.length, now.budget) - 1,
      };
      const holds =
        claimed.current.size > 0 &&
        claimed.current.size <= now.budget &&
        shown.last >= shown.first &&
        coversView(at, shown, now.focused);
      if (holds) return;
      next = liveWindow(now.ordered.length, now.budget, now.settled, now.focused)
        .map((i) => now.ordered[i])
        .filter(wanted);
    }
    if (sameSet(next, claimed.current)) return;
    claimed.current = new Set(next);
    hub.claim(paneId, next);
  }, [hub, paneId, claimKey]);
  useEffect(
    () => () => {
      hub?.release(paneId);
      claimed.current = NONE;
    },
    [hub, paneId],
  );

  // The stale episode (D17): read on the shared clock's tick, said through the panel's announcer.
  const episode = useMemo(
    () =>
      createStaleEpisode({
        say,
        entered: () =>
          reportWatchlist({
            name: "data_confidence.state_entered",
            surface: "SCR-100",
            state: "stale",
          }),
      }),
    [say],
  );
  useEffect(() => () => episode.dispose(), [episode]);
  useEffect(() => episode.hold(down), [down, episode]);
  const tick = useRef<() => void>(() => undefined);
  tick.current = () => {
    if (hub === null || down) return;
    const now = secondClock.getSnapshot();
    episode.update(
      symbols.filter(
        (s) => live.has(s) && !isDelisted(facts.bySymbol.get(s)) && isStale(hub.store.get(s), now),
      ),
    );
  };
  useEffect(() => secondClock.subscribe(() => tick.current()), []);

  // Save failures (§4.2 Errors): rolled back; said once.
  const error = state.error;
  const sayError = useRef<(kind: "failed" | "conflict" | "refused") => void>(() => undefined);
  sayError.current = (kind) => {
    if (kind === "refused") props.sayAlert(COPY.notSent);
    else say(kind === "conflict" ? COPY.conflict(name) : COPY.saveFailed(name));
  };
  useEffect(() => {
    if (error !== null) sayError.current(error.kind); // one message per failure
  }, [error]);

  // Focus after Undo (FM-13): the first restored row.
  const focusNext = useRef<string | null>(null);
  useEffect(() => {
    const symbol = focusNext.current;
    if (symbol === null) return;
    focusNext.current = null;
    const cells = root.current?.querySelectorAll<HTMLElement>('[data-column="symbol"]') ?? [];
    const cell = [...cells].find((node) => node.textContent?.includes(symbol) === true);
    cell?.focus();
  });

  const gridTabStop = (): HTMLElement | null =>
    root.current?.querySelector<HTMLElement>('[role="grid"] [tabindex="0"]') ?? null;

  const write = readOnly ? COPY.writeReason : undefined;
  const moveReason = (symbol: string): { up?: string; down?: string } => {
    const one =
      write ??
      (needle !== "" ? COPY.reorderFiltered : effective !== null ? COPY.reorderSorted : undefined);
    if (one !== undefined) return { up: one, down: one };
    const at = symbols.indexOf(symbol);
    return {
      ...(at <= 0 ? { up: COPY.first } : {}),
      ...(at >= symbols.length - 1 ? { down: COPY.last } : {}),
    };
  };
  const move = (symbol: string, direction: "up" | "down"): void => {
    const reason = moveReason(symbol)[direction];
    if (reason !== undefined) return say(reason);
    const to = symbols.indexOf(symbol) + (direction === "up" ? -1 : 1);
    edits.move(symbol, to);
    say(COPY.moved(symbol, to + 1, symbols.length));
    reportWatchlist({
      name: "watchlist.reordered",
      watchlist_id: list.id,
      symbol,
      position: to + 1,
    });
  };
  const remove = (symbol: string): void => {
    if (write !== undefined) return say(write);
    edits.remove(symbol);
    say(COPY.removed(symbol));
    reportWatchlist({ name: "watchlist.symbol_removed", watchlist_id: list.id, symbol });
  };
  const undo = (): void => {
    const restored = edits.undo();
    focusNext.current = restored[0] ?? null;
  };
  const [active, setActive] = useState<string | null>(null);
  const activate = (symbol: string): void => {
    setActive(symbol);
    props.syncGroup.setSymbol(symbol);
    reportWatchlist({ name: "watchlist.symbol_activated", watchlist_id: list.id, symbol });
  };
  const copy = (symbol: string): void => {
    void navigator.clipboard?.writeText(symbol).catch(() => undefined);
  };
  const add = (symbol: string) => {
    const outcome = edits.add(symbol);
    if (outcome !== "added") return outcome;
    reportWatchlist({ name: "watchlist.symbol_added", watchlist_id: list.id, symbol });
    setBatch((held) => new Set([...held, symbol]));
    clearTimeout(batchTimer.current);
    batchTimer.current = setTimeout(endBatch, ADDS_SETTLE_MS);
    return outcome;
  };

  const rowActions = (symbol: string): MenuItem[] => {
    const delisted = isDelisted(facts.bySymbol.get(symbol));
    const gate = delisted ? { disabledReason: COPY.delisted } : {};
    const { panelHost } = props;
    const panels = panelHost.panels?.() ?? [];
    const reasons = moveReason(symbol);
    const items: MenuItem[] = [];
    const { openInNewChart, sendToPanel } = panelHost;
    if (openInNewChart !== undefined)
      items.push({
        id: "open",
        label: COPY.openInNewChart,
        onSelect: () => openInNewChart(symbol),
        ...gate,
      });
    if (sendToPanel !== undefined && panels.length > 0)
      items.push({
        id: "send",
        label: COPY.sendToPanel,
        items: panels.map((p) => ({
          id: `send-${p.id}`,
          label: p.name,
          onSelect: () => sendToPanel(symbol, p.id),
        })),
        ...gate,
      });
    items.push({ id: "copy", label: COPY.copySymbol, onSelect: () => copy(symbol) });
    items.push({
      id: "up",
      label: COPY.moveUp,
      onSelect: () => move(symbol, "up"),
      ...(reasons.up === undefined ? {} : { disabledReason: reasons.up }),
    });
    items.push({
      id: "down",
      label: COPY.moveDown,
      onSelect: () => move(symbol, "down"),
      ...(reasons.down === undefined ? {} : { disabledReason: reasons.down }),
    });
    items.push({
      id: "remove",
      label: COPY.removeFrom(name),
      onSelect: () => remove(symbol),
      ...(write === undefined ? {} : { disabledReason: write }),
    });
    return items;
  };

  // Columns (CMP-056): Symbol locked; the Status slot fixed, not listed. While a write reason is set the host
  // ignores the picker's changes, the menu staying open (#5146's hand-off).
  const pickerColumns: ColumnPickerColumn[] = [
    ...WATCHLIST_DEFAULT_COLUMNS,
    ...WATCHLIST_OPTIONAL_COLUMNS,
  ].map((id) => ({
    id,
    label: COLUMN_HEADERS.get(id) ?? id,
    visible: columns.includes(id),
    ...(id === "symbol" ? { lockedReason: COPY.symbolFixed } : {}),
  }));
  const onColumn = (id: string, visible: boolean): void => {
    if (write !== undefined || id === "symbol") return;
    const next = visible
      ? [...columns.filter((c) => c !== id), id]
      : columns.filter((c) => c !== id);
    edits.setColumns(next);
    reportWatchlist({
      name: "watchlist.column_changed",
      watchlist_id: list.id,
      column: id,
      visible,
    });
  };

  // The Sort menu (§4.1 footer): manual order, then each sortable column; live sorts T2 past the budget.
  const header =
    effective === null ? null : (COLUMN_HEADERS.get(effective.columnId) ?? effective.columnId);
  const sortItems: MenuItem[] = [
    {
      id: "manual",
      kind: "radio",
      label: COPY.sortManual,
      checked: effective === null,
      onSelect: () => setSort(null),
    },
    ...columns.map((id): MenuItem => ({
      id: `sort-${id}`,
      kind: "radio",
      label: COLUMN_HEADERS.get(id) ?? id,
      checked: effective?.columnId === id,
      onSelect: () =>
        setSort({
          columnId: id,
          direction:
            effective?.columnId === id && effective.direction === "ascending"
              ? "descending"
              : "ascending",
        }),
      ...(liveSortGated && isLiveColumn(id) ? { disabledReason: COPY.sortNeedsLive } : {}),
    })),
  ];

  const capped = symbols.length >= LIST_CAP;
  const addReason =
    write !== undefined
      ? { text: write, nodeId: ids.notice }
      : capped
        ? { text: COPY.capFull, nodeId: ids.cap }
        : undefined;
  const openAdd = (): void => {
    if (addReason !== undefined) return say(addReason.text);
    setAddOpen(true);
  };

  // Virtualised beyond 60 rows: the rows in view and as many again around them.
  const windowed = ordered.length > VIRTUALIZE_ABOVE;
  const offset = windowed
    ? Math.min(Math.max(0, (view?.first ?? 0) - OVERSCAN), Math.max(0, ordered.length - DRAWN_ROWS))
    : 0;
  const drawn = windowed ? ordered.slice(offset, offset + DRAWN_ROWS) : ordered;
  const order =
    effective === null
      ? COPY.manualOrder
      : COPY.sortedBy(header ?? effective.columnId, effective.direction);
  const notLiveDetail = (now: number): string =>
    hubState.waitingUntil !== null
      ? COPY.notLiveWait(hubState.waitingUntil - now)
      : COPY.notLiveShort(hub?.othersHolding(paneId, symbols) ?? 0);

  // Ctrl+F (§6.2): the footer's filter, from anywhere in the list's grid or footer. A listener on the view, not a
  // handler on a static element: the grid's own keys reach it as they bubble.
  useEffect(() => {
    const node = root.current;
    if (node === null) return undefined;
    const onKeyDown = (event: globalThis.KeyboardEvent): void => {
      if (event.defaultPrevented || event.altKey || event.shiftKey) return;
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "f") return;
      event.preventDefault();
      node.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
    };
    node.addEventListener("keydown", onKeyDown);
    return () => node.removeEventListener("keydown", onKeyDown);
  }, []);
  const onFocusIn = (event: FocusEvent<HTMLDivElement>): void => {
    setFocusIn(true);
    const row = event.target instanceof Element ? event.target.closest("tr[aria-rowindex]") : null;
    const at = Number(row?.getAttribute("aria-rowindex") ?? NaN) - 2;
    if (Number.isInteger(at) && at >= 0) setFocusedSymbol(ordered[at] ?? null);
  };
  const onFocusOut = (event: FocusEvent<HTMLDivElement>): void => {
    if (!event.currentTarget.contains(event.relatedTarget)) setFocusIn(false);
  };

  const empty =
    symbols.length === 0 ? (
      readOnly ? (
        <EmptyState title={COPY.emptyTitle} description={COPY.writeReason} />
      ) : (
        <EmptyState
          title={COPY.emptyTitle}
          description={COPY.emptyBody(name)}
          actions={[{ label: COPY.emptyAction, onClick: openAdd }]}
          link={{ label: COPY.importList, href: props.managerHref }}
        />
      )
    ) : (
      <EmptyState variant="filtered-empty" title={COPY.noMatch(name, filter.trim())} />
    );

  return (
    <div ref={root}>
      {readOnly ? (
        <p
          id={ids.notice}
          style={{ ...NOTE, padding: "var(--space-2) var(--space-panel-padding)" }}
        >
          {COPY.readOnly}
        </p>
      ) : null}
      <div
        onPointerEnter={() => setPointerIn(true)}
        onPointerLeave={() => setPointerIn(false)}
        onFocus={onFocusIn}
        onBlur={onFocusOut}
      >
        <Table<string>
          grid
          reflow="grid"
          caption={COPY.caption(name, symbols.length, order, needle !== "", paused)}
          captionHidden
          columns={watchlistColumns(columns, {
            item: (symbol: string) => ({ symbol, priceScale: 2 }),
            sortable: true,
            ...(liveSortGated ? { liveSortReason: COPY.sortNeedsLive } : {}),
          })}
          rows={drawn}
          rowKey={(symbol) => symbol}
          rowLabel={(symbol) => symbol}
          sort={effective ?? undefined}
          onSortChange={(next) => setSort(next)}
          rowWindow={windowed ? { offset, total: ordered.length } : undefined}
          onRowsInView={onRowsInView}
          announce={say}
          sortReasonId={liveSortGated ? ids.sortNote : undefined}
          emptyState={empty}
          rowActions={rowActions}
          renderRow={(symbol, grid) => (
            <LiveRow
              grid={grid}
              symbol={symbol}
              columns={columns}
              hub={hub}
              instrument={facts.bySymbol.get(symbol)}
              live={live.has(symbol)}
              liveSince={hubState.openedAt}
              down={down}
              statusId={props.statusId}
              active={active === symbol}
              description={
                active === symbol && props.syncGroup.name !== null
                  ? COPY.showsIn(props.syncGroup.name)
                  : undefined
              }
              notLiveDetail={notLiveDetail}
              onActivate={() => activate(symbol)}
              onMove={(direction) => move(symbol, direction)}
              moveReason={moveReason(symbol)}
              onRemove={() => remove(symbol)}
              removeReason={write}
              onCopy={copy}
            />
          )}
        />
        <div style={FOOTER}>
          <AddSymbolPopover
            listName={name}
            listSymbols={symbols}
            facts={facts}
            open={addOpen}
            onOpenChange={(open) => {
              setAddOpen(open);
              if (!open) endBatch();
            }}
            onAdd={add}
            say={say}
            reason={addReason}
          />
          {capped && write === undefined ? (
            <span id={ids.cap} style={NOTE}>
              {COPY.capFull}
            </span>
          ) : null}
          <ColumnPicker
            variant="menu"
            label={COPY.columns}
            columns={pickerColumns}
            onChange={onColumn}
            {...(write === undefined ? {} : { writeReason: write, writeReasonId: ids.notice })}
          />
          <Menu
            trigger={
              <Button variant="ghost" size="sm" iconRight="chevron-down">
                {`${COPY.sort(header)}${paused ? COPY.sortPaused : ""}`}
              </Button>
            }
            items={sortItems}
            announceReason={say}
          />
          {paused ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setRanking(rankRef.current());
                setOutOfDate(false);
              }}
            >
              {COPY.resort}
            </Button>
          ) : null}
          <div style={FILTER}>
            <SearchBox
              label={COPY.filter}
              value={filter}
              onChange={(value) => setFilter(value)}
              onClear={() => setFilter("")}
              onKeyDown={(event) => {
                if (event.key !== "Escape") return;
                event.preventDefault();
                setFilter("");
                gridTabStop()?.focus();
              }}
            />
          </div>
          {state.removed.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={undo}>
              {COPY.undo(state.removed.length)}
            </Button>
          ) : null}
          <p style={COUNT}>{COPY.count(symbols.length, liveCount)}</p>
        </div>
        {liveSortGated ? (
          <p id={ids.sortNote} style={{ ...NOTE, padding: "0 var(--space-panel-padding)" }}>
            {COPY.sortNeedsLive}
          </p>
        ) : null}
        {error === null ? null : (
          <p style={{ ...NOTE, padding: "var(--space-2) var(--space-panel-padding)" }}>
            {error.kind === "refused"
              ? COPY.notSent
              : error.kind === "conflict"
                ? COPY.conflict(name)
                : COPY.saveFailed(name)}{" "}
            {error.kind === "failed" ? (
              <Button variant="ghost" size="sm" onClick={() => edits.retry()}>
                {COPY.retry}
              </Button>
            ) : error.kind === "conflict" ? (
              <Button variant="ghost" size="sm" onClick={props.onReload}>
                {COPY.reload(name)}
              </Button>
            ) : null}
          </p>
        )}
      </div>
    </div>
  );
}
