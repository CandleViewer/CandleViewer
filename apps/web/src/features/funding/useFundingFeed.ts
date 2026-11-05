// E24-S03 (#778) slice 1: the React side of the funding pane's history. It starts one feed for the symbol
// and window, restarts it when either changes, and stops it on unmount.
import { useEffect, useState } from "react";
import { createFundingAnalytics, type FundingAnalytics } from "./analytics";
import { FUNDING_SYMBOL, startFundingFeed, type FundingFeedHandle } from "./fundingFeed";
import {
  fetchFundingHistory,
  type FundingHistoryRequest,
  type FundingHistoryResult,
} from "./history";

export interface FundingFeedHookOptions {
  readonly fromMs: number;
  readonly toMs: number;
  readonly loadHistory?:
    ((req: FundingHistoryRequest) => Promise<FundingHistoryResult>) | undefined;
  readonly wallNow?: (() => number) | undefined;
  readonly analytics?: FundingAnalytics | undefined;
}

const defaultAnalytics = createFundingAnalytics();

/** The running feed, or `null` for a symbol that is not a USDT perpetual. */
export function useFundingFeed(
  symbol: string,
  options: FundingFeedHookOptions,
): FundingFeedHandle | null {
  const { fromMs, toMs, wallNow } = options;
  const loadHistory = options.loadHistory ?? fetchFundingHistory;
  const analytics = options.analytics ?? defaultAnalytics;
  const [feed, setFeed] = useState<FundingFeedHandle | null>(null);

  useEffect(() => {
    if (!FUNDING_SYMBOL.test(symbol)) return undefined;
    const started = startFundingFeed({
      symbol,
      window: { fromMs, toMs },
      loadHistory,
      wallNow,
      onFailed: (status, code) => analytics.historyFailed(symbol, status, code),
    });
    setFeed(started);
    return () => {
      started.stop();
      setFeed((current) => (current === started ? null : current));
    };
  }, [symbol, fromMs, toMs, loadHistory, wallNow, analytics]);

  // a symbol change never shows the previous feed, not even for one render
  return feed?.symbol === symbol ? feed : null;
}
