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
export const regionName = (symbol: string): string => `Basis, ${symbol}`;

/** D03 §3: `basis, mark − index · source`; with `last` it reads `basis, last − index`. */
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
