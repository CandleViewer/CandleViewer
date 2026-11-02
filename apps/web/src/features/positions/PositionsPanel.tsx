/**
 * SCR-063, the Positions & orders grid panel, on R-130 `/positions` (E29-S01 #911): the page's
 * heading, the panel's notices and the five tabs (E29-D02 §4, D-17), the Positions tab live
 * (`PositionsTab.tsx`) and the other four placeholders (BQ-15). The route tree mounts it lazily
 * (BQ-16), so none of this is in the first bundle.
 *
 * - **The session** (`positionsSession.ts`): the feed, the positions store and the account signals,
 *   with the feed's announcements and the sort, live as long as the panel. CMP-042 mounts only the
 *   selected tab, so a tab switch keeps the book, every account's state and its "since", and says
 *   nothing again; the feed runs, and speaks, while another tab shows.
 * - **View state** (BQ-16): per user on this device under `panelState.ts`'s versioned key, in the
 *   `layoutStore` shape; R-130's `?groupBy=` and `?account=` deep links (`12` §7) set the view
 *   over it without being stored, and the server re-validates an account's scope whatever a link says.
 *   The tabs wait for that view (a layout effect, before paint), so a stored tab never mounts another.
 * - **Notices over every tab**, in the band under the toolbar (D02 §2, D-16; boards 16 and 17): the
 *   kill switch (S-19 for the Owner, S-20 for every other role; D02 §10.3), from `WsState` and the
 *   engage time on the shell's last `system` frame, CMP-028 `danger` with CMP-019's `lock`,
 *   `live="off"` and never dismissible while it holds; and a read-only session's one panel-header
 *   notice (S-22, D02 §10.4) led by the `lock`: one `rbac.permission` line per write the session
 *   lacks, verbatim, each its own node, its id keyed by its permission (`noticeIdOf`), in the DOM at
 *   mount, for the gated controls to point at (`32-design-specs.md` G-T2.5). This PR mounts no
 *   write control (BQ-3), so none points yet.
 * - **Announcements:** the panel's announcer (`usePanelAnnouncer`) writes to the shell's; the gated
 *   announcement of the atoms below (G-T2.3) is routed there too, as each screen owns its own
 *   (`ShellLayout`'s provider is a no-op).
 * - **First visit:** the route's focus move runs before this lazy chunk renders and lands on the
 *   shell's `main`; the panel completes it on mount, to its `h1` (a restoration, E09-D09 §9.4).
 */
import "./positions.css";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type JSX,
  type ReactNode,
} from "react";
import { useLocation } from "react-router";
import { Callout, GatedAnnounceProvider, Icon, Tabs, type TabItem } from "@candleviewer/ui";
import { getActiveClient, subscribeActiveClient } from "../../lib/ws/client/activeClient";
import type { KillSwitchView } from "../../lib/ws/state/types";
import { ROUTE_TITLES } from "../../routes/titles";
import { useShellSelector } from "../../shell/useShellSelector";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { engagedAtOf, killSwitchBanner, useAccountSignals, type Role } from "./accountSignals";
import { usePanelAnnouncer, type PanelAnnouncer } from "./announce";
import { bindKinds, D02_TEXT, permissionLines, type WritePermission } from "./copy";
import { reportOpened } from "./events";
import { useFeedAnnouncements } from "./feedAnnouncements";
import type { SortState } from "./model/sort";
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
import {
  usePositionsSession,
  type FeedClient,
  type PositionsDeps,
  type PositionsSession,
} from "./positionsSession";
import { usePositions } from "./positionsStore";
import { PositionsTab, utcTime } from "./PositionsTab";

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

/**
 * The S-22 notice's line ids by the permission each names (E29-S03's gated controls point at
 * them): `${notice}-${suffix}`, stable whatever else the session lacks.
 */
export const NOTICE_ID_SUFFIX: Readonly<Record<WritePermission, string>> = {
  "positions:write": "positions-write",
  "orders:write": "orders-write",
};
export const noticeIdOf = (notice: string, permission: WritePermission): string =>
  `${notice}-${NOTICE_ID_SUFFIX[permission]}`;

/** The client's kill switch as `useSyncExternalStore` reads it: `unknown` without a client. */
function useKillSwitch(client: FeedClient | null): KillSwitchView {
  const read = (): KillSwitchView => client?.getState().killSwitch ?? UNKNOWN;
  return useSyncExternalStore(client?.subscribe ?? noSubscription, read, read);
}

/** S-19 and S-20 (D02 §10.3; board 16): the kill switch's band while it is engaged. */
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
      <Callout tone="danger" icon="lock" live="off" title={title ?? ""}>
        {more.length === 0 ? undefined : <p>{more.join(" ")}</p>}
      </Callout>
    </div>
  );
}

/** The feed's announcements for the panel's life (`feedAnnouncements.ts`); it renders nothing. */
function FeedAnnouncements({
  session,
  announcer,
}: {
  readonly session: PositionsSession;
  readonly announcer: PanelAnnouncer;
}): null {
  const snap = usePositions(session.store, (s) => s);
  const accounts = useAccountSignals(session.signals, (s) => s.accounts);
  const shellEnv = useShellSelector((s) => s.environment);
  useFeedAnnouncements({
    snap,
    accounts,
    environment: shellEnv !== "unknown" ? shellEnv : (snap.accounts[0]?.environment ?? null),
    announcer,
    spokenByFocus: session.spokenByFocus,
  });
  return null;
}

export interface PositionsPanelProps {
  /** A test's client and seams; the route passes none (the app's active client, the real API). */
  readonly deps?: PositionsDeps | undefined;
}

export function PositionsPanel({ deps }: PositionsPanelProps = {}): JSX.Element {
  const headingId = useId();
  const noticeId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const { search } = useLocation();
  const userId = useShellSelector((s) => s.me?.user?.id ?? null);
  const role: Role = useShellSelector((s) => s.me?.role ?? null) ?? "viewer";
  const permissions = useShellSelector((s) => (s.me === null ? null : (s.me.permissions ?? NONE)));
  const tab = usePanelState("tab");
  const active = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const client: FeedClient | null = deps?.client ?? active;
  const announcer = usePanelAnnouncer();
  const session = usePositionsSession(client, deps?.feed);
  const [sort, setSort] = useState<SortState | null>(null);
  const [ready, setReady] = useState(false);

  // Whose view, then the link over it, at mount and on each new link, before the tabs mount: the
  // first committed render holds them, and this effect's update renders them before paint. The
  // panel's readers subscribe in their passive effects (React 18's `useSyncExternalStore`), so the
  // toolbar can show the stored view for a moment before the link's.
  useLayoutEffect(() => {
    setPanelUser(userId);
    applyDeepLink(readDeepLink(search));
    setReady(true);
  }, [userId, search]);
  useEffect(() => reportOpened(getPanelState().tab), []);

  // The first visit's route focus fell to the shell's `main` before this chunk rendered: complete it.
  useEffect(() => {
    const h1 = heading.current;
    const main = h1?.closest("main");
    if (h1 === null || main == null || document.activeElement !== main) return;
    if (!h1.hasAttribute("tabindex")) {
      h1.setAttribute("tabindex", "-1");
      h1.addEventListener("blur", () => h1.removeAttribute("tabindex"), { once: true });
    }
    h1.focus();
  }, []);

  // S-22: one panel-header notice of the writes the session lacks (a Viewer's two lines).
  const lines = permissions === null ? [] : permissionLines(permissions);
  const notices: ReactNode = (
    <>
      <KillSwitchBanner client={client} role={role} />
      {lines.length === 0 ? null : (
        <div id={noticeId} className="cv-positions__notice" data-part="ReadOnlyNotice">
          <span className="cv-positions__lock">
            <Icon name="lock" />
          </span>
          <div className="cv-positions__notice-lines">
            {lines.map(({ permission, line }) => (
              <p
                key={permission}
                id={noticeIdOf(noticeId, permission)}
                className="cv-positions__reason"
              >
                {line}
              </p>
            ))}
          </div>
        </div>
      )}
    </>
  );
  return (
    <ScreenRoot>
      <div className="cv-positions" data-scr="SCR-063">
        <h1 id={headingId} ref={heading} className="cv-positions__title">
          {ROUTE_TITLES["R-130"]}
        </h1>
        {ready ? (
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
                if (shown === "positions") {
                  return (
                    <PositionsTab
                      session={session}
                      announcer={announcer}
                      sort={sort}
                      setSort={setSort}
                      notices={notices}
                      saveFile={deps?.saveFile}
                      wall={deps?.feed?.wall}
                    />
                  );
                }
                if (shown === undefined) return null;
                return (
                  <div className="cv-positions__tab">
                    {notices}
                    <PlaceholderTab tab={shown} />
                  </div>
                );
              }}
            />
          </GatedAnnounceProvider>
        ) : null}
        <FeedAnnouncements session={session} announcer={announcer} />
      </div>
    </ScreenRoot>
  );
}
