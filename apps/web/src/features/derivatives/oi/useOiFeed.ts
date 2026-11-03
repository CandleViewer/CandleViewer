// E24-S01 (#776) slice 1: the React side of the OI pane's feed. It starts one feed for the symbol on the
// app's active WS client, restarts it when the client, symbol, bar or window changes, and releases it on
// unmount. A bar change for the same symbol is `oi_panel.interval_changed` (D02 §14).
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getActiveClient, subscribeActiveClient } from "../../../lib/ws/client/activeClient";
import { createOiAnalytics, type OiAnalytics } from "./analytics";
import { fetchOiHistory, type HistoryRequest, type HistoryResult } from "./history";
import { OI_SYMBOL, startOiFeed, type OiClock, type OiFeedHandle } from "./oiFeed";

export interface OiFeedHookOptions {
  readonly paneId: string;
  readonly barMs: number;
  readonly fromMs: number;
  readonly toMs: number;
  readonly loadHistory?: ((req: HistoryRequest) => Promise<HistoryResult>) | undefined;
  readonly clock?: OiClock | undefined;
  readonly analytics?: OiAnalytics | undefined;
}

const defaultAnalytics = createOiAnalytics();

/**
 * The running feed, or `null` without a client or for a symbol that is not a USDT perpetual.
 *
 * Contract: the window (`fromMs`/`toMs`), `analytics`, `loadHistory` and `clock` are effect dependencies, so
 * they must be stable across renders (primitives, module constants or memoised); a value that changes
 * identity or number rebuilds the feed: it stops, resubscribes and refetches history.
 */
export function useOiFeed(symbol: string, options: OiFeedHookOptions): OiFeedHandle | null {
  const { paneId, barMs, fromMs, toMs, clock } = options;
  const loadHistory = options.loadHistory ?? fetchOiHistory;
  const analytics = options.analytics ?? defaultAnalytics;
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const [feed, setFeed] = useState<OiFeedHandle | null>(null);
  const lastBar = useRef<{ symbol: string; barMs: number } | null>(null);

  useEffect(() => {
    const prev = lastBar.current;
    if (prev !== null && prev.symbol === symbol && prev.barMs !== barMs) {
      analytics.intervalChanged(symbol, prev.barMs, barMs);
    }
    lastBar.current = { symbol, barMs };
  }, [analytics, symbol, barMs]);

  useEffect(() => {
    if (client === null || !OI_SYMBOL.test(symbol)) return undefined;
    const started = startOiFeed(client, {
      symbol,
      paneId,
      barMs,
      window: { fromMs, toMs },
      loadHistory,
      clock,
      analytics,
    });
    setFeed(started);
    return () => {
      started.stop();
      setFeed((current) => (current === started ? null : current));
    };
  }, [client, symbol, paneId, barMs, fromMs, toMs, loadHistory, clock, analytics]);

  // a symbol or bar change never shows the previous feed, not even for one render
  return feed?.symbol === symbol && feed.barMs === barMs ? feed : null;
}
