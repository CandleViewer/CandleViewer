/**
 * SCR-063, the Positions & orders grid panel, on R-130 `/positions` (E29-S01 #911): the page's
 * heading, the panel's notices and the five tabs (E29-D02 §4, D-17), the Positions tab live
 * (`PositionsTab.tsx`) and the other four placeholders (BQ-15). The route tree mounts it lazily
 * (BQ-16), so none of this is in the first bundle.
 *
 * - **View state** (BQ-16): per user on this device under `panelState.ts`'s versioned key, in the
 *   `layoutStore` shape; R-130's `?groupBy=` and `?account=` deep links (`12` §7) set the view
 *   over it without being stored, and the server re-validates an account's scope whatever a link says.
 * - **Notices over every tab:** the kill switch (S-19 for the Owner, S-20 for every other role; D02
 *   §10.3), from `WsState` and the engage time on the shell's last `system` frame, CMP-028 `danger`,
 *   `live="off"` and never dismissible while it holds; and a read-only session's one panel-header
 *   notice (S-22, D02 §10.4): one `rbac.permission` line per write the session lacks, verbatim, each
 *   line its own node with a stable id, in the DOM at mount, for the gated controls to point at
 *   (`32-design-specs.md` G-T2.5). This PR mounts no write control (BQ-3), so none points yet.
 * - **Announcements:** the tab's lines go to the shell's announcer through `announce.ts`; the
 *   gated announcement of the atoms below (G-T2.3) is routed there too, as each screen owns its
 *   own (`ShellLayout`'s provider is a no-op).
 */
import "./positions.css";
import { useEffect, useId, useLayoutEffect, useState, useSyncExternalStore, type JSX } from "react";
import { useLocation } from "react-router";
import { Callout, GatedAnnounceProvider, Tabs, type TabItem } from "@candleviewer/ui";
import { getActiveClient, subscribeActiveClient } from "../../lib/ws/client/activeClient";
import type { KillSwitchView } from "../../lib/ws/state/types";
import { ROUTE_TITLES } from "../../routes/titles";
import { useShellSelector } from "../../shell/useShellSelector";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { engagedAtOf, killSwitchBanner, type Role } from "./accountSignals";
import { createPanelAnnouncer } from "./announce";
import { bindKinds, D02_TEXT, permissionLines } from "./copy";
import { reportOpened } from "./events";
import {
  applyDeepLink,
  getPanelState,
  PANEL_TABS,
  readDeepLink,
  setPanelUser,
  updatePanelState,
  usePanelState,
  type PanelTab,
} from "./panelState";
import { PlaceholderTab } from "./PlaceholderTab";
import { PositionsTab, utcTime, type FeedClient, type PositionsDeps } from "./PositionsTab";

const TAB_WORDS: Readonly<Record<PanelTab, string>> = {
  positions: D02_TEXT.tabPositions.string,
  working_orders: D02_TEXT.tabWorkingOrders.string,
  fills: D02_TEXT.tabFills.string,
  trade_groups: D02_TEXT.tabTradeGroups.string,
  algos: D02_TEXT.tabAlgos.string,
};
const TABS: readonly TabItem[] = PANEL_TABS.map((id) => ({ id, label: TAB_WORDS[id] }));
const UNKNOWN: KillSwitchView = Object.freeze({ state: "unknown" });
const NONE: readonly string[] = [];
const noSubscription = (): (() => void) => () => undefined;

/** The client's kill switch as `useSyncExternalStore` reads it: `unknown` without a client. */
function useKillSwitch(client: FeedClient | null): KillSwitchView {
  const read = (): KillSwitchView => client?.getState().killSwitch ?? UNKNOWN;
  return useSyncExternalStore(client?.subscribe ?? noSubscription, read, read);
}

/** S-19 and S-20 (D02 §10.3): the kill switch's banner while it is engaged, over every tab. */
function KillSwitchBanner({
  client,
  role,
}: {
  readonly client: FeedClient | null;
  readonly role: Role;
}): JSX.Element | null {
  const view = useKillSwitch(client);
  const engagedAt = useShellSelector((s) => engagedAtOf(s.systemByKind));
  if (view.state !== "engaged") return null;
  const [title, ...more] = killSwitchBanner(role).map((key) =>
    bindKinds(key, { time: utcTime(engagedAt) }),
  );
  return (
    <div className="cv-positions__banner" data-part="KillSwitchBanner">
      <Callout tone="danger" live="off" title={title ?? ""}>
        {more.length === 0 ? undefined : <p>{more.join(" ")}</p>}
      </Callout>
    </div>
  );
}

export interface PositionsPanelProps {
  /** A test's client and seams; the route passes none (the app's active client, the real API). */
  readonly deps?: PositionsDeps | undefined;
}

export function PositionsPanel({ deps }: PositionsPanelProps = {}): JSX.Element {
  const headingId = useId();
  const noticeId = useId();
  const { search } = useLocation();
  const userId = useShellSelector((s) => s.me?.user?.id ?? null);
  const role: Role = useShellSelector((s) => s.me?.role ?? null) ?? "viewer";
  const permissions = useShellSelector((s) => (s.me === null ? null : (s.me.permissions ?? NONE)));
  const tab = usePanelState("tab");
  const active = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const client: FeedClient | null = deps?.client ?? active;
  const [announcer] = useState(() => createPanelAnnouncer());
  useEffect(() => () => announcer.dispose(), [announcer]);

  // Whose view, then the link over it, at mount and on each new link. The panel's readers subscribe in their
  // passive effects (React 18's `useSyncExternalStore`), so the toolbar can show the stored view for a moment
  // before the link's; the rows come later, with the feed's first read.
  useLayoutEffect(() => {
    setPanelUser(userId);
    applyDeepLink(readDeepLink(search));
  }, [userId, search]);
  useEffect(() => reportOpened(getPanelState().tab), []);

  // S-22: one panel-header notice of the writes the session lacks (a Viewer's two lines).
  const lines = permissions === null ? NONE : permissionLines(permissions);
  return (
    <ScreenRoot>
      <div className="cv-positions" data-scr="SCR-063">
        <h1 id={headingId} className="cv-positions__title">
          {ROUTE_TITLES["R-130"]}
        </h1>
        <KillSwitchBanner client={client} role={role} />
        {lines.length === 0 ? null : (
          <div id={noticeId} className="cv-positions__notice" data-part="ReadOnlyNotice">
            {lines.map((line, i) => (
              <p key={line} id={`${noticeId}-${String(i)}`} className="cv-positions__reason">
                {line}
              </p>
            ))}
          </div>
        )}
        <GatedAnnounceProvider announce={(reason) => announcer.say("polite", reason)}>
          <Tabs
            aria-labelledby={headingId}
            tabs={TABS}
            value={tab}
            onChange={(id) => {
              const next = PANEL_TABS.find((t) => t === id);
              if (next !== undefined) updatePanelState({ tab: next });
            }}
            renderPanel={(id) => {
              const shown = PANEL_TABS.find((t) => t === id);
              if (shown === "positions")
                return <PositionsTab client={client} announcer={announcer} deps={deps} />;
              return shown === undefined ? null : <PlaceholderTab tab={shown} />;
            }}
          />
        </GatedAnnounceProvider>
      </div>
    </ScreenRoot>
  );
}
