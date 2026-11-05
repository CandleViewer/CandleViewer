// E24-S03 (#778) slice 1: the settled funding read, `22` `getFundingHistory` (§19.110), cursor-paged to a bound.
// A malformed item is dropped, never coerced; rates stay decimal strings. The interval is the served
// `funding_interval_minutes` (BQ 8); an absent member is unknown, never 8 h and never "covered".
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";
import { isAccruing, type PredictedRate } from "./predicted";

type FundingOk =
  generated.rest.operations["getFundingHistory"]["responses"][200]["content"]["application/json"];
type FundingItem = NonNullable<FundingOk["items"]>[number];
type FundingMeta = NonNullable<FundingOk["meta"]>;
type ApiCoverage = NonNullable<FundingMeta["coverage"]>;
type ApiGap = ApiCoverage["gaps"][number];
type Problem = generated.rest.components["schemas"]["Problem"];

/** One settled rate: the settlement time and the rate per interval as sent (`0.0001` is 0.01 %). */
export interface SettledPoint {
  readonly tMs: number;
  readonly rate: string;
  /** The server's annualised % (§19.110) when served; never computed here. */
  readonly annualisedPct?: string;
}

/** `meta.coverage`'s members the pane reads (BQ 6); the edges stay the server's. */
export interface FundingCoverage {
  /** True: the store was not backfilled over the window, so an empty page is "not recorded". */
  readonly noCoverage: boolean;
  readonly gaps: readonly { readonly fromMs: number; readonly toMs: number }[];
}

export interface FundingHistoryOk {
  readonly kind: "ok";
  readonly settled: readonly SettledPoint[];
  /** E24-S04: the item flagged predicted (BQ-2), `null` when this read has none; never carried over. */
  readonly predicted: PredictedRate | null;
  /** `null`: not served; the pane states no interval and draws no step. */
  readonly intervalMinutes: number | null;
  /** `null`: not served (contract first); read as unknown, never as covered. */
  readonly coverage: FundingCoverage | null;
  /** PROPOSED: the page bound ran out before `to`. */
  readonly truncated: boolean;
}

/** `failed.status` is `null` with no answer (network, deadline, unreadable body). */
export type FundingHistoryResult =
  | FundingHistoryOk
  | { readonly kind: "unavailable" }
  | { readonly kind: "failed"; readonly status: number | null; readonly code: string | null };

export interface FundingClock {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
}

export interface FundingHistoryRequest {
  readonly symbol: string;
  readonly fromMs: number;
  readonly toMs: number;
  readonly signal: AbortSignal;
  readonly clock?: FundingClock | undefined;
  readonly maxPages?: number | undefined;
}

export const DEADLINE_MS = 10_000;
export const PAGE_LIMIT = 500; // `22` `Limit` 1–500
/**
 * PROPOSED: at most 10 pages of 500 settlements per read. The handler refuses a window over 400 days (the
 * mounting slice clamps `fromMs..toMs`): that is 1 200 settlements at 8 h, so only a 1 h symbol read over
 * more than 208 days runs out, and the pane says "Recent history not loaded.".
 */
export const MAX_PAGES = 10;

const SYSTEM: FundingClock = {
  setTimeout: (run, ms) => setTimeout(run, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>), // our own id back
};

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

/** `22` `Decimal`: `^-?[0-9]+(\.[0-9]+)?$`, arbitrary precision. */
export const isDecimal = (v: unknown): v is string =>
  typeof v === "string" && /^-?[0-9]+(\.[0-9]+)?$/.test(v);

/** RFC 3339 `date-time` only (`22` `format: date-time`); `Date.parse` alone takes looser text. */
const RFC3339 = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;

export const timeOf = (v: unknown): number | null => {
  const ms = typeof v === "string" && RFC3339.test(v) ? Date.parse(v) : NaN;
  return Number.isFinite(ms) ? ms : null;
};

/** The server's annualised % as sent (`annualised_pct`, §19.110); `null` when absent or malformed. */
const annualisedOf = (item: unknown): string | null => {
  const v = get(item, "annualised_pct" satisfies keyof FundingItem);
  return isDecimal(v) ? v : null;
};

/**
 * A served settled point, the predicted rate (never a step of the settled line, D03 §5.3) or `null` when
 * malformed. Fail closed: only `predicted: false` without `estimated: true` is settled (BQ-2).
 */
export function parseItem(
  item: unknown,
): { readonly settled: SettledPoint } | { readonly predicted: PredictedRate } | null {
  const rate = get(item, "funding_rate" satisfies keyof FundingItem);
  if (!isDecimal(rate)) return null;
  const tMs = timeOf(get(item, "t" satisfies keyof FundingItem));
  const annualisedPct = annualisedOf(item);
  const flags = {
    predicted: get(item, "predicted" satisfies keyof FundingItem),
    estimated: get(item, "estimated" satisfies keyof FundingItem),
  };
  if (isAccruing(flags)) return { predicted: { tMs, rate, annualisedPct } };
  return tMs === null
    ? null
    : { settled: { tMs, rate, ...(annualisedPct === null ? {} : { annualisedPct }) } };
}

export function parseInterval(body: unknown): number | null {
  const v = get(body, "funding_interval_minutes" satisfies keyof FundingOk);
  return typeof v === "number" && Number.isSafeInteger(v) && v >= 1 ? v : null;
}

/** `meta.coverage`; absent → `null` (unknown), malformed → `null` too, never a guessed "covered". */
export function parseCoverage(meta: unknown): FundingCoverage | null {
  const c = get(meta, "coverage" satisfies keyof FundingMeta);
  const noCoverage = get(c, "no_coverage" satisfies keyof ApiCoverage);
  const gaps = get(c, "gaps" satisfies keyof ApiCoverage);
  if (typeof noCoverage !== "boolean" || !Array.isArray(gaps)) return null;
  const spans: { fromMs: number; toMs: number }[] = [];
  for (const gap of gaps) {
    const fromMs = timeOf(get(gap, "from" satisfies keyof ApiGap));
    const toMs = timeOf(get(gap, "to" satisfies keyof ApiGap));
    if (fromMs === null || toMs === null) return null;
    spans.push({ fromMs, toMs });
  }
  return { noCoverage, gaps: spans };
}

export function fundingPath(
  req: Pick<FundingHistoryRequest, "symbol" | "fromMs" | "toMs">,
  cursor: string | null,
): string {
  const q = new URLSearchParams({
    symbol: req.symbol,
    from: new Date(req.fromMs).toISOString(),
    to: new Date(req.toMs).toISOString(),
    limit: String(PAGE_LIMIT),
  });
  if (cursor !== null) q.set("cursor", cursor);
  return `/api/v1/market/funding?${q.toString()}`;
}

async function getPage(
  path: string,
  signal: AbortSignal,
  clock: FundingClock,
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

/** Reads the window page by page; settled points come back ascending and unique by time. */
export async function fetchFundingHistory(
  req: FundingHistoryRequest,
): Promise<FundingHistoryResult> {
  const clock = req.clock ?? SYSTEM;
  const byTime = new Map<number, SettledPoint>();
  let predicted: PredictedRate | null = null;
  let out: Omit<FundingHistoryOk, "settled"> | null = null;
  let cursor: string | null = null;
  for (let page = 0; page < (req.maxPages ?? MAX_PAGES); page += 1) {
    const answer = await getPage(fundingPath(req, cursor), req.signal, clock);
    if (answer === null) return { kind: "failed", status: null, code: null };
    // `api/funding.py` 404 `not_found`: the instruments cache lacks the symbol (D02 `funding-unavailable`)
    if (answer.status === 404) return { kind: "unavailable" };
    const code = get(answer.body, "code" satisfies keyof Problem);
    if (answer.status !== 200) {
      return {
        kind: "failed",
        status: answer.status,
        code: typeof code === "string" ? code : null,
      };
    }
    const items = get(answer.body, "items" satisfies keyof FundingOk);
    const meta = get(answer.body, "meta" satisfies keyof FundingOk);
    if (!Array.isArray(items)) return { kind: "failed", status: 200, code: "malformed" };
    out ??= {
      kind: "ok",
      intervalMinutes: parseInterval(answer.body),
      predicted: null,
      coverage: parseCoverage(meta),
      truncated: true,
    };
    for (const item of items) {
      const parsed = parseItem(item);
      if (parsed === null) continue;
      if ("predicted" in parsed) predicted = parsed.predicted;
      else byTime.set(parsed.settled.tMs, parsed.settled);
    }
    const next = get(meta, "next_cursor" satisfies keyof FundingMeta);
    const more = get(meta, "has_more" satisfies keyof FundingMeta) === true;
    const last = !more || typeof next !== "string" || next === "";
    out = { ...out, truncated: !last };
    if (last) break;
    cursor = next;
  }
  if (out === null) return { kind: "failed", status: null, code: null };
  return { ...out, predicted, settled: [...byTime.values()].sort((a, b) => a.tMs - b.tMs) };
}
