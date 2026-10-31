/**
 * E29-S01 (#911) consumer contract (C-6.2, the ticket's test plan): the frames the shipped mappers
 * wrote validate against `cv://ws/v1/positions.schema.json` (and `wallet`, `system`, `machines`)
 * through the WS schema harness; the client's `sub` frame validates; the REST bodies fit the
 * generated `listPositions` 200 (plain and `?aggregate=true`) and `listExchangeAccounts` 200; and
 * the client's grouping by symbol gives the server's `AggregatePosition` figures (BQ-12).
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { sameAmount } from "../../src/features/positions/model/decimal";
import { groupRows } from "../../src/features/positions/model/grouping";
import {
  accountInfo,
  mapRow,
  type AccountInfo,
  type PositionRowModel,
} from "../../src/features/positions/model/rowMapping";
import { createPositionsStore } from "../../src/features/positions/positionsStore";
import { lockoutChannel, startPositionsFeed } from "../../src/features/positions/wsPositions";
import { sub } from "../../src/lib/ws/protocol/frames";
import { fakeClient, golden, SUB1, SUB2 } from "../features/positions/support/fakes";
import { repoFile, validateClientFrame, validatePayload } from "../lib/ws/support/schemaHarness";

type Schemas = generated.rest.components["schemas"];
type Position = Schemas["Position"];
type AggregatePosition = Schemas["AggregatePosition"];
type ExchangeAccount = Schemas["ExchangeAccount"];
type ListPositions200 =
  generated.rest.operations["listPositions"]["responses"][200]["content"]["application/json"];
type ListAccounts200 =
  generated.rest.operations["listExchangeAccounts"]["responses"][200]["content"]["application/json"];
type RequiredKeys<T> = { [K in keyof T]-?: object extends Pick<T, K> ? never : K }[keyof T];

/** The generated `Position`'s members, held to the type both ways at compile time. */
const POSITION_KEYS = [
  "is_paper",
  "id",
  "exchange_account_id",
  "symbol",
  "side",
  "position_idx",
  "size",
  "avg_price",
  "mark_price",
  "position_value",
  "leverage",
  "margin_mode",
  "unrealised_pnl",
  "realised_pnl_session",
  "liq_price",
  "bust_price",
  "take_profit",
  "stop_loss",
  "trailing_stop",
  "tpsl_mode",
  "native_stop_present",
  "trade_group_id",
  "r_multiple",
  "updated_at",
] as const satisfies readonly (keyof Position)[];
/** The generated type's required members: `is_paper` too, which has a default (openapi-typescript). */
const POSITION_REQUIRED = [
  "is_paper",
  "id",
  "exchange_account_id",
  "symbol",
  "side",
  "size",
] as const satisfies readonly RequiredKeys<Position>[];
const AGGREGATE_KEYS = [
  "symbol",
  "net_size",
  "gross_size",
  "weighted_avg_price",
  "unrealised_pnl",
  "accounts",
] as const satisfies readonly (keyof AggregatePosition)[];
const LEG_KEYS = [
  "exchange_account_id",
  "size",
  "side",
  "unrealised_pnl",
] as const satisfies readonly (keyof NonNullable<AggregatePosition["accounts"]>[number])[];
const DECIMALS = [
  "size",
  "avg_price",
  "mark_price",
  "position_value",
  "leverage",
  "unrealised_pnl",
  "realised_pnl_session",
  "liq_price",
  "bust_price",
  "take_profit",
  "stop_loss",
  "trailing_stop",
  "r_multiple",
] as const satisfies readonly (keyof Position)[];

const DECIMAL = /^-?[0-9]+(\.[0-9]+)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const isDecimalOrNull = (v: unknown): boolean =>
  v === null || (typeof v === "string" && DECIMAL.test(v));

/** Each item of a REST position list against the generated `Position`. */
function positionProblems(item: Record<string, unknown>): string[] {
  const problems: string[] = [];
  for (const key of Object.keys(item))
    if (!(POSITION_KEYS as readonly string[]).includes(key)) problems.push(`unknown ${key}`);
  for (const key of POSITION_REQUIRED) if (!(key in item)) problems.push(`missing ${key}`);
  for (const key of DECIMALS)
    if (key in item && !isDecimalOrNull(item[key])) problems.push(`${key} not a Decimal`);
  if (!["long", "short", "flat"].includes(item["side"] as string)) problems.push("side");
  if (!UUID.test(String(item["id"])) || !UUID.test(String(item["exchange_account_id"])))
    problems.push("uuid");
  if ("position_idx" in item && ![0, 1, 2].includes(item["position_idx"] as number))
    problems.push("position_idx");
  if ("updated_at" in item && Number.isNaN(Date.parse(String(item["updated_at"]))))
    problems.push("updated_at");
  return problems;
}

describe("WS frames validate against the 23 §15 schemas (fixtures from the shipped mappers)", () => {
  it("the positions snapshot, each delta, and the contract-valid frames", () => {
    expect(validatePayload("positions", golden("ws_positions_snapshot.json"))).toEqual([]);
    for (const { body } of golden<{ body: unknown }[]>("ws_positions_deltas.json")) {
      expect(validatePayload("positions", body)).toEqual([]);
    }
    expect(validatePayload("positions", golden("ws_positions_contract_fields.json"))).toEqual([]);
  });

  it("the harness is not vacuous: a number size or an unknown member is refused", () => {
    const snapshot = golden<generated.ws.Positions>("ws_positions_snapshot.json");
    const [first] = snapshot.positions;
    expect(validatePayload("positions", { positions: [{ ...first, size: 0.25 }] }).join()).toMatch(
      /must be string/,
    );
    expect(validatePayload("positions", { positions: [{ ...first, adl_rank: 2 }] }).join()).toMatch(
      /additional properties/,
    );
  });

  it("the wallet snapshot, the resyncing notice, E29-T06's notices and a B20 machine state", () => {
    expect(validatePayload("wallet", golden("ws_wallet_snapshot.json"))).toEqual([]);
    expect(validatePayload("system", golden("ws_system_account_notice.json"))).toEqual([]);
    for (const reason of ["oms.account_desync", "oms.account_stale", "oms.account_synced"]) {
      const frame = {
        kind: "account_notice",
        severity: "warning",
        reason,
        message: "role-neutral",
        exchange_account_ids: [SUB1],
      };
      expect(validatePayload("system", frame)).toEqual([]);
    }
    const lock = JSON.parse(
      repoFile("services/api/candleviewer/statechart/machines/machine_hashes.lock"),
    ) as {
      machines: Record<string, { hash: string }>;
    };
    const hash = lock.machines["risk_lockout"]?.hash ?? ""; // B20's chart hash
    const machine = {
      machine_kind: "risk_lockout",
      state: "locked",
      tags: ["trading_blocked"],
      degraded: false,
      machine_hash: hash,
      environment: "live",
      updated_at_ms: 1_793_455_331_000,
    };
    expect(validatePayload("machines", machine)).toEqual([]);
  });
});

describe("the client's sub frame validates (23 §13.5)", () => {
  it("positions and wallet name the accounts; B20 takes universal options only", async () => {
    const ws = fakeClient();
    const accounts = golden<ListAccounts200>("rest_list_exchange_accounts.json").items ?? [];
    const feed = startPositionsFeed({
      client: ws.client,
      store: createPositionsStore(),
      api: {
        listPositions: async () => ({ kind: "ok", items: [], aggregates: [] }),
        listExchangeAccounts: async () => ({ kind: "ok", items: accounts }),
      },
      performance: null,
      raf: () => 0,
      caf: () => undefined,
    });
    await Promise.resolve();
    await Promise.resolve();
    feed.stop();
    const topics = ws.handles.map((h) =>
      h.spec.opts === undefined ? { ch: h.ch } : { ch: h.ch, opts: h.spec.opts },
    );
    expect(topics.map((t) => t.ch)).toEqual(
      expect.arrayContaining(["positions", "wallet", lockoutChannel(SUB2)]),
    );
    const [first, ...rest] = topics;
    expect(first).toBeDefined();
    expect(
      validateClientFrame(
        sub("c-1", { topics: [first as (typeof topics)[number], ...rest], snapshot: true }),
      ),
    ).toEqual([]);
    const ids = (topics[0]?.opts as { exchange_account_ids: string[] }).exchange_account_ids;
    expect(ids.length).toBeGreaterThan(0); // never empty: an empty list is `invalid_options` (23 §6.2)
  });
});

describe("REST bodies fit the generated listPositions 200 and listExchangeAccounts 200", () => {
  it("the key lists are the generated types' (compile time, both ways)", () => {
    expectTypeOf<Exclude<keyof Position, (typeof POSITION_KEYS)[number]>>().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<RequiredKeys<Position>, (typeof POSITION_REQUIRED)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof AggregatePosition, (typeof AGGREGATE_KEYS)[number]>
    >().toEqualTypeOf<never>();
    expectTypeOf<keyof ListPositions200>().toEqualTypeOf<"items" | "aggregates">();
  });

  it.each(["rest_list_positions.json", "rest_list_positions_aggregate.json"])("%s", (name) => {
    const body = golden<Record<string, unknown>>(name);
    expect(Object.keys(body).sort()).toEqual(["aggregates", "items"]);
    for (const item of body["items"] as Record<string, unknown>[])
      expect(positionProblems(item)).toEqual([]);
    for (const aggregate of body["aggregates"] as Record<string, unknown>[]) {
      expect(
        Object.keys(aggregate).every((k) => (AGGREGATE_KEYS as readonly string[]).includes(k)),
      ).toBe(true);
      for (const key of ["net_size", "gross_size", "weighted_avg_price", "unrealised_pnl"]) {
        if (key in aggregate) expect(aggregate[key]).toMatch(DECIMAL);
      }
      for (const leg of aggregate["accounts"] as Record<string, unknown>[]) {
        expect(Object.keys(leg).every((k) => (LEG_KEYS as readonly string[]).includes(k))).toBe(
          true,
        );
        expect(["long", "short"]).toContain(leg["side"]);
      }
    }
  });

  it("listExchangeAccounts: a page of ExchangeAccount items", () => {
    const body = golden<ListAccounts200>("rest_list_exchange_accounts.json");
    expect(body.meta).toEqual({ next_cursor: null, has_more: false, count: 3 });
    for (const account of body.items ?? []) {
      const typed: ExchangeAccount = account;
      expect(["live", "demo", "testnet"]).toContain(typed.environment);
      expect(["one_way", "hedge"]).toContain(typed.position_mode);
      expect(["cross", "isolated", "portfolio"]).toContain(typed.margin_mode);
    }
  });

  it("BQ-12: the client's group by symbol gives ?aggregate=true's net size and uPnL", () => {
    const body = golden<ListPositions200>("rest_list_positions_aggregate.json");
    const directory = new Map(
      golden<ListAccounts200>("rest_list_exchange_accounts.json")
        .items?.map(accountInfo)
        .filter((a): a is AccountInfo => a !== null)
        .map((a) => [a.id, a]),
    );
    const rows = (body.items ?? [])
      .map((item) => mapRow(item, "rest", directory))
      .filter((r): r is PositionRowModel => r !== null);
    const groups = groupRows(rows, "symbol", () => null);
    const aggregates = body.aggregates ?? [];
    expect(groups.map((g) => g.key)).toEqual(aggregates.map((a) => a.symbol));
    for (const [i, group] of groups.entries()) {
      const aggregate = aggregates[i];
      expect(sameAmount(group.netSize, aggregate?.net_size)).toBe(true);
      expect(sameAmount(group.unrealisedPnl, aggregate?.unrealised_pnl)).toBe(true);
      expect(group.rows.map((r) => r.accountId)).toEqual(
        aggregate?.accounts?.map((a) => a.exchange_account_id),
      );
    }
  });
});
