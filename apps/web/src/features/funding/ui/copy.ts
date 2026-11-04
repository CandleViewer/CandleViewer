// E24-S03 (#778): the funding pane's strings. D02 §15 / D03 §5 are the source of every string; the ones
// they do not carry are marked PROPOSED here and go to the E24-D05 copy deck owner.
import { intervalWords, utcTime } from "./format";

/** D02 §5.3 / D03 S54-32 legend. */
export const PANE_LABEL = "Funding rate";
/** PROPOSED: the region's name, after `14`'s "Derivatives context BTCUSDT" and E24-S01's OI region. */
export const regionName = (symbol: string): string => `Funding, ${symbol}`;
/** D02 §15 "settles every 8 h". */
export const settlesEvery = (minutes: number): string => `settles every ${intervalWords(minutes)}`;
/** PROPOSED: the interval is not served, so none is stated and no step is drawn (never 8 h). */
export const INTERVAL_UNKNOWN = "settlement interval not published";

/** PROPOSED: the loading region's one sentence (the skeleton is hidden from assistive technology). */
export const LOADING = "Loading funding history…";
/** D02 §15 retry band. */
export const RETRY_TITLE = "Couldn't load funding history";
export const RETRY = "Retry";
/** E24-D04 A-20 (as A-13 "Retry loading OI"): the button's name; its visible label stays "Retry". */
export const RETRY_NAME = "Retry loading Funding";
export const lastLoaded = (ms: number): string => `Last loaded ${utcTime(ms)}`;
/** D02 §15 / D03 S54-38: only when `meta.coverage` says the window is recorded (BQ 6). */
export const emptyTitle = (symbol: string): string => `No funding has settled for ${symbol} yet`;
/** PROPOSED: an empty window the store has not recorded (`no_coverage`), or coverage not served. */
export const notRecordedTitle = (symbol: string): string =>
  `Funding history for ${symbol} is not recorded for this range`;
/** D02 §15 / D03 S54-39. */
export const unavailableTitle = (symbol: string): string =>
  `Funding unavailable for ${symbol}: the instrument is not available right now.`;
/** PROPOSED: the page bound ran out before the window's end. */
export const TRUNCATED = "Recent history not loaded.";
/** PROPOSED: the gaps' sentence, so a missing settlement is said in text, never only a hole. */
export const GAP_WORDS = "missing settlement · not recorded";

/** PROPOSED: the table's caption (its name), after D02 §11's Funding row. */
export const tableCaption = (symbol: string): string => `Funding rate, ${symbol}, settled`;
/** PROPOSED: CMP-049's 200-row cap, said in the caption so the table's name carries it (F4). */
export const showingNewest = (shown: number, total: number): string =>
  `showing the newest ${String(shown)} of ${total.toLocaleString("en-US")}`;
/** D02 §11's columns; the Annualised column is E24-S04's (out of scope here). */
export const COL_SETTLEMENT = "Settlement (UTC)";
export const COL_RATE = "Rate (% per interval)";
export const COL_STATUS = "Status";
export const COL_INTERVAL = "Interval (h)";
export const STATUS_SETTLED = "settled";
/** PROPOSED: no settled row in view. */
export const NO_ROWS = "No settlements in view.";
