// E24-S05 (#780) slice 2: the backfill read, `GET /api/v1/market/liquidations` (`22` `getLiquidations`), and the
// coverage it reports. BQ 3 (ruled 6612481277, #780): one read per mount and per symbol change; coverage comes from
// its `meta.coverage`, never from the oldest row received (the ticket's technical notes).
// Order: `22` states none; the E24-T03 handler serves `items` "ascending by `ts`" and pages in its dedup-key order,
// a total order led by `ts` (#5273 at 9bf4ec8c2, `api/liquidations.py`, `orderflow/liquidations.py` "Paging"). This
// read relies on it: the newest prints are on the last page. So a read that hits its page bound is narrowed back
// from `to` and read again, so the window's newest end is what is kept, next to live; whichever end was not loaded
// is returned as `truncated` with its time, and the pane says it. Every item is checked against the generated
// `Liquidation`; a malformed one is counted.
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import type {
  LiqCoverage,
  LiqHistoryClock,
  LiqHistoryRequest,
  LiqHistoryResult,
  LiqTruncation,
} from "./history";
import { CLUSTER_WINDOW_MS, parseRestItem, type LiquidationPrint } from "./prints";

type Coverage = generated.rest.components["schemas"]["LiquidationsPageMeta"]["coverage"];

export const DEADLINE_MS = 10_000;
/** `22`: `limit` 1–500. */
export const PAGE_LIMIT = 500;
/** PROPOSED: two pages of 500 per attempt, the ring's 1,000 prints. */
export const MAX_PAGES = 2;
/** PROPOSED: a window narrowed to a quarter per attempt; the sixth attempt reads 31 days / 4^5 ≈ 44 minutes. */
export const MAX_ATTEMPTS = 6;

const SYSTEM: LiqHistoryClock = {
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this clock's `setTimeout` returned; the cast only restores that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

/** A `date-time` or `null`; `undefined` for anything else. */
const timeOrNull = (v: unknown): number | null | undefined => {
  if (v === null) return null;
  const ms = typeof v === "string" ? Date.parse(v) : NaN;
  return Number.isFinite(ms) ? ms : undefined;
};

export function parseCoverage(meta: unknown): LiqCoverage | null {
  const c = get(meta, "coverage");
  const first = timeOrNull(get(c, "first_available_ts" satisfies keyof Coverage));
  const from = timeOrNull(get(c, "covered_from" satisfies keyof Coverage));
  const to = timeOrNull(get(c, "covered_to" satisfies keyof Coverage));
  const none = get(c, "no_coverage" satisfies keyof Coverage);
  if (first === undefined || from === undefined || to === undefined || typeof none !== "boolean") {
    return null;
  }
  return { firstAvailableMs: first, coveredFromMs: from, coveredToMs: to, noCoverage: none };
}

export function historyPath(
  req: Omit<LiqHistoryRequest, "signal" | "keep">,
  cursor: string | null,
): string {
  const q = new URLSearchParams({
    symbol: req.symbol,
    from: new Date(req.fromMs).toISOString(),
    to: new Date(req.toMs).toISOString(),
    limit: String(PAGE_LIMIT),
    cluster_window_ms: String(CLUSTER_WINDOW_MS),
  });
  if (req.minNotionalUsd !== null) q.set("min_notional_usd", req.minNotionalUsd);
  if (cursor !== null) q.set("cursor", cursor);
  return `/api/v1/market/liquidations?${q.toString()}`;
}

async function getPage(
  path: string,
  signal: AbortSignal,
  clock: LiqHistoryClock,
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

type WindowRead =
  | {
      readonly kind: "ok";
      readonly prints: LiquidationPrint[];
      readonly coverage: LiqCoverage;
      readonly hasMore: boolean;
      readonly malformed: number;
    }
  | Extract<LiqHistoryResult, { kind: "failed" }>;

/** One window, page by page up to `maxPages`; `hasMore` when the bound stopped it. */
async function readWindow(
  req: LiqHistoryRequest,
  clock: LiqHistoryClock,
  maxPages: number,
): Promise<WindowRead> {
  const prints: LiquidationPrint[] = [];
  let coverage: LiqCoverage | null = null;
  let malformed = 0;
  let cursor: string | null = null;
  for (let page = 0; page < maxPages; page += 1) {
    const answer = await getPage(historyPath(req, cursor), req.signal, clock);
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
    coverage ??= pageCoverage;
    for (const item of items) {
      const print = parseRestItem(item, req.symbol);
      if (print === null) malformed += 1;
      else prints.push(print);
    }
    const next = get(meta, "next_cursor");
    if (get(meta, "has_more") !== true || typeof next !== "string" || next === "") {
      return { kind: "ok", prints, coverage, hasMore: false, malformed };
    }
    cursor = next;
  }
  if (coverage === null) return { kind: "failed", status: null, code: null };
  return { kind: "ok", prints, coverage, hasMore: true, malformed };
}

/**
 * Reads the window and keeps its newest `keep` prints, ascending. A read stopped by its page bound is narrowed
 * from `to` (a quarter of the span left each time) and read again; the coverage is the full window's.
 */
export async function fetchLiquidationHistory(req: LiqHistoryRequest): Promise<LiqHistoryResult> {
  const clock = req.clock ?? SYSTEM;
  const maxPages = req.maxPages ?? MAX_PAGES;
  const maxAttempts = req.maxAttempts ?? MAX_ATTEMPTS;
  let coverage: LiqCoverage | null = null;
  let malformed = 0;
  let fromMs = req.fromMs;
  for (let attempt = 1; ; attempt += 1) {
    const read = await readWindow({ ...req, fromMs }, clock, maxPages);
    if (read.kind === "failed") return read;
    coverage ??= read.coverage;
    malformed += read.malformed;
    if (!read.hasMore || attempt >= maxAttempts) {
      const all = ascending(read.prints);
      const prints = all.slice(-req.keep);
      const first = coverage.firstAvailableMs;
      const cut = fromMs > req.fromMs && first !== null && first < fromMs;
      // `keep` dropped read prints: the loaded window starts at the oldest kept one (#5764 U2)
      const kept = prints[0];
      const truncated: LiqTruncation | null = read.hasMore
        ? { side: "newer", atMs: prints.at(-1)?.tsMs ?? fromMs }
        : all.length > prints.length && kept !== undefined
          ? { side: "older", atMs: kept.tsMs }
          : cut
            ? { side: "older", atMs: fromMs }
            : null;
      return { kind: "ok", prints, coverage, truncated, malformed };
    }
    fromMs = req.toMs - Math.floor((req.toMs - fromMs) / 4);
  }
}

const ascending = (prints: LiquidationPrint[]): LiquidationPrint[] =>
  [...prints].sort((a, b) => a.tsMs - b.tsMs);
