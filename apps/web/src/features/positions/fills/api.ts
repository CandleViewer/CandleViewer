/**
 * The fills' REST reads (E29-S04 #979), through `apiFetch` and typed from the generated
 * `packages/protocol` types (C-4.16): `listExecutions` one cursor page at a time (`22`: newest
 * first by fill time, at most 500 a page, at most 25 accounts a request, cursors bound to the
 * caller and the query and valid for an hour), `getOrder?include_events=true` (the order's terms
 * and events, for the slippage's intent and its amend, BQ-8), `getTradeGroup` and `getInstrument`
 * (the tick, cached per symbol). All are reads: nothing here writes, and no server `detail`
 * reaches the screen; an outcome is a fixed kind. Scope is the server's (`executions:read` on
 * granted accounts; `403 account_scope_denied` refuses a request naming any other account whole).
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import { MAX_ACCOUNT_IDS } from "../api";
import { isUuid } from "../model/rowMapping";

type Schemas = generated.rest.components["schemas"];
export type Execution = Schemas["Execution"];
export type OrderWithEvents = Schemas["OrderWithEvents"];
export type TradeGroup = Schemas["TradeGroup"];
export type InstrumentDetail = Schemas["InstrumentDetail"];
type ExecutionsParams = NonNullable<
  generated.rest.operations["listExecutions"]["parameters"]["query"]
>;

export type FillsReadFailure =
  "account_scope_denied" | "forbidden" | "not_found" | "invalid_cursor" | "invalid" | "unavailable";

export type Read<T> =
  { readonly kind: "ok"; readonly value: T } | { readonly kind: FillsReadFailure };

export interface ExecutionsPage {
  readonly items: readonly Execution[];
  readonly nextCursor: string | null;
  readonly hasMore: boolean;
}

/** What `readExecutions` read: a page that failed after the first keeps the pages before it. */
export interface ExecutionsRead {
  readonly items: readonly Execution[];
  /** No page remains. */
  readonly complete: boolean;
  /** Why a page after the first failed (`complete` is then false); `null` when none did. */
  readonly failure: FillsReadFailure | null;
}

export interface ExecutionsQuery {
  /** At most 25 (`22` `AccountIdsQuery`); omitted, every account the caller may view. */
  readonly accountIds?: readonly string[];
  readonly symbol?: string;
  readonly orderId?: string;
  readonly tradeGroupId?: string;
  /** RFC 3339 UTC; `from` inclusive, `to` exclusive (`22` `From`, `To`). */
  readonly from?: string;
  readonly to?: string;
}

/** `22` `Limit.maximum`. */
export const PAGE_LIMIT = 500;

/** The seam the feed, the drawer and the tests share. */
export interface FillsApi {
  listExecutions(
    query: ExecutionsQuery,
    page?: { readonly cursor?: string; readonly limit?: number },
    signal?: AbortSignal,
  ): Promise<Read<ExecutionsPage>>;
  getOrder(orderId: string, signal?: AbortSignal): Promise<Read<OrderWithEvents>>;
  getTradeGroup(tradeGroupId: string, signal?: AbortSignal): Promise<Read<TradeGroup>>;
  getInstrument(symbol: string, signal?: AbortSignal): Promise<Read<InstrumentDetail>>;
}

async function failure(res: Response): Promise<FillsReadFailure> {
  if (res.status === 404) return "not_found";
  if (res.status !== 400 && res.status !== 403) return "unavailable"; // 503, 401 after renewal
  let code: unknown;
  try {
    code = ((await res.json()) as { code?: unknown }).code;
  } catch {
    code = undefined;
  }
  if (res.status === 400) return code === "invalid_cursor" ? "invalid_cursor" : "invalid";
  return code === "account_scope_denied" ? "account_scope_denied" : "forbidden";
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The query string, `exchange_account_ids` repeated (`22`: `explode: true`). */
export function executionsSearch(
  query: ExecutionsQuery,
  page: { readonly cursor?: string; readonly limit?: number } = {},
): string {
  const ids = query.accountIds ?? [];
  if (ids.length > MAX_ACCOUNT_IDS)
    throw new RangeError("listExecutions takes at most 25 accounts");
  const limit = page.limit ?? PAGE_LIMIT;
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > PAGE_LIMIT)
    throw new RangeError("listExecutions takes a limit of 1 to 500");
  const typed: ExecutionsParams = {
    ...(ids.length > 0 && { exchange_account_ids: [...ids] }),
    ...(query.symbol !== undefined && { symbol: query.symbol }),
    ...(query.orderId !== undefined && { order_id: query.orderId }),
    ...(query.tradeGroupId !== undefined && { trade_group_id: query.tradeGroupId }),
    ...(query.from !== undefined && { from: query.from }),
    ...(query.to !== undefined && { to: query.to }),
    ...(page.cursor !== undefined && { cursor: page.cursor }),
    limit,
  };
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(typed)) {
    for (const one of Array.isArray(value) ? value : [value]) params.append(name, String(one));
  }
  return `?${params.toString()}`;
}

const init = (signal?: AbortSignal): RequestInit | undefined =>
  signal === undefined ? undefined : { signal };

async function read<T>(
  path: string,
  shape: (body: unknown) => T | null,
  signal?: AbortSignal,
): Promise<Read<T>> {
  try {
    const res = await apiFetch(path, init(signal));
    if (!res.ok) return { kind: await failure(res) };
    const value = shape(await res.json());
    return value === null ? { kind: "unavailable" } : { kind: "ok", value };
  } catch {
    return { kind: "unavailable" };
  }
}

function pageOf(body: unknown): ExecutionsPage | null {
  if (!isRecord(body) || !Array.isArray(body["items"]) || !isRecord(body["meta"])) return null;
  if (!body["items"].every(isRecord)) return null;
  const next = body["meta"]["next_cursor"];
  const hasMore = body["meta"]["has_more"] === true && typeof next === "string";
  return {
    items: body["items"] as Execution[],
    nextCursor: typeof next === "string" ? next : null,
    hasMore,
  };
}

const record = <T>(body: unknown): T | null => (isRecord(body) ? (body as T) : null);

export const fillsApi: FillsApi = {
  listExecutions: (query, page, signal) =>
    read(`/api/v1/executions${executionsSearch(query, page)}`, pageOf, signal),
  getOrder: async (orderId, signal) =>
    isUuid(orderId)
      ? read(`/api/v1/orders/${orderId}?include_events=true`, record<OrderWithEvents>, signal)
      : { kind: "invalid" },
  getTradeGroup: async (tradeGroupId, signal) =>
    isUuid(tradeGroupId)
      ? read(`/api/v1/trade-groups/${tradeGroupId}`, record<TradeGroup>, signal)
      : { kind: "invalid" },
  getInstrument: (symbol, signal) =>
    read(`/api/v1/instruments/${encodeURIComponent(symbol)}`, record<InstrumentDetail>, signal),
};

/**
 * Up to `maxPages` pages of one query, following `next_cursor` (a bound, so a server that keeps
 * saying `has_more` never loops); `complete` is false when more remain, or a later page failed.
 */
export async function readExecutions(
  api: FillsApi,
  query: ExecutionsQuery,
  maxPages: number,
  signal?: AbortSignal,
): Promise<Read<ExecutionsRead>> {
  const items: Execution[] = [];
  let cursor: string | undefined;
  for (let n = 0; n < maxPages; n += 1) {
    const page = await api.listExecutions(query, cursor === undefined ? {} : { cursor }, signal);
    if (page.kind !== "ok")
      return n === 0 ? page : { kind: "ok", value: { items, complete: false, failure: page.kind } };
    items.push(...page.value.items);
    if (!page.value.hasMore || page.value.nextCursor === null)
      return { kind: "ok", value: { items, complete: true, failure: null } };
    cursor = page.value.nextCursor;
  }
  return { kind: "ok", value: { items, complete: false, failure: null } };
}

/** Instruments a cache holds at most (C-2.18); past it the oldest is dropped first. */
export const MAX_TICKS = 64;

/**
 * The tick size per symbol from `getInstrument` (BQ-8), each read once while it answers; a failed
 * read is not kept, so a later open asks again. `null`: no tick, so slippage reads "—".
 */
export function createTickCache(
  api: Pick<FillsApi, "getInstrument">,
  max = MAX_TICKS,
): (symbol: string, signal?: AbortSignal) => Promise<string | null> {
  const ticks = new Map<string, Promise<string | null>>();
  return (symbol, signal) => {
    const held = ticks.get(symbol);
    if (held !== undefined) return held;
    const asked = api.getInstrument(symbol, signal).then((out) => {
      const tick = out.kind === "ok" ? out.value.tick_size : undefined;
      if (typeof tick !== "string") ticks.delete(symbol);
      return typeof tick === "string" ? tick : null;
    });
    ticks.set(symbol, asked);
    if (ticks.size > max) ticks.delete(ticks.keys().next().value as string);
    return asked;
  };
}
