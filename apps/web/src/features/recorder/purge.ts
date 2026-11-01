/**
 * Purge data…, the pure part (E16-S01 PR 3; E16-D02 §6.5; E16-D04 §1.3, §7): the default window bound, the bound
 * sent, the body's figures and the dialog's own validity rules after the typed symbol's. No React.
 */
import { DECK, fill } from "./copy";
import { PURGE_TEXT } from "./detailCopy";
import { dayOf, sizeText, DAY_MS, type Estimate } from "./estimate";
import { DEFAULT_RETENTION_DAYS } from "./grid";
import { parseMs, type RecorderRow } from "./model";
import type { StorageUsage } from "./model/types";

/** `purgeRecordedData`'s reason: 3 to 280 characters (`22`), counted as the server does, by code point. */
export const REASON_MIN = 3;
export const REASON_MAX = 280;

/** What the purge dialog needs to know of a symbol it offers. */
export interface PurgeTarget {
  readonly symbol: string;
  readonly pinned: boolean;
  readonly retentionDays: number | null;
  /** The symbol's recorded size: the page's live figure (the row's), else the storage report's. */
  readonly diskBytes: number | null;
  /** When it began recording: the window's start when no coverage answered. */
  readonly startedAt: string | null;
}

/** A purge this client started: what its banner and its terminal line name (D02 §3, §3.2). */
export interface PurgeJob {
  readonly jobId: string;
  readonly symbol: string;
  /** The window's upper bound sent, epoch ms: the banner's "recorded before {date}". */
  readonly beforeMs: number;
}

/**
 * D02 §6.5's default bound: the retention cut-off, today less the row's retention in whole UTC days; a pinned
 * row (no retention) takes the default retention's (`22`: 30 days).
 */
export function defaultBefore(target: PurgeTarget | undefined, nowMs: number): string {
  const days =
    target?.pinned === false
      ? (target.retentionDays ?? DEFAULT_RETENTION_DAYS)
      : DEFAULT_RETENTION_DAYS;
  return dayOf(nowMs - days * DAY_MS);
}

/** `22`'s stable code tokens: lowercase, digits and underscores, after a letter. */
const CODE_TOKEN = /^[a-z][a-z0-9_]*$/;

/**
 * A failed job's code for its line (`Job.error`, a stable code in `22`): the token itself, else "failed", so a server
 * that sends free text never puts it on an assertive line (C-5347-d08).
 */
export const jobErrorCode = (error: unknown): string =>
  typeof error === "string" && CODE_TOKEN.test(error) ? error : "failed";

/** The bound sent: the day's 00:00 UTC, an RFC 3339 instant with an offset (`22` `before`). */
export const beforeInstant = (day: string): string => `${day}T00:00:00Z`;

/** The bound as epoch ms; null for no day, or one that does not parse. */
export const beforeMs = (day: string | null): number | null =>
  day === null ? null : parseMs(beforeInstant(day));

/** D02 §6.5's body for an estimate and a bound (frozen row (viii): what, how much, cannot be undone). */
export function purgeBody(estimate: Estimate, boundDay: string): string {
  return fill(DECK["storage.purge.body"][0], {
    "{size}": sizeText(estimate.bytes),
    "{from}": estimate.fromMs === null ? "—" : dayOf(estimate.fromMs),
    "{to}": boundDay,
  });
}

/**
 * E16-D04 §1.3's validity look, the dialog's own rules after the typed symbol's (CMP-044 checks that one): a date
 * that parses (CMP-047's typed error, in its own words: the picker commits nothing invalid, so `boundDay` is still the
 * last valid one, A-5347-d02), a bound no later than now, then a reason of at least 3 characters. Undefined when all
 * hold.
 */
export function purgeValidity(
  boundDay: string | null,
  reason: string,
  nowMs: number,
  dateError: string | null = null,
): string | undefined {
  if (dateError !== null) return dateError;
  const bound = beforeMs(boundDay);
  if (bound === null || bound > nowMs) return DECK["storage.purge.before.reason"][0];
  // Code points, as the server counts (an emoji is one, C-5347-08), never UTF-16 units.
  if ([...reason.trim()].length < REASON_MIN) return PURGE_TEXT.reasonShort;
  return undefined;
}

/**
 * The symbols the dialog offers: the page's rows in their order (a refused entry only with data on disk), then the
 * storage report's other symbols by name (data kept after its row left). A row's size is the page's own, the 1 Hz
 * frame's, so the dialog never contradicts the grid's Size; the one-shot report's only where the row has none
 * (C-5347-03).
 */
export function purgeTargets(
  rows: readonly RecorderRow[],
  storage: StorageUsage | null,
): PurgeTarget[] {
  const reported = new Map(
    (storage?.symbols ?? []).flatMap((s) =>
      s.symbol === undefined ? [] : [[s.symbol, s] as const],
    ),
  );
  const fromRows = rows
    .filter((row) => row.state !== "refused" || (row.diskBytes ?? 0) > 0)
    .map((row) => ({
      symbol: row.symbol,
      pinned: row.pinned,
      retentionDays: row.retentionDays,
      diskBytes: row.diskBytes ?? reported.get(row.symbol)?.used_bytes ?? null,
      startedAt: row.startedAt,
    }));
  const listed = new Set(rows.map((row) => row.symbol));
  const others = [...reported.values()]
    .filter((s) => s.symbol !== undefined && !listed.has(s.symbol))
    .sort((a, b) => (a.symbol ?? "").localeCompare(b.symbol ?? ""))
    .map((s) => ({
      symbol: s.symbol ?? "",
      pinned: s.pinned ?? false,
      retentionDays: null,
      diskBytes: s.used_bytes ?? null,
      startedAt: null,
    }));
  return [...fromRows, ...others];
}
