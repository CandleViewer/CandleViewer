/**
 * SCR-141's steady-state estimate and its preview fallback (E16-S03; E16-D03 §5, §9; D03-D7; BQ-3).
 * Both read the sampled `StorageUsage` report, which is per symbol across all its streams (never per
 * stream or per date, D03-G5), so every figure is an estimate and the dialog says so. Pure: integer
 * bytes, UTC dates from the report's own `generated_at`, no clock, no fetch and no strings.
 */
import { GB } from "../model/format";
import {
  DAYS_MAX,
  effectiveRows,
  SEED,
  STREAMS,
  type Draft,
  type ExemptRow,
  type Reduction,
  type StorageUsage,
  type StreamKind,
  type SymbolCode,
} from "./retentionModel";

const DAY_MS = 86_400_000;

/** Bytes as GB (`GB`, 10^9), one decimal (D03 §14 `{size}`): 189 800 000 000 is 189.8. */
export const gigabytes = (bytes: number): number => Math.round(bytes / (GB / 10)) / 10;

/** The steady-state sentence's figures (D03 §9 `SCR-141/estimate`; D03-D7). */
export interface SteadyState {
  /** Non-pinned growth times the window: an upper bound on the fast store, in bytes. */
  readonly bytes: number;
  readonly growthPerDay: number;
  /** The longest window: the largest `retain_days` among the effective rows (`steadyState`). */
  readonly windowDays: number;
  readonly capBytes: number | null;
  /** `bytes` as a whole percent of `cap_bytes`; null without a cap. */
  readonly pct: number | null;
  /** Stated apart: pinned symbols are never deleted by retention. */
  readonly pinnedGrowthPerDay: number;
}

/**
 * Non-pinned `daily_growth_bytes` times the longest window (the largest `retain_days` among the
 * effective rows: the eight global rows, a missing one on its seed as `toRequest` sends it, and the
 * overrides of non-pinned symbols), with the pinned growth stated apart. Every row's days are its
 * fast-store window (`read_policy_row`; a `drop` row's is its total).
 */
export function steadyState(storage: StorageUsage, draft: Draft): SteadyState {
  const pinned = new Set<SymbolCode | undefined>();
  let growthPerDay = 0;
  let pinnedGrowthPerDay = 0;
  for (const s of storage.symbols ?? []) {
    const growth = s.daily_growth_bytes ?? 0;
    if (s.pinned === true) {
      pinned.add(s.symbol);
      pinnedGrowthPerDay += growth;
    } else growthPerDay += growth;
  }
  const rows = effectiveRows(draft);
  const globals = STREAMS.map(
    (stream) =>
      rows.find((row) => row.symbol === null && row.stream === stream)?.days ??
      SEED[stream].hotDays,
  );
  const overrides = rows
    .filter((row) => row.symbol !== null && !pinned.has(row.symbol))
    .map((row) => row.days);
  const windowDays = Math.max(...globals, ...overrides);
  const bytes = growthPerDay * windowDays;
  const cap = storage.cap_bytes ?? 0;
  return {
    bytes,
    growthPerDay,
    windowDays,
    capBytes: cap > 0 ? cap : null,
    pct: cap > 0 ? Math.round((bytes * 100) / cap) : null,
    pinnedGrowthPerDay,
  };
}

/** One symbol in the preview: about this much of its recorded streams goes at the first run. */
export interface PreviewRow {
  readonly symbol: SymbolCode;
  readonly streams: readonly StreamKind[];
  /** The cut-off date (UTC YYYY-MM-DD): data older than it becomes eligible; null with no report time. */
  readonly to: string | null;
  /** "Recording started about {since}": `generated_at` minus `used_bytes / daily_growth_bytes` days. */
  readonly since: string | null;
  /** Growth times the days between the start and the cut-off; 0 when nothing predates the cut-off. */
  readonly bytes: number;
  /** "Nothing recorded before {to} exists yet": nothing predates the cut-off. */
  readonly nothingBefore: boolean;
}

/** "What becomes eligible for deletion" (D03 §5 `SCR-141/preview`). */
export interface Preview {
  /** `estimate` from the storage report; `server` once D03-G1's preview route answers. */
  readonly source: "estimate" | "server";
  readonly rows: readonly PreviewRow[];
  readonly exempt: readonly ExemptRow[];
  readonly totalBytes: number;
  readonly symbolCount: number;
}

/** The preview's one seam: this fallback until D03-G1's route exists, then a call that sends the draft. */
export type PreviewSource = (
  storage: StorageUsage,
  draft: Draft,
  reduction: Reduction,
) => Preview | Promise<Preview>;

/** A UTC date (YYYY-MM-DD); null for an instant `Date` cannot hold, so it never throws. */
function isoDate(ms: number): string | null {
  const date = new Date(ms);
  return Number.isNaN(date.getTime()) ? null : date.toISOString().slice(0, 10);
}

function previewRow(
  symbol: SymbolCode,
  streams: readonly StreamKind[],
  days: number,
  usage: { readonly used_bytes?: number; readonly daily_growth_bytes?: number } | undefined,
  asOf: number,
): PreviewRow {
  const used = usage?.used_bytes ?? 0;
  const growth = usage?.daily_growth_bytes ?? 0;
  const known = Number.isFinite(asOf);
  const to = known ? isoDate(asOf - days * DAY_MS) : null;
  // A start more than `DAYS_MAX` days back (a tiny or a stopped growth) is not placed either.
  const held = growth > 0 ? used / growth : Number.POSITIVE_INFINITY;
  const since = known && held <= DAYS_MAX ? isoDate(asOf - Math.round(held * DAY_MS)) : null;
  if (since === null) {
    // The start cannot be placed: all of it may predate the cut-off, an upper bound.
    return { symbol, streams, to, since, bytes: used, nothingBefore: used === 0 };
  }
  const bytes = Math.max(0, used - growth * days);
  return { symbol, streams, to, since, bytes, nothingBefore: bytes === 0 };
}

/**
 * The client-side preview (D03 §5, BQ-3), per non-pinned symbol a reduction reaches: its cut-off is
 * `generated_at` minus the shortest new total among its shrinking streams, its recording start is
 * `generated_at - used_bytes / daily_growth_bytes` (none when that is over `DAYS_MAX` days or is no
 * date), and its size the growth over the days between them; the pinned symbols are the exempt
 * rows. A line over symbols no report lists (`scope` null) adds no row. The draft is the server
 * source's input; this fallback reads only the report and the reduction.
 */
export function fallbackPreview(
  storage: StorageUsage,
  draft: Draft,
  reduction: Reduction,
): Preview {
  const asOf = Date.parse(storage.generated_at ?? "");
  const usage = new Map((storage.symbols ?? []).map((s) => [s.symbol, s]));
  const { lines } = reduction.confirm;
  const symbols = [...new Set(lines.flatMap((line) => line.scope ?? []))].sort();
  const rows = symbols.map((symbol) => {
    const own = lines.filter((line) => line.scope?.includes(symbol) === true);
    const streams = STREAMS.filter((stream) => own.some((line) => line.stream === stream));
    const days = Math.min(...own.map((line) => line.total.days));
    return previewRow(symbol, streams, days, usage.get(symbol), asOf);
  });
  return {
    source: "estimate",
    rows,
    exempt: reduction.exempt,
    totalBytes: rows.reduce((sum, row) => sum + row.bytes, 0),
    symbolCount: rows.length,
  };
}

/** The preview's one seam (BQ-3): the fallback until D03-G1's preview route is served. */
export const previewSource: PreviewSource = fallbackPreview;
