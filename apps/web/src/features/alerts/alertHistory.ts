/**
 * Firing history (E40-S01; E40-D02 §2.6): delivery rows grouped per firing (one transaction stamps
 * every channel row of a firing with the same `fired_at`), newest first, and the CSV of the same rows.
 */
import type { DeliveryRow } from "./types.js";

export interface HistoryChannel {
  readonly channel: string;
  readonly word: string;
  readonly suppressedStorm: boolean;
}

export interface Firing {
  readonly firedAt: string;
  readonly message: string;
  readonly channels: readonly HistoryChannel[];
  readonly suppressedStorm: boolean;
}

const CHANNEL_WORD: Readonly<Record<string, string>> = {
  in_app: "In app",
  desktop: "Desktop",
  email: "Email",
  webhook: "Webhook",
  push: "Push",
};
const SUPPRESS_REASON: Readonly<Record<string, string>> = {
  storm: "(storm)",
  owner_inactive: "(user disabled)",
  recipient_deleted: "(recipient removed)",
};

export function statusWord(row: DeliveryRow): string {
  switch (row.status) {
    case "sent":
      return "delivered";
    case "acked":
      return "delivered, read";
    case "queued":
      return row.channel === "desktop" ? "not shown on the desktop" : "queued";
    case "failed":
      return "failed";
    case "suppressed":
      return `suppressed ${SUPPRESS_REASON[row.error ?? ""] ?? "(channel unavailable)"}`;
    default:
      return String(row.status ?? "unknown");
  }
}

export function groupFirings(rows: readonly DeliveryRow[]): readonly Firing[] {
  const byTime = new Map<string, DeliveryRow[]>();
  for (const row of rows) {
    const key = row.fired_at ?? "";
    byTime.set(key, [...(byTime.get(key) ?? []), row]);
  }
  return [...byTime.entries()]
    .sort(([a], [b]) => Date.parse(b) - Date.parse(a))
    .map(([firedAt, group]) => {
      const channels = group.map((row) => ({
        channel: CHANNEL_WORD[row.channel ?? ""] ?? String(row.channel),
        word: statusWord(row),
        suppressedStorm: row.status === "suppressed" && row.error === "storm",
      }));
      return {
        firedAt,
        message: group.find((row) => (row.message ?? "") !== "")?.message ?? "",
        channels,
        suppressedStorm: channels.some((c) => c.suppressedStorm),
      };
    });
}

/** A cell starting with one of these is a formula to a spreadsheet; a leading `'` defuses it. */
const FORMULA_START = /^\s*[=+\-@]|^[\t\r]/;

export function csvCell(value: string): string {
  const safe = FORMULA_START.test(value) ? `'${value}` : value;
  return /[",\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

export const CSV_HEADER = ["fired_at", "channel", "status", "reason", "message"] as const;

/** One CSV line per delivery row, newest first, every row of every firing. */
export function historyCsv(rows: readonly DeliveryRow[]): string {
  const sorted = [...rows].sort(
    (a, b) => Date.parse(b.fired_at ?? "") - Date.parse(a.fired_at ?? ""),
  );
  const lines = sorted.map((row) =>
    [row.fired_at ?? "", row.channel ?? "", row.status ?? "", row.error ?? "", row.message ?? ""]
      .map(csvCell)
      .join(","),
  );
  return [CSV_HEADER.join(","), ...lines].join("\r\n") + "\r\n";
}
