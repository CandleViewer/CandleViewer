/**
 * The Working-orders tab's REST reads (E29-S02 #912): `GET /orders?open_only=true` (`22`
 * `listOrders`), through `apiFetch` and typed from the generated `packages/protocol` types
 * (C-4.16), and the account directory the Positions tab reads (`listExchangeAccounts`). Reads only:
 * the amend, cancel and cancel-all writes are this story's later PRs.
 *
 * `open_only` is "every state but `filled`, `cancelled`, `rejected`, `expired` and `killed`, so
 * `held` and `untracked` too" (`22`), which the WS snapshot never carries (BQ-6). Outcomes are
 * fixed kinds, so no server `detail` reaches the screen (BQ-2); a filter naming an account outside
 * the caller's grants is refused whole and audited by the server (`403 account_scope_denied`).
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import { MAX_ACCOUNT_IDS, positionsApi, type AccountsOutcome, type ReadFailure } from "../api";

export type Order = generated.rest.components["schemas"]["Order"];
type ListOrdersQuery = NonNullable<generated.rest.operations["listOrders"]["parameters"]["query"]>;

export type OrdersOutcome =
  | {
      readonly kind: "ok";
      readonly items: readonly Order[];
      /** More pages than `MAX_PAGES` were on offer: the read stops there, bounded (C-2.18). */
      readonly truncated: boolean;
    }
  | { readonly kind: ReadFailure };

export interface OrdersQuery {
  /** Restrict to these accounts (`exchange_account_ids`, at most 25); omit for all in scope. */
  readonly accountIds?: readonly string[];
  /** The non-terminal set, held and untracked included (`22` `open_only`). */
  readonly openOnly?: boolean;
}

/** The seam the feed and the tests share (the positions tab's pattern). */
export interface OrdersApi {
  listOrders(query?: OrdersQuery, signal?: AbortSignal): Promise<OrdersOutcome>;
  listExchangeAccounts(signal?: AbortSignal): Promise<AccountsOutcome>;
}

/** `22` `Limit.maximum`, and a cap so a bad cursor never loops. */
export const PAGE = 500;
export const MAX_PAGES = 10;

async function failure(res: Response): Promise<ReadFailure> {
  if (res.status === 400) return "invalid";
  if (res.status !== 403) return "unavailable"; // 503, 401 after the renewal, anything unexpected
  try {
    const body = (await res.json()) as { code?: unknown };
    return body.code === "account_scope_denied" ? "account_scope_denied" : "forbidden";
  } catch {
    return "forbidden";
  }
}

const isObjectArray = (value: unknown): value is object[] =>
  Array.isArray(value) && value.every((v) => typeof v === "object" && v !== null);

/** The query string: `exchange_account_ids` repeated (`explode: true`), a page, a cursor. */
export function ordersSearch(query: OrdersQuery = {}, cursor: string | null = null): string {
  const ids = query.accountIds ?? [];
  if (ids.length > MAX_ACCOUNT_IDS) throw new RangeError("listOrders takes at most 25 accounts");
  const typed: ListOrdersQuery = {
    limit: PAGE,
    ...(ids.length > 0 && { exchange_account_ids: [...ids] }),
    ...(query.openOnly === true && { open_only: true }),
    ...(cursor !== null && { cursor }),
  };
  const params = new URLSearchParams();
  for (const id of typed.exchange_account_ids ?? []) params.append("exchange_account_ids", id);
  if (typed.open_only === true) params.set("open_only", "true");
  params.set("limit", String(typed.limit));
  if (typed.cursor !== undefined) params.set("cursor", typed.cursor);
  return `?${params.toString()}`;
}

async function listOrders(query: OrdersQuery = {}, signal?: AbortSignal): Promise<OrdersOutcome> {
  const items: Order[] = [];
  let cursor: string | null = null;
  try {
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const res = await apiFetch(
        `/api/v1/orders${ordersSearch(query, cursor)}`,
        signal === undefined ? undefined : { signal },
      );
      if (!res.ok) return { kind: await failure(res) };
      const body = (await res.json()) as {
        items?: unknown;
        meta?: { has_more?: unknown; next_cursor?: unknown };
      };
      if (!isObjectArray(body.items)) return { kind: "unavailable" };
      items.push(...(body.items as Order[]));
      const next = body.meta?.next_cursor;
      if (body.meta?.has_more !== true || typeof next !== "string") {
        return { kind: "ok", items, truncated: false };
      }
      cursor = next;
    }
    return { kind: "ok", items, truncated: true };
  } catch {
    return { kind: "unavailable" };
  }
}

export const ordersApi: OrdersApi = {
  listOrders,
  listExchangeAccounts: (signal) => positionsApi.listExchangeAccounts(signal),
};
