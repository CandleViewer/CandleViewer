// E24-S01 (#776) slice 1: the backfill read, `GET /api/v1/market/open-interest` (`22`
// `getOpenInterestHistory`), cursor-paged to a bound. Every item is checked against the generated
// `OpenInterestPoint`; a malformed item is counted and dropped, never coerced. Values stay decimal
// strings: the client formats, never computes (the ticket's "No client-side computation").
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import { isDecimal } from "./decimal";
import { isOiInterval, OI_INTERVAL_MS, type OiInterval } from "./intervals";

type Schemas = generated.rest.components["schemas"];
export type OpenInterestPoint = Schemas["OpenInterestPoint"];
export type OpenInterestCoverage = Schemas["OpenInterestPageMeta"]["coverage"];
export type OiSource = OpenInterestPoint["source"];

/** One stored point: `t` parsed, the decimals as sent. */
export interface HistoryPoint {
  readonly tMs: number;
  /** Base coin, both sides (`22`). */
  readonly base: string;
  readonly interval: OiInterval;
  readonly source: OiSource;
}

export interface Coverage {
  readonly fromMs: number | null;
  readonly toMs: number | null;
  readonly nativeInterval: OiInterval;
  readonly source: OiSource;
  readonly gaps: readonly { readonly fromMs: number; readonly toMs: number }[];
}

export type HistoryResult =
  | {
      readonly kind: "ok";
      readonly points: readonly HistoryPoint[];
      readonly coverage: Coverage;
      /**
       * What the page bound left out. The route reads ascending from `from` (E24-T01 handler, `22` items
       * ascending by `t`), so the read starts late enough to reach `to`: `older` = the window's start was
       * moved up past stored points (`coverage.from` before the new start); `newer` = the pages ran out, or a
       * page said `has_more` without a usable cursor, so the newest points were not read (defensive; a clamped
       * window holds at most the bound's point count); `null` = the whole window was read.
       * `coverage.gaps` unions every page's (`22`: per page) plus a gap per dropped malformed item.
       */
      readonly truncated: "older" | "newer" | null;
      readonly malformed: number;
    }
  | {
      readonly kind: "failed";
      /** `null`: no answer (network, deadline, abort, unreadable body); 200 with `code: "malformed"` is a body that is not the contract's. */
      readonly status: number | null;
      readonly code: string | null;
    };

export interface HistoryClock {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
}

/** PROPOSED: a server contract breach the read survives, reported once per read (never printed). */
export type HistoryAnomaly = "cursor_missing";

export interface HistoryRequest {
  readonly symbol: string;
  readonly interval: OiInterval;
  readonly fromMs: number;
  readonly toMs: number;
  readonly signal: AbortSignal;
  readonly clock?: HistoryClock | undefined;
  /** PROPOSED: at most 10 pages of 500 (5 000 points) per open. */
  readonly maxPages?: number | undefined;
  /** Called at most once per read, as the read ends, when the server broke its contract but the data read is valid. */
  readonly onAnomaly?: ((anomaly: HistoryAnomaly) => void) | undefined;
}

export const DEADLINE_MS = 10_000;
/** `22` `Limit`: 1–500 (default 100); the handler's `MAX_LIMIT` is 500. The 200 in the route's text is Bybit's own page. */
export const PAGE_LIMIT = 500;
export const MAX_PAGES = 10;
/** `22`: `to - from` is at most 400 days (400 `invalid_time_range`). */
export const MAX_RANGE_MS = 400 * 86_400_000;

const SYSTEM: HistoryClock = {
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this clock's `setTimeout` returned; the cast only restores that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

const timeOf = (v: unknown): number | null => {
  const ms = typeof v === "string" ? Date.parse(v) : NaN;
  return Number.isFinite(ms) ? ms : null;
};

const isSource = (v: unknown): v is OiSource => v === "rest" || v === "ws_ticker";

export function parsePoint(item: unknown): HistoryPoint | null {
  const tMs = timeOf(get(item, "t"));
  const base = get(item, "open_interest");
  const interval = get(item, "interval");
  const source = get(item, "source");
  if (tMs === null || !isDecimal(base) || !isOiInterval(interval) || !isSource(source)) return null;
  return { tMs, base, interval, source };
}

export function parseCoverage(meta: unknown): Coverage | null {
  const c = get(meta, "coverage");
  const native = get(c, "native_interval");
  const source = get(c, "source");
  const gaps = get(c, "gaps");
  if (!isOiInterval(native) || !isSource(source) || !Array.isArray(gaps)) return null;
  const from = get(c, "from");
  const to = get(c, "to");
  const spans: { fromMs: number; toMs: number }[] = [];
  for (const gap of gaps) {
    const fromMs = timeOf(get(gap, "from"));
    const toMs = timeOf(get(gap, "to"));
    if (fromMs === null || toMs === null) return null;
    spans.push({ fromMs, toMs });
  }
  return {
    fromMs: from === null ? null : timeOf(from),
    toMs: to === null ? null : timeOf(to),
    nativeInterval: native,
    source,
    gaps: spans,
  };
}

export function historyPath(req: Omit<HistoryRequest, "signal">, cursor: string | null): string {
  const q = new URLSearchParams({
    symbol: req.symbol,
    interval: req.interval,
    from: new Date(req.fromMs).toISOString(),
    to: new Date(req.toMs).toISOString(),
    limit: String(PAGE_LIMIT),
  });
  if (cursor !== null) q.set("cursor", cursor);
  return `/api/v1/market/open-interest?${q.toString()}`;
}

async function getPage(
  path: string,
  signal: AbortSignal,
  clock: HistoryClock,
): Promise<{ status: number; body: unknown } | null> {
  if (signal.aborted) return null;
  const call = new AbortController();
  const end = (): void => call.abort();
  const deadline = clock.setTimeout(end, DEADLINE_MS);
  signal.addEventListener("abort", end);
  try {
    const res = await apiFetch(path, { method: "GET", signal: call.signal });
    const body: unknown = await res.json().catch(() => null);
    return { status: res.status, body };
  } catch {
    return null;
  } finally {
    clock.clearTimeout(deadline);
    signal.removeEventListener("abort", end);
  }
}

/** Reads the window page by page; the points come back ascending and unique by time. */
export async function fetchOiHistory(req: HistoryRequest): Promise<HistoryResult> {
  const clock = req.clock ?? SYSTEM;
  const maxPages = req.maxPages ?? MAX_PAGES;
  // ascending reads: start no earlier than the bound's worth of points before `to`, so the newest are read
  // and no earlier than the server's 400-day range bound, which it refuses rather than clamps (4h and 1d reach it)
  const fromMs = Math.max(
    req.fromMs,
    req.toMs - maxPages * PAGE_LIMIT * OI_INTERVAL_MS[req.interval],
    req.toMs - MAX_RANGE_MS,
  );
  const clamped = { ...req, fromMs };
  const byTime = new Map<number, HistoryPoint>();
  let coverage: Coverage | null = null;
  const gaps: Span[] = [];
  let malformed = 0;
  let cursor: string | null = null;
  for (let page = 0; page < maxPages; page += 1) {
    const answer = await getPage(historyPath(clamped, cursor), req.signal, clock);
    if (answer === null) return { kind: "failed", status: null, code: null };
    if (answer.status !== 200) {
      const code = get(answer.body, "code");
      return {
        kind: "failed",
        status: answer.status,
        code: typeof code === "string" ? code : null,
      };
    }
    const items = get(answer.body, "items");
    const meta = get(answer.body, "meta");
    const pageCoverage = parseCoverage(meta);
    if (!Array.isArray(items) || pageCoverage === null) {
      return { kind: "failed", status: 200, code: "malformed" };
    }
    coverage ??= pageCoverage; // everything but `gaps` is page 0's
    gaps.push(...pageCoverage.gaps);
    for (const item of items) {
      const point = parsePoint(item);
      if (point !== null) byTime.set(point.tMs, point);
      else {
        malformed += 1;
        const hole = holeOf(item, req.interval);
        if (hole !== null) gaps.push(hole);
      }
    }
    const next = get(meta, "next_cursor");
    const more = get(meta, "has_more") === true;
    if (more && (typeof next !== "string" || next === "")) {
      // `has_more` without a cursor: the rest cannot be read: said ("newer") and counted, never a silent ok
      if (!req.signal.aborted) {
        try {
          req.onAnomaly?.("cursor_missing"); // a throwing callback never rejects the read
        } catch {
          // the report is best-effort
        }
      }
      return done(byTime, coverage, gaps, "newer", malformed);
    }
    if (!more || typeof next !== "string") {
      // A3: "older" only when the clamp cut stored data: the store starts before the clamped start
      // (`coverage.from`); with nothing stored there was nothing to cut
      const cut = fromMs > req.fromMs && coverage.fromMs !== null && coverage.fromMs < fromMs;
      return done(byTime, coverage, gaps, cut ? "older" : null, malformed);
    }
    cursor = next;
  }
  if (coverage === null) return { kind: "failed", status: null, code: null };
  return done(byTime, coverage, gaps, "newer", malformed);
}

interface Span {
  readonly fromMs: number;
  readonly toMs: number;
}

/** The span a dropped item held: its `t` for one interval, when `t` still reads. */
function holeOf(item: unknown, requested: OiInterval): Span | null {
  const tMs = timeOf(get(item, "t"));
  if (tMs === null) return null;
  const own = get(item, "interval");
  return { fromMs: tMs, toMs: tMs + OI_INTERVAL_MS[isOiInterval(own) ? own : requested] };
}

/** Overlapping or touching spans become one, ascending. */
function mergeSpans(spans: readonly Span[]): Span[] {
  const out: { fromMs: number; toMs: number }[] = [];
  for (const s of [...spans].sort((a, b) => a.fromMs - b.fromMs)) {
    const last = out[out.length - 1];
    if (last !== undefined && s.fromMs <= last.toMs) last.toMs = Math.max(last.toMs, s.toMs);
    else out.push({ ...s });
  }
  return out;
}

function done(
  byTime: ReadonlyMap<number, HistoryPoint>,
  first: Coverage,
  gaps: readonly Span[],
  truncated: "older" | "newer" | null,
  malformed: number,
): HistoryResult {
  const coverage = { ...first, gaps: mergeSpans(gaps) };
  return { kind: "ok", points: ascending(byTime), coverage, truncated, malformed };
}

const ascending = (byTime: ReadonlyMap<number, HistoryPoint>): HistoryPoint[] =>
  [...byTime.values()].sort((a, b) => a.tMs - b.tMs);
