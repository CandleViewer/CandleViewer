// E22-S01 (#714) PR-A: the React side of the tape's subscription. It starts one feed loop for the
// symbol on the app's active WS client (`activeClient.ts`, as `useWsState` reads it), restarts it
// when the client or the symbol changes, and releases it on unmount. Behind `TAPE_ENABLED`
// (BQ-217): off, it subscribes to nothing. The panel (PR-B) reads coarse state with
// `useTapeSnapshot(feed?.store)` and rows from `feed.ring` in `feed.onFrame`.
import { useEffect, useState, useSyncExternalStore } from "react";
import type { WsClient } from "../../lib/ws/api";
import { getActiveClient, subscribeActiveClient } from "../../lib/ws/client/activeClient";
import { TAPE_ENABLED } from "./flag";
import { startTapeFeed, TAPE_SYMBOL, type TapeClock, type TapeFeedHandle } from "./model/tapeFeed";

export interface TapeSubscriptionOptions {
  readonly paneId: string;
  /** Defaults to the build-time flag; a harness may force it. */
  readonly enabled?: boolean | undefined;
  readonly capacity?: number | undefined;
  readonly clock?: TapeClock | undefined;
  /** A client other than the app's active one (the Playwright harness, the stories, tests). */
  readonly client?: Pick<WsClient, "consume" | "setPane"> | undefined;
}

/** The running feed, or `null` while off, without a client, or for a symbol that is not valid. */
export function useTapeSubscription(
  symbol: string,
  options: TapeSubscriptionOptions,
): TapeFeedHandle | null {
  const { paneId, capacity, clock } = options;
  const enabled = options.enabled ?? TAPE_ENABLED;
  const active = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const client = options.client ?? active;
  const [feed, setFeed] = useState<TapeFeedHandle | null>(null);

  useEffect(() => {
    if (!enabled || client === null) return undefined;
    if (!TAPE_SYMBOL.test(symbol)) return undefined; // a symbol outside it subscribes to nothing
    const started = startTapeFeed(client, { symbol, paneId, capacity, clock });
    started.setVisibility("visible");
    setFeed(started);
    return () => {
      started.stop();
      setFeed((current) => (current === started ? null : current));
    };
  }, [enabled, client, symbol, paneId, capacity, clock]);

  // a symbol change never shows the previous symbol's feed, not even for one render
  return feed?.symbol === symbol ? feed : null;
}
