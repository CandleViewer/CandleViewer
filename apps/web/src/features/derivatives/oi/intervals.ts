// E24-S01 (#776) slice 1: the open-interest series' intervals, units and bar alignment. Nothing here
// touches a value: alignment is on time only, and units are words read off the symbol (BQ 1).
import type { generated } from "@candleviewer/protocol";

export type OiInterval = generated.rest.components["schemas"]["OpenInterestPoint"]["interval"];

/** `22` `getOpenInterestHistory` `interval`: `1s` is the ticker-recorded series, the rest Bybit REST (the enum ends at `1d`). */
export const OI_INTERVAL_MS: Readonly<Record<OiInterval, number>> = {
  "1s": 1_000,
  "5min": 300_000,
  "15min": 900_000,
  "30min": 1_800_000,
  "1h": 3_600_000,
  "4h": 14_400_000,
  "1d": 86_400_000,
};

/** The REST-backfilled intervals, finest first (`22`: `5min`…`1d`, `source: rest`). */
export const REST_INTERVALS: readonly OiInterval[] = ["5min", "15min", "30min", "1h", "4h", "1d"];

const LABEL: Readonly<Record<OiInterval, string>> = {
  "1s": "1 s",
  "5min": "5 min",
  "15min": "15 min",
  "30min": "30 min",
  "1h": "1 h",
  "4h": "4 h",
  "1d": "1 d",
};

export const isOiInterval = (v: unknown): v is OiInterval =>
  typeof v === "string" && Object.hasOwn(OI_INTERVAL_MS, v);

/** "5 min": the copy deck's span words (D02 §15 `Native granularity 5 min`). */
export const intervalLabel = (interval: OiInterval): string => LABEL[interval];

/**
 * PROPOSED (BQ 4): the REST interval asked for a chart bar: the coarsest REST interval no coarser than the bar,
 * else the finest (`5min`), so a 1 m chart reads 5 min history and shows the note.
 */
export function requestInterval(barMs: number): OiInterval {
  let chosen: OiInterval = "5min";
  for (const interval of REST_INTERVALS) if (OI_INTERVAL_MS[interval] <= barMs) chosen = interval;
  return chosen;
}

/**
 * US-DERIV-001 sc. 2 (BQ 4): the note when the chart's bar is finer than the history's native granularity, read
 * from `meta.coverage.native_interval`, never a hard-coded 5 min. `null` when there is nothing to say.
 */
export function granularityNote(barMs: number, native: OiInterval | null): string | null {
  if (native === null || !(barMs < OI_INTERVAL_MS[native])) return null;
  return `Native granularity ${LABEL[native]}`;
}

const WEEK_MS = 7 * 86_400_000;
/** The epoch is a Thursday: weeks open on Monday 00:00 UTC. */
const MONDAY_OFFSET_MS = 4 * 86_400_000;

/**
 * The bar a timestamp falls in, UTC-aligned (US-DERIV-001 sc. 2): an epoch grid up to a day, Monday-aligned for a
 * 7-day bar. A month has no fixed `barMs`, so M bars are unsupported (`22` serves nothing above `1d`).
 */
export function alignToBar(tsMs: number, barMs: number): number {
  const origin = barMs === WEEK_MS ? MONDAY_OFFSET_MS : 0;
  const shifted = tsMs - origin;
  const rem = shifted % barMs;
  return (rem < 0 ? shifted - rem - barMs : shifted - rem) + origin;
}

/** The base coin of a USDT linear perpetual ("BTCUSDT" → "BTC"): REST `open_interest`'s unit (BQ 1). */
export function baseCoin(symbol: string): string {
  return symbol.endsWith("USDT") && symbol.length > 4 ? symbol.slice(0, -4) : symbol;
}

/** The quote unit of `open_interest_value`: USDT on screen, as D02 §15 rules for every quote amount (NG-12). */
export const QUOTE_UNIT = "USDT";
