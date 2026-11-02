/**
 * The Positions panel's session (E29-S01 #911): the feed (`wsPositions.ts`), the positions store and
 * the account signals, owned by `PositionsPanel` for the route's life. CMP-042 mounts the selected
 * tab's panel only, so a session owned by the Positions tab would end on every tab switch: the book
 * re-read, every account state but the shell's last notice lost, a lock's "since" moved to the
 * return and its announcement said again. Owned here, a tab switch keeps the book and the states,
 * and the feed runs while another tab shows.
 */
import { useEffect, useRef, useState } from "react";
import type { WsClient } from "../../lib/ws/api";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";
import {
  createAccountSignals,
  startAccountSignals,
  type AccountSignalsStore,
} from "./accountSignals";
import { createPositionsStore, type PositionsStore, type Withdrawn } from "./positionsStore";
import type { SaveFile } from "./exportFile";
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

export interface PositionsSession {
  readonly store: PositionsStore;
  readonly signals: AccountSignalsStore;
  /** S-02's Retry: the running feed's; nothing while none runs. */
  readonly retry: () => void;
  /** The withdrawn lines a focus move spoke (E29-D05 F-02): the tab writes, the panel reads. */
  readonly spokenByFocus: WeakSet<Withdrawn>;
}

/** The session for `client` (none without one), its feed restarted only when the client changes. */
export function usePositionsSession(
  client: FeedClient | null,
  feed: PositionsDeps["feed"],
): PositionsSession {
  const [store] = useState(createPositionsStore);
  const [signals] = useState(createAccountSignals);
  const running = useRef<PositionsFeed | null>(null);
  useEffect(() => {
    if (client === null) return undefined;
    const started = startPositionsFeed({ ...feed, client, store, signals });
    running.current = started;
    const stopSignals = startAccountSignals(signals, {
      shell: { getState: getShellState, subscribe: subscribeShellState },
      ws: client,
      wall: feed?.wall,
    });
    return () => {
      stopSignals();
      started.stop();
      if (running.current === started) running.current = null;
    };
  }, [client, store, signals, feed]);
  const [session] = useState<PositionsSession>(() => ({
    store,
    signals,
    retry: () => running.current?.retry(),
    spokenByFocus: new WeakSet(),
  }));
  return session;
}
