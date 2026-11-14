// E24-S07 (#782) slice 2: the samples the stories and tests share: `22` `getLiquidationsByPrice`'s `byPrice` example
// (slice 0), varied only in members the generated `LiquidationsByPrice` declares.
import type { ByPriceAnswer } from "./byPriceRead";

type Coverage = ByPriceAnswer["meta"]["coverage"];

/** `22`'s example as served: the store covers 06:30:00.250 UTC onwards of a day read from 00:00 UTC (partial). */
export const EXAMPLE: ByPriceAnswer = {
  symbol: "BTCUSDT",
  from: "2026-09-14T00:00:00Z",
  to: "2026-09-14T11:00:00Z",
  bucket_ticks: 20,
  tick_size: "0.10",
  estimated: false,
  items: [
    {
      price_lo: "62880.00",
      price_hi: "62882.00",
      long_notional_usd: "202473.60",
      short_notional_usd: "0",
      prints: 1,
    },
    {
      price_lo: "63120.00",
      price_hi: "63122.00",
      long_notional_usd: "0",
      short_notional_usd: "41330.25",
      prints: 2,
    },
  ],
  meta: {
    coverage: {
      first_available_ts: "2026-09-14T06:30:00.250Z",
      covered_from: "2026-09-14T06:30:00.250Z",
      covered_to: "2026-09-14T11:00:00Z",
      no_coverage: false,
    },
  },
};

/** The answer's own `to`: the stories' reference time. */
export const NOW = Date.parse(EXAMPLE.to);

const withCoverage = (over: Partial<Coverage>, items = EXAMPLE.items): ByPriceAnswer => ({
  ...EXAMPLE,
  items,
  meta: { coverage: { ...EXAMPLE.meta.coverage, ...over } },
});
const NONE = { covered_from: null, covered_to: null, no_coverage: true } as const;

/** The store covers the whole day so far. */
export const FULL = withCoverage({
  first_available_ts: "2026-09-01T00:00:00Z",
  covered_from: EXAMPLE.from,
});
/** The covered day holds no print. */
export const EMPTY: ByPriceAnswer = { ...FULL, items: [] };
/** The window ends before the first stored print. */
export const NOT_RECORDED = withCoverage(
  { ...NONE, first_available_ts: "2026-09-15T08:00:00Z" },
  [],
);
/** Nothing stored for the symbol at all. */
export const NEVER_RECORDED = withCoverage({ ...NONE, first_available_ts: null }, []);
/** BQ 7's positive: a flag set to true draws the estimated word (a fixture: no (b) answer carries it). */
export const FLAGGED: ByPriceAnswer = { ...FULL, estimated: true };
