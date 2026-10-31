/**
 * SCR-100 Watchlist panel (E08-S08; E08-D07; `14` SCR-100), as R-111's routed page in the shell's `main` until E15's
 * pane host (pre-ruling 1). The panel is a labelled region ("Watchlist Majors") with the list tabs (CMP-162) and the
 * panel status in its header row, and the list's grid and footer (`ListView`) under them.
 *
 * - Data: `GET /watchlists` (the lists), E08-S09's instrument index (price scale, delisted), the ticker hub (one
 *   batched `ticker` for every pane).
 * - States (§4.2): loading (skeleton rows), load error (Retry), no lists, an empty list, and per row the ticker
 *   states; Disconnected (D4) is the header's status, "Disconnected — last data 00:12 ago", for the whole outage and
 *   until the ticker snapshot after the reconnect, one attribute on the panel demoting every row. It is never a scrim
 *   and gates no control (C-13); the connection region announces it, so the panel says nothing of it.
 * - The panel owns no live region (D17): it says through the app's one announcer, and its gated controls' refusals go
 *   there too (#5146's hand-off: the shell's own provider is a no-op).
 * - Ports: the sync group (E15-S04), the pane host and the pane settings (E15), each with a default (pre-ruling 2).
 */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type JSX,
} from "react";
import {
  EmptyState,
  GatedAnnounceProvider,
  Table,
  WATCHLIST_DEFAULT_COLUMNS,
  WatchlistGroupTabs,
  watchlistColumns,
} from "@candleviewer/ui";
import { useWsState } from "../../lib/ws/client/useWsState";
import { announce, forget } from "../app-shell/announcer";
import { reportWatchlist } from "./analytics";
import { COPY } from "./copy";
import { useInstrumentFacts, useListLookups, type InstrumentSource } from "./instruments";
import type { Watchlist } from "./listEdits";
import { ListView } from "./ListView";
import {
  NO_PANEL_HOST,
  NO_SYNC_GROUP,
  localPaneSettings,
  type PaneSettingsPort,
  type PanelHostPort,
  type SyncGroupPort,
} from "./ports";
import { useSecondClock } from "./ticker/secondClock";
import type { HubState, TickerHub } from "./ticker/tickerHub";
import type { WatchlistApi } from "./watchlistApi";

/** R-110: SCR-101, the manager (#4702 PR c), and the paths to it. */
export const MANAGER_HREF = "/watchlist";

const PANEL: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  border: "calc(var(--border-hairline) * 1px) solid var(--color-border-subtle)",
};
const STATUS: CSSProperties = {
  margin: 0,
  color: "var(--color-text-primary)",
  whiteSpace: "nowrap",
};
const IDLE_HUB: HubState = {
  live: new Set(),
  waitingUntil: null,
  paused: null,
  snaps: 0,
  openedAt: null,
};
const noHub = (): (() => void) => () => undefined;
const idle = (): HubState => IDLE_HUB;

export interface WatchlistPanelProps {
  /** The list to show: R-111's `:groupId` (the pane's `watchlist_id` once panes exist). */
  readonly listId: string;
  readonly paneId: string;
  readonly api: WatchlistApi;
  /** The connection's ticker hub; `null` while the shell holds no WS client. */
  readonly hub: TickerHub | null;
  readonly instruments: InstrumentSource;
  readonly syncGroup?: SyncGroupPort;
  readonly panelHost?: PanelHostPort;
  readonly paneSettings?: PaneSettingsPort;
  /** No `workspaces:write` (E08-D07 D13): the lists read-only, every write T2 with one notice. */
  readonly readOnly?: boolean;
  /** A tab, or a list from "More lists": the page shows that list. */
  readonly onSwitchList?: (id: string) => void;
  /** "+", Rename, Duplicate, Delete…, "Manage watchlists…" and "Create watchlist": SCR-101 (#4702 PR c). */
  readonly onManage?: () => void;
  /** The lists loaded and `listId` is none of them. */
  readonly onMissing?: () => void;
}

type Load =
  | { readonly kind: "loading" }
  | { readonly kind: "failed" }
  | { readonly kind: "ready"; readonly lists: readonly Watchlist[] };

/** The hub's state, re-read on its transitions only (never per frame). */
function useHubState(hub: TickerHub | null): HubState {
  const subscribe = useCallback(
    (listener: () => void) => (hub === null ? noHub() : hub.subscribe(listener)),
    [hub],
  );
  const read = useCallback(() => (hub === null ? idle() : hub.getState()), [hub]);
  return useSyncExternalStore(subscribe, read, read);
}

/**
 * Disconnected (D4): the transport is down (an outage, reconnect attempts included), and after it comes back until the
 * ticker snapshot that follows the reconnect (`23` §7.4) — while anything is subscribed to bring one.
 */
function useFeedDown(hubState: HubState): boolean {
  const outage = useWsState().outage !== null;
  const [awaiting, setAwaiting] = useState<number | null>(null);
  const hub$ = useRef(hubState);
  hub$.current = hubState;
  const wasDown = useRef(false);
  useEffect(() => {
    if (outage) {
      wasDown.current = true;
      setAwaiting(null);
      return;
    }
    if (!wasDown.current) return;
    wasDown.current = false;
    if (hub$.current.live.size > 0) setAwaiting(hub$.current.snaps);
  }, [outage]);
  useEffect(() => {
    if (awaiting !== null && hubState.snaps > awaiting) setAwaiting(null);
  }, [awaiting, hubState.snaps]);
  return outage || awaiting !== null;
}

/** The header's status: Disconnected, else the paused notice, else nothing. Re-rendered on the clock's second. */
function PanelStatus({
  id,
  hub,
  down,
  paused,
}: {
  readonly id: string;
  readonly hub: TickerHub | null;
  readonly down: boolean;
  readonly paused: HubState["paused"];
}): JSX.Element {
  const now = useSecondClock();
  const last = hub?.lastDataMs() ?? null;
  const text = down
    ? COPY.disconnected(last === null ? null : Math.max(0, now - last))
    : paused !== null
      ? COPY.paused(paused.delayMs)
      : "";
  return (
    <p id={id} style={STATUS}>
      {text}
    </p>
  );
}

export function WatchlistPanel(props: WatchlistPanelProps): JSX.Element | null {
  const { listId, paneId, api, hub, instruments } = props;
  const syncGroup = props.syncGroup ?? NO_SYNC_GROUP;
  const panelHost = props.panelHost ?? NO_PANEL_HOST;
  const paneSettings = props.paneSettings ?? localPaneSettings;
  const readOnly = props.readOnly ?? false;
  const statusId = useId();
  const noticeId = useId();
  const key = `watchlist:${paneId}`;

  // The panel's words go to the app's polite region (D17), each said once, the same words again on a new press.
  const say = useCallback(
    (text: string) => {
      forget(key);
      announce("polite", text, key);
    },
    [key],
  );
  const sayAlert = useCallback(
    (text: string) => {
      forget(`${key}:alert`);
      announce("assertive", text, `${key}:alert`);
    },
    [key],
  );

  const facts = useInstrumentFacts(instruments);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoad({ kind: "loading" });
    api.list(controller.signal).then(
      (lists) => {
        if (!controller.signal.aborted) setLoad({ kind: "ready", lists });
      },
      () => {
        if (!controller.signal.aborted) setLoad({ kind: "failed" });
      },
    );
    return () => controller.abort();
  }, [api, attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const lists = load.kind === "ready" ? load.lists : [];
  const list = lists.find((l) => l.id === listId);
  useListLookups(instruments, facts, list?.symbols ?? []);
  const { onMissing } = props;
  const missing = load.kind === "ready" && lists.length > 0 && list === undefined;
  useEffect(() => {
    if (missing) onMissing?.();
  }, [missing, onMissing]);
  useEffect(() => {
    if (list !== undefined) paneSettings.write(paneId, { watchlist_id: list.id });
  }, [list, paneId, paneSettings]);

  const hubState = useHubState(hub);
  const down = useFeedDown(hubState);
  const paused = hubState.paused;
  useEffect(() => {
    if (down)
      reportWatchlist({
        name: "data_confidence.state_entered",
        surface: "SCR-100",
        state: "disconnected",
      });
  }, [down]);
  useEffect(() => {
    // §4.5: the paused notice is said once per refusal; Disconnected replaces it.
    if (paused !== null && !down) say(COPY.paused(paused.delayMs));
  }, [paused, down, say]);

  // The shown list's own count (its local edits), for its tab: "Majors, 11 symbols" after a removal.
  const [count, setCount] = useState<{ readonly id: string; readonly n: number } | null>(null);
  const onCount = useCallback((n: number) => setCount({ id: listId, n }), [listId]);
  const onManage = props.onManage ?? (() => undefined);

  if (missing) return null;
  const columns = watchlistColumns(WATCHLIST_DEFAULT_COLUMNS, {
    item: (symbol: string) => ({ symbol, priceScale: 2 }),
  });
  if (load.kind !== "ready" || facts.snapshot.phase === "loading") {
    return (
      <section aria-label={COPY.title} style={PANEL}>
        <Table<string>
          grid
          caption={COPY.title}
          captionHidden
          columns={columns}
          rows={[]}
          rowKey={(symbol) => symbol}
          loading={load.kind === "loading" || facts.snapshot.phase === "loading"}
          announce={load.kind === "failed" ? sayAlert : say}
          {...(load.kind === "failed"
            ? { error: { message: COPY.loadFailed, onRetry: reload } }
            : {})}
        />
      </section>
    );
  }
  if (list === undefined) {
    return (
      <section aria-label={COPY.title} style={PANEL}>
        {readOnly ? (
          // The sentence form (E09-D09 §2.2): the reason alone, no button.
          <EmptyState title={COPY.noListsReadOnly} description={COPY.writeReason} />
        ) : (
          <EmptyState
            title={COPY.noListsTitle}
            actions={[{ label: COPY.createList, onClick: onManage }]}
          />
        )}
      </section>
    );
  }

  const counts = Object.fromEntries(
    lists.map((l) => [l.id, count?.id === l.id ? count.n : l.symbols.length]),
  );
  const writeReason = readOnly ? COPY.writeReason : undefined;
  return (
    <section
      aria-label={COPY.region(list.name)}
      style={PANEL}
      data-cv-feed={down ? "disconnected" : undefined}
    >
      <GatedAnnounceProvider announce={say}>
        <WatchlistGroupTabs
          aria-label={COPY.tablist}
          groups={lists.map((l) => ({ id: l.id, name: l.name }))}
          counts={counts}
          activeId={list.id}
          onSwitch={(id) => props.onSwitchList?.(id)}
          onCreate={onManage}
          onRename={onManage}
          onDuplicate={onManage}
          onDelete={onManage}
          onManage={onManage}
          headerEnd={<PanelStatus id={statusId} hub={hub} down={down} paused={paused} />}
          {...(writeReason === undefined ? {} : { writeReason, writeReasonId: noticeId })}
        >
          <ListView
            key={`${list.id}:${list.version}:${String(attempt)}`}
            list={list}
            paneId={paneId}
            api={api}
            hub={hub}
            hubState={hubState}
            facts={facts}
            down={down}
            statusId={statusId}
            readOnly={readOnly}
            noticeId={noticeId}
            syncGroup={syncGroup}
            panelHost={panelHost}
            paneSettings={paneSettings}
            say={say}
            sayAlert={sayAlert}
            onCount={onCount}
            onReload={reload}
            managerHref={MANAGER_HREF}
          />
        </WatchlistGroupTabs>
      </GatedAnnounceProvider>
    </section>
  );
}
