/**
 * "About" how much a symbol recorded before a bound (E16-D02 §6.4, §6.5; C-5: no purge preview is served, so the
 * dialogs estimate): the storage report's size times the share of the symbol's rows recorded before the bound,
 * each coverage interval's rows prorated by time; without intervals, the share of the time since it began. The
 * audit record carries the exact figures. Pure.
 */
import { formatBytes, formatDate, parseMs } from "./model";
import type { DataCoverage } from "./recorderApi";

export const DAY_MS = 86_400_000;

/** "2026-10-01": a bound's day as the date field holds it (UTC). */
export const dayOf = (ms: number): string => formatDate(ms);

export interface Estimate {
  /** About how many bytes were recorded before the bound; null with no size known. */
  readonly bytes: number | null;
  /** The window's start: the earliest recorded interval, else the row's start. */
  readonly fromMs: number | null;
}

export function estimateBefore(
  coverage: DataCoverage | null,
  diskBytes: number | null,
  startedAt: string | null,
  boundMs: number,
  nowMs: number,
): Estimate {
  let total = 0;
  let before = 0;
  let earliest: number | null = null;
  for (const stream of coverage?.streams ?? []) {
    for (const span of stream.intervals ?? []) {
      const from = parseMs(span.from);
      const to = parseMs(span.to);
      const rows = span.rows ?? 0;
      if (from === null || to === null || to < from || rows <= 0) continue;
      earliest = earliest === null ? from : Math.min(earliest, from);
      total += rows;
      if (to <= boundMs) before += rows;
      else if (from < boundMs) before += (rows * (boundMs - from)) / Math.max(1, to - from);
    }
  }
  const fromMs = earliest ?? parseMs(startedAt);
  let share: number | null = total > 0 ? before / total : null;
  if (share === null && fromMs !== null && nowMs > fromMs) {
    share = Math.min(1, Math.max(0, (boundMs - fromMs) / (nowMs - fromMs)));
  }
  return { bytes: diskBytes === null || share === null ? null : diskBytes * share, fromMs };
}

/** "5.5 GB", the deck's `{size}`; "—" when no size is known. */
export const sizeText = (bytes: number | null): string =>
  bytes === null ? "—" : formatBytes(Math.max(0, bytes));
