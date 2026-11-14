/**
 * The while-you-were-offline summary's reads (E29-S07 #1028; BQ-9 of the ruling of record
 * 6575172489, BQ-4 ruled (6610918411): built on #5584's generated types).
 *
 * - `getReconciliationDigest` (`22`, `GET /exchange-accounts/{accountId}/reconciliation/latest`):
 *   the account's latest reported pass, so the summary never infers a correction from the client's
 *   cache. `404` is "no digest" (none yet, or an account outside the caller's grants, SR-E29-13).
 * - `listExecutions` in the client's offline window and `getOrder` for each order a fill landed
 *   on: E29-D03 §4.6's fills clause ("filled" only once the order reached Filled, else "partly
 *   filled"). Bounded: one page and at most `MAX_ORDER_READS` order reads, else no fills clause.
 *
 * Outcomes are fixed kinds: no server `detail` reaches the screen. Read-only; nothing is sent.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
export type ReconciliationDigest = Schemas["ReconciliationDigest"];
type Execution = Schemas["Execution"];

export type DigestOutcome =
  | { readonly kind: "ok"; readonly digest: ReconciliationDigest }
  | { readonly kind: "none" | "forbidden" | "unavailable" };

/** An order a `Trade` fill landed on while offline, with whether it reached Filled. */
export interface OfflineOrder {
  readonly accountId: string;
  readonly orderId: string;
  readonly filled: boolean;
}

/** `null`: the window could not be read whole, so no fills clause is shown (never a guess). */
export type FillsOutcome = readonly OfflineOrder[] | null;

export interface ReconciliationReads {
  getDigest(accountId: string, signal?: AbortSignal): Promise<DigestOutcome>;
  offlineFills(
    accountIds: readonly string[],
    window: { readonly fromMs: number; readonly toMs: number },
    signal?: AbortSignal,
  ): Promise<FillsOutcome>;
}

/** `22` `AccountIdsQuery.maxItems`. */
const MAX_ACCOUNT_IDS = 25;
/** One page of fills (`22` `Limit.maximum`) and a bound on the order reads it causes (C-2.18). */
const PAGE = 500;
export const MAX_ORDER_READS = 10;

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStrings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((s) => typeof s === "string");

/** The members the summary reads; a member it does not know is tolerated (C-6.3). */
export function isDigest(body: unknown): body is ReconciliationDigest {
  if (!isRecord(body)) return false;
  const lists = ["corrected", "resolved_from_history", "newly_unknown", "untracked", "sl_repaired"];
  return (
    typeof body["exchange_account_id"] === "string" &&
    typeof body["confirmed_at"] === "string" &&
    typeof body["trigger"] === "string" &&
    isRecord(body["counts"]) &&
    Array.isArray(body["position_drift"]) &&
    lists.every((name) => isStrings(body[name]))
  );
}

const opts = (signal?: AbortSignal): RequestInit | undefined =>
  signal === undefined ? undefined : { signal };

async function getDigest(accountId: string, signal?: AbortSignal): Promise<DigestOutcome> {
  try {
    const res = await apiFetch(
      `/api/v1/exchange-accounts/${encodeURIComponent(accountId)}/reconciliation/latest`,
      opts(signal),
    );
    if (res.status === 404) return { kind: "none" };
    if (res.status === 403) return { kind: "forbidden" };
    if (!res.ok) return { kind: "unavailable" };
    const body: unknown = await res.json();
    return isDigest(body) ? { kind: "ok", digest: body } : { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}

async function orderFilled(orderId: string, signal?: AbortSignal): Promise<boolean | null> {
  const res = await apiFetch(`/api/v1/orders/${encodeURIComponent(orderId)}`, opts(signal));
  if (!res.ok) return null;
  const body: unknown = await res.json();
  // `Order.state` (`OrderState`): "filled" once it reached Filled (E29-D03 §4.6)
  return isRecord(body) && typeof body["state"] === "string" ? body["state"] === "filled" : null;
}

async function offlineFills(
  accountIds: readonly string[],
  window: { readonly fromMs: number; readonly toMs: number },
  signal?: AbortSignal,
): Promise<FillsOutcome> {
  if (accountIds.length === 0 || accountIds.length > MAX_ACCOUNT_IDS) return null;
  try {
    const params = new URLSearchParams();
    for (const id of accountIds) params.append("exchange_account_ids", id);
    params.set("from", new Date(window.fromMs).toISOString());
    params.set("to", new Date(window.toMs).toISOString());
    params.set("limit", String(PAGE));
    const res = await apiFetch(`/api/v1/executions?${params.toString()}`, opts(signal));
    if (!res.ok) return null;
    const body: unknown = await res.json();
    if (!isRecord(body) || !Array.isArray(body["items"])) return null;
    if (isRecord(body["meta"]) && body["meta"]["has_more"] === true) return null;
    const orders = new Map<string, string>(); // order id -> account id, `Trade` fills only
    for (const item of body["items"] as Execution[]) {
      if (item.exec_type !== "Trade" || item.order_id === undefined) continue;
      if (item.exchange_account_id === undefined) continue;
      orders.set(item.order_id, item.exchange_account_id);
    }
    if (orders.size > MAX_ORDER_READS) return null;
    const out: OfflineOrder[] = [];
    for (const [orderId, accountId] of orders) {
      const filled = await orderFilled(orderId, signal);
      if (filled === null) return null;
      out.push({ accountId, orderId, filled });
    }
    return out;
  } catch {
    return null;
  }
}

export const reconciliationReads: ReconciliationReads = { getDigest, offlineFills };
