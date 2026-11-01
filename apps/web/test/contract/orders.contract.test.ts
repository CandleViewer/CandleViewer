/**
 * E29-S02 (#912) consumer contract (C-6.2, the ticket's test plan): the `orders` frames the shipped
 * mappers wrote validate against `cv://ws/v1/orders.schema.json` through the WS schema harness; the
 * client's `sub` frame validates; the REST bodies fit the generated `Order` (the `listOrders` 200),
 * `AmendOrderRequest`, `CancelAllRequest` and `BulkAccountResult`; and the row model reads every
 * order both feeds serve.
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { mapOrder, type WsOrder } from "../../src/features/positions/orders/model/orderRow";
import { createOrdersStore } from "../../src/features/positions/orders/ordersStore";
import { startOrdersFeed } from "../../src/features/positions/orders/wsOrders";
import { sub } from "../../src/lib/ws/protocol/frames";
import {
  deltaBody,
  directory,
  exchangeAccounts,
  fakeClient,
  golden,
  restOpen,
  snapshotBody,
  type DeltaCase,
  type OrdersBody,
} from "../features/positions/orders/support/orders";
import { validateClientFrame, validatePayload } from "../lib/ws/support/schemaHarness";

type Schemas = generated.rest.components["schemas"];
type Order = Schemas["Order"];
type AmendOrderRequest = Schemas["AmendOrderRequest"];
type CancelAllRequest = Schemas["CancelAllRequest"];
type BulkAccountResult = Schemas["BulkAccountResult"];
type BulkEntry = NonNullable<BulkAccountResult["results"]>[number];
type LegError = Schemas["LegError"];
type ListOrders200 =
  generated.rest.operations["listOrders"]["responses"][200]["content"]["application/json"];
type RequiredKeys<T> = { [K in keyof T]-?: object extends Pick<T, K> ? never : K }[keyof T];

/** The generated `Order`'s members, held to the type both ways at compile time. */
const ORDER_KEYS = [
  "algo",
  "avg_fill_price",
  "close_on_trigger",
  "created_at",
  "environment",
  "exchange_account_id",
  "exchange_order_id",
  "filled_qty",
  "id",
  "intent",
  "is_paper",
  "lifecycle_state",
  "order_link_id",
  "order_type",
  "parent_order_id",
  "position_idx",
  "price",
  "provenance",
  "qty",
  "reduce_only",
  "rejected_reason",
  "remaining_qty",
  "side",
  "state",
  "stop_loss",
  "symbol",
  "take_profit",
  "time_in_force",
  "tpsl_mode",
  "trade_group_id",
  "trade_group_leg_id",
  "trigger_by",
  "trigger_direction",
  "trigger_price",
  "updated_at",
] as const satisfies readonly (keyof Order)[];
const ORDER_REQUIRED = [
  "exchange_account_id",
  "id",
  "is_paper",
  "order_type",
  "qty",
  "side",
  "state",
  "symbol",
] as const satisfies readonly RequiredKeys<Order>[];
const ORDER_DECIMALS = [
  "avg_fill_price",
  "filled_qty",
  "price",
  "qty",
  "remaining_qty",
  "stop_loss",
  "take_profit",
  "trigger_price",
] as const satisfies readonly (keyof Order)[];
const AMEND_KEYS = [
  "price",
  "qty",
  "stop_loss",
  "take_profit",
  "trigger_price",
] as const satisfies readonly (keyof AmendOrderRequest)[];
const CANCEL_ALL_KEYS = [
  "exchange_account_ids",
  "exclude_reduce_only",
  "intents",
  "symbol",
] as const satisfies readonly (keyof CancelAllRequest)[];
const BULK_KEYS = [
  "requested",
  "results",
  "succeeded",
] as const satisfies readonly (keyof BulkAccountResult)[];
const BULK_ENTRY_KEYS = [
  "affected",
  "error",
  "exchange_account_id",
  "ok",
] as const satisfies readonly (keyof BulkEntry)[];
const LEG_ERROR_KEYS = [
  "code",
  "exchange_ret_code",
  "message",
  "retryable",
] as const satisfies readonly (keyof LegError)[];

const DECIMAL = /^-?[0-9]+(\.[0-9]+)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const isDecimalOrNull = (v: unknown): boolean =>
  v === null || (typeof v === "string" && DECIMAL.test(v));
const keysIn = (body: object, allowed: readonly string[]): string[] =>
  Object.keys(body).filter((k) => !allowed.includes(k));

/** Each item of a `listOrders` page against the generated `Order`. */
function orderProblems(item: Record<string, unknown>): string[] {
  const problems = keysIn(item, ORDER_KEYS).map((k) => `unknown ${k}`);
  for (const key of ORDER_REQUIRED) if (!(key in item)) problems.push(`missing ${key}`);
  for (const key of ORDER_DECIMALS)
    if (key in item && !isDecimalOrNull(item[key])) problems.push(`${key} not a Decimal`);
  if (!UUID.test(String(item["id"])) || !UUID.test(String(item["exchange_account_id"])))
    problems.push("uuid");
  if (!["buy", "sell"].includes(item["side"] as string)) problems.push("side");
  if (!["market", "limit"].includes(item["order_type"] as string)) problems.push("order_type");
  if (!["placed", "reconciliation", "recorded_stop"].includes(item["provenance"] as string))
    problems.push("provenance");
  if ("created_at" in item && Number.isNaN(Date.parse(String(item["created_at"]))))
    problems.push("created_at");
  return problems;
}

const CASES: readonly DeltaCase[] = [
  "created",
  "submitted",
  "acked",
  "amend_request",
  "amend_accepted",
  "amend_rejected",
  "amend_unknown",
  "cancel_request",
  "cancel_lost_race",
  "cancel_110001",
  "reconcile_filled",
  "untracked_adopted",
  "held",
  "late",
];

describe("WS frames validate against cv://ws/v1/orders.schema.json (fixtures from the shipped mappers)", () => {
  it("the snapshot, every delta and the contract-valid frames", () => {
    expect(validatePayload("orders", snapshotBody())).toEqual([]);
    const deltas = golden<{ case: string; body: unknown }[]>("ws_orders_deltas.json");
    expect(deltas.map((x) => x.case)).toEqual(CASES);
    for (const { body } of deltas) expect(validatePayload("orders", body)).toEqual([]);
    expect(validatePayload("orders", golden("ws_orders_contract_fields.json"))).toEqual([]);
  });

  it("the harness is not vacuous: a number qty or an unknown member is refused", () => {
    const [first] = snapshotBody().orders;
    expect(validatePayload("orders", { orders: [{ ...first, qty: 0.25 }] }).join()).toMatch(
      /must be string/,
    );
    expect(validatePayload("orders", { orders: [{ ...first, ret_msg: "x" }] }).join()).toMatch(
      /additional properties/,
    );
  });

  it("every frame the client reads maps to a row (the model's reader covers the schema)", () => {
    const dir = directory();
    const bodies: OrdersBody[] = [snapshotBody(), ...CASES.map(deltaBody)];
    for (const body of bodies) {
      for (const item of body.orders) expect(mapOrder(item as WsOrder, "ws", dir)).not.toBeNull();
    }
  });
});

describe("the client's sub frame validates (23 §13.5)", () => {
  it("orders names the accounts and asks for every order, not the open set alone (BQ-14)", async () => {
    const ws = fakeClient();
    const feed = startOrdersFeed({
      client: ws.client,
      store: createOrdersStore(),
      api: {
        listOrders: async () => ({ kind: "ok", items: [], truncated: false }),
        listExchangeAccounts: async () => ({ kind: "ok", items: exchangeAccounts() }),
      },
      performance: null,
      raf: () => 0,
      caf: () => undefined,
    });
    await Promise.resolve();
    await Promise.resolve();
    feed.stop();
    const [handle] = ws.handles;
    expect(handle?.ch).toBe("orders");
    const topic = { ch: "orders", opts: handle?.spec.opts ?? {} };
    expect(validateClientFrame(sub("c-1", { topics: [topic], snapshot: true }))).toEqual([]);
    const ids = (topic.opts as { exchange_account_ids: string[] }).exchange_account_ids;
    expect(ids.length).toBeGreaterThan(0); // never empty: an empty list is `invalid_options`
    expect(topic.opts).not.toHaveProperty("open_only");
  });
});

describe("REST bodies fit the generated types", () => {
  it("the key lists are the generated types' (compile time, both ways)", () => {
    expectTypeOf<Exclude<keyof Order, (typeof ORDER_KEYS)[number]>>().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<RequiredKeys<Order>, (typeof ORDER_REQUIRED)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof AmendOrderRequest, (typeof AMEND_KEYS)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof CancelAllRequest, (typeof CANCEL_ALL_KEYS)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof BulkAccountResult, (typeof BULK_KEYS)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof BulkEntry, (typeof BULK_ENTRY_KEYS)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<Exclude<keyof LegError, (typeof LEG_ERROR_KEYS)[number]>>().toEqualTypeOf<never>();
  });

  it("listOrders?open_only=true: a page of Order items, held and untracked among them", () => {
    const body = golden<ListOrders200 & { meta?: unknown }>("rest_list_orders_open.json");
    expect(body.meta).toEqual({ next_cursor: null, has_more: false, count: 7 });
    // `Page`'s own `items` widens the element type: the generated `Order` is what each one is
    const items = (body.items ?? []) as Order[];
    for (const item of items) {
      expect(orderProblems(item as unknown as Record<string, unknown>)).toEqual([]);
      const typed: Order = item;
      expect(mapOrder(typed, "rest", directory())).not.toBeNull();
    }
    expect(items.map((o) => o.lifecycle_state)).toEqual(
      expect.arrayContaining(["held", "untracked", "partially_filled"]),
    );
    // newest first by creation time (22)
    const created = items.map((o) => Date.parse(o.created_at ?? ""));
    expect([...created].sort((a, b) => b - a)).toEqual(created);
    expect(restOpen()).toHaveLength(7);
  });

  it("AmendOrderRequest: the specimen's price, a Decimal string, never a number", () => {
    const body = golden<AmendOrderRequest>("rest_amend_order_request.json");
    expect(keysIn(body, AMEND_KEYS)).toEqual([]);
    expect(body).toEqual({ price: "2495.00" });
    expect(body.price).toMatch(DECIMAL);
  });

  it("CancelAllRequest: the accounts, reduce-only exits kept (22's default)", () => {
    const body = golden<CancelAllRequest>("rest_cancel_all_request.json");
    expect(keysIn(body, CANCEL_ALL_KEYS)).toEqual([]);
    expect(body.exclude_reduce_only).toBe(true);
    expect(body.exchange_account_ids?.every((id) => UUID.test(id))).toBe(true);
  });

  it("BulkAccountResult: one entry per account, the OMS's own words for a failure (SR-E29-09)", () => {
    const body = golden<BulkAccountResult>("rest_cancel_all_partial.json");
    expect(keysIn(body, BULK_KEYS)).toEqual([]);
    expect([body.requested, body.succeeded]).toEqual([5, 3]);
    for (const entry of body.results ?? []) {
      expect(keysIn(entry, BULK_ENTRY_KEYS)).toEqual([]);
      expect(entry.ok).toBe(entry.error === null);
      if (entry.error != null) {
        expect(keysIn(entry.error, LEG_ERROR_KEYS)).toEqual([]);
        expect(["exchange_unavailable", "timeout"]).toContain(entry.error.code);
      }
    }
    expect(body.results?.filter((r) => r.ok === false).map((r) => r.affected)).toEqual([0, 1]);
  });
});
