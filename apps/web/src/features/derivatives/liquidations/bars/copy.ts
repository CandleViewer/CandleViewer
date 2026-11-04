// E24-S06 (#781): the liquidation bars' strings. D02 §6, §11, §15 and D03 S54-40 / S54-45 / S54-47 are the source;
// a string they do not carry is marked PROPOSED and goes to the E24-D05 copy deck owner.
import { groupedDecimal, utcTime } from "../ui/format";

export const BARS_LABEL = "Liquidation bars";
/** PROPOSED: the region's name, after #780's `Liquidations, BTCUSDT`. */
export const regionName = (symbol: string): string => `Liquidation bars, ${symbol}`;

/**
 * D02 §6 `liq-bars`: "Showing prints ≥ 50,000 USDT", only when non-zero, and only when the server applies it to the
 * bars (BQ-1, ruled 6618707867). Until `liquidation_notional` takes `min_notional_usd` (G-row on #723) the bars are
 * unfiltered and the legend says so, naming the filter the FEED really has (its own `min_notional_usd`, the value in
 * the feed's snapshot): never a filter claim the server does not apply.
 */
export const filterLine = (minNotionalUsd: string, appliedToBars: boolean): string =>
  appliedToBars
    ? `Showing prints ≥ ${groupedDecimal(minNotionalUsd)} USDT`
    : `Bars: all prints · feed ≥ ${groupedDecimal(minNotionalUsd)} USDT`;

/** D02 §6 `liq-partial`'s boundary label, and `liq-before-coverage` / `liq-never-recorded` (shared with #780). */
export const recordedFrom = (when: string): string => `Recorded from ${when}`;
export const notRecordedBefore = (when: string): string =>
  `Not recorded before ${when} — this is not 'no liquidations'`;
export const neverRecorded = (symbol: string): string =>
  `No liquidation history for ${symbol}. Bybit publishes none, and this symbol has never been recorded.`;

/** D02 §11's table: the columns with their units, the state in words. */
export const tableCaption = (symbol: string, interval: string): string =>
  `Liquidation bars, ${symbol}, ${interval} bars, newest first`;
export const COL_BAR = "Bar (UTC)";
export const COL_LONG = "Long liquidated (USDT)";
export const COL_SHORT = "Short liquidated (USDT)";
export const COL_STATE = "State";
/** PROPOSED: a bar that opens before the recorder began: its figures are the recorded part. */
export const recordedPartial = (when: string): string => `recorded from ${when}`;
export const STATE_WORDS = {
  recorded: "recorded",
  zero: "zero",
  unknown: "not recorded",
} as const;

/** PROPOSED: a bar's cell where the server sent no number (never a blank, never 0). */
export const NOT_RECORDED = "not recorded";

/** PROPOSED: the crosshair readout's words; the side words and glyphs are the pane's JSX (the glyph is `aria-hidden`). */
export const readoutUnknown = (when: string): string => `${when} · ${NOT_RECORDED}`;

/** The controls (D02 §10): the mode segments and the threshold field. */
export const MODE_NAME = "Liquidation display";
export const MODE_BARS = "Bars";
export const MODE_HEATMAP = "Heatmap";
export const THRESHOLD_LABEL = "Minimum notional (USDT)";
export const THRESHOLD_INVALID = "Enter a number, 0 or more.";
/** PROPOSED (BQ-6, ruled 6618707867): the heatmap waits for a recorded-density surface (NG-15); never client-bucketed. */
export const HEATMAP_PENDING =
  "The realised-liquidation heatmap is not available yet. Switch to Bars to see recorded liquidations per bar.";

/** PROPOSED: states (after D02 §9 / #780's copy). */
export const LOADING = "Loading liquidation bars…";
export const NO_BARS = "The server returned no bars for this range.";
export const RETRY_TITLE = "Couldn't load liquidation bars";
export const RETRY = "Retry";
export const RETRY_NAME = "Retry loading Liquidation bars";
export const COVERAGE_FAILED =
  "Recording coverage could not be loaded, so bars are not drawn: a bar cannot be told from an unrecorded one.";
/** PROPOSED: the table's 200-row cut, disclosed (as #780's feed). */
export const newestOf = (shown: number, total: number): string =>
  `Table shows the newest ${String(shown)} of ${String(total)} bars.`;
/** `22` `getMetrics` 422 (#5341): the `detail` of a code the server does not compute yet; any other 422 is generic. */
export const NOT_COMPUTED_DETAIL = "not computed by this server yet";
export const NOT_COMPUTED = "Liquidation bars are not available on this server yet.";
export const COVERAGE_PENDING = "Waiting for recording coverage before drawing bars.";
export const lastLoaded = (ms: number): string => `Last loaded ${utcTime(ms)}`;
export const stale = (lastMs: number): string => `Stale · last ${utcTime(lastMs)}`;
/** PROPOSED: the history bound, disclosed. */
export const windowLimited = (bars: number): string => `Showing the newest ${String(bars)} bars.`;
/** PROPOSED: a count of values the server sent that were not numbers; they read "not recorded". */
export const MALFORMED = (n: number): string =>
  `${String(n)} ${n === 1 ? "value was" : "values were"} unreadable and shown as not recorded.`;
