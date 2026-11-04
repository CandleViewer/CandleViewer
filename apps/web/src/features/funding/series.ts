// E24-S03 (#778) slice 1: the stepped funding series for the engine's linked sub-pane and the table: one step
// per settled rate, its width the served `funding_interval_minutes` (BQ 8), never the points' spacing, which
// would stretch a step over a missing settlement. The bars form (`deriv.funding_style`) reads the same steps.
import type { FundingHistoryOk, SettledPoint } from "./history";
import type { PredictedRate } from "./predicted";

export interface FundingStep {
  /**
   * PROPOSED: a rate settled at `toMs` accrued over the interval before it, so its step spans
   * `[toMs − interval, toMs]` and ends at its settlement.
   */
  readonly fromMs: number;
  readonly toMs: number;
  readonly rate: string;
}

export interface FundingGap {
  readonly fromMs: number;
  readonly toMs: number;
}

export interface FundingSeriesModel {
  /** `null` when not served: no step is drawn and no interval is stated. */
  readonly intervalMs: number | null;
  readonly settled: readonly SettledPoint[];
  readonly steps: readonly FundingStep[];
  /** `meta.coverage.gaps`: spans with a missing settlement, reported and never filled. */
  readonly gaps: readonly FundingGap[];
  /**
   * E24-S04: the accruing rate, a separate marker beyond the last settled step and never a step of the settled
   * line (D03 §5.3); `null`: none published, so no marker and no phantom point.
   */
  readonly predicted: PredictedRate | null;
}

export const EMPTY_SERIES: FundingSeriesModel = {
  intervalMs: null,
  settled: [],
  steps: [],
  gaps: [],
  predicted: null,
};

const MINUTE_MS = 60_000;

export function buildFundingSeries({
  settled,
  intervalMinutes,
  coverage,
  predicted = null,
}: Pick<FundingHistoryOk, "settled" | "intervalMinutes" | "coverage"> & {
  readonly predicted?: PredictedRate | null;
}): FundingSeriesModel {
  const intervalMs = intervalMinutes === null ? null : intervalMinutes * MINUTE_MS;
  const ascending = [...settled].sort((a, b) => a.tMs - b.tMs);
  return {
    intervalMs,
    settled: ascending,
    steps:
      intervalMs === null
        ? []
        : ascending.map((p) => ({ fromMs: p.tMs - intervalMs, toMs: p.tMs, rate: p.rate })),
    gaps: coverage?.gaps ?? [],
    predicted,
  };
}

/**
 * The settled points after a newer read (slice 2's settlement poll): unique by time, the newer read wins,
 * ascending. Returns `true` with the list when `next` added a settlement the model did not have.
 */
export function mergeSettled(
  prev: readonly SettledPoint[],
  next: readonly SettledPoint[],
): { readonly points: readonly SettledPoint[]; readonly added: boolean } {
  const byTime = new Map(prev.map((p) => [p.tMs, p] as const));
  let added = false;
  for (const p of next) {
    if (!byTime.has(p.tMs)) added = true;
    byTime.set(p.tMs, p);
  }
  return { points: [...byTime.values()].sort((a, b) => a.tMs - b.tMs), added };
}

/** E24-S04 BQ-1: the annualised toggle exists only when the server served an annualised value to show. */
export const servesAnnualised = (series: FundingSeriesModel): boolean =>
  series.intervalMs !== null &&
  ((series.predicted !== null && series.predicted.annualisedPct !== null) ||
    series.settled.some((p) => p.annualisedPct !== undefined));
