// E24-S08 (#783) slice 1: the basis readout's strings. D03 §3 (the Basis row) is the source of every
// string; the ones it does not carry are marked PROPOSED and go to the E24-D05 copy deck owner.
import type { BasisSource } from "../settings";
import { utcTime } from "./format";

export const UNIT = "USDT";
export const PANE_LABEL = "Basis";
export const MARK_LABEL = "Mark";
export const INDEX_LABEL = "Index";
export const BASIS_LABEL = "Basis";
/** PROPOSED: the readout's name, after `14:1201`'s "Derivatives context BTCUSDT". */
export const panelName = (symbol: string): string => `Basis panel, ${symbol}`;
export const regionName = (symbol: string): string => `Basis, ${symbol}`;

/**
 * BQ 2, ruled (6612480577): the source line follows the contract default `last` (`24` §7: `basis = last − index`).
 * D03 S54-6 draws `basis, mark − index` with default `mark`, which becomes a D03 A-row after merge. The selected
 * source decides the word; D03's "· source" suffix is the selector beside it.
 */
export const sourceLine = (source: BasisSource): string => `basis, ${source} − index`;
/** The spoken form of the source line (the minus sign in words). */
export const sourceSpoken = (source: BasisSource): string => `basis, ${source} minus index`;

export const SOURCE_GROUP = "Basis source";
export const SOURCE_OPTIONS = [
  { value: "mark", label: "mark" },
  { value: "last", label: "last" },
] as const;
/** PROPOSED: the one polite sentence after the user changes the source (never per tick). */
export const sourceChanged = (source: BasisSource): string =>
  `Basis source is now ${source}: ${sourceSpoken(source)}.`;

export const NO_VALUE = "no value yet";
/** PROPOSED: the basis is not computable while the ticker carries no index (or no mark for `mark`). */
export const NO_BASIS = "no basis for this source";

/** D03 §10.2 "Stale 7s · last 13:42:05": the chip carries the age, this the last-good time. */
export const lastGood = (ms: number): string => `last ${utcTime(ms)}`;

/**
 * PROPOSED: D03 S54-8 `basis-retry` reads "Couldn't load the basis series · Retry" for the optional basis
 * SERIES sub-pane. This slice is the live readout with no series (BQ 1, 6), so "the basis series" would be
 * false here; the title says "basis" and the rest (Retry, "Last loaded hh:mm:ss UTC") is S54-8 verbatim.
 */
export const RETRY_TITLE = "Couldn't load basis";
export const RETRY = "Retry";
export const lastLoaded = (ms: number): string => `Last loaded ${utcTime(ms)}`;
/** PROPOSED: the band when the source failed before any item arrived (no timestamp is invented). */
export const NEVER_LOADED = "Nothing loaded yet.";

/** D03 S54-9 `ratio-unavailable`: verbatim; no timestamp, no series (BQ 3, ruled (6612480577): the gap is on #784). */
export const RATIO_LABEL = "L/S ratio";
export const RATIO_UNAVAILABLE = "source unavailable";
export const RATIO_ROW = `${RATIO_LABEL} · ${RATIO_UNAVAILABLE}`;

export const TABLE_SHOW = "Show table";
export const TABLE_HIDE = "Hide table";
export const tableCaption = (symbol: string): string => `Basis, ${symbol}, latest values`;
export const COL_TIME = "Time (UTC)";
export const COL_MARK = "Mark (USDT)";
export const COL_INDEX = "Index (USDT)";
export const COL_BASIS = "Basis (USDT)";
export const COL_PCT = "Basis %";
export const COL_SOURCE = "Source";
export const NO_ROWS = "No basis values yet.";

/** PROPOSED: the accessible names of the two polite regions (the panel's state, the readout's source change). */
export const STATE_REGION = "Basis state";
export const SOURCE_REGION = "Basis source change";
