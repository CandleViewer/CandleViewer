/**
 * SCR-140's row detail, the pure part (E16-S01 PR 3; E16-D02 §4.1, §6.3, §6.4, §6.7; E16-D06 KB-03, T2-01, T2-02):
 * the health figures (the newest frame's, else the status's), the row's one action and its T2 reason, the
 * retention select's options and the figures as text. No React; the server decides every write (C-12.4).
 */
import type { SelectOption } from "@candleviewer/ui";
import { fill } from "./copy";
import { DETAIL_TEXT } from "./detailCopy";
import { STREAM_LABELS } from "./pageCopy";
import {
  formatDate,
  formatHourMinute,
  parseMs,
  stopBlockedKey,
  t2Reason,
  type RecorderRow,
} from "./model";
import type { RecorderFrame, RecordingStatus } from "./model/types";
import type { StreamKind } from "./grid";

/** D02 §6.7's Health: the figures a row's detail reads. */
export interface RowHealth {
  readonly lagMs: number | null;
  readonly rowsLastHour: number | null;
  readonly resyncsLastHour: number | null;
  readonly lastEventAtMs: number | null;
  readonly droppedMessages: number | null;
}

const num = (value: number | null | undefined): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/** The frame's row (1 Hz), else the status's (the first paint, or a frame that omits the symbol). */
export function rowHealth(
  symbol: string,
  frame: RecorderFrame | null,
  status: RecordingStatus | null,
): RowHealth | null {
  const live = frame?.symbols.find((s) => s.symbol === symbol);
  if (live !== undefined) {
    return {
      lagMs: num(live.lag_ms),
      rowsLastHour: num(live.rows_last_hour),
      resyncsLastHour: num(live.resyncs_last_hour),
      lastEventAtMs: num(live.last_event_at_ms),
      droppedMessages: num(live.dropped_messages),
    };
  }
  const read = status?.symbols?.find((s) => s.symbol === symbol);
  if (read === undefined) return null;
  return {
    lagMs: num(read.lag_ms),
    rowsLastHour: num(read.rows_last_hour),
    resyncsLastHour: num(read.resyncs_last_hour),
    lastEventAtMs: parseMs(read.last_event_at),
    droppedMessages: num(read.dropped_messages),
  };
}

/** The row's one action (D02 §4.1): Stop, Keep recording or Record again; none while refused or stopping. */
export type RowActionKind = "stop" | "keep" | "again";

export interface RowAction {
  readonly kind: RowActionKind;
  /** The §8.5 T2 reason (`recorder.stop_blocked.*`, `recorder.symbol_cap`), inline in the drawer (2a). */
  readonly reason: string | undefined;
}

export function rowAction(row: RecorderRow, grace: string): RowAction | null {
  if (row.state === "refused" || row.state === "stopping") return null;
  if (row.state === "lingering") return { kind: "keep", reason: undefined };
  if (row.state === "stopped") {
    const capped = row.recordAgainBlockedReason === "symbol_cap";
    return { kind: "again", reason: capped ? t2Reason("recorder.symbol_cap", grace) : undefined };
  }
  const key = stopBlockedKey(row);
  return { kind: "stop", reason: key === null ? undefined : t2Reason(key, grace) };
}

/** "2026-09-01 09:00 UTC" (D02 §6.7: "started (UTC date and time)"); "—" while starting. */
export function startedText(iso: string | null | undefined): string {
  const ms = parseMs(iso);
  return ms === null ? "—" : `${formatDate(ms)} ${formatHourMinute(ms)} UTC`;
}

/** "Trades, Order-book deltas, Tickers" in the contract's order. */
export const streamsText = (streams: readonly StreamKind[] | undefined): string =>
  streams === undefined || streams.length === 0
    ? "—"
    : streams.map((kind) => STREAM_LABELS[kind]).join(", ");

/** A count with D02 §3's grouping, "41 220 118". */
export const grouped = (count: number): string =>
  Math.round(count).toLocaleString("en-US").replaceAll(",", " ");

/** "30 days"; "1 day" (C-5347-08). */
export const daysText = (n: number): string =>
  n === 1 ? DETAIL_TEXT.day : fill(DETAIL_TEXT.days, { "{n}": n });

/** The retention select's values: "forever" (pinned), a day count, or "custom" (SCR-141 once registered). */
export const FOREVER = "forever";
export const CUSTOM = "custom";

/**
 * D02 §6.4: 7 · 30 · 90 · 365 days, the row's own value when it is none of them, "Forever" while pinned, and
 * "Custom…" when SCR-141 is registered (BQ-11).
 */
export function retentionOptions(row: RecorderRow, custom: boolean): SelectOption[] {
  const days = new Set<number>(DETAIL_TEXT.retentionDays);
  if (!row.pinned && row.retentionDays !== null) days.add(row.retentionDays);
  const options: SelectOption[] = [...days]
    .sort((a, b) => a - b)
    .map((n) => ({ value: String(n), label: daysText(n) }));
  if (row.pinned) options.push({ value: FOREVER, label: DETAIL_TEXT.forever });
  if (custom) options.push({ value: CUSTOM, label: DETAIL_TEXT.custom });
  return options;
}

/** The select's value for the row: "forever" while pinned, else its days; undefined when none is known. */
export const retentionValue = (row: RecorderRow): string | undefined =>
  row.pinned ? FOREVER : row.retentionDays === null ? undefined : String(row.retentionDays);
