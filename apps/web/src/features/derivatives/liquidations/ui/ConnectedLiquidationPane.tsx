// E24-S05 (#780): the liquidation feed wired to its subscription and its read, with AN-4's polite cascade summary
// through the shell's one announcer (never per print) and `liquidation.print_clicked`. The host (SCR-054) passes
// the pane id, a stable window, the optional `min_notional_usd` filter and `onLocate` (the crosshair). The summary
// names rates, so it is silent while the user's `announce_prices` is off (ruling 23:38Z).
import { useEffect, useRef, type JSX } from "react";
import { usePreferences } from "../../../a11y-preferences";
import { announce, forget } from "../../../app-shell/announcer";
import { createLiqAnalytics } from "../analytics";
import { CascadeSummary } from "../cascade";
import { INITIAL_LIQ_SNAPSHOT, useLiqSnapshot } from "../liquidationFeed";
import { useLiquidationFeed, type LiqFeedHookOptions } from "../useLiquidationFeed";
import { LiquidationPane } from "./LiquidationPane";

export interface ConnectedLiquidationPaneProps extends LiqFeedHookOptions {
  readonly symbol: string;
  /** Moves the chart's crosshair to a print's time. */
  readonly onLocate?: ((tsMs: number) => void) | undefined;
  /** AN-4's writer; the shell announcer by default. */
  readonly say?: ((text: string) => void) | undefined;
  /** Monotonic ms for the throttle. */
  readonly now?: (() => number) | undefined;
}

const defaultAnalytics = createLiqAnalytics();

let said = 0;
/** The shell announcer says a key once; a fresh key per summary, forgotten at once, keeps it re-sayable. */
const politeToShell = (text: string): void => {
  said += 1;
  const key = `liq-cascade:${String(said)}`;
  announce("polite", text, key);
  forget(key);
};

export function ConnectedLiquidationPane({
  symbol,
  onLocate,
  say = politeToShell,
  now = () => performance.now(),
  ...feedOptions
}: ConnectedLiquidationPaneProps): JSX.Element {
  const analytics = feedOptions.analytics ?? defaultAnalytics;
  const feed = useLiquidationFeed(symbol, { ...feedOptions, analytics });
  const snapshot = useLiqSnapshot(feed);
  const summary = useRef(new CascadeSummary());
  const silent = usePreferences().prefs.announce_prices === "off";
  const { ratePerSec, longShare } = snapshot;
  useEffect(() => {
    if (silent) return;
    const text = summary.current.observe(ratePerSec, longShare, now());
    if (text !== null) say(text);
  }, [ratePerSec, longShare, now, say, silent]);
  return (
    <LiquidationPane
      key={`${symbol}|${feedOptions.minNotionalUsd ?? ""}`} // a new feed, a new pane: no held rows survive
      symbol={symbol}
      snapshot={feed === null ? INITIAL_LIQ_SNAPSHOT : snapshot}
      onRetry={() => feed?.retry()}
      onPrintActivate={(p) => {
        analytics.printClicked(symbol, p.side, p.clusterSize);
        onLocate?.(p.tsMs);
      }}
    />
  );
}
