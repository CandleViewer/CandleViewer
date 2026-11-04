// E24-S06 (#781): `GET /market/metrics` responses built to the shape `22` `getMetrics` declares in #5341 (head
// 021c79460, not on `main`; its `MetricCode` / `MetricPoint.v` are not in the generated types yet). Pinned by content:
// `CONTRACT` quotes the sentences of that diff this client relies on, so a re-pin to the merge commit that changes
// one fails the test that reads it. A response is a server frame shape, not a Bybit payload.
import type { BarSide } from "../../../../../src/features/derivatives/liquidations/bars/barsRead";
import type { SidePoints } from "../../../../../src/features/derivatives/liquidations/bars/model";

export const CONTRACT = {
  /** `22` `getMetrics` description. */
  zeroSentence: 'a bar with no liquidation prints reads `"0"`',
  /** `22` `getMetrics` description: params go in `params`; `side` is `both`, `long` or `short`. */
  paramsSentence: "`side` is `both` (the default), `long` or `short`",
  /**
   * ROUTER-ONLY: not in `22` or `24` at the pinned head; the sentence is `market_metrics.py`'s `detail` for a code
   * the server does not compute ("not computed by this server yet: <codes>"). The pane keys on its prefix, so a
   * re-pin to the merge commit re-reads `market_metrics.py` for it (and for the 422 an unlisted symbol gets).
   */
  notComputedDetail: "not computed by this server yet",
  /** #5341's route test: the registry unit and the resolved params echo. */
  unit: "notional",
  alias: "liquidation_intensity",
} as const;

export interface WirePoint {
  t: string;
  v: unknown;
}

export const wirePoints = (points: SidePoints): WirePoint[] =>
  [...points].map(([t, v]) => ({ t: new Date(t).toISOString(), v }));

/** One `liquidation_notional` series for `side`, with the registry's unit and the resolved params echo. */
export const metricsBody = (
  side: BarSide,
  points: WirePoint[],
  over: Record<string, unknown> = {},
) => ({
  symbol: "BTCUSDT",
  bar_type: "time",
  param: "60",
  series: [
    {
      metric: "liquidation_notional",
      estimated: false,
      params: { side },
      unit: CONTRACT.unit,
      points,
      ...over,
    },
  ],
  meta: {
    count: points.length,
    has_more: false,
    next_cursor: null,
    generated_at: "2026-10-21T11:30:00Z",
  },
});
