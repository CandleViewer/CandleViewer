/**
 * SCR-063's Positions tab (E29-S01 #911): the feed (`wsPositions.ts`) and the account signals
 * (`accountSignals.ts`) into CMP-114, under the toolbar and the account slot (E29-D02 §2).
 *
 * - **Sources (BQ-18):** the WS snapshot is authoritative; REST paints first while it is pending and
 *   is the fallback while the link is down, never polled; a `snap` replaces the REST view wholesale
 *   (the store's rule). S-02's budget is 5 s.
 * - **States** (the ticket's six; D02 §10.1–§10.4; D06 S-01 to S-04, S-08, S-14, S-15, S-19 to
 *   S-22): loading (S-01, "Loading Sub-1 · LIVE…" per account, `aria-busy`, skeleton rows), empty
 *   (S-03, title and cause only, BQ-15), no accounts, filter-empty (S-04), could not load (S-02,
 *   CMP-027 and Retry), reconciling and desync (S-14, S-15: the group-header marker and one CMP-028
 *   line, `live="off"`, most severe account first; BQ-14), the stale and kill-switch locks (D03 §4.1),
 *   an account withdrawn (S-08). The kill-switch banner and the Viewer's notice are the panel's
 *   (`PositionsPanel.tsx`), as they cover every tab.
 * - **T2:** this tab mounts no write control (the Actions column, the chords and Flatten account…
 *   are E29-S03's, BQ-3), so nothing here is T2; every control is a read or a view choice, never T2
 *   (E29-D04 §4.2). A Manager's read-only grant renders its `rbac.account_read_only` notice once, in
 *   that account's header, its node in the DOM at mount with a stable id for the gated controls to
 *   come (D02 §10.4, `32-design-specs.md` G-T2.5).
 * - **Announcements** (`announce.ts`): crossings (RT-05, RT-12), account episodes (RT-07, RT-11),
 *   could not load (RT-15), and the focused row's and the totals' changed values (RT-16).
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type JSX,
  type ReactNode,
} from "react";
import {
  Button,
  Callout,
  EmptyState,
  ErrorState,
  PositionsGrid,
  Skeleton,
  Tag,
  type PositionsGridColumnId,
  type TableSort,
} from "@candleviewer/ui";
import { useAmbientWriter } from "../../chart/a11y/politeWriter";
import type { WsClient } from "../../lib/ws/api";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";
import { useShellSelector } from "../../shell/useShellSelector";
import {
  accountLine,
  createAccountSignals,
  startAccountSignals,
  useAccountSignals,
  type AccountSignal,
  type Role,
} from "./accountSignals";
import {
  accountAnnouncements,
  crossingAnnouncements,
  rowValuesText,
  sayAll,
  signOf,
  totalsValuesText,
  type PanelAnnouncer,
  type SaidEpisodes,
} from "./announce";
import { bindDeck, bindKinds, D02_TEXT, DECK } from "./copy";
import { exportPositionsCsv } from "./csv";
import { reportFiltered, reportGrouped } from "./events";
import { exportFileName, saveCsv, type SaveFile } from "./exportFile";
import {
  accountWords,
  chipsRestated,
  envWord,
  gridGroups,
  gridTotals,
  totalsLabel,
  type GridRow,
} from "./gridModel";
import type { FilterAction } from "./model/filters";
import type { GroupBy } from "./model/grouping";
import type { AccountInfo, Environment } from "./model/rowMapping";
import { pressHeader, type SortColumn, type SortState } from "./model/sort";
import { buildPositionsView } from "./model/view";
import { getPanelState, updateChips, updatePanelState, usePanelState } from "./panelState";
import { createPositionsStore, usePositions } from "./positionsStore";
import { MANDATORY_COLUMNS, OPTIONAL_COLUMNS, Toolbar } from "./Toolbar";
import { startPositionsFeed, type PositionsFeed, type PositionsFeedOptions } from "./wsPositions";

/** The client the feed reads: the app's active one, or a test's fake (`support/fakes.ts`). */
export type FeedClient = Pick<WsClient, "consume" | "getState" | "subscribe">;

/** What a test injects (the `SessionsApi` pattern, BQ-19); the route passes none. */
export interface PositionsDeps {
  readonly client?: FeedClient | undefined;
  /** The feed's seams: the REST API, timers, rAF, clocks and the performance marks. */
  readonly feed?: Omit<PositionsFeedOptions, "client" | "store" | "signals"> | undefined;
  readonly saveFile?: SaveFile | undefined;
}

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
function markerWords(signal: AccountSignal, role: Role): string | null {
  const line = accountLine(signal, role);
  if (line === null) return null;
  if (line.marker === "kill_lock") return D02_TEXT.killLockMarker.string;
  if (line.marker === "acct.marker.stale")
    return bindKinds(line.marker, { time: utcTime(signal.oms?.sinceMs ?? null) });
  return DECK[line.marker].string;
}

export interface PositionsTabProps {
  readonly client: FeedClient | null;
  readonly announcer: PanelAnnouncer;
  readonly deps?: PositionsDeps | undefined;
}

export function PositionsTab({ client, announcer, deps }: PositionsTabProps): JSX.Element {
  const ids = useId();
  const [store] = useState(createPositionsStore);
  const [signals] = useState(createAccountSignals);
  const feed = useRef<PositionsFeed | null>(null);
  const toolbar = useRef<HTMLDivElement>(null);
  const feedOptions = deps?.feed;

  useEffect(() => {
    if (client === null) return undefined;
    const started = startPositionsFeed({ ...feedOptions, client, store, signals });
    feed.current = started;
    const stopSignals = startAccountSignals(signals, {
      shell: { getState: getShellState, subscribe: subscribeShellState },
      ws: client,
      wall: feedOptions?.wall,
    });
    return () => {
      stopSignals();
      started.stop();
      if (feed.current === started) feed.current = null;
    };
  }, [client, store, signals, feedOptions]);

  const snap = usePositions(store, (s) => s);
  const states = useAccountSignals(signals, (s) => s.accounts);
  const role: Role = useShellSelector((s) => s.me?.role ?? null) ?? "viewer";
  const grants = useShellSelector((s) => s.me?.accounts ?? NO_ACCOUNTS);
  const shellEnv = useShellSelector((s) => s.environment);
  const chips = usePanelState("chips");
  const groupBy = usePanelState("groupBy");
  const columnsByTab = usePanelState("columns");
  const density = usePanelState("density");
  const [sort, setSort] = useState<SortState | null>(null);

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

  const failedLines =
    snap.accounts.length > 0
      ? snap.accounts.map((a) =>
          bindKinds("blotter.ui.snapshot_failed", {
            label: a.label,
            environment: envWord(a.environment),
          }),
        )
      : [
          bindKinds("blotter.ui.snapshot_failed", {
            label: D02_TEXT.tabPositions.string,
            environment: envWord(environment),
          }),
        ];
  const failed = snap.status === "snapshot_failed";
  // What the announcement effects read as it stands (labels, lists): written first, so they see this render's.
  const listed = (id: string): boolean => directory.has(id) && !withdrawn.has(id);
  const latest = useRef({ label, listed, failedLines });
  useEffect(() => {
    latest.current = { label, listed, failedLines };
  });

  // RT-05 and RT-12: each crossing once (a `seq` is never reused; a re-run of the effect says nothing again).
  const crossingSeq = useRef(0);
  useEffect(() => {
    const fresh = snap.crossings.filter((c) => c.seq > crossingSeq.current);
    if (fresh.length === 0) return;
    crossingSeq.current = Math.max(...fresh.map((c) => c.seq));
    const rows = new Map(snap.rows.map((r) => [r.key, r]));
    sayAll(
      announcer,
      crossingAnnouncements(
        fresh,
        (key) => rows.get(key),
        (key) => snap.liq.get(key),
      ),
    );
  }, [snap, announcer]);

  // RT-07 and RT-11: each account's episode once, and its end on an account still listed.
  const said = useRef<SaidEpisodes>(new Map());
  useEffect(() => {
    const read = latest.current;
    const next = accountAnnouncements(said.current, states, role, read.label, read.listed);
    said.current = next.said;
    sayAll(announcer, next.batch);
  }, [states, role, announcer]);

  // RT-15: could not load, said once per failure (S-02's lines show with `live="off"`).
  const wasFailed = useRef(false);
  useEffect(() => {
    if (failed && !wasFailed.current) announcer.say("polite", latest.current.failedLines.join(" "));
    wasFailed.current = failed;
  }, [failed, announcer]);

  // RT-16: the focused row's and the totals' changed values, at most once per 2 s per field.
  const ambient = useAmbientWriter(AMBIENT_FIELDS);
  const focused = useRef<string | null>(null);
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
  };

  const onGroupBy = (by: GroupBy): void => {
    updatePanelState({ groupBy: by });
    reportGrouped(by);
  };
  const onChips = (action: FilterAction): void => {
    const before = getPanelState().chips;
    updateChips(action);
    const after = getPanelState().chips;
    if (after !== before) reportFiltered(after);
  };
  const onColumns = (next: readonly PositionsGridColumnId[]): void =>
    updatePanelState({ columns: { ...getPanelState().columns, positions: [...next] } });
  const onExport = (): void => {
    const text = exportPositionsCsv(view.rows, [...MANDATORY_COLUMNS, ...columns], snap.liq);
    (deps?.saveFile ?? saveCsv)(
      exportFileName(new Date(feedOptions?.wall?.() ?? Date.now())),
      text,
    );
  };
  const onSortChange = (next: TableSort): void => {
    const column = SORT_COLUMNS.find((c) => c === next.columnId);
    if (column === undefined) return;
    setSort((current) =>
      pressHeader(current, column, snap.rows, (row) => snap.liq.get(row.key)?.distancePct ?? null),
    );
  };

  const markerOf = (accountId: string): ReactNode => {
    const signal = states.get(accountId);
    const words = signal === undefined ? null : markerWords(signal, role);
    const notice = readOnly(accountId);
    if (words === null && !notice) return undefined;
    return (
      <>
        {words === null || signal === undefined ? null : (
          <Tag variant={toneOf(signal)} label={words} />
        )}
        {notice ? (
          <span id={readOnlyId(accountId)} className="cv-positions__reason">
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
  const slotLine = slot === undefined ? null : accountLine(slot[1], role);
  const slotAccount: AccountInfo | undefined =
    slot === undefined ? undefined : directory.get(slot[0]);

  const grid = (empty: ReactNode): JSX.Element => (
    <div className="cv-positions__grid" onFocus={onGridFocus} onBlur={onGridBlur}>
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
        announce={(text) => announcer.say("polite", text)}
      />
    </div>
  );

  let body: ReactNode;
  if (snap.status === "no_accounts") {
    body = <EmptyState title={DECK["blotter.ui.no_accounts"].string} headingLevel={2} />;
  } else if (failed || snap.status === "revoked") {
    body = (
      <>
        <div className="cv-positions__failed" data-part="SnapshotFailed">
          {failed
            ? failedLines.map((line) => (
                <ErrorState key={line} form="banner" severity="warning" live="off" message={line} />
              ))
            : null}
          <Button onClick={() => feed.current?.retry()}>{D02_TEXT.retry.string}</Button>
        </div>
        {snap.rows.length > 0 ? grid(null) : null}
      </>
    );
  } else if (snap.source === "none" && (snap.status === "idle" || snap.status === "loading")) {
    body =
      snap.accounts.length === 0 ? (
        <PositionsGrid caption={D02_TEXT.tabPositions.string} captionHidden groups={[]} loading />
      ) : (
        <div className="cv-positions__loading" role="status" data-part="Loading">
          {snap.accounts.map((a) => (
            <section key={a.id} aria-busy="true" aria-labelledby={`${ids}-loading-${a.id}`}>
              <p id={`${ids}-loading-${a.id}`}>
                {bindKinds("blotter.ui.loading", {
                  label: a.label,
                  environment: envWord(a.environment),
                })}
              </p>
              <Skeleton shape="row" count={3} />
            </section>
          ))}
        </div>
      );
  } else if (view.filterEmpty) {
    body = grid(
      <EmptyState
        variant="filtered-empty"
        title={bindKinds("blotter.ui.filter_empty", { count: String(chips.length) })}
        description={chipsRestated(chips, directory)}
        actions={[
          { label: D02_TEXT.clearFilters.string, onClick: () => onChips({ type: "clear" }) },
        ]}
        headingLevel={2}
      />,
    );
  } else {
    body = grid(
      <EmptyState
        title={DECK["blotter.ui.empty"].string}
        description={DECK["blotter.ui.empty_cause"].string}
        headingLevel={2}
      />,
    );
  }

  return (
    <div className="cv-positions__tab" data-part="PositionsTab">
      <div ref={toolbar}>
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
        />
      </div>
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
      {snap.withdrawn.map((w) => (
        <Callout
          key={w.accountId}
          tone="info"
          live="polite"
          title={bindDeck("panel.no_longer_shown", { "{account}": w.label ?? label(w.accountId) })}
          dismissible
          onDismiss={() => {
            store.dismissWithdrawn(w.accountId);
            store.commit();
            toolbar.current?.querySelector<HTMLElement>("button")?.focus();
          }}
        />
      ))}
      {body}
    </div>
  );
}
