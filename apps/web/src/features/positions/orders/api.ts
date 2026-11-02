/**
 * The Working-orders tab's REST calls (E29-S02 #912), through `apiFetch` and typed from the
 * generated `packages/protocol` types (C-4.16): the reads, `GET /orders?open_only=true` (`22`
 * `listOrders`) and the account directory the Positions tab reads (`listExchangeAccounts`); and the
 * cancel writes (`cancelOrder`, `cancelAllOrders`; `ordersWrites` below). The amend is PR3's.
 *
 * `open_only` is "every state but `filled`, `cancelled`, `rejected`, `expired` and `killed`, so
 * `held` and `untracked` too" (`22`), which the WS snapshot never carries (BQ-6). Outcomes are
 * fixed kinds, so no server `detail` reaches the screen (BQ-2); a filter naming an account outside
 * the caller's grants is refused whole and audited by the server (`403 account_scope_denied`).
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import {
  failure,
  isObjectArray,
  MAX_ACCOUNT_IDS,
  positionsApi,
  type AccountsOutcome,
  type ReadFailure,
} from "../api";

export type Order = generated.rest.components["schemas"]["Order"];
type ListOrdersQuery = NonNullable<generated.rest.operations["listOrders"]["parameters"]["query"]>;

export type OrdersOutcome =
  | {
      readonly kind: "ok";
      readonly items: readonly Order[];
      /**
       * Pages were on offer that this read did not take: more than `MAX_PAGES` (it stops there,
       * bounded, C-2.18), or a page that says there is more and names no cursor to follow.
       */
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
      if (body.meta?.has_more !== true) return { kind: "ok", items, truncated: false };
      const next = body.meta.next_cursor;
      // More pages on offer and none to follow (no cursor, or one that is no string): the read is
      // cut short, so it settles nothing (a complete read closes the rows it no longer lists)
      if (typeof next !== "string") return { kind: "ok", items, truncated: true };
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

/*
 * The cancel writes (E29-S02 PR2; `22` `cancelOrder`, `cancelAllOrders`).
 *
 * - **One `Idempotency-Key` per request body** (BQ-8): each call holds its request (method, path,
 *   key, body) and every send of it is that held request, byte for byte. The same key goes out
 *   again only for a re-send of the identical request: after a transport failure (no answer, so it
 *   may have arrived) and after `409 idempotency_in_flight` or a `429`, each with its `Retry-After`;
 *   at most `MAX_RESENDS` times. Any other answer ends the call, and a later call ("Retry failed")
 *   is a new request with a new key: `22` stores only a `2xx` under a key, and a cancel-all's
 *   stored `200` would answer the same key again for 24 h.
 * - **No arm token** (`32-design-specs.md` R5; `22` `ArmToken`): a cancel never meets the arm,
 *   so no `X-Arm-Token` header is ever sent here, whatever the session holds (C-2.6).
 * - **Fixed kinds:** an answer is read for its status and `code` only; no `detail`, `message` or
 *   `exchange_ret_code` reaches the caller (BQ-2, SR-E29-09). `403 risk_limit_breached` on a
 *   cancel is the command port's `NATIVE_STOP_REQUIRED` (a recorded stop's row while its position
 *   is open): the server's enforcement of C-2.6 behind the client's own skip (`model/bulk.ts`).
 */

type CancelAllRequest = generated.rest.components["schemas"]["CancelAllRequest"];
export type { CancelAllRequest };

/** A write that ended without the server taking it, as the caller shows it. */
export type WriteFailure =
  /** `403 risk_limit_breached`: a native stop's row while its position is open (C-2.6). */
  | "native_stop"
  /** `403 account_scope_denied`: the account is outside the caller's grants (S-22, `rbac.account`). */
  | "account_scope"
  /** `403 view_as_read_only`: a view-as session writes nothing (S-22, `rbac.view_as`). */
  | "view_as"
  /** Any other `403`: a view-only grant, a read-only role, CSRF. */
  | "forbidden"
  /** `409` but in flight: `conflict`, `account_unavailable`, `idempotency_key_reuse`; nothing sent. */
  | "conflict"
  /**
   * A `429` still so after the re-sends, none of which went unanswered: the server took nothing.
   * A `429` after an unanswered send, or a `409 idempotency_in_flight`, is `unavailable` instead.
   */
  | "busy"
  /** `502 exchange_error`: Bybit refused it and the order stays live. */
  | "exchange_refused"
  /** `503 store_unavailable`: a read before the send failed, nothing was sent. */
  | "store_unavailable"
  | "not_found"
  | "invalid"
  /**
   * The outcome is not known: no answer after the re-sends, an answer this client cannot read, a
   * `409 idempotency_in_flight` (an earlier send of the key is still running), or a `429` after a
   * send that went unanswered (that send may have arrived).
   */
  | "unavailable";

export type CancelOutcome =
  | {
      readonly kind: "accepted";
      /** The order's B1 state in the `202`, when it carries one (`unknown` after a `110001`). */
      readonly lifecycle: string | null;
    }
  | { readonly kind: WriteFailure };

/** One account of a cancel-all's `BulkAccountResult`: its `LegError` read for `code` and `retryable` only. */
export interface AccountCancelResult {
  readonly accountId: string;
  readonly ok: boolean;
  /** The orders cancelled on it. */
  readonly affected: number;
  readonly code: string | null;
  readonly retryable: boolean;
}

export type CancelAllOutcome =
  | { readonly kind: "ok"; readonly results: readonly AccountCancelResult[] }
  | { readonly kind: WriteFailure };

export interface OrdersWrites {
  /** `DELETE /orders/{orderId}`: one request, its own key. */
  cancelOrder(orderId: string, signal?: AbortSignal): Promise<CancelOutcome>;
  /** `POST /orders/cancel-all`: one request, its own key. */
  cancelAllOrders(body: CancelAllRequest, signal?: AbortSignal): Promise<CancelAllOutcome>;
}

/** A request as first sent: every re-send is this, its key included (BQ-8). */
export interface HeldWrite {
  readonly method: "DELETE" | "POST";
  readonly path: string;
  readonly key: string;
  readonly body: string | null;
}

/** Re-sends of one held request at most, after a transport failure, a `409 idempotency_in_flight` or a `429`. */
export const MAX_RESENDS = 2;
/** The wait before re-sending when no `Retry-After` is given (`22`: `Retry-After: 1`). */
export const RESEND_WAIT_MS = 1_000;
/** A `Retry-After` longer than this is cut to it, so a cancel never waits long unseen. */
export const MAX_RESEND_WAIT_MS = 5_000;

export interface WritesDeps {
  readonly fetch?: (path: string, init: RequestInit) => Promise<Response>;
  /** A fresh UUIDv4 per request (`22` Idempotency). */
  readonly newKey?: () => string;
  readonly sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

const UUID_PATH = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A wait that an abort ends early; it lets go of its abort listener either way. */
const platformSleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    const done = (): void => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal?.addEventListener("abort", done, { once: true });
  });

/**
 * `Retry-After` as ms: its whole-seconds form (`22` sends `1`), `0` now, at most the cap however
 * long the number; the default when it is absent or another form (an HTTP date). Read digit by
 * digit, capped as it accumulates: no positions module parses through `Number`
 * (`decimal.test.ts`'s guard), though a wait is no money.
 */
export function retryAfterMs(res: Response): number {
  const text = res.headers.get("Retry-After")?.trim() ?? "";
  if (!/^[0-9]+$/.test(text)) return RESEND_WAIT_MS;
  let ms = 0;
  for (const digit of text) {
    ms = Math.min(ms * 10 + (digit.charCodeAt(0) - 48) * 1_000, MAX_RESEND_WAIT_MS);
  }
  return ms;
}

async function codeOf(res: Response): Promise<string | null> {
  try {
    const body = (await res.clone().json()) as { code?: unknown };
    return typeof body.code === "string" ? body.code : null;
  } catch {
    return null;
  }
}

/** `403`'s codes that name their own reason (S-22); any other is `forbidden`. */
const FORBIDDEN: Readonly<Record<string, WriteFailure>> = {
  risk_limit_breached: "native_stop",
  account_scope_denied: "account_scope",
  view_as_read_only: "view_as",
};

/**
 * A refused answer's fixed kind, by status and `code` alone. `answered` is false when an earlier send
 * of the same key went unanswered: a `429` then leaves the outcome unknown, as an in-flight `409` does.
 */
async function failureOf(res: Response, answered = true): Promise<WriteFailure> {
  const code = await codeOf(res);
  switch (res.status) {
    case 400:
      return "invalid";
    case 403:
      return (
        (code !== null && Object.hasOwn(FORBIDDEN, code) ? FORBIDDEN[code] : undefined) ??
        "forbidden"
      );
    case 404:
      return "not_found";
    case 409:
      return code === "idempotency_in_flight" ? "unavailable" : "conflict";
    case 429:
      return answered ? "busy" : "unavailable";
    case 502:
      return "exchange_refused";
    case 503:
      return code === "store_unavailable" ? "store_unavailable" : "unavailable";
    default:
      return "unavailable";
  }
}

/** The last answer of a held request (`null`: none), and whether every send before it was settled. */
interface HeldAnswer {
  readonly res: Response | null;
  /** False once a send of the key went unanswered or answered `409 idempotency_in_flight`. */
  readonly answered: boolean;
}

/** The answer of a held request, re-sent with its own key while the rule above allows. */
async function sendHeldWrite(
  held: HeldWrite,
  deps: Required<WritesDeps>,
  signal: AbortSignal | undefined,
): Promise<HeldAnswer> {
  let answered = true;
  for (let attempt = 0; ; attempt += 1) {
    const headers: Record<string, string> = { "Idempotency-Key": held.key };
    if (held.body !== null) headers["Content-Type"] = "application/json";
    const init: RequestInit = { method: held.method, headers };
    if (held.body !== null) init.body = held.body;
    if (signal !== undefined) init.signal = signal;
    let res: Response | null;
    try {
      res = await deps.fetch(held.path, init);
    } catch {
      res = null; // no answer: it may have arrived, so only the same key may follow it
    }
    if (signal?.aborted === true) return { res, answered: answered && res !== null };
    const inFlight =
      res !== null && res.status === 409 && (await codeOf(res)) === "idempotency_in_flight";
    if (!(res === null || res.status === 429 || inFlight) || attempt >= MAX_RESENDS)
      return { res, answered };
    // an unanswered send may have arrived, and an in-flight one is still running: from here on the
    // key's outcome is not known whatever a later send of it is refused with
    if (res === null || inFlight) answered = false;
    await deps.sleep(res === null ? RESEND_WAIT_MS : retryAfterMs(res), signal);
  }
}

const isRecord = (v: unknown): v is Readonly<Record<string, unknown>> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** A `BulkAccountResult` entry as the caller reads it, or `null` for one that names no account. */
function accountResult(entry: unknown): AccountCancelResult | null {
  if (!isRecord(entry) || typeof entry["exchange_account_id"] !== "string") return null;
  const error = isRecord(entry["error"]) ? entry["error"] : null;
  const affected = entry["affected"];
  return {
    accountId: entry["exchange_account_id"].toLowerCase(),
    ok: entry["ok"] === true,
    affected: typeof affected === "number" && Number.isSafeInteger(affected) ? affected : 0,
    code: typeof error?.["code"] === "string" ? error["code"] : null,
    retryable: error?.["retryable"] === true,
  };
}

export function createOrdersWrites(options: WritesDeps = {}): OrdersWrites {
  const deps: Required<WritesDeps> = {
    fetch: options.fetch ?? ((path, init) => apiFetch(path, init)),
    newKey: options.newKey ?? (() => crypto.randomUUID()),
    sleep: options.sleep ?? platformSleep,
  };
  return {
    async cancelOrder(orderId, signal) {
      if (!UUID_PATH.test(orderId)) return { kind: "invalid" };
      const held: HeldWrite = Object.freeze({
        method: "DELETE",
        path: `/api/v1/orders/${orderId.toLowerCase()}`,
        key: deps.newKey(),
        body: null,
      });
      const { res, answered } = await sendHeldWrite(held, deps, signal);
      if (res === null) return { kind: "unavailable" };
      if (res.status !== 202) return { kind: await failureOf(res, answered) };
      try {
        const order = (await res.json()) as { lifecycle_state?: unknown };
        const lifecycle = typeof order.lifecycle_state === "string" ? order.lifecycle_state : null;
        return { kind: "accepted", lifecycle };
      } catch {
        return { kind: "accepted", lifecycle: null };
      }
    },
    async cancelAllOrders(body, signal) {
      const held: HeldWrite = Object.freeze({
        method: "POST",
        path: "/api/v1/orders/cancel-all",
        key: deps.newKey(),
        body: JSON.stringify(body),
      });
      const { res, answered } = await sendHeldWrite(held, deps, signal);
      if (res === null) return { kind: "unavailable" };
      if (res.status !== 200) return { kind: await failureOf(res, answered) };
      try {
        const answer = (await res.json()) as { results?: unknown };
        if (!Array.isArray(answer.results)) return { kind: "unavailable" };
        const results = answer.results
          .map(accountResult)
          .filter((r): r is AccountCancelResult => r !== null);
        return { kind: "ok", results };
      } catch {
        return { kind: "unavailable" };
      }
    },
  };
}

export const ordersWrites: OrdersWrites = createOrdersWrites();
