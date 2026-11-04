import { useEffect, useReducer, useRef, type JSX } from "react";
import { accessToken } from "../../lib/auth/accessToken";
import { getActiveClient } from "../../lib/ws/client/activeClient";
import { useWsState } from "../../lib/ws/client/useWsState";
import {
  connectionRegion,
  regionAnnouncement,
  type ConnectionRegionView,
  type RegionReason,
} from "../../lib/ws/state/connectionRegion";
import { useShellSelector } from "../../shell/useShellSelector.js";
import {
  announce,
  clearAnnouncements,
  CONNECTION_KEYS,
  CONNECTION_PREFIX,
  forget,
} from "./announcer";
import { RecoveredRegionSlot } from "../reconciliation/RecoveredRegion";
import { streamReady } from "../reconciliation/reassurance";
import { stopsConfirmedNow, useStopsConfirmed } from "../reconciliation/stopsConfirmed";
import { ConnectionRegion } from "./ConnectionRegion";

/**
 * The announcer key of a §11 row: rows 1 and 14 are `CONNECTION_KEYS` (once per episode, also
 * across a remount); row 2 has one key per read-only reason.
 */
function keyOf(reason: RegionReason): string {
  if (reason === "disconnected") return CONNECTION_KEYS.disconnected;
  if (reason === "fatal" || reason === "session") return CONNECTION_KEYS.retryStopped;
  return `${CONNECTION_PREFIX}read-only:${reason}`;
}

const EPISODE: ReadonlySet<RegionReason> = new Set(["disconnected", "fatal", "session"]);

/** The views whose text moves with the clock: the countdown, the ages, the 30 s / 5 min steps. */
const ticks = (view: ConnectionRegionView | null): boolean =>
  view?.state === "reconnecting" || view?.state === "long-outage";

const signIn = (): void => accessToken.endSession();
/** CMP-077 `Retry now`: the client refuses it after a 4403 and while a handshake is under way. */
const retryNow = (): void => void getActiveClient()?.retryNow();

/**
 * CMP-077's container (#306 slice 4b), the banner slot's first content (`ShellBanner`):
 * `useWsState` and the shell store's private-feed hand-over → slice 4a's `connectionRegion`. It
 * re-renders at 1 Hz only while the view has a clock in it. It is the one writer of E17-D02 §11
 * rows 1, 2 and 14 (the chip announces nothing), through the shell announcer, on a change of
 * reason and never per tick; it ends the Disconnected episode itself when the link is back.
 *
 * While the session holds a view-as context (E42-S03), a `4403` close is the server ending or
 * holding that context (`bye` `view_as_expired`, `23` §9.6), never "Session ended": the region
 * shows nothing and says nothing for it, and SCR-124's banner speaks (V-8).
 */
export function ConnectionRegionSlot(): JSX.Element {
  const ws = useWsState();
  const privateFeedDown = useShellSelector((s) => s.degraded.privateHandedOver);
  const viewing = useShellSelector((s) => s.viewAs.kind === "held");
  const [, tick] = useReducer((n: number) => n + 1, 0);
  // Read at render: a transition renders with the clock of that moment, never the last tick's.
  // E29-S07 (#1028): the stops clause only while the reassurance gate holds (BQ-7 ruled)
  // With the link up the claim also needs the stream live and the private snapshots in: the watch
  // that drops a verdict at a delta runs only then, so the claim is never read off a stale verdict.
  const stopsConfirmed =
    useStopsConfirmed() && (ws.link.kind !== "up" || streamReady(ws, privateFeedDown));
  const region = connectionRegion(ws, Date.now(), { privateFeedDown, stopsConfirmed });
  // A viewer disabled while viewing gets a 4403 too (`bye user_disabled`): muted here, it is
  // surfaced by the view-as source, whose re-read on that close the server answers 401, and the
  // token holder routes to sign-in (`accessToken.ts`). Only that re-read failing on the network
  // leaves the chip alone to show the loss.
  const muted = (r: ConnectionRegionView | null): ConnectionRegionView | null =>
    viewing && r?.reason === "session" ? null : r;
  const view = muted(region);
  const last = useRef<ConnectionRegionView | null>(null);

  useEffect(() => {
    const prev = last.current;
    last.current = view;
    if (prev?.reason === view?.reason) return;
    // Leaving a reason lets its next entry speak: row 14 once per entry, row 2 per reason; row 1's
    // key stays for the whole episode (a retry after a stop is no new episode).
    if (prev !== null && prev.reason !== "disconnected") forget(keyOf(prev.reason));
    // The link is back: the episode ends. Scoped to the connection keys: it forgets rows 1, 14
    // and the row 2 keys (safe, as the next reason is said below) and empties a live region only
    // while it holds a connection message, so no stale alert outlives the outage and another
    // writer's announcement stays.
    if (prev !== null && EPISODE.has(prev.reason) && (view === null || !EPISODE.has(view.reason))) {
      clearAnnouncements(CONNECTION_PREFIX);
    }
    // E29-S07 (#1028, review of #5759): what is spoken is judged when it is spoken, not at the render. The
    // watch's stop (the cleanup of RecoveredRegion's effect) applies the frames still buffered at the link drop
    // before this effect runs, and a verdict it drops there must not be read out as a stops claim. Only the
    // store half of the gate can have moved since the render (`ws` and the hand-over are the render's own).
    // The recomputed region takes the same view-as mute as the shown one (E42-S03 V-8).
    const claimDropped = stopsConfirmed && !stopsConfirmedNow();
    const spoken =
      claimDropped && view !== null
        ? muted(connectionRegion(ws, Date.now(), { privateFeedDown, stopsConfirmed: false }))
        : view;
    const said = regionAnnouncement(prev, spoken);
    if (said !== null && view !== null) announce(said.politeness, said.text, keyOf(view.reason));
  });

  const clocked = ticks(view);
  useEffect(() => {
    if (!clocked) return undefined;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [clocked]);

  // E29-S07 (#1028): `recovered` is kept mounted beside the other states, to see the outage begin.
  return (
    <>
      {view === null ? null : (
        <ConnectionRegion
          view={view}
          onSignIn={signIn}
          onRetryNow={retryNow}
          retrying={ws.link.kind === "connecting"}
        />
      )}
      <RecoveredRegionSlot ws={ws} privateFeedDown={privateFeedDown} visible={view === null} />
    </>
  );
}
