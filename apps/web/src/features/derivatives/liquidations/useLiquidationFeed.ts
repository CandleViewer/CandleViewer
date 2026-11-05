// E24-S05 (#780): the React side of the liquidation feed. It starts one feed for the symbol on the app's active
// WS client, restarts it when the client, symbol, filter or window changes, and releases it on unmount. BQ 3
// (ruled 6612481277): each start reads the window once, so the coverage is read per mount and per symbol change. The
// host passes a stable window (SCR-054's visible range), never a fresh `Date.now()` per render. `loadHistory` and
// `clock` are read through refs, so an inline function or object never restarts the feed.
// TODO(#778): the `min_notional_usd` filter is the host's component state until #778's `deriv` block
// carries it; no local storage.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getActiveClient, subscribeActiveClient } from "../../../lib/ws/client/activeClient";
import { createLiqAnalytics, type LiqAnalytics } from "./analytics";
import type { LiqHistoryRequest, LiqHistoryResult } from "./history";
import { fetchLiquidationHistory } from "./historyRead";
import {
  feedFilter,
  LIQ_SYMBOL,
  startLiquidationFeed,
  type LiqClock,
  type LiqFeedHandle,
} from "./liquidationFeed";

export interface LiqFeedHookOptions {
  readonly paneId: string;
  readonly fromMs: number;
  readonly toMs: number;
  readonly minNotionalUsd?: string | null | undefined;
  readonly loadHistory?: ((req: LiqHistoryRequest) => Promise<LiqHistoryResult>) | undefined;
  readonly clock?: LiqClock | undefined;
  readonly analytics?: LiqAnalytics | undefined;
}

const defaultAnalytics = createLiqAnalytics();

/** The running feed, or `null` without a client or for a symbol that is not a USDT perpetual. */
export function useLiquidationFeed(
  symbol: string,
  options: LiqFeedHookOptions,
): LiqFeedHandle | null {
  const { paneId, fromMs, toMs } = options;
  const minNotionalUsd = feedFilter(options.minNotionalUsd);
  const loadRef = useRef(options.loadHistory ?? fetchLiquidationHistory);
  const clockRef = useRef(options.clock);
  const analyticsRef = useRef(options.analytics ?? defaultAnalytics);
  // the latest props, kept in refs after each commit (never written during render); declared before the feed's
  // effect, so a start reads this render's values
  useEffect(() => {
    loadRef.current = options.loadHistory ?? fetchLiquidationHistory;
    clockRef.current = options.clock;
    analyticsRef.current = options.analytics ?? defaultAnalytics;
  });
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const [feed, setFeed] = useState<LiqFeedHandle | null>(null);

  useEffect(() => {
    if (client === null || !LIQ_SYMBOL.test(symbol) || !(fromMs < toMs)) return undefined;
    const started = startLiquidationFeed(client, {
      symbol,
      paneId,
      minNotionalUsd,
      window: { fromMs, toMs },
      loadHistory: (req) => loadRef.current(req),
      clock: clockRef.current,
      onBackfillFailed: (status, code) => analyticsRef.current.backfillFailed(symbol, status, code),
    });
    setFeed(started);
    return () => {
      started.stop();
      setFeed((current) => (current === started ? null : current));
    };
  }, [client, symbol, paneId, minNotionalUsd, fromMs, toMs]);

  // a symbol, filter or window change, or a lost client, never shows the previous feed, not even for one render
  const current =
    client !== null &&
    feed?.symbol === symbol &&
    feed.minNotionalUsd === minNotionalUsd &&
    feed.window.fromMs === fromMs &&
    feed.window.toMs === toMs;
  return current ? feed : null;
}
