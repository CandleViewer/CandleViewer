import { FundingCountdown } from "@candleviewer/ui";
import type { FundingSnapshot } from "../fundingFeed";
import type { SettledPoint } from "../history";
import { buildReadout, type PredictedRate } from "../predicted";
import { buildFundingSeries } from "../series";
import { FundingMethodologyHost } from "./FundingMethodologyHost";
import { FundingPane, type FundingPaneProps } from "./FundingPane";
import { PredictedReadout, readoutRate } from "./PredictedReadout";

// E24-S04 (#779): the predicted and annualised funding, every state of D02 §5.1 / §5.3. Values are the
// recorded fixtures' rates (`bybit/2026-10-05/rest/funding_history_*.json`); the annualised percentages are
// the server's `annualised_pct` (§19.110: rate × 525600 / interval × 100), written out here, never computed
// by the component. Plain CSF.
export default {
  title: "Chart primitives/OiFundingLiqPane/FundingPredicted",
  component: FundingPane,
};

const LAST = 1700006400000;
const SETTLES = Date.UTC(2023, 10, 15, 8, 0, 0);
const settled = (hours: number, annualised: boolean): SettledPoint[] =>
  ["0.00012", "-0.00004", "0.00008", "0.0001"].map((rate, i) => ({
    tMs: LAST - (3 - i) * hours * 3_600_000,
    rate,
    ...(annualised ? { annualisedPct: pctOf(rate, hours * 60) } : {}),
  }));
/** The server's numbers for the stories: 0.0001 at 480 min is 10.95 % p.a. (D02 §5.1). */
const pctOf = (rate: string, interval: number): string =>
  ((Number(rate) * 525600 * 100) / interval).toFixed(4);
const accruing = (rate: string, interval: number, annualised: boolean): PredictedRate => ({
  tMs: LAST + interval * 60_000,
  rate,
  annualisedPct: annualised ? pctOf(rate, interval) : null,
});

const snapshot = (
  hours: number,
  predicted: PredictedRate | null,
  annualised: boolean,
): FundingSnapshot => ({
  history: { phase: "ready", empty: false, coverage: "covered", truncated: false },
  series: buildFundingSeries({
    settled: settled(hours, annualised),
    intervalMinutes: hours * 60,
    coverage: null,
    predicted,
  }),
  lastSuccessAtMs: Date.parse("2023-11-15T09:14:02Z"),
});

const header = (
  snap: FundingSnapshot,
  tickerRate: string | null,
  annualised: boolean,
  symbol = "BTCUSDT",
) => {
  const readout = buildReadout({
    tickerRate,
    historyReady: true,
    predicted: snap.series.predicted,
    intervalMinutes: snap.series.intervalMs === null ? null : snap.series.intervalMs / 60_000,
  });
  return (
    <FundingMethodologyHost>
      <FundingCountdown
        symbol={symbol}
        rate={readoutRate(readout, annualised)}
        rateExtra={<PredictedReadout readout={readout} annualised={annualised} />}
        nextFundingTimeMs={tickerRate === null ? undefined : SETTLES}
        now={() => SETTLES - 11_564_000}
      />
    </FundingMethodologyHost>
  );
};

type Story = { render: () => JSX.Element };
const story = (
  snap: FundingSnapshot,
  tickerRate: string | null,
  annualised: boolean,
  props: Partial<FundingPaneProps> = {},
): Story => ({
  render: () => (
    <FundingPane
      symbol="BTCUSDT"
      snapshot={snap}
      onRetry={() => undefined}
      annualised={annualised}
      onAnnualisedChange={() => undefined}
      countdown={header(snap, tickerRate, annualised)}
      {...props}
    />
  ),
});

const withBoth = snapshot(8, accruing("0.0001", 480, true), true);

/** Settled history only: the accruing rate is not published, so n/a, no marker, no row. */
export const PredictedAbsent = story(snapshot(8, null, true), null, false, {
  showTables: true,
});
/** "Funding +0.0100 % / 8 h · predicted (estimated)": no annualised value served, so no toggle. */
export const PredictedNoAnnualised = story(
  snapshot(8, accruing("0.0001", 480, false), false),
  "0.0001",
  false,
  {
    showTables: true,
  },
);
/** D02 §5.1: per-interval first, the annualised figure second, the formula in its tooltip. */
export const SettledAndPredicted = story(withBoth, "0.0001", false, { showTables: true });
/** D02 §5.1 "Annualised on": the annualised figure first. */
export const Annualised = story(withBoth, "0.0001", true, { showTables: true });
/** The ticker moved after the REST read: the served annualised value is for another rate, so it is not shown. */
export const TickerMovedOn = story(withBoth, "0.00012", true);
/** A 4 h symbol: the factor is 525600 / 240, from the same response as the rate. */
export const FourHourInterval = story(
  { ...snapshot(4, accruing("0.0001", 240, true), true) },
  "0.0001",
  true,
  { symbol: "ETHUSDT" },
);
