/**
 * The gap facts the chart pane carries (E16-D05 §3, §6–§8): the typed interval list handed to the engine's band (BQ-02:
 * the band layer, its label, its tooltip and the cursor sentence are not in this pass; the list is) and the chart
 * region's description. Coverage older than the report's 90 days is unknown, never a gap and never covered (D05-CG1). A
 * reason this client does not know is still a gap, with the fallback words (C-6.3).
 */
import { gapText, type DataCoverage } from "../symbol-info/coverage";
import { GAP_BACKFILLED, GAP_MISSING, GAP_SENTENCE, GAP_UNKNOWN, fill } from "./copy";

const DAY = 86_400_000;
/** `/market/data-coverage` answers the last 90 days only (D05-CG1, BQ-14 RULED). */
export const COVERAGE_HORIZON_MS = 90 * DAY;

export interface TimeWindow {
  readonly fromMs: number;
  readonly toMs: number;
}

/** One gap on the render model: epoch ms, clipped to the window and the report horizon. */
export interface GapInterval {
  readonly fromMs: number;
  readonly toMs: number;
  /** `22`'s open-ended `gaps[].reason`, as served (`null` when absent). */
  readonly reason: string | null;
  /**
   * D05-G1 (BQ-04): `true` only when the server sends `backfilled: true`. The columns exist (`21`:3248-3249,
   * `24`:4176-4177) but `22` does not serve them yet, so it is read by presence (the PROPOSED branch).
   */
  readonly backfilled: boolean;
}

const time = (iso: string | undefined): number | null => {
  const ms = iso === undefined ? NaN : Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
};

/** The report's horizon: `generated_at` − 90 days; `null` without a readable `generated_at`. */
export function coverageHorizon(coverage: DataCoverage): number | null {
  const at = time(coverage.generated_at);
  return at === null ? null : at - COVERAGE_HORIZON_MS;
}

/**
 * Every gap of every stream that meets `window`, deduplicated and in time order; clipped to the window for the engine,
 * or whole (`clip` false) where the words name the gap itself (SCR-047's reason 2).
 */
export function gapIntervals(
  coverage: DataCoverage,
  window: TimeWindow,
  clip = true,
): GapInterval[] {
  const horizon = coverageHorizon(coverage) ?? Number.NEGATIVE_INFINITY;
  const start = Math.max(window.fromMs, horizon);
  const seen = new Map<string, GapInterval>();
  for (const stream of coverage.streams ?? []) {
    for (const gap of stream.gaps ?? []) {
      const from = time(gap.from);
      const to = time(gap.to);
      if (from === null || to === null || to <= start || from >= window.toMs) continue;
      const clipped: GapInterval = {
        fromMs: clip ? Math.max(from, start) : from,
        toMs: clip ? Math.min(to, window.toMs) : to,
        reason: gap.reason ?? null,
        backfilled: Reflect.get(gap, "backfilled") === true,
      };
      const key = `${String(clipped.fromMs)}:${String(clipped.toMs)}:${String(clipped.reason)}`;
      if (!seen.has(key)) seen.set(key, clipped);
    }
  }
  return [...seen.values()].sort((a, b) => a.fromMs - b.fromMs);
}

/** The earliest recorded interval start, or `null` when nothing was recorded in the report. */
export function earliestRecorded(coverage: DataCoverage): number | null {
  let earliest: number | null = null;
  for (const stream of coverage.streams ?? []) {
    for (const interval of stream.intervals ?? []) {
      const from = time(interval.from);
      if (from !== null && (earliest === null || from < earliest)) earliest = from;
    }
  }
  return earliest;
}

/** The deck's cause sentence for a reason (D05 §2), `{N}` filled; an unknown reason takes the fallback (C-6.3). */
export function gapCause(reason: string | null, retentionDays: number | null = null): string {
  const sentence =
    reason !== null && Object.hasOwn(GAP_SENTENCE, reason) ? GAP_SENTENCE[reason] : undefined;
  return sentence === undefined ? GAP_UNKNOWN : fill(sentence, { N: String(retentionDays ?? 30) });
}

/** "02:11" in UTC. */
export const utcTime = (ms: number): string => new Date(ms).toISOString().slice(11, 16);
/** "2026-09-04" in UTC. */
export const utcDate = (ms: number): string => new Date(ms).toISOString().slice(0, 10);
/** "2026-09-04 08:00 UTC": the deck's `{ts}`, text with its zone. */
export const utcStamp = (ms: number): string => `${utcDate(ms)} ${utcTime(ms)} UTC`;

/**
 * `chip.partial.missing`: every range in the merged `symbol-info` `gapText` words (one implementation; D05's short
 * causes differ, a C-row to E16-D05), every range listed (G-09: no cut-off rule yet). A `backfilled` gap adds
 * `gap.tooltip.backfilled`, PROPOSED until `22` serves the field (D05-G1).
 */
export function missingSentence(gaps: readonly GapInterval[]): string | null {
  if (gaps.length === 0) return null;
  const ranges = gaps.map((gap) => {
    const text = gapText(gap.fromMs, gap.toMs, gap.reason ?? undefined);
    return gap.backfilled ? `${text} (${GAP_BACKFILLED})` : text;
  });
  return fill(GAP_MISSING, { ranges: ranges.join("; ") });
}
