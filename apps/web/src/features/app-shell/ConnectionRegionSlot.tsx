import { useEffect, useReducer, useRef, type JSX } from "react";
import { accessToken } from "../../lib/auth/accessToken";
import { useWsState } from "../../lib/ws/client/useWsState";
import {
  connectionRegion,
  regionAnnouncement,
  type ConnectionRegionView,
  type RegionReason,
} from "../../lib/ws/state/connectionRegion";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { announce, clearAnnouncements, CONNECTION_KEYS, forget } from "./announcer";
import { ConnectionRegion } from "./ConnectionRegion";

/**
 * The announcer key of a §11 row: rows 1 and 14 are `CONNECTION_KEYS` (once per episode, also
 * across a remount); row 2 has one key per read-only reason.
 */
function keyOf(reason: RegionReason): string {
  if (reason === "disconnected") return CONNECTION_KEYS.disconnected;
  if (reason === "fatal" || reason === "session") return CONNECTION_KEYS.retryStopped;
  return `connection:read-only:${reason}`;
}

const EPISODE: ReadonlySet<RegionReason> = new Set(["disconnected", "fatal", "session"]);

/** The views whose text moves with the clock: the countdown, the ages, the 30 s / 5 min steps. */
const ticks = (view: ConnectionRegionView | null): boolean =>
  view?.state === "reconnecting" || view?.state === "long-outage";

const signIn = (): void => accessToken.endSession();

/**
 * CMP-077's container (#306 slice 4b), the banner slot's first content (`ShellBanner`):
 * `useWsState` and the shell store's private-feed hand-over → slice 4a's `connectionRegion`. It
 * re-renders at 1 Hz only while the view has a clock in it. It is the one writer of E17-D02 §11
 * rows 1, 2 and 14 (the chip announces nothing), through the shell announcer, on a change of
 * reason and never per tick; it ends the Disconnected episode itself when the link is back.
 */
export function ConnectionRegionSlot(): JSX.Element | null {
  const ws = useWsState();
  const privateFeedDown = useShellSelector((s) => s.degraded.privateHandedOver);
  const [, tick] = useReducer((n: number) => n + 1, 0);
  // Read at render: a transition renders with the clock of that moment, never the last tick's.
  const view = connectionRegion(ws, Date.now(), { privateFeedDown });
  const last = useRef<ConnectionRegionView | null>(null);

  useEffect(() => {
    const prev = last.current;
    last.current = view;
    if (prev?.reason === view?.reason) return;
    // Leaving a reason lets its next entry speak: row 14 once per entry, row 2 per reason; row 1's
    // key stays for the whole episode (a retry after a stop is no new episode).
    if (prev !== null && prev.reason !== "disconnected") forget(keyOf(prev.reason));
    // The link is back: the episode ends. `clearAnnouncements` forgets every key — the row 2 keys
    // too, which is safe as the next reason is said below — and empties both live regions, so no
    // stale alert text outlives the outage.
    if (prev !== null && EPISODE.has(prev.reason) && (view === null || !EPISODE.has(view.reason))) {
      clearAnnouncements();
    }
    const said = regionAnnouncement(prev, view);
    if (said !== null && view !== null) announce(said.politeness, said.text, keyOf(view.reason));
  });

  const clocked = ticks(view);
  useEffect(() => {
    if (!clocked) return undefined;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [clocked]);

  return view === null ? null : <ConnectionRegion view={view} onSignIn={signIn} />;
}
