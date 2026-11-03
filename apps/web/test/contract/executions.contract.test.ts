/**
 * E29-S04 (#979) consumer contract (C-6.2, the ticket's test plan): the `executions` frames the
 * shipped mappers wrote validate against `cv://ws/v1/executions.schema.json` through the WS schema
 * harness; the client's `sub` frame validates and asks no throttle; the REST bodies fit the
 * generated `listExecutions` 200 and `getOrder` 200 (`OrderWithEvents`).
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { createFillsStore } from "../../src/features/positions/fills/fillsStore";
import { startFillsFeed } from "../../src/features/positions/fills/wsFills";
import { sub } from "../../src/lib/ws/protocol/frames";
import { golden as fillsGolden, order } from "../features/positions/fills/support/fills";
import { fakeClient, golden } from "../features/positions/support/fakes";
import { validateClientFrame, validatePayload } from "../lib/ws/support/schemaHarness";

type Schemas = generated.rest.components["schemas"];
type Execution = Schemas["Execution"];
type Order = Schemas["Order"];
type ListExecutions200 =
  generated.rest.operations["listExecutions"]["responses"][200]["content"]["application/json"];
type RequiredKeys<T> = { [K in keyof T]-?: object extends Pick<T, K> ? never : K }[keyof T];

/** The generated `Execution`'s members, held to the type both ways at compile time. */
const EXECUTION_KEYS = [
  "is_paper",
  "id",
  "exec_id",
  "order_id",
  "exchange_account_id",
  "trade_group_id",
  "symbol",
  "side",
  "exec_qty",
  "exec_price",
  "exec_value",
  "fee",
  "fee_rate",
  "fee_coin",
  "is_maker",
  "exec_type",
  "exec_pnl",
  "ts",
] as const satisfies readonly (keyof Execution)[];
const EXECUTION_REQUIRED = ["is_paper"] as const satisfies readonly RequiredKeys<Execution>[];
const ORDER_REQUIRED = [
  "is_paper",
  "id",
  "exchange_account_id",
  "symbol",
  "side",
  "order_type",
  "state",
  "qty",
] as const satisfies readonly RequiredKeys<Order>[];
const DECIMALS = ["exec_qty", "exec_price", "exec_value", "fee", "fee_rate", "exec_pnl"] as const;
const DECIMAL = /^-?[0-9]+(\.[0-9]+)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const EXEC_TYPES = ["Trade", "AdlTrade", "Funding", "BustTrade", "Settle"];

function executionProblems(item: Record<string, unknown>): string[] {
  const problems: string[] = [];
  for (const key of Object.keys(item))
    if (!(EXECUTION_KEYS as readonly string[]).includes(key)) problems.push(`unknown ${key}`);
  for (const key of EXECUTION_REQUIRED) if (!(key in item)) problems.push(`missing ${key}`);
  for (const key of DECIMALS)
    if (key in item && !DECIMAL.test(String(item[key]))) problems.push(`${key} not a Decimal`);
  for (const key of ["id", "exchange_account_id", "order_id"])
    if (key in item && !UUID.test(String(item[key]))) problems.push(`${key} not a uuid`);
  if (!["buy", "sell"].includes(String(item["side"]))) problems.push("side");
  if ("exec_type" in item && !EXEC_TYPES.includes(String(item["exec_type"])))
    problems.push("exec_type");
  if (!RFC3339.test(String(item["ts"]))) problems.push("ts");
  return problems;
}

describe("WS frames validate against 23 §15.3 (fixtures from the shipped mappers)", () => {
  it("the executions snapshot and its delta", () => {
    expect(validatePayload("executions", fillsGolden("ws_executions_snapshot.json"))).toEqual([]);
    for (const { body } of fillsGolden<{ body: unknown }[]>("ws_executions_deltas.json"))
      expect(validatePayload("executions", body)).toEqual([]);
  });

  it("the harness is not vacuous: a number qty, an unknown member and no order_id are refused", () => {
    const [first] = fillsGolden<generated.ws.Executions>("ws_executions_snapshot.json").executions;
    if (first === undefined) throw new Error("golden");
    const noOrder: Partial<typeof first> = { ...first };
    delete noOrder.order_id;
    expect(
      validatePayload("executions", { executions: [{ ...first, exec_qty: 0.5 }] }).join(),
    ).toMatch(/must be string/);
    expect(
      validatePayload("executions", { executions: [{ ...first, order_price: "1" }] }).join(),
    ).toMatch(/additional properties/);
    expect(validatePayload("executions", { executions: [noOrder] }).join()).toMatch(
      /required property 'order_id'/,
    );
  });
});

describe("the client's sub frame validates (23 §13.5)", () => {
  it("executions names the accounts and asks no throttle", async () => {
    const ws = fakeClient();
    const accounts = golden<{ items: Schemas["ExchangeAccount"][] }>(
      "rest_list_exchange_accounts.json",
    ).items;
    // an event waiter, not a count of turns: it resolves when the feed subscribes
    let subscribed: () => void = () => undefined;
    const consumed = new Promise<void>((resolve) => {
      subscribed = resolve;
    });
    const feed = startFillsFeed({
      client: {
        ...ws.client,
        consume: (spec, rs) => {
          const handle = ws.client.consume(spec, rs);
          subscribed();
          return handle;
        },
      },
      store: createFillsStore(),
      api: {
        listExecutions: async () => ({
          kind: "ok",
          value: { items: [], nextCursor: null, hasMore: false },
        }),
        getOrder: async () => ({ kind: "unavailable" }),
        getTradeGroup: async () => ({ kind: "unavailable" }),
        getInstrument: async () => ({ kind: "unavailable" }),
      },
      accounts: { listExchangeAccounts: async () => ({ kind: "ok", items: accounts }) },
      performance: null,
      raf: () => 0,
      caf: () => undefined,
    });
    await consumed;
    feed.stop();
    const [handle] = ws.handles;
    expect(handle?.ch).toBe("executions");
    const opts = handle?.spec.opts ?? {};
    expect(
      validateClientFrame(sub("c-1", { topics: [{ ch: "executions", opts }], snapshot: true })),
    ).toEqual([]);
    expect(Object.keys(opts)).toEqual(["exchange_account_ids"]); // no throttle_ms: never throttled
    expect((opts as { exchange_account_ids: string[] }).exchange_account_ids).toHaveLength(3);
  });
});

describe("REST bodies fit the generated listExecutions 200 and getOrder 200", () => {
  it("the key lists are the generated types' (compile time, both ways)", () => {
    expectTypeOf<
      Exclude<keyof Execution, (typeof EXECUTION_KEYS)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<RequiredKeys<Execution>, (typeof EXECUTION_REQUIRED)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<RequiredKeys<Order>, (typeof ORDER_REQUIRED)[number]>
    >().toEqualTypeOf<never>();
  });

  it("listExecutions: a page of Execution items, newest first", () => {
    const body = fillsGolden<ListExecutions200>("rest_list_executions.json");
    expect(body.meta).toEqual({ next_cursor: null, has_more: false, count: body.items?.length });
    const items = (body.items ?? []) as unknown as Record<string, unknown>[];
    for (const item of items) expect(executionProblems(item)).toEqual([]);
    const ts = items.map((i) => String(i["ts"]));
    expect(ts).toEqual([...ts].sort().reverse());
  });

  it.each(["limit", "stop_exit", "amended", "at_limit", "market"] as const)(
    "getOrder %s: an OrderWithEvents, its fills oldest first, its events kinds of OrderEventKind",
    (name) => {
      const body = order(name) as unknown as Record<string, unknown>;
      for (const key of ORDER_REQUIRED) expect(body).toHaveProperty(key);
      const fills = body["executions"] as Record<string, unknown>[];
      for (const fill of fills) expect(executionProblems(fill)).toEqual([]);
      const ts = fills.map((f) => String(f["ts"]));
      expect(ts).toEqual([...ts].sort());
      const kinds: readonly Schemas["OrderEventKind"][] = (order(name).events ?? []).map(
        (e) => e.kind ?? "error",
      );
      expect(kinds.every((k) => typeof k === "string")).toBe(true);
      expect(kinds.at(-1)).toBe("fill");
    },
  );
});
