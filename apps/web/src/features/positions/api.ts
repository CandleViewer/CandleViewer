/**
 * The Positions tab's REST reads (E29-S01 #911): `GET /positions` (`22` `listPositions`, plain and
 * `?aggregate=true`) and `GET /exchange-accounts` (`listExchangeAccounts`), through `apiFetch`,
 * typed from the generated `packages/protocol` types (C-4.16). Both are read-only: this story sends
 * no mutating request (BQ-3). REST is first paint while the WS snapshot is pending and the fallback
 * while the link is down, never polled (BQ-18; `wsPositions.ts` decides when).
 *
 * Outcomes are fixed kinds: no server `detail` reaches the screen. A filter naming an account
 * outside the caller's grants is refused whole, audited (`403 account_scope_denied`, SR-E29-13);
 * the scenario's refusal is the server's, and the client never filters for security.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
export type Position = Schemas["Position"];
export type AggregatePosition = Schemas["AggregatePosition"];
export type ExchangeAccount = Schemas["ExchangeAccount"];
type ListPositionsQuery = NonNullable<
  generated.rest.operations["listPositions"]["parameters"]["query"]
>;

export type ReadFailure = "account_scope_denied" | "forbidden" | "invalid" | "unavailable";

export type PositionsOutcome =
  | {
      readonly kind: "ok";
      readonly items: readonly Position[];
      readonly aggregates: readonly AggregatePosition[];
    }
  | { readonly kind: ReadFailure };

export type AccountsOutcome =
  | { readonly kind: "ok"; readonly items: readonly ExchangeAccount[] }
  | { readonly kind: ReadFailure };

export interface PositionsQuery {
  /** Restrict to these accounts (`exchange_account_ids`, at most 25); omit for every one in scope. */
  readonly accountIds?: readonly string[];
  readonly aggregate?: boolean;
}

/** The seam the store and the tests share (the `SessionsApi` pattern). */
export interface PositionsApi {
  listPositions(query?: PositionsQuery, signal?: AbortSignal): Promise<PositionsOutcome>;
  /** Every page, bounded: the caller's accounts with their labels and modes. */
  listExchangeAccounts(signal?: AbortSignal): Promise<AccountsOutcome>;
}

/** `22` `AccountIdsQuery.maxItems` (and `23` §13.5's on `sub`). */
export const MAX_ACCOUNT_IDS = 25;
/** `22` `Limit.maximum`, and a cap so a bad cursor never loops. */
const PAGE = 500;
const MAX_PAGES = 10;

/** A refused read's fixed kind, never its `detail` (the Working-orders reads share it). */
export async function failure(res: Response): Promise<ReadFailure> {
  if (res.status === 400) return "invalid";
  if (res.status !== 403) return "unavailable"; // 503, 401 after the renewal, anything unexpected
  try {
    const body = (await res.json()) as { code?: unknown };
    return body.code === "account_scope_denied" ? "account_scope_denied" : "forbidden";
  } catch {
    return "forbidden";
  }
}

/** A page's `items`: an array of objects, else the read is `unavailable`. */
export const isObjectArray = (value: unknown): value is object[] =>
  Array.isArray(value) && value.every((v) => typeof v === "object" && v !== null);

/** The query string, `exchange_account_ids` repeated (`22`: `explode: true`). */
export function positionsSearch(query: PositionsQuery = {}): string {
  const params = new URLSearchParams();
  const ids = query.accountIds ?? [];
  if (ids.length > MAX_ACCOUNT_IDS) throw new RangeError("listPositions takes at most 25 accounts");
  const typed: ListPositionsQuery = {
    ...(ids.length > 0 && { exchange_account_ids: [...ids] }),
    ...(query.aggregate === true && { aggregate: true }),
  };
  for (const id of typed.exchange_account_ids ?? []) params.append("exchange_account_ids", id);
  if (typed.aggregate === true) params.set("aggregate", "true");
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

async function listPositions(
  query: PositionsQuery = {},
  signal?: AbortSignal,
): Promise<PositionsOutcome> {
  try {
    const res = await apiFetch(
      `/api/v1/positions${positionsSearch(query)}`,
      signal === undefined ? undefined : { signal },
    );
    if (!res.ok) return { kind: await failure(res) };
    const body = (await res.json()) as { items?: unknown; aggregates?: unknown };
    if (!isObjectArray(body.items)) return { kind: "unavailable" };
    const aggregates = body.aggregates === undefined ? [] : body.aggregates;
    if (!isObjectArray(aggregates)) return { kind: "unavailable" };
    return {
      kind: "ok",
      items: body.items as Position[],
      aggregates: aggregates as AggregatePosition[],
    };
  } catch {
    return { kind: "unavailable" };
  }
}

async function listExchangeAccounts(signal?: AbortSignal): Promise<AccountsOutcome> {
  const items: ExchangeAccount[] = [];
  let cursor: string | null = null;
  try {
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const after = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
      const res = await apiFetch(
        `/api/v1/exchange-accounts?limit=${PAGE}${after}`, // the balance's MM rate: first paint (BQ-11)
        signal === undefined ? undefined : { signal },
      );
      if (!res.ok) return { kind: await failure(res) };
      const body = (await res.json()) as {
        items?: unknown;
        meta?: { has_more?: unknown; next_cursor?: unknown };
      };
      if (!isObjectArray(body.items)) return { kind: "unavailable" };
      items.push(...(body.items as ExchangeAccount[]));
      const next = body.meta?.next_cursor;
      if (body.meta?.has_more !== true || typeof next !== "string") break;
      cursor = next;
    }
    return { kind: "ok", items };
  } catch {
    return { kind: "unavailable" };
  }
}

export const positionsApi: PositionsApi = { listPositions, listExchangeAccounts };
