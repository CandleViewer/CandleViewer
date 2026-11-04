// E24-S02 (#777): a typed fixture of #5341's `/market/metrics` answer for `open_interest_delta` and
// `oi_price_quadrant` (bar-scoped, 5 min bars), in the shapes #5341's own tests pin (`["20","20",null]`,
// `["long_buildup","short_buildup",null]`, a `null` for a bar with no OI sample, never 0). Documented-shape,
// not a live capture (C-13.5), and its bars are invented: the times, the decimals and the six-bar shape
// are this file's, only the field names and values per bar are #5341's. Pinned to #5341's head `021c794`:
// "if #5341 merges as is" it stands; re-pin to the merge commit once it lands (R6). The stories and the
// tests read it. Bars 0-2 and 4-5 hold an OI point; bar 3
// has none (no sample), bar 4 is a flat OI bar the server could not classify.
import type { OiRow } from "../series";
import type { MetricSeriesLike } from "./bars";

const MIN = 60_000;
export const FIXTURE_T0 = Date.parse("2026-10-21T09:00:00Z");
export const FIXTURE_BAR_MS = 5 * MIN;
const iso = (i: number): string => new Date(FIXTURE_T0 + i * FIXTURE_BAR_MS).toISOString();

export const DELTA_SERIES: MetricSeriesLike = {
  unit: "qty",
  points: [
    { t: iso(0), v: "20" },
    { t: iso(1), v: "12.5" },
    { t: iso(2), v: "-8.25" },
    { t: iso(3), v: null },
    { t: iso(4), v: "0" },
    { t: iso(5), v: "-3" },
  ],
};

export const QUADRANT_SERIES: MetricSeriesLike = {
  unit: "enum",
  points: [
    { t: iso(0), v: "long_buildup" },
    { t: iso(1), v: "short_buildup" },
    { t: iso(2), v: "short_covering" },
    { t: iso(3), v: null },
    { t: iso(4), v: null },
    { t: iso(5), v: "long_unwind" },
  ],
};

export const FIXTURE_ROWS: readonly OiRow[] = [0, 1, 2, 4, 5].map((i) => ({
  tMs: FIXTURE_T0 + i * FIXTURE_BAR_MS,
  spanMs: FIXTURE_BAR_MS,
  base: String(51_280 + i * 7),
  valueUsdt: null,
  source: "rest",
  forming: false,
  asOfMs: FIXTURE_T0 + i * FIXTURE_BAR_MS,
}));
