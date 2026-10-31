/**
 * R-111 `/watchlist/:groupId` (`12` §2): SCR-100 as the routed page in the shell's `main` until E15's pane host
 * (pre-ruling 1), its heading the panel header's "Watchlist". The page supplies the panel's defaults: the app's REST
 * client, the connection's ticker hub, the instrument index, the session's `workspaces:write` (read from the shell's
 * `/me`, never a role name; the server enforces it, C-2.12) and the navigation: a tab switches the route, the
 * manager's paths go to R-110 (SCR-101, #4702 PR c), and an id that is none of the user's lists is the not-found state.
 */
import { useMemo, useState, type JSX } from "react";
import { useNavigate, useParams } from "react-router";
import { useShellSelector } from "../../shell/useShellSelector";
import { NotFoundState } from "../../routes/ErrorStates";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { COPY } from "./copy";
import { useWatchlistIndex } from "./instruments";
import { MANAGER_HREF, WatchlistPanel } from "./WatchlistPanel";
import { useTickerHub } from "./ticker/wsTickerTransport";
import { createWatchlistApi } from "./watchlistApi";

/** The page's pane until panes exist: one watchlist pane per route visit. */
export const ROUTE_PANE = "r111";

export function WatchlistRoute(): JSX.Element {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const api = useMemo(() => createWatchlistApi(), []);
  const hub = useTickerHub();
  const instruments = useWatchlistIndex();
  const writable = useShellSelector((s) => s.me?.permissions.includes("workspaces:write") === true);
  const [missing, setMissing] = useState<string | null>(null);
  if (groupId === undefined || missing === groupId) return <NotFoundState />;
  return (
    <ScreenRoot>
      <h1>{COPY.title}</h1>
      <WatchlistPanel
        listId={groupId}
        paneId={ROUTE_PANE}
        api={api}
        hub={hub}
        instruments={instruments}
        readOnly={!writable}
        onSwitchList={(id) => void navigate(`/watchlist/${encodeURIComponent(id)}`)}
        onManage={() => void navigate(MANAGER_HREF)}
        onMissing={() => setMissing(groupId)}
      />
    </ScreenRoot>
  );
}
