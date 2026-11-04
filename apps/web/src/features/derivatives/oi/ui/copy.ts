// E24-S01 (#776) slice 2: the OI pane's strings. D02 §15 is the source of every string; the ones it does
// not carry are marked PROPOSED here and go to the E24-D05 copy deck owner.
import { utcDateTime, utcTime } from "./format";

export const PANE_LABEL = "Open interest";
/** PROPOSED: the region's name, after `14:1201`'s "Derivatives context BTCUSDT". */
export const regionName = (symbol: string): string => `Open interest, ${symbol}`;
export const OI_LABEL = "OI";
/** D03 §3 OI variant while the ticker carries no single-side field (G6). */
export const BOTH_SIDES = "(both sides)";
/** BQ 2 (PROPOSED): the per-bar delta, labelled as such, until a 1 h window is served. */
export const DELTA_LABEL = "Δ per bar";
export const DELTA_NAME = "Open interest change per bar";

export const TABLE_SHOW = "Show table";
export const TABLE_HIDE = "Hide table";

/** D02 §9 `backfilling`. */
export const BACKFILLING = "Loading OI history…";
/** PROPOSED: the loading region's one sentence (the skeleton is hidden from assistive technology). */
export const LOADING = "Loading open interest…";
/** D02 §15 retry band. */
export const RETRY_TITLE = "Couldn't load OI history";
export const RETRY = "Retry";
export const lastLoaded = (ms: number): string => `Last loaded ${utcTime(ms)}`;
/** D02 §4 `oi-empty`; the second sentence only where true. */
export const emptyTitle = (symbol: string): string => `No open-interest history for ${symbol} yet.`;
export const LIVE_STREAMING = "Live OI is streaming now.";
/** BQ 7 (PROPOSED): `coverage.from` names where the stored history starts when this window holds none. */
export const historyStarts = (ms: number): string => `History starts ${utcDateTime(ms)}.`;
/** PROPOSED: the bounded read left out the window's start (it reads ascending, so it starts late). */
export const TRUNCATED_OLDER = "Older history not loaded.";
/** PROPOSED: the pages ran out before `to` (defensive; a clamped window never needs more). */
export const TRUNCATED_NEWER = "Recent history not loaded.";
/** D03 §10.2 "Stale 7s · last 13:42:05": the chip carries the age, this the last-good time. */
export const lastGood = (ms: number): string => `last ${utcTime(ms)}`;

export const SOURCE_WORDS = { rest: "REST history", ws_ticker: "live" } as const;
/** PROPOSED: the table's gap rows, in words (the a11y note: gaps conveyed in text). */
export const GAP_WORDS = {
  recorded: "gap · not recorded",
  failed: "gap · not loaded",
  live: "gap · live stream interrupted",
} as const;

export const tableCaption = (symbol: string): string => `Open interest, ${symbol}, visible points`;
export const COL_TIME = "Time (UTC)";
export const COL_SPAN = "Span";
export const colBase = (coin: string): string => `OI (${coin}, both sides)`;
export const COL_VALUE = "OI (USDT, both sides)";
export const COL_SOURCE = "Source";
export const FORMING = "forming";
/** A2 (PROPOSED): a history span cut short where live begins, so it never overlaps a finer live bar. */
export const CLIPPED = "(clipped)";
/** B5 (PROPOSED): the table's cap, stated where it applies. */
export const showingNewest = (shown: number, total: number): string =>
  `Showing the newest ${String(shown)} of ${total.toLocaleString("en-US")}.`;
export const NO_ROWS = "No open-interest points in view.";
