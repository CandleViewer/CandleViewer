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
  /** `fired_at` plus the lowest delivery id of the firing: unique even for equal timestamps. */
  readonly key: string;
  readonly firedAt: string;
  readonly message: string;
  readonly channels: readonly HistoryChannel[];
  readonly suppressedStorm: boolean;
}

/** A timestamp that does not parse sorts last, never as NaN. */
export function timeOf(iso: string | undefined): number {
  const ms = Date.parse(iso ?? "");
  return Number.isFinite(ms) ? ms : Number.NEGATIVE_INFINITY;
}

const newestFirst = (a: string | undefined, b: string | undefined): number => {
  const x = timeOf(a);
  const y = timeOf(b);
  return x === y ? 0 : x < y ? 1 : -1;
};

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

/**
 * A firing is the channel rows sharing one `fired_at`; a second row for a channel the firing already
 * holds starts another firing, so two firings with equal timestamps stay two.
 */
export function groupFirings(rows: readonly DeliveryRow[]): readonly Firing[] {
  const groups: { firedAt: string; rows: DeliveryRow[] }[] = [];
  for (const row of [...rows].sort((a, b) => (a.id ?? 0) - (b.id ?? 0))) {
    const firedAt = row.fired_at ?? "";
    const open = groups.find(
      (g) => g.firedAt === firedAt && !g.rows.some((r) => r.channel === row.channel),
    );
    if (open === undefined) groups.push({ firedAt, rows: [row] });
    else open.rows.push(row);
  }
  return groups
    .sort((a, b) => newestFirst(a.firedAt, b.firedAt))
    .map(({ firedAt, rows: group }) => {
      const channels = group.map((row) => ({
        channel: CHANNEL_WORD[row.channel ?? ""] ?? String(row.channel),
        word: statusWord(row),
        suppressedStorm: row.status === "suppressed" && row.error === "storm",
      }));
      return {
        key: `${firedAt}#${Math.min(...group.map((r) => r.id ?? 0))}`,
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

/** UTF-8 byte order mark: spreadsheets read the file as UTF-8, not the local code page. */
const BOM = "\uFEFF";

export const CSV_HEADER = ["fired_at", "channel", "status", "reason", "message"] as const;

/** One CSV line per delivery row, newest first, every row of every firing. */
export function historyCsv(rows: readonly DeliveryRow[]): string {
  const sorted = [...rows].sort((a, b) => newestFirst(a.fired_at, b.fired_at));
  const lines = sorted.map((row) =>
    [row.fired_at ?? "", row.channel ?? "", row.status ?? "", row.error ?? "", row.message ?? ""]
      .map(csvCell)
      .join(","),
  );
  return BOM + [CSV_HEADER.join(","), ...lines].join("\r\n") + "\r\n";
}
