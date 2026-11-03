// E24-S05 (#780) slice 2: the backfill read, `GET /api/v1/market/liquidations` (`22` `getLiquidations`), and the
// coverage it reports. BQ 3 (ruled 6612481277, #780): one read per mount and per symbol change; coverage comes from its
// `meta.coverage`, never from the oldest row received (the ticket's technical notes). The read follows the
// cursor to a page bound (the window is ascending, so the newest prints are on the last page) and keeps the
// newest `keep`. Every item is checked against the generated `Liquidation`; a malformed one is counted.
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import { CLUSTER_WINDOW_MS, parseRestItem, type LiquidationPrint } from "./prints";

type Coverage = generated.rest.components["schemas"]["LiquidationsPageMeta"]["coverage"];

/** `meta.coverage`, times parsed. */
export interface LiqCoverage {
  /** The first stored print for the symbol; `null` when none is stored. */
  readonly firstAvailableMs: number | null;
  /** The part of the requested window the store answers for. */
  readonly coveredFromMs: number | null;
  readonly coveredToMs: number | null;
  /** The window ends before `first_available_ts`, or nothing is stored: empty means "not recorded". */
  readonly noCoverage: boolean;
}

export type LiqHistoryResult =
  | {
      readonly kind: "ok";
      /** Ascending, at most `keep`. */
      readonly prints: readonly LiquidationPrint[];
      readonly coverage: LiqCoverage;
      /** The page bound stopped the read with `has_more` still true. */
      readonly truncated: boolean;
      readonly malformed: number;
    }
  | {
      readonly kind: "failed";
      /** `null`: no answer (network, deadline, unreadable body). */
      readonly status: number | null;
      readonly code: string | null;
    };

export interface LiqHistoryClock {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
}

export interface LiqHistoryRequest {
  readonly symbol: string;
  readonly fromMs: number;
  readonly toMs: number;
  readonly minNotionalUsd: string | null;
  readonly signal: AbortSignal;
  /** The prints kept: the ring's capacity. */
  readonly keep: number;
  readonly clock?: LiqHistoryClock | undefined;
  readonly maxPages?: number | undefined;
}

export const DEADLINE_MS = 10_000;
/** `22`: `limit` 1–500. */
export const PAGE_LIMIT = 500;
/** PROPOSED (as E24-S01's OI read): at most 10 pages of 500 per read. */
export const MAX_PAGES = 10;

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

/** Reads the window page by page and keeps the newest `keep` prints, ascending. */
export async function fetchLiquidationHistory(req: LiqHistoryRequest): Promise<LiqHistoryResult> {
  const clock = req.clock ?? SYSTEM;
  const maxPages = req.maxPages ?? MAX_PAGES;
  let kept: LiquidationPrint[] = [];
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
      else kept.push(print);
    }
    if (kept.length > req.keep) kept = kept.slice(-req.keep);
    const next = get(meta, "next_cursor");
    if (get(meta, "has_more") !== true || typeof next !== "string" || next === "") {
      return { kind: "ok", prints: ascending(kept), coverage, truncated: false, malformed };
    }
    cursor = next;
  }
  if (coverage === null) return { kind: "failed", status: null, code: null };
  return { kind: "ok", prints: ascending(kept), coverage, truncated: true, malformed };
}

const ascending = (prints: LiquidationPrint[]): LiquidationPrint[] =>
  [...prints].sort((a, b) => a.tsMs - b.tsMs);
