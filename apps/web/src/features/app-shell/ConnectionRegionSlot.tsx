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
import { announce, CONNECTION_KEYS, forget } from "./announcer";
import { ConnectionRegion } from "./ConnectionRegion";

/**
 * The announcer key of a §11 row: rows 1 and 14 share the chip container's `CONNECTION_KEYS`, so the
 * two writers say each once per episode; row 2 has one key per read-only reason.
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
 * CMP-077's container (#306 slice 4b), `ShellCanvasOverlaySlot`'s content: `useWsState` and the
 * shell store's private-feed hand-over → slice 4a's `connectionRegion`. It re-renders at 1 Hz only
 * while the view has a clock in it, and writes §11 rows 1, 2 and 14 through the shell announcer on a
 * change of reason, never per tick. The chip container ends the episode (`clearAnnouncements` on the
 * return to live); the region forgets its own keys when its reason leaves, so a later entry speaks.
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
    // key stays for the whole episode (a retry after a stop is no new episode) and goes with it.
    if (prev !== null && prev.reason !== "disconnected") forget(keyOf(prev.reason));
    if (prev !== null && EPISODE.has(prev.reason) && (view === null || !EPISODE.has(view.reason))) {
      forget(CONNECTION_KEYS.disconnected);
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
