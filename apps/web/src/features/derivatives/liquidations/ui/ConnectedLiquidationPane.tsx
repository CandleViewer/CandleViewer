// E24-S05 (#780): the liquidation feed wired to its subscription and its read, with AN-4's polite cascade summary
// through the shell's one announcer (never per print) and `liquidation.print_clicked`. The host (SCR-054) passes
// the pane id, a stable window, the optional `min_notional_usd` filter and `onLocate` (the crosshair). The summary
// names rates, so it is silent while the user's `announce_prices` is off (ruling 23:38Z).
import { useEffect, useRef, type JSX } from "react";
import { usePreferences } from "../../../a11y-preferences";
import { announce, forget, lastWrittenAt, REGION_BUDGET_MS } from "../../../app-shell/announcer";
import { createLiqAnalytics } from "../analytics";
import { CASCADE_THRESHOLD_PER_SEC, CascadeSummary, SUMMARY_RECHECK_MS } from "../cascade";
import { INITIAL_LIQ_SNAPSHOT, useLiqSnapshot } from "../liquidationFeed";
import { useLiquidationFeed, type LiqFeedHookOptions } from "../useLiquidationFeed";
import { LiquidationPane } from "./LiquidationPane";

export interface ConnectedLiquidationPaneProps extends LiqFeedHookOptions {
  readonly symbol: string;
  /** Moves the chart's crosshair to a row's time: a lone print's own, a bucket row's 250 ms bucket start. */
  readonly onLocate?: ((tsMs: number) => void) | undefined;
  /** AN-4's writer; the shell announcer by default. */
  readonly say?: ((text: string) => void) | undefined;
  /** Monotonic ms for the throttle. */
  readonly now?: (() => number) | undefined;
  /** The shell region's budget: whether a polite write may land now (E17-D02 §11). */
  readonly canSay?: (() => boolean) | undefined;
}

const perfNow = (): number => performance.now();
/** E17-D02 §11: a writer waits out REGION_BUDGET_MS from the polite region's last write. */
const politeBudgetOpen = (): boolean => Date.now() - lastWrittenAt("polite") >= REGION_BUDGET_MS;

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
  now = perfNow,
  canSay = politeBudgetOpen,
  ...feedOptions
}: ConnectedLiquidationPaneProps): JSX.Element {
  const analytics = feedOptions.analytics ?? defaultAnalytics;
  const feed = useLiquidationFeed(symbol, { ...feedOptions, analytics });
  const snapshot = useLiqSnapshot(feed);
  // a new feed, a new throttle: a symbol or filter switch gets its own leading edge (review A m3)
  const feedKey = `${symbol}|${feedOptions.minNotionalUsd ?? ""}`;
  const summary = useRef<{ readonly key: string; readonly throttle: CascadeSummary } | null>(null);
  const silent = usePreferences().prefs.announce_prices === "off";
  const { ratePerSec, longShare } = snapshot;
  // this commit's evaluation, kept for the steady-cascade timer (written in an effect, never during render)
  const evaluate = useRef((): void => undefined);
  useEffect(() => {
    evaluate.current = () => {
      if (silent) return;
      if (summary.current?.key !== feedKey) {
        summary.current = { key: feedKey, throttle: new CascadeSummary() };
      }
      const text = summary.current.throttle.observe(ratePerSec, longShare, now(), canSay);
      if (text !== null) say(text);
    };
    evaluate.current();
  }, [feedKey, ratePerSec, longShare, now, say, canSay, silent]);
  // a steady cascade (a flat rate, or a write the region's budget refused) is re-checked every second while it
  // lasts; the throttle keeps the cap at one summary per 5 s
  const active = !silent && ratePerSec >= CASCADE_THRESHOLD_PER_SEC;
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => evaluate.current(), SUMMARY_RECHECK_MS);
    return () => clearInterval(timer);
  }, [active, feedKey]);
  return (
    <LiquidationPane
      key={feedKey} // a new feed, a new pane: no held rows survive
      symbol={symbol}
      snapshot={feed === null ? INITIAL_LIQ_SNAPSHOT : snapshot}
      onRetry={() => feed?.retry()}
      // rows activate (and the grid's hint promises a crosshair move) only when the host can move the crosshair
      onPrintActivate={
        onLocate === undefined
          ? undefined
          : (p) => {
              analytics.printClicked(symbol, p.side, p.clusterSize);
              onLocate(p.tsMs);
            }
      }
    />
  );
}
