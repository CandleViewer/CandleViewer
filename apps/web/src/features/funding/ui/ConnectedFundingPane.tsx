// E24-S03 (#778): the pane on its history feed and the symbol's one countdown entry; at each settlement the
// entry signals the feed, which polls `to = now` and appends the settled rate (BQ 5). The plot slot stays empty.
import { useEffect, useMemo, useRef, useState, type JSX, type ReactNode } from "react";
import type { SecondTick } from "@candleviewer/ui";
import { syncedTick, useSyncedClockSkew } from "../../../lib/state/syncedTick";
import { loadFundingCharges } from "../charges";
import {
  useCountdownFeed,
  useCountdownSnapshot,
  type CountdownClock,
  type CountdownFeedOptions,
} from "../countdownFeed";
import { INITIAL_FUNDING_SNAPSHOT, useFundingSnapshot } from "../fundingFeed";
import { createFundingAnalytics } from "../analytics";
import { buildReadout } from "../predicted";
import { useFundingFeed, type FundingFeedHookOptions } from "../useFundingFeed";
import { FundingCountdownView } from "./ConnectedFundingCountdown";
import { FundingPane } from "./FundingPane";

export interface ConnectedFundingPaneProps extends FundingFeedHookOptions {
  readonly symbol: string;
  readonly plot?: ReactNode;
  readonly visible?: { readonly fromMs: number; readonly toMs: number } | undefined;
  /** The SCR-054 group's "Show tables" (E24-D04 A-03). */
  readonly showTables?: boolean | undefined;
  readonly tick?: SecondTick | undefined;
  readonly loadCharges?: CountdownFeedOptions["loadCharges"] | undefined;
  readonly countdownClock?: CountdownClock | undefined;
  /** The pane's countdown speaks AN-1 / AN-2 (default); a screen with the header's passes `false` (D03 §13). */
  readonly announce?: boolean | undefined;
}

const defaultAnalytics = createFundingAnalytics();

export function ConnectedFundingPane({
  symbol,
  plot,
  visible,
  showTables = false,
  tick = syncedTick,
  loadCharges = loadFundingCharges,
  countdownClock,
  announce = true,
  ...feedOptions
}: ConnectedFundingPaneProps): JSX.Element {
  const analytics = feedOptions.analytics ?? defaultAnalytics;
  // TODO(#5699): `deriv.funding_annualised` (the key #5699's `22` serves, `feat/e24-funding-contract`) is a server setting; until it merges the toggle is session state
  // (no local storage, ruling #778 item 8), so a reload restores the default (off).
  const [annualised, setAnnualised] = useState(false);
  const feed = useFundingFeed(symbol, feedOptions);
  const snapshot = useFundingSnapshot(feed);
  const countdownFeed = useCountdownFeed(symbol, { tick, loadCharges, clock: countdownClock });
  const countdown = useCountdownSnapshot(countdownFeed);
  const clockSkewMs = useSyncedClockSkew(tick);
  const { stale: s } = countdown;
  const stale = useMemo(() => (s.tier === "fresh" ? undefined : { ...s, tier: s.tier }), [s]);
  useEffect(() => {
    if (feed === null || countdownFeed === null) return undefined;
    return countdownFeed.onSettlement((deadlineMs) => feed.settle(deadlineMs));
  }, [feed, countdownFeed]);
  const shown = feed === null ? INITIAL_FUNDING_SNAPSHOT : snapshot;
  const readout = useMemo(
    () =>
      buildReadout({
        tickerRate: countdown.rate,
        historyReady: shown.history.phase === "ready",
        predicted: shown.series.predicted,
        intervalMinutes: shown.series.intervalMs === null ? null : shown.series.intervalMs / 60_000,
      }),
    [countdown.rate, shown],
  );
  // the ticket's counter: one report per entry into n/a, so a missing rate is visible without a flood
  const wasNa = useRef(false);
  useEffect(() => {
    const na = readout.kind === "na" && shown.history.phase === "ready";
    if (na && !wasNa.current) analytics.predictedNa(symbol);
    wasNa.current = na;
  }, [readout.kind, shown.history.phase, analytics, symbol]);
  return (
    <FundingPane
      symbol={symbol}
      snapshot={shown}
      annualised={annualised}
      onAnnualisedChange={(next) => {
        setAnnualised(next);
        analytics.annualiseToggled(symbol, next);
      }}
      onRetry={() => feed?.retry()}
      plot={plot}
      visible={visible}
      showTables={showTables}
      stale={stale}
      countdown={
        <FundingCountdownView
          symbol={symbol}
          snapshot={countdown}
          tick={tick}
          clockSkewMs={clockSkewMs}
          announce={announce}
          readout={readout}
          annualised={annualised}
        />
      }
    />
  );
}
