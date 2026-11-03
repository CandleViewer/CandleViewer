// E24-S08 (#783) slice 1: the React side of the basis feed. It starts one feed for the symbol on the app's
// active WS client, restarts it when the client or symbol changes, and releases it on unmount.
import { useEffect, useState, useSyncExternalStore } from "react";
import { getActiveClient, subscribeActiveClient } from "../../lib/ws/client/activeClient";
import { BASIS_SYMBOL, startBasisFeed, type BasisClock, type BasisFeedHandle } from "./basisFeed";

export interface BasisFeedHookOptions {
  readonly paneId: string;
  readonly clock?: BasisClock | undefined;
}

/** The running feed, or `null` without a client or for a symbol that is not a USDT perpetual. */
export function useBasisFeed(
  symbol: string,
  options: BasisFeedHookOptions,
): BasisFeedHandle | null {
  const { paneId, clock } = options;
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const [feed, setFeed] = useState<BasisFeedHandle | null>(null);

  useEffect(() => {
    if (client === null || !BASIS_SYMBOL.test(symbol)) return undefined;
    const started = startBasisFeed(client, { symbol, paneId, clock });
    setFeed(started);
    return () => {
      started.stop();
      setFeed((current) => (current === started ? null : current));
    };
  }, [client, symbol, paneId, clock]);

  // a symbol change never shows the previous feed, not even for one render
  return feed?.symbol === symbol ? feed : null;
}
