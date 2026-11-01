/**
 * SCR-140's grid, the pure part (E16-S01; E16-D02 §1, §4, §5, §9.1; BQ-10): the FilterBar's fields
 * and their match, the symbol search, the sort by Symbol, Since or Size and the order the grid
 * keeps while the page is open, and a model row in CMP-177's props. No React.
 */
import type { FilterBarField, FilterBarFilter, RecorderStatusRowData } from "@candleviewer/ui";
import type { generated } from "@candleviewer/protocol";
import { fill } from "./copy";
import { formatDuration, formatHourMinute, type DiskLevel, type RecorderRow } from "./model";
import type { RecorderPolicy } from "./model/types";
import { FILTER_TEXT, PAGE_TEXT } from "./pageCopy";

export type StreamKind = generated.rest.components["schemas"]["StreamKind"];

/** D02 §6.1: the streams offered, in its order; the first four are the add's defaults (`22`). */
export const STREAMS: readonly StreamKind[] = [
  "trades",
  "orderbook_delta",
  "tickers",
  "liquidations",
  "klines",
];
export const DEFAULT_STREAMS: readonly StreamKind[] = STREAMS.slice(0, 4);
export const DEPTHS = [1, 50, 200, 500] as const;
export type Depth = (typeof DEPTHS)[number];
export const DEFAULT_DEPTH: Depth = 200;
/** `22` AddRecordedSymbolRequest's default; D02 §6.1's stepper runs 1–3650 days. */
export const DEFAULT_RETENTION_DAYS = 30;
export const RETENTION_MIN_DAYS = 1;
export const RETENTION_MAX_DAYS = 3650;

type FieldId = keyof typeof FILTER_TEXT;
const field = (id: FieldId): FilterBarField => ({
  id,
  label: FILTER_TEXT[id].label,
  options: Object.entries(FILTER_TEXT[id].values).map(([value, label]) => ({ value, label })),
});
/** "Add filter"'s menu, in order (BQ-10, and D02 §8.3's Depth for "Reduce depth"). */
export const FILTER_FIELDS: readonly FilterBarField[] = (
  ["reason", "state", "pinned", "attention", "depth"] as const
).map(field);
/** D02 §5.2: the summary's "{m} auto-recorded" applies this chip. */
export const AUTO_FILTER: FilterBarFilter = { field: "reason", value: "auto" };
export const PINNED_FILTER: FilterBarFilter = { field: "pinned", value: "yes" };
/** D02 §8.3's "Reduce depth": the rows at depth 500 or 200. */
export const DEEP_FILTERS: readonly FilterBarFilter[] = [
  { field: "depth", value: "500" },
  { field: "depth", value: "200" },
];

/** BQ-10: degraded, gated, silent, error or refused. */
const ATTENTION: ReadonlySet<string> = new Set(["degraded", "gated", "silent", "error", "refused"]);

/** A row's value for a field, as the FilterBar's option values spell it. */
function valueOf(row: RecorderRow, id: string): string {
  switch (id) {
    case "reason":
      return row.reason === "manual" ? "manual" : "auto";
    case "state":
      return row.state === "lingering" ? "recording" : row.state;
    case "pinned":
      return row.pinned ? "yes" : "no";
    case "attention":
      return ATTENTION.has(row.state) ? "yes" : "no";
    case "depth":
      return row.depth === null ? "" : String(row.depth);
    default:
      return "";
  }
}

/**
 * The filters and the search: values of one field match any of them, fields all of theirs; the
 * search matches the symbol, ignoring case and outer spaces.
 */
export function rowMatches(
  row: RecorderRow,
  filters: readonly FilterBarFilter[],
  query: string,
): boolean {
  const needle = query.trim().toUpperCase();
  if (needle !== "" && !row.symbol.toUpperCase().includes(needle)) return false;
  const byField = new Map<string, Set<string>>();
  for (const { field: id, value } of filters) {
    byField.set(id, (byField.get(id) ?? new Set<string>()).add(value));
  }
  return [...byField].every(([id, values]) => values.has(valueOf(row, id)));
}

export type SortColumn = "symbol" | "since" | "size";
export interface GridSort {
  readonly columnId: string;
  readonly direction: "ascending" | "descending";
}

/** Symbol by name; Since and Size by value, a row with none last whichever the direction. */
export function compareRows(sort: GridSort): (a: RecorderRow, b: RecorderRow) => number {
  const sign = sort.direction === "ascending" ? 1 : -1;
  const key = (row: RecorderRow): number => {
    const value = sort.columnId === "since" ? Date.parse(row.startedAt ?? "") : row.diskBytes;
    return value ?? Number.NaN;
  };
  return (a, b) => {
    if (sort.columnId === "symbol") return sign * a.symbol.localeCompare(b.symbol);
    const [x, y] = [key(a), key(b)];
    const [noX, noY] = [Number.isNaN(x), Number.isNaN(y)];
    if (noX || noY) return noX === noY ? a.symbol.localeCompare(b.symbol) : noX ? 1 : -1;
    return sign * (x - y) || a.symbol.localeCompare(b.symbol);
  };
}

/** The order the grid shows and the sort it was made by. */
export interface GridOrder {
  readonly symbols: readonly string[];
  readonly sort: GridSort | undefined;
}

/**
 * D02 §9.1: nothing re-sorts while the page is open. A sort the user asks for orders the rows now;
 * after that a row keeps its place, a new row joins the end and a row that left leaves its place.
 * Without a sort, the server's order (BQ-10) on the first rows.
 */
export function nextOrder(
  previous: GridOrder | null,
  rows: readonly RecorderRow[],
  sort: GridSort | undefined,
): GridOrder {
  const same =
    previous !== null &&
    previous.sort?.columnId === sort?.columnId &&
    previous.sort?.direction === sort?.direction;
  if (!same) {
    const ordered = sort === undefined ? rows : [...rows].sort(compareRows(sort));
    return { symbols: ordered.map((row) => row.symbol), sort };
  }
  const present = new Set(rows.map((row) => row.symbol));
  const kept = previous.symbols.filter((symbol) => present.has(symbol));
  const known = new Set(kept);
  const joined = rows.filter((row) => !known.has(row.symbol)).map((row) => row.symbol);
  const symbols = [...kept, ...joined];
  const unchanged =
    symbols.length === previous.symbols.length &&
    symbols.every((symbol, i) => symbol === previous.symbols[i]);
  return unchanged ? previous : { symbols, sort };
}

/** What a row's cells read besides the row itself (D02 §2: the storage, sessions and coverage reads). */
export interface RowContext {
  readonly nowMs: number;
  readonly stale: boolean;
  readonly policy: RecorderPolicy | null;
  readonly diskLevel: DiskLevel;
  readonly capBytes: number | null;
  /** `StorageUsage.symbols[].daily_growth_bytes` by symbol. */
  readonly growth: ReadonlyMap<string, number>;
  /** Symbols whose rate is the add-time estimate ("est.", D02 §1) until an hour of data exists. */
  readonly estimated: ReadonlySet<string>;
  /** A stopped row's last session `ended_at` (ms), from `listRecordingSessions`. */
  readonly stoppedAtMs: ReadonlyMap<string, number>;
  /** Gaps in the last 24 h by symbol, from `getDataCoverage`. */
  readonly gaps: ReadonlyMap<string, number>;
}

/** The ISO text of `ms`, or null: none given, or past `Date`'s range, where `toISOString` throws (C-5309-13). */
const iso = (ms: number | null): string | null => {
  const date = ms === null ? null : new Date(ms);
  return date === null || Number.isNaN(date.getTime()) ? null : date.toISOString();
};

/** D02 §5.1's Why? words for an auto row, from its reason, its start and the policy. */
export function whyWords(row: RecorderRow, policy: RecorderPolicy | null): string {
  const w = PAGE_TEXT.why;
  const grace = policy === null ? "" : formatDuration(policy.autostop_grace_s);
  const startMs = row.startedAt === null ? Number.NaN : Date.parse(row.startedAt);
  const at = (ms: number): string => (Number.isNaN(ms) ? "—" : formatHourMinute(ms));
  const values = { "{symbol}": row.symbol, "{grace}": grace, "{start}": at(startMs) };
  if (row.reason === "position_open") return fill(w.position, values);
  if (row.reason === "rule_dependency") return fill(w.rule, values);
  if (row.reason === "alert_dependency") return fill(w.alert, values);
  const dwell = policy?.autostart_delay_s ?? 0;
  const chart = fill(w.chart, {
    ...values,
    "{open}": at(startMs - dwell * 1000),
    "{dwell}": formatDuration(dwell),
  });
  const kept = row.pinned
    ? w.keptForever
    : row.retentionDays === null
      ? null
      : fill(w.kept, { "{days}": row.retentionDays });
  return kept === null ? chart : `${chart} ${kept}`;
}

/**
 * A model row as CMP-177's props (D02 §4.2): the row derives nothing (the model did, BQ-8). `null`
 * for a row whose reason is not known yet (a refused start read from the status before a frame).
 */
export function rowData(row: RecorderRow, ctx: RowContext): RecorderStatusRowData | null {
  if (row.reason === null) return null;
  const growth = ctx.growth.get(row.symbol) ?? null;
  const cap = ctx.capBytes;
  return {
    symbol: row.symbol,
    reason: row.reason,
    state: row.state,
    lingerUntil: iso(row.lingerUntilMs),
    refusal: row.refusal,
    stopBlockedReason: row.stopBlockedReason,
    recordAgainBlockedReason: row.recordAgainBlockedReason,
    startedAt: row.startedAt,
    stoppedAt: iso(ctx.stoppedAtMs.get(row.symbol) ?? null),
    depth: row.depth,
    dailyGrowthBytes: growth,
    growthEstimated: ctx.estimated.has(row.symbol),
    diskUsageBytes: row.diskBytes,
    budgetShare: cap === null || cap <= 0 || row.diskBytes === null ? null : row.diskBytes / cap,
    diskLevel: ctx.diskLevel,
    retentionDays: row.retentionDays,
    pinned: row.pinned,
    stale: ctx.stale,
    lastEventAt: iso(row.lastEventAtMs),
    gapCount: ctx.gaps.get(row.symbol) ?? 0,
    ...(ctx.policy === null
      ? {}
      : { symbolLimit: ctx.policy.max_symbols, graceSeconds: ctx.policy.autostop_grace_s }),
    ...(row.reason === "manual" ? {} : { why: whyWords(row, ctx.policy) }),
    now: ctx.nowMs,
  };
}
