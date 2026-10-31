/**
 * R-111 `/watchlist/:groupId` and R-110 `/watchlist` (`12` §2): SCR-100 as the routed page in the shell's `main` until
 * E15's pane host (pre-ruling 1), its heading the panel header's "Watchlist", and SCR-101 over it as query state,
 * `?modal=watchlists` (`14` SCR-101; E08-D07 D24), which R-110 opens. The page supplies the defaults: the app's REST
 * client, the connection's ticker hub, the instrument index, the session's `workspaces:write` (read from the shell's
 * `/me`, never a role name; the server enforces it, C-2.12) and the navigation: a tab switches the route (marked
 * `ROUTE_FOCUS_KEEP`, so focus stays on the tab: #304 S10), the panel's
 * manager paths open SCR-101 (a history entry, so Back closes it) with their intent, and an id that is none of the
 * user's lists is the not-found state. When SCR-101 closes the panel reads the lists again; a list it deleted that
 * the page showed hands the page to the list it shows (or the first); R-110 goes to that list, or with none stays,
 * showing the no-list state (its `?modal=watchlists` gone too, however it came). With no opener to return focus to (a
 * deep link, a reload, R-110), closing puts it on the page: the shown list's tab, else its first control ("Create
 * watchlist"), else its heading.
 */
import { useEffect, useId, useMemo, useRef, useState, type JSX, type RefObject } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { EmptyState } from "@candleviewer/ui";
import { useShellSelector } from "../../shell/useShellSelector";
import { NotFoundState } from "../../routes/ErrorStates";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { ROUTE_FOCUS_KEEP } from "../app-shell/useRouteFocus";
import { COPY } from "./copy";
import { useWatchlistIndex } from "./instruments";
import { MODAL_PARAM, MODAL_WATCHLISTS, type ManagerIntent } from "./manager/intent";
import { WatchlistManager, type ManagerOutcome } from "./manager/WatchlistManager";
import { WatchlistPanel } from "./WatchlistPanel";
import { createWatchlistSync } from "./sync";
import { useTickerHub } from "./ticker/wsTickerTransport";
import { createWatchlistApi } from "./watchlistApi";

/** The page's pane until panes exist: one watchlist pane per route visit. */
export const ROUTE_PANE = "r111";
/** Marks the history entry this page pushed to open SCR-101: closing goes back over it. */
const OPENED_HERE = "cvWatchlistsOpened";

const listPath = (id: string): string => `/watchlist/${encodeURIComponent(id)}`;

export function WatchlistRoute(): JSX.Element {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const api = useMemo(() => createWatchlistApi(), []);
  const sync = useMemo(() => createWatchlistSync(), []);
  const hub = useTickerHub();
  const instruments = useWatchlistIndex();
  const writable = useShellSelector((s) => s.me?.permissions.includes("workspaces:write") === true);
  const [missing, setMissing] = useState<string | null>(null);
  const [intent, setIntent] = useState<ManagerIntent | undefined>(undefined);
  /** R-110 closed with no list: the page shows the no-list state instead. */
  const [dismissed, setDismissed] = useState(false);
  const atManager = groupId === undefined;
  const managerOpen = params.get(MODAL_PARAM) === MODAL_WATCHLISTS || (atManager && !dismissed);
  // Where focus goes when SCR-101 closes with no opener left (A-5335-08): read as it closes, on the page then shown.
  const headingId = useId();
  const pageFocus = useMemo<RefObject<HTMLElement | null>>(
    () => ({
      get current() {
        const heading = document.getElementById(headingId);
        const page = heading?.parentElement ?? null;
        return (
          page?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]') ??
          page?.querySelector<HTMLElement>('button:not([aria-disabled="true"])') ??
          heading
        );
      },
    }),
    [headingId],
  );
  // However SCR-101 closes (its Close, `Esc`, Back), the panel reads the lists again and the intent is spent.
  const wasOpen = useRef(managerOpen);
  useEffect(() => {
    if (wasOpen.current && !managerOpen) {
      sync.publish({ kind: "reread" });
      setIntent(undefined);
    }
    wasOpen.current = managerOpen;
  }, [managerOpen, sync]);

  const openManager = (next: ManagerIntent): void => {
    setIntent(next);
    if (atManager) {
      setDismissed(false);
      return;
    }
    const query = new URLSearchParams(params);
    query.set(MODAL_PARAM, MODAL_WATCHLISTS);
    setParams(query, { state: { [OPENED_HERE]: true } });
  };
  const closeManager = (outcome: ManagerOutcome): void => {
    const next = outcome.selectedId ?? outcome.listIds[0];
    const shownGone = groupId !== undefined && !outcome.listIds.includes(groupId);
    if ((atManager || shownGone) && next !== undefined) {
      void navigate(listPath(next), { replace: true });
      return;
    }
    if (atManager) {
      setDismissed(true);
      // A typed or linked `?modal=watchlists` goes too, or the manager would stay open (C-5335-06).
      if (params.has(MODAL_PARAM)) {
        const query = new URLSearchParams(params);
        query.delete(MODAL_PARAM);
        setParams(query, { replace: true });
      }
      return;
    }
    const opened = (location.state as Readonly<Record<string, unknown>> | null)?.[OPENED_HERE];
    if (opened === true) {
      void navigate(-1);
      return;
    }
    const query = new URLSearchParams(params);
    query.delete(MODAL_PARAM);
    setParams(query, { replace: true });
  };

  const manager = managerOpen ? (
    <WatchlistManager
      api={api}
      sync={sync}
      instruments={instruments}
      initialListId={groupId}
      intent={intent}
      readOnly={!writable}
      onClose={closeManager}
      fallbackFocusRef={pageFocus}
    />
  ) : null;

  if (atManager)
    return (
      <ScreenRoot>
        <h1 id={headingId} tabIndex={-1}>
          {COPY.title}
        </h1>
        {managerOpen ? null : writable ? (
          <EmptyState
            title={COPY.noListsTitle}
            actions={[{ label: COPY.createList, onClick: () => openManager({ kind: "create" }) }]}
          />
        ) : (
          // The sentence form (E09-D09 §2.2): the reason alone, no button.
          <EmptyState title={COPY.noListsReadOnly} description={COPY.writeReason} />
        )}
        {manager}
      </ScreenRoot>
    );
  if (missing === groupId && !managerOpen) return <NotFoundState />;
  return (
    <ScreenRoot>
      <h1 id={headingId} tabIndex={-1}>
        {COPY.title}
      </h1>
      <WatchlistPanel
        listId={groupId}
        paneId={ROUTE_PANE}
        api={api}
        hub={hub}
        instruments={instruments}
        readOnly={!writable}
        sync={sync}
        onSwitchList={(id) => void navigate(listPath(id), { state: { [ROUTE_FOCUS_KEEP]: true } })}
        onManage={openManager}
        onMissing={() => setMissing(groupId)}
      />
      {manager}
    </ScreenRoot>
  );
}
