import { FundingCountdown } from "@candleviewer/ui";
import type { FundingSnapshot } from "../fundingFeed";
import type { SettledPoint } from "../history";
import { buildFundingSeries } from "../series";
import { FundingPane, type FundingPaneProps } from "./FundingPane";

// CMP-186 OiFundingLiqPane, the `FundingOnly` sub-pane (E24-S03 #778): every history state of D02 §5.3 / §9.
// Rates and times are the documented-shape fixtures' (exception #1778 A, C-13.5):
// `bybit/2026-10-05/rest/funding_history_{BTCUSDT_8h,ETHUSDT_4h}.json`. Plain CSF; `.storybook/main.ts` lists
// this folder, so the Storybook a11y run (axe with contrast) covers every state.
export default { title: "Chart primitives/OiFundingLiqPane/FundingOnly", component: FundingPane };

const RATES = ["0.00012", "-0.00004", "0.00008", "0.0001"];
const LAST = 1700006400000;
const settled = (hours: number): SettledPoint[] =>
  RATES.map((rate, i) => ({ tMs: LAST - (3 - i) * hours * 3_600_000, rate }));
const series = (
  points: SettledPoint[],
  intervalMinutes: number | null,
  gaps: { fromMs: number; toMs: number }[] = [],
) =>
  buildFundingSeries({ settled: points, intervalMinutes, coverage: { noCoverage: false, gaps } });

const ready = (over: Partial<Extract<FundingSnapshot["history"], { phase: "ready" }>> = {}) =>
  ({ phase: "ready", empty: false, coverage: "covered", truncated: false, ...over }) as const;

const btc: FundingSnapshot = {
  history: ready(),
  series: series(settled(8), 480),
  lastSuccessAtMs: Date.parse("2023-11-15T09:14:02Z"),
};
const none = series([], 480);

type Story = { render: () => JSX.Element };
const story = (props: Partial<FundingPaneProps>): Story => ({
  render: () => (
    <FundingPane symbol="BTCUSDT" snapshot={btc} onRetry={() => undefined} {...props} />
  ),
});

/** `SCR-054/funding-line`: settles every 8 h. */
export const Populated = story({});
/** `SCR-054/funding-interval-4h`: six steps a day. */
export const FourHourInterval = story({
  symbol: "ETHUSDT",
  snapshot: { ...btc, series: series(settled(4), 240) },
});
/** The group's "Show tables" pressed (E24-D04 A-03). */
export const TableOpen = story({ showTables: true });
/** A missing settlement: a gap row in words, never a stretched step. */
export const Gaps = story({
  snapshot: {
    ...btc,
    series: series(
      settled(8).filter((_, i) => i !== 1),
      480,
      [{ fromMs: LAST - 24 * 3_600_000, toMs: LAST - 8 * 3_600_000 }],
    ),
  },
  showTables: true,
});
/** PROPOSED: the page bound ran out before the window's end. */
export const Truncated = story({ snapshot: { ...btc, history: ready({ truncated: true }) } });
export const Loading = story({ snapshot: { ...btc, history: { phase: "loading" } } });
export const LoadingFirst = story({
  snapshot: { history: { phase: "loading" }, series: series([], null), lastSuccessAtMs: null },
});
/** `SCR-054/funding-empty` (BQ 6: coverage says the window is recorded). */
export const Empty = story({
  symbol: "SOLUSDT",
  snapshot: { ...btc, history: ready({ empty: true }), series: none },
});
/** PROPOSED: an empty window the store has not recorded. */
export const NotRecorded = story({
  symbol: "SOLUSDT",
  snapshot: { ...btc, history: ready({ empty: true, coverage: "not-recorded" }), series: none },
});
/** `SCR-054/funding-retry`: the last good series stays, in the plot and the table. */
export const Retry = story({
  snapshot: { ...btc, history: { phase: "failed", status: 503 } },
  showTables: true,
});
/** A failed first read: no last good time and no interval claim. */
export const RetryFirst = story({
  snapshot: { history: { phase: "failed", status: null }, series: none, lastSuccessAtMs: null },
});
/** `SCR-054/funding-unavailable`. */
export const Unavailable = story({
  symbol: "SOLUSDT",
  snapshot: { history: { phase: "unavailable" }, series: series([], null), lastSuccessAtMs: null },
});
/** PROPOSED: the interval is not served, so none is stated. */
export const IntervalUnknown = story({
  snapshot: { ...btc, series: series(settled(8), null) },
  showTables: true,
});
export const Comfortable = story({ density: "comfortable", headingLevel: 2 });
/** Long text: a long real symbol in every sentence, empty with coverage not served (BQ 6 "unknown"). */
export const LongText = story({
  symbol: "1000000BABYDOGEUSDT",
  snapshot: { ...btc, history: ready({ empty: true, coverage: "unknown" }), series: none },
});
export const Stale = story({
  stale: { tier: "t1", ageS: 7, lastTsMs: Date.parse("2023-11-15T15:55:41Z") },
});
/** D03 S54-38 `funding-empty`: none settled yet, the legend's countdown (silent: the header's speaks) running. */
const SETTLES = Date.UTC(2023, 10, 15, 8, 0, 0);
export const EmptyWithCountdown = story({
  symbol: "SOLUSDT",
  snapshot: { ...btc, history: ready({ empty: true }), series: none },
  countdown: (
    <FundingCountdown
      announce={false}
      symbol="SOLUSDT"
      nextFundingTimeMs={SETTLES}
      now={() => SETTLES - 11_564_000}
    />
  ),
});
