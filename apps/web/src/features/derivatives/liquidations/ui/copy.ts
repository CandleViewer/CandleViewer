// E24-S05 (#780): the liquidation feed's strings. D02 §15 is the source of every string; the ones it does not
// carry are marked PROPOSED here and go to the E24-D05 copy deck owner.
import { groupedDecimal, utcTime } from "./format";

export const PANE_LABEL = "Liquidations";
/** PROPOSED: the region's name, after `14:1201`'s "Derivatives context BTCUSDT" (as E24-S01's OI pane). */
export const regionName = (symbol: string): string => `Liquidations, ${symbol}`;
/** D02 §15, under the feed (memo F15; no "lower bounds" on screen, DV-8). */
export const COMPLETENESS =
  "Bybit publishes liquidations in 500 ms batches; every print is included — history is limited to what the recorder captured";
/** D02 §15, the filter line (only when a filter is set). */
export const filterLine = (minNotionalUsd: string): string =>
  `Showing prints ≥ ${groupedDecimal(minNotionalUsd)} USDT`;

/** D02 §15 feed controls. */
export const PAUSE = "Pause";
export const newCount = (n: number): string => `${String(n)} new`;
/** PROPOSED: the `N new` control's name says what it does (D03 §10.1: `Enter` resumes at the top). */
export const newCountName = (n: number): string =>
  `${String(n)} new ${n === 1 ? "print" : "prints"}, show newest`;
/** PROPOSED: the 40-row cut, disclosed (review B M3). */
export const newestOf = (shown: number, held: number): string =>
  `Showing the newest ${String(shown)} of ${groupedDecimal(String(held))} prints.`;

/** PROPOSED: the table's caption (the feed is the table, D02 §11). */
export const tableCaption = (symbol: string): string =>
  `Liquidation prints, ${symbol}, newest first`;
/** D02 §11 / D03 S54-66 headers with their units. */
export const COL_TIME = "Time (UTC)";
export const COL_SIDE = "Liquidated side";
export const COL_PRINTS = "Prints";
/** PROPOSED: the grid's description, so the row activation is discoverable (a11y review). */
export const ACTIVATE_HINT = "Enter moves the chart crosshair to this print.";
/** D02 §6's bucket row: the average bankruptcy price is labelled. */
export const AVG = "avg";
export const colSize = (base: string): string => `Size (${base})`;
export const COL_PRICE = "Bankruptcy price (p), USDT";
export const COL_NOTIONAL = "Notional (USDT)";
export const COL_CLUSTER = "Cluster (×N)";
/** PROPOSED: a print without a served notional (it is optional on the wire). */
export const NO_NOTIONAL = "not served";

/** PROPOSED: no print has arrived since the feed opened (never "no liquidations"). */
export const WAITING = "No prints received since the feed opened.";

// slice 2: history, coverage and the feed's states (D02 §6, §9, §15; D03 S54-45 … S54-50, S54-70 … S54-75)

/** D02 §15, the partial chip: its name, then its sentence (the first available time, `14:1213`). */
export const sinceChip = (when: string): string => `since ${when}`;
export const partialSentence = (when: string): string =>
  `No history before ${when}. Bybit publishes no liquidation history; earlier prints were not recorded.`;
/** D02 §6 `liq-never-recorded`; the second sentence only where true. */
export const neverRecorded = (symbol: string): string =>
  `No liquidation history for ${symbol}. Bybit publishes none, and this symbol has never been recorded.`;
export const LIVE_STREAMING = "Live liquidations are streaming now.";
/** D02 §6 `liq-before-coverage`: never an empty list. */
export const beforeCoverage = (when: string): string =>
  `Not recorded before ${when} — this is not 'no liquidations'`;
/** D02 §15 retry bands. */
export const RETRY_TITLE = "Couldn't load liquidation history";
/** D02 §15 `liq-coverage-retry` (`api/market_coverage.py`, verbatim): the server's 503. */
export const COVERAGE_RETRY = "Recording metadata is not available yet; retry shortly.";
export const RETRY = "Retry";
/** D04 A-19: the retry control names what it retries. */
export const RETRY_NAME = "Retry loading Liquidations";
export const lastLoaded = (ms: number): string => `Last loaded ${utcTime(ms)}`;
/** PROPOSED (after D02 §9's "Loading OI history…"). */
export const LOADING = "Loading liquidation history…";
/** PROPOSED: inside coverage, an empty window says what was recorded, never "no liquidations". */
export const emptyRecorded = (when: string): string => `No prints recorded since ${when}.`;
/** PROPOSED: the end of the window the read did not load (review A M3), with its time. */
export const truncated = (side: "older" | "newer", when: string): string =>
  side === "older"
    ? `Older prints not loaded: before ${when}.`
    : `Newer prints not loaded: after ${when}.`;
/** PROPOSED: CMP-239's `disconnected` and `stale` words with D03 §10.2's "last" time. */
export const disconnected = (lastMs: number | null): string =>
  lastMs === null ? "Disconnected" : `Disconnected · last ${utcTime(lastMs)}`;
export const stale = (lastMs: number | null): string =>
  lastMs === null ? "Stale" : `Stale · last ${utcTime(lastMs)}`;
