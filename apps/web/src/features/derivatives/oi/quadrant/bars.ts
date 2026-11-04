// E24-S02 (#777) slice 1: the per-bar delta model. `open_interest_delta` and `oi_price_quadrant` arrive from
// `/market/metrics` as served (#5341; bar-scoped, `bar_type=time`): the delta is a decimal string and is never
// combined, summed or re-derived here (exact decimals, "no client-side computation"); the quadrant is the
// served enum. A `null` is first-class: "unclassified" (BQ-3). It reads "(no OI sample)" only when the OI
// feed itself (#776's rows) holds no point for the bar; flat price or flat OI also serve `null` and the wire
// cannot tell them apart (a G-row on #723), so those stay plain "unclassified".
import type { generated } from "@candleviewer/protocol";
import type { OiRow } from "../series";
import { quadrantOf, type QuadrantWire } from "./quadrant";

/**
 * The generated `MetricSeries`, narrowed to what this reads. R6 pin: `oi_price_quadrant` and the enum `v`
 * come from #5341, read at its head `021c794`; "if #5341 merges as is" these types are unchanged (`v` is a
 * string either way, a decimal or the enum value). `unit` is optional on the wire: an absent one shows no
 * unit word (`deltaUnitLabel`), never a hard-coded one.
 */
export type MetricSeriesLike = Pick<
  generated.rest.components["schemas"]["MetricSeries"],
  "points" | "unit"
>;

export type UnclassifiedReason = "no_sample" | "unclassified";

export interface OiBar {
  readonly tMs: number;
  /** The served per-bar OI change; `null` = none for the bar (never 0). */
  readonly delta: string | null;
  readonly quadrant: QuadrantWire | null;
  /** Set exactly when `quadrant` is null. */
  readonly reason: UnclassifiedReason | null;
}

export interface OiBarModel {
  readonly bars: readonly OiBar[];
  /** From `MetricSeries.unit` (BQ-7), never hard-coded; `null` when the series carries none. */
  readonly deltaUnit: string | null;
  /** The chart's bar, so a consumer aligns a feed row to its metrics bar with `alignToBar`. */
  readonly barMs: number;
  /** The symbol the series was built for; a pane showing another symbol treats these bars as absent. */
  readonly symbol: string;
}

export interface QuadrantCounts {
  readonly byQuadrant: Readonly<Record<QuadrantWire, number>>;
  readonly noSample: number;
  /** `null` quadrants without the no-sample reason. */
  readonly unclassified: number;
  /** noSample + unclassified. */
  readonly unclassifiedTotal: number;
}

/**
 * Does the sorted `rows` hold a point overlapping [fromMs, fromMs + barMs)? Binary search for the last row
 * starting before the bar's end; the feed's rows do not overlap (a history span is clipped where live
 * begins, #776 A2), so that row is the only candidate.
 */
function hasSample(rows: readonly OiRow[], fromMs: number, barMs: number): boolean {
  const end = fromMs + barMs;
  let lo = 0;
  let hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((rows[mid]?.tMs ?? Infinity) < end) lo = mid + 1;
    else hi = mid;
  }
  const r = rows[lo - 1];
  return r !== undefined && r.tMs + r.spanMs > fromMs;
}

/**
 * Join the two served series by bar open time. `rows` is the OI feed's series (#776): its absence for a bar is
 * the only source of "no OI sample". `barMs` is the chart's bar.
 */
export function buildOiBars(
  delta: MetricSeriesLike,
  quadrant: MetricSeriesLike,
  rows: readonly OiRow[],
  barMs: number,
  symbol: string,
): OiBarModel {
  const sorted = [...rows].sort((x, y) => x.tMs - y.tMs);
  const q = new Map<number, unknown>();
  for (const p of quadrant.points) q.set(Date.parse(p.t), p.v);
  // one bar per open time: a duplicated `t` keeps the later point (last write wins)
  const byT = new Map<number, (typeof delta.points)[number]>();
  for (const p of delta.points) byT.set(Date.parse(p.t), p);
  const bars = [...byT.values()]
    .map((p): OiBar => {
      const tMs = Date.parse(p.t);
      const cls = quadrantOf(q.get(tMs));
      return {
        tMs,
        delta: p.v,
        quadrant: cls,
        reason: cls !== null ? null : hasSample(sorted, tMs, barMs) ? "unclassified" : "no_sample",
      };
    })
    .filter((b) => Number.isFinite(b.tMs))
    .sort((a, b) => a.tMs - b.tMs);
  return { bars, deltaUnit: delta.unit ?? null, barMs, symbol };
}

/**
 * The unit word shown for the delta (orchestrator ruling 2026-11-04 on #777, BQ-7 follow-up): the series'
 * unit is a kind ("qty"), so it is labelled with the symbol's base coin from instrument info, as a display
 * label only, never a value. Any other unit is shown as served; an unknown base coin falls back to "qty".
 * TODO(#723 G-row): a server `unit_coin` on `MetricSeries` replaces this derivation.
 */
export function deltaUnitLabel(unit: string, base: string | null | undefined): string;
export function deltaUnitLabel(unit: string | null, base: string | null | undefined): string | null;
export function deltaUnitLabel(
  unit: string | null,
  instrumentBaseCoin: string | null | undefined,
): string | null {
  if (unit !== "qty") return unit; // a served unit as it is; none served, none shown
  return instrumentBaseCoin === null ||
    instrumentBaseCoin === undefined ||
    instrumentBaseCoin === ""
    ? unit
    : instrumentBaseCoin;
}

export function countBars(bars: readonly OiBar[]): QuadrantCounts {
  const byQuadrant: Record<QuadrantWire, number> = {
    long_buildup: 0,
    short_covering: 0,
    short_buildup: 0,
    long_unwind: 0,
  };
  let noSample = 0;
  let unclassified = 0;
  for (const b of bars) {
    if (b.quadrant !== null) byQuadrant[b.quadrant] += 1;
    else if (b.reason === "no_sample") noSample += 1;
    else unclassified += 1;
  }
  return { byQuadrant, noSample, unclassified, unclassifiedTotal: noSample + unclassified };
}
