/**
 * SCR-063's Positions tab (E29-S01 #911): the panel's session (`positionsSession.ts`: the feed and the
 * account signals) into CMP-114, under the toolbar, the panel's notices and the account slot (E29-D02
 * §2). The panel owns the session and the feed's announcements, so a tab switch keeps them.
 *
 * - **Sources (BQ-18):** the WS snapshot is authoritative; REST paints first while it is pending and
 *   is the fallback while the link is down, never polled; a `snap` replaces the REST view wholesale
 *   (the store's rule). S-02's budget is 5 s.
 * - **States** (the ticket's six; D02 §10.1–§10.4; D06 S-01 to S-04, S-08, S-14, S-15, S-19 to
 *   S-22): loading (S-01, "Loading Sub-1 · LIVE…" per account, `aria-busy`, skeleton rows) until the
 *   book is read, the link up or not; empty (S-03, title and cause only, BQ-15) only for a book read
 *   and empty; no accounts; filter-empty (S-04); could not load (S-02, CMP-027 and Retry, no row of
 *   the failed accounts: D02:333); reconciling and desync (S-14, S-15: the group-header marker and
 *   one CMP-028 line, `live="off"`, most severe account first; BQ-14), the stale and kill-switch
 *   locks (D03 §4.1); an account withdrawn (S-08: its "No longer shown" line under the rows, D02
 *   §10.1 and board 17). None owns a live region: the panel's announcer speaks (E17-D02 §11).
 * - **The panel's notices** (the kill switch, S-19 and S-20; a read-only session, S-22) sit in the
 *   band under the toolbar, as boards 16 and 17 draw them (D02 §2, D-16).
 * - **T2:** this tab mounts no write control (the Actions column, the chords and Flatten account…
 *   are E29-S03's, BQ-3), so nothing here is T2; every control is a read or a view choice, never T2
 *   (E29-D04 §4.2). A Manager's read-only grant renders its `rbac.account_read_only` notice once, in
 *   that account's header, its node in the DOM at mount with a stable id for the gated controls to
 *   come (D02 §10.4, `32-design-specs.md` G-T2.5).
 * - **Announcements** (`announce.ts`): the filtered result after a chip change (D04 §2.6, D05 §8.1,
 *   polite, once per change, latest wins), the focused row's and the totals' changed values (RT-16).
 * - **Focus** never drops to `body` (D05 §5.4): Retry hands it to the tab, Clear filters to "+ Filter"
 *   (as CMP-055's Clear all does), and a focused row whose account is withdrawn to that account's line
 *   (F-02), which then speaks itself and the panel's RT-15 stays silent for it.
 */
import {
  useEffect,
  useId,
  useInsertionEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  type Dispatch,
  type FocusEvent,
  type JSX,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  Button,
  Callout,
  EmptyState,
  ErrorState,
  Icon,
  PositionsGrid,
  rowsWord,
  Skeleton,
  Tag,
  type PositionsGridColumnId,
  type TableSort,
} from "@candleviewer/ui";
import { useAmbientWriter } from "../../chart/a11y/politeWriter";
import { useShellSelector } from "../../shell/useShellSelector";
import { accountLine, useAccountSignals, type AccountSignal } from "./accountSignals";
import { rowValuesText, signOf, totalsValuesText, type PanelAnnouncer } from "./announce";
import { bindKinds, D02_TEXT, DECK } from "./copy";
import { exportPositionsCsv } from "./csv";
import { reportFiltered, reportGrouped } from "./events";
import { exportFileName, saveCsv, type SaveFile } from "./exportFile";
import { showsLoading } from "./feedAnnouncements";
import {
  accountWords,
  chipsRestated,
  envWord,
  failedLines,
  filterEmptyTitle,
  gridGroups,
  gridTotals,
  loadingLine,
  totalsLabel,
  withdrawnLine,
  type GridRow,
} from "./gridModel";
import type { FilterAction } from "./model/filters";
import type { GroupBy } from "./model/grouping";
import type { AccountInfo, Environment } from "./model/rowMapping";
import { pressHeader, type SortColumn, type SortState } from "./model/sort";
import { buildPositionsView } from "./model/view";
import { getPanelState, updateChips, updatePanelState, usePanelState } from "./panelState";
import type { PositionsSession } from "./positionsSession";
import { usePositions, type Withdrawn } from "./positionsStore";
import { MANDATORY_COLUMNS, OPTIONAL_COLUMNS, Toolbar } from "./Toolbar";

/** The money columns' unit (one product: USDT linear perpetuals, C-1.3). */
const CURRENCY = "USDT";
const AMBIENT_FIELDS = ["row", "totals"] as const;
const SORT_COLUMNS: readonly SortColumn[] = [
  "account",
  "symbol",
  "side",
  "size",
  "entry",
  "mark",
  "upnl",
  "r",
  "rpnl_today",
  "liq_price",
  "liq_dist",
  "leverage",
  "margin",
];
const NO_ACCOUNTS: readonly { readonly exchange_account_id: string; readonly mode: string }[] = [];

/** An epoch time as D02 writes one, "14:02:11" (UTC); "—" when the client does not know it. */
export const utcTime = (ms: number | null): string =>
  ms === null || !Number.isFinite(ms) ? "—" : new Date(ms).toISOString().slice(11, 19);

/** D03 §4.1's tone of an account state: Reconciling info, Verifying warning, a lock danger. */
const toneOf = (signal: AccountSignal): "info" | "warning" | "danger" =>
  signal.oms?.state === "reconciling"
    ? "info"
    : signal.oms?.state === "desync"
      ? "warning"
      : "danger";

/** The slot's order (D03 §4.2): a lock, then Verifying, then Reconciling. */
const severityOf = (signal: AccountSignal): number =>
  signal.oms?.state === "stale" ? 0 : signal.oms?.state === "desync" ? 1 : 2;

/** The header marker's words (D02 §10.2, D03 §4.1): "checking", "Verifying", the locks'. */
function markerWords(signal: AccountSignal): string | null {
  const line = accountLine(signal);
  if (line === null) return null;
  if (line.marker === "kill_lock") return D02_TEXT.killLockMarker.string;
  if (line.marker === "acct.marker.stale")
    return bindKinds(line.marker, { time: utcTime(signal.oms?.sinceMs ?? null) });
  return DECK[line.marker].string;
}

/** A position row's account: its key is `exchange_account_id|symbol|position_idx`. */
const accountOfKey = (key: string): string => key.slice(0, key.indexOf("|"));

export interface PositionsTabProps {
  readonly session: PositionsSession;
  readonly announcer: PanelAnnouncer;
  /** The panel's: a header press's order survives a tab switch, as the book does. */
  readonly sort: SortState | null;
  readonly setSort: Dispatch<SetStateAction<SortState | null>>;
  /** The panel's notices over every tab (S-19, S-20, S-22), drawn in the band under the toolbar. */
  readonly notices?: ReactNode;
  readonly saveFile?: SaveFile | undefined;
  /** Epoch ms for the export's file name; defaults to `Date.now`. */
  readonly wall?: (() => number) | undefined;
}

export function PositionsTab({
  session,
  announcer,
  sort,
  setSort,
  notices,
  saveFile,
  wall,
}: PositionsTabProps): JSX.Element {
  const { store, signals, spokenByFocus } = session;
  const ids = useId();
  const root = useRef<HTMLDivElement>(null);
  const gridBox = useRef<HTMLDivElement>(null);
  const addFilterId = `${ids}-add-filter`;

  const snap = usePositions(store, (s) => s);
  const states = useAccountSignals(signals, (s) => s.accounts);
  const grants = useShellSelector((s) => s.me?.accounts ?? NO_ACCOUNTS);
  const shellEnv = useShellSelector((s) => s.environment);
  const chips = usePanelState("chips");
  const groupBy = usePanelState("groupBy");
  const columnsByTab = usePanelState("columns");
  const density = usePanelState("density");

  const directory = useMemo(() => new Map(snap.accounts.map((a) => [a.id, a])), [snap.accounts]);
  const environment: Environment | null =
    shellEnv !== "unknown" ? shellEnv : (snap.accounts[0]?.environment ?? null);
  const view = useMemo(
    () =>
      buildPositionsView({
        rows: snap.rows,
        chips,
        groupBy,
        sort,
        environment,
        realisedToday: (id) => snap.realisedToday.get(id) ?? null,
      }),
    [snap, chips, groupBy, sort, environment],
  );
  const columns: readonly PositionsGridColumnId[] = (
    columnsByTab.positions ?? OPTIONAL_COLUMNS
  ).flatMap((id) => OPTIONAL_COLUMNS.filter((c) => c === id));
  const label = (accountId: string): string => accountWords(accountId, directory);
  const withdrawn = new Set(snap.withdrawn.map((w) => w.accountId));
  const readOnly = (accountId: string): boolean =>
    grants.some((g) => g.mode === "read" && g.exchange_account_id.toLowerCase() === accountId);
  const readOnlyId = (accountId: string): string => `${ids}-read-only-${accountId}`;
  const failed = snap.status === "snapshot_failed";
  const revoked = snap.status === "revoked";
  const loading = showsLoading(snap);
  /** The grid shows rows or an empty state only once the book is read (S-03 needs a book known empty). */
  const gridShown = snap.status !== "no_accounts" && !failed && !revoked && !loading;

  // RT-16: the focused row's and the totals' changed values, at most once per 2 s per field.
  const ambient = useAmbientWriter(AMBIENT_FIELDS);
  const focused = useRef<string | null>(null);
  /** F-02: the grid row that last held focus (below), and its value as this commit began. */
  const rowFocus = useRef<string | null>(null);
  const rowFocusBefore = useRef<string | null>(null);
  const lastRow = useRef<{ key: string; text: string; upnl: number | null; r: number | null }>();
  const lastTotals = useRef<{ text: string; upnl: number | null }>();
  const totalsWords = totalsLabel(environment);
  useEffect(() => {
    const key = focused.current;
    const row = key === null ? undefined : snap.rows.find((r) => r.key === key);
    if (row === undefined) {
      lastRow.current = undefined;
    } else {
      const text = rowValuesText(row, CURRENCY);
      const upnl = signOf(row.unrealisedPnl);
      const r = signOf(row.r.value);
      const before = lastRow.current;
      if (before !== undefined && before.key === row.key && before.text !== text) {
        const flipped =
          (before.upnl !== null && upnl !== before.upnl) || (before.r !== null && r !== before.r);
        ambient.set("row", text, flipped);
      }
      lastRow.current = { key: row.key, text, upnl, r };
    }
    if (totalsWords === null || view.totals.count === 0) return;
    const text = totalsValuesText(totalsWords, view.totals.unrealisedPnl, CURRENCY);
    const upnl = signOf(view.totals.unrealisedPnl);
    const before = lastTotals.current;
    if (before !== undefined && before.text !== text)
      ambient.set("totals", text, before.upnl !== null && upnl !== before.upnl);
    lastTotals.current = { text, upnl };
  }, [snap, view, totalsWords, ambient]);
  const onGridFocus = (event: FocusEvent<HTMLDivElement>): void => {
    const target = event.target instanceof Element ? event.target : null;
    const key = target?.closest("tr[data-key]")?.getAttribute("data-key") ?? null;
    rowFocus.current = key;
    if (key === focused.current) return;
    focused.current = key;
    // the row's values as focus lands are its baseline: the next change from them is news
    const row = key === null ? undefined : snap.rows.find((r) => r.key === key);
    lastRow.current =
      row === undefined
        ? undefined
        : {
            key: row.key,
            text: rowValuesText(row, CURRENCY),
            upnl: signOf(row.unrealisedPnl),
            r: signOf(row.r.value),
          };
  };
  const onGridBlur = (event: FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) focused.current = null;
    // the user took focus elsewhere; focus that falls to `body` with its row is kept for F-02
    if (next instanceof Node && !event.currentTarget.contains(next)) rowFocus.current = null;
  };

  // The filtered result (D04 §2.6, D05 §8.1, WCAG 4.1.3): after a chip change, once the view
  // rebuilds, the title of the state it shows, else the positions in view in CMP-049's words. A
  // newer result replaces one still waiting for the region's budget.
  const filterChanged = useRef(false);
  useEffect(() => {
    if (!filterChanged.current) return;
    filterChanged.current = false;
    if (!gridShown) return; // the loading or failed state's own line says what is shown
    const text = view.filterEmpty
      ? filterEmptyTitle(chips.length)
      : view.empty
        ? DECK["blotter.ui.empty"].string
        : rowsWord(view.rows.length);
    announcer.say("polite", text, "filter");
  }, [chips, view, gridShown, announcer]);

  // F-02 (E29-D05 §5.4): when the focused row's account is withdrawn, focus goes to its line, which
  // speaks itself, so the panel's RT-15 stays silent for it. The row is the one that last held
  // focus: kept while focus falls to `body` with it (a narrowing drops every row before the
  // directory names who left), read before this commit's layout effects, where CMP-049's own
  // restore hands focus to the next row first.
  useInsertionEffect(() => {
    rowFocusBefore.current = rowFocus.current;
  });
  const lines = useRef(new Map<string, HTMLElement>());
  const seenWithdrawn = useRef<ReadonlySet<Withdrawn>>(new Set(snap.withdrawn));
  useLayoutEffect(() => {
    const seen = seenWithdrawn.current;
    seenWithdrawn.current = new Set(snap.withdrawn);
    const key = rowFocusBefore.current;
    if (key === null) return;
    const entry = snap.withdrawn.find((w) => !seen.has(w) && w.accountId === accountOfKey(key));
    const line = entry === undefined ? undefined : lines.current.get(entry.accountId);
    const active = document.activeElement;
    const lost =
      active === null || active === document.body || gridBox.current?.contains(active) === true;
    if (entry === undefined || line === undefined || !lost) return;
    rowFocus.current = null;
    spokenByFocus.add(entry);
    line.focus();
  }, [snap.withdrawn, spokenByFocus]);

  const onGroupBy = (by: GroupBy): void => {
    updatePanelState({ groupBy: by });
    reportGrouped(by);
  };
  const onChips = (action: FilterAction): void => {
    const before = getPanelState().chips;
    filterChanged.current = true; // before the change, so the render it causes finds it
    updateChips(action);
    const after = getPanelState().chips;
    if (after === before) {
      filterChanged.current = false;
      return;
    }
    reportFiltered(after);
  };
  const onClearFilters = (): void => {
    onChips({ type: "clear" });
    // its button leaves with the state: focus goes to the add control, as CMP-055's Clear all's does
    document.getElementById(addFilterId)?.focus();
  };
  const onRetry = (): void => {
    session.retry();
    root.current?.focus(); // Retry leaves with S-02: the tab keeps focus, never `body`
  };
  const onColumns = (next: readonly PositionsGridColumnId[]): void =>
    updatePanelState({ columns: { ...getPanelState().columns, positions: [...next] } });
  const onExport = (): void => {
    const text = exportPositionsCsv(view.rows, [...MANDATORY_COLUMNS, ...columns], snap.liq);
    (saveFile ?? saveCsv)(exportFileName(new Date(wall?.() ?? Date.now())), text);
  };
  const onSortChange = (next: TableSort): void => {
    const column = SORT_COLUMNS.find((c) => c === next.columnId);
    if (column === undefined) return;
    setSort((current) =>
      pressHeader(current, column, snap.rows, (row) => snap.liq.get(row.key)?.distancePct ?? null),
    );
  };
  const say = (text: string): void => announcer.say("polite", text);

  const markerOf = (accountId: string): ReactNode => {
    const signal = states.get(accountId);
    const words = signal === undefined ? null : markerWords(signal);
    const notice = readOnly(accountId);
    if (words === null && !notice) return undefined;
    return (
      <>
        {words === null || signal === undefined ? null : (
          <Tag variant={toneOf(signal)} label={words} />
        )}
        {notice ? (
          <span id={readOnlyId(accountId)} className="cv-positions__reason">
            <span className="cv-positions__lock">
              <Icon name="lock" />
            </span>
            {DECK["rbac.account_read_only"].string}
          </span>
        ) : null}
      </>
    );
  };

  // The slot's one line (D-16, BQ-14): the most severe listed account's, `live="off"` (RT-11 speaks).
  const slot = [...states]
    .filter(([id, signal]) => signal.oms !== null && directory.has(id) && !withdrawn.has(id))
    .sort(([a, x], [b, y]) => severityOf(x) - severityOf(y) || label(a).localeCompare(label(b)))[0];
  const slotLine = slot === undefined ? null : accountLine(slot[1]);
  const slotAccount: AccountInfo | undefined =
    slot === undefined ? undefined : directory.get(slot[0]);

  // S-08: each withdrawn account's line where its rows were, not live (the panel's RT-15 speaks),
  // focusable by script for F-02's move; it leaves when the account is served again.
  const withdrawnLines =
    snap.withdrawn.length === 0 ? null : (
      <div className="cv-positions__withdrawn" data-part="Withdrawn">
        {snap.withdrawn.map((w) => (
          <p
            key={w.accountId}
            tabIndex={-1}
            ref={(node) => {
              if (node === null) lines.current.delete(w.accountId);
              else lines.current.set(w.accountId, node);
            }}
          >
            {withdrawnLine(w, directory)}
          </p>
        ))}
      </div>
    );

  const grid = (empty: ReactNode): JSX.Element => (
    <div className="cv-positions__grid" ref={gridBox} onFocus={onGridFocus} onBlur={onGridBlur}>
      <PositionsGrid<GridRow>
        caption={D02_TEXT.tabPositions.string}
        captionHidden
        groups={gridGroups({
          groups: view.groups,
          accounts: directory,
          liq: snap.liq,
          environment,
          markerOf,
        })}
        totals={gridTotals(view.totals, environment)}
        columns={columns}
        density={density}
        currency={CURRENCY}
        sort={sort === null ? undefined : { columnId: sort.column, direction: sort.direction }}
        onSortChange={onSortChange}
        emptyState={empty}
        announce={say}
      />
    </div>
  );

  let body: ReactNode;
  if (snap.status === "no_accounts") {
    body = <EmptyState title={DECK["blotter.ui.no_accounts"].string} headingLevel={2} />;
  } else if (failed) {
    // S-02: the failed accounts show no row (D02:333), whatever a REST read painted
    body = (
      <div className="cv-positions__failed" data-part="SnapshotFailed">
        {failedLines(snap.accounts, environment).map((line) => (
          <ErrorState key={line} form="banner" severity="warning" live="off" message={line} />
        ))}
        <Button onClick={onRetry}>{D02_TEXT.retry.string}</Button>
      </div>
    );
  } else if (revoked) {
    // S-08 for the whole feed: the lines, then Retry, never a bare Retry
    body = (
      <div className="cv-positions__failed" data-part="Revoked">
        {withdrawnLines}
        <Button onClick={onRetry}>{D02_TEXT.retry.string}</Button>
      </div>
    );
  } else if (loading) {
    // S-01: until the book is read, whether or not the link is up (never S-03 for a book not read)
    body =
      snap.accounts.length === 0 ? (
        <PositionsGrid
          caption={D02_TEXT.tabPositions.string}
          captionHidden
          groups={[]}
          loading
          announce={say}
        />
      ) : (
        <div className="cv-positions__loading" data-part="Loading">
          {snap.accounts.map((a) => (
            <div
              key={a.id}
              role="group"
              aria-busy="true"
              aria-labelledby={`${ids}-loading-${a.id}`}
            >
              <p id={`${ids}-loading-${a.id}`}>{loadingLine(a)}</p>
              <Skeleton shape="row" count={3} />
            </div>
          ))}
        </div>
      );
  } else {
    body = (
      <>
        {grid(
          view.filterEmpty ? (
            <EmptyState
              variant="filtered-empty"
              title={filterEmptyTitle(chips.length)}
              description={chipsRestated(chips, directory)}
              actions={[{ label: D02_TEXT.clearFilters.string, onClick: onClearFilters }]}
              headingLevel={2}
            />
          ) : (
            <EmptyState
              title={DECK["blotter.ui.empty"].string}
              description={DECK["blotter.ui.empty_cause"].string}
              headingLevel={2}
            />
          ),
        )}
      </>
    );
  }

  return (
    <div className="cv-positions__tab" data-part="PositionsTab" ref={root} tabIndex={-1}>
      <Toolbar
        accounts={snap.accounts}
        chips={chips}
        groupBy={groupBy}
        columns={columns}
        onGroupBy={onGroupBy}
        onChips={onChips}
        onColumns={onColumns}
        onExport={onExport}
        density={density}
        addFilterId={addFilterId}
      />
      {notices}
      {slot === undefined || slotLine === null ? null : (
        <div className="cv-positions__slot" data-part="AccountSlot">
          <Callout
            tone={toneOf(slot[1])}
            live="off"
            title={bindKinds(slotLine.line, {
              label: label(slot[0]),
              environment: envWord(slotAccount?.environment ?? environment),
            })}
          />
        </div>
      )}
      {body}
      {revoked ? null : withdrawnLines}
    </div>
  );
}
