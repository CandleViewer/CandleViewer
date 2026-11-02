/**
 * E29-S04 (#979) one fill row from either wire form (`fillRow.ts`): the goldens the shipped
 * mappers wrote, so the WS and REST copies of one fill read the same (time, decimals), the members
 * the wire may leave out read as missing with a reason, the fee is its cash effect (BQ-11), and a
 * malformed item is dropped.
 */
import { describe, expect, it } from "vitest";
import {
  fillTime,
  headStub,
  liquidityOf,
  mapFill,
  mergeFill,
  newestFirst,
  sideShown,
  tailStub,
  type FillRowModel,
} from "../../../../src/features/positions/fills/model/fillRow";
import { MAIN, SUB2 } from "../support/fakes";
import { ORDER_A3F2, restItems, rowsOf, snapshotBody } from "./support/fills";

const ws = rowsOf(snapshotBody().executions, "ws");
const rest = rowsOf(restItems(), "rest");
const byExec = (rows: FillRowModel[], tail: string): FillRowModel => {
  const row = rows.find((r) => r.execId.endsWith(tail));
  if (row === undefined) throw new Error(tail);
  return row;
};
const wsItem = snapshotBody().executions[3];
if (wsItem === undefined) throw new Error("golden");

describe("Per-fill detail: each fill row shows time, price, quantity, fee with its currency, maker/taker flag, order id and exec id", () => {
  it("board 02's first fill, as the WS item carries it", () => {
    const row = byExec(ws, "0004");
    expect(new Date(row.tsMs).toISOString()).toBe("2026-10-22T14:02:11.418Z");
    expect([row.price, row.qty, row.feeCash, row.feeCoin]).toEqual([
      "63410",
      "0.1",
      "-3.48755",
      "USDT",
    ]);
    expect(liquidityOf(row)).toBe("taker");
    expect([tailStub(row.orderId ?? ""), headStub(row.execId)]).toEqual(["…a3f2", "7f3c9a1e…"]);
    expect(row.execId).toBe("7f3c9a1e-4219-438b-b30a-32ec86300004");
    expect(row.orderId).toBe(ORDER_A3F2);
  });
});

describe("one fill, either wire form", () => {
  it("the WS and REST copies of every fill read the same time, decimals and members", () => {
    for (const w of ws) {
      const r = rest.find((x) => x.key === w.key);
      expect(r).toBeDefined();
      // every member but the source and the two only one wire form carries
      const strip = (row: FillRowModel): Record<string, unknown> =>
        Object.fromEntries(
          Object.entries(row).filter(
            ([k]) => !["source", "tradeGroupId", "environment"].includes(k),
          ),
        );
      expect(strip(w)).toEqual(strip(r as FillRowModel));
    }
  });

  it("REST's microseconds are cut to the millisecond, as the server's epoch_ms floors them", () => {
    expect(fillTime({ ts: "2026-10-22T14:02:11.418999Z" })).toBe(
      fillTime({ ts_ms: 1792677731418 }),
    );
    expect(fillTime({ ts: "2026-10-22T14:02:11Z" })).toBe(1792677731000);
    expect(fillTime({ ts: "2026-10-22T16:02:11.4+02:00" })).toBe(1792677731400);
    for (const bad of [{ ts: "yesterday" }, { ts_ms: -1 }, { ts_ms: 1.5 }, {}])
      expect(fillTime(bad)).toBeNull();
  });

  it("WS carries no trade group (unknown), REST says none or names it; REST no environment", () => {
    expect(byExec(ws, "0010").tradeGroupId).toBeUndefined();
    expect(byExec(rest, "0010").tradeGroupId).toBe("0c000000-0000-4000-8000-000000007c1e");
    expect(byExec(rest, "0004").tradeGroupId).toBeNull();
    expect([byExec(ws, "0004").environment, byExec(rest, "0004").environment]).toEqual([
      "live",
      undefined,
    ]);
  });
});

describe("what the wire may leave out reads as missing (D03 D-9, BQ-11)", () => {
  const partial: Partial<typeof wsItem> = { ...wsItem };
  delete partial.fee;
  delete partial.is_maker;
  delete partial.exec_type;
  const bare = partial as typeof wsItem;

  it("no fee, no coin, no liquidity flag and no type are missing, never 0, USDT, Taker or Trade", () => {
    const row = mapFill({ ...bare, fee_coin: "" }, "ws");
    expect(row).toMatchObject({ fee: null, feeCash: null, feeCoin: null, maker: null });
    expect(row?.type).toEqual({ kind: "missing" });
    expect(row === null ? null : liquidityOf(row)).toBe("not_a_trade");
    const trade = mapFill({ ...bare, exec_type: "Trade" }, "ws");
    expect(trade === null ? null : liquidityOf(trade)).toBe("not_reported");
  });

  it("REST's fill of no order has no order id (the ADL fill); WS never sends one", () => {
    const adl = byExec(rest, "0014");
    expect(adl).toMatchObject({ orderId: null, accountId: SUB2, type: { kind: "adl" } });
    expect(ws.some((r) => r.orderId === null)).toBe(false);
  });

  it("the fee is its cash effect: paid when positive, received when negative (a rebate)", () => {
    expect(mapFill({ ...wsItem, fee: "0.38052" }, "ws")?.feeCash).toBe("-0.38052");
    expect(mapFill({ ...wsItem, fee: "-0.12" }, "ws")?.feeCash).toBe("0.12");
    expect(mapFill({ ...wsItem, fee: "0" }, "ws")?.feeCash).toBe("0");
  });

  it.each([
    ["AdlTrade", { kind: "adl" }],
    ["BustTrade", { kind: "liquidation" }],
    ["Funding", { kind: "funding" }],
    ["Settle", { kind: "settlement" }],
    ["SessionSettlePnl", { kind: "other", name: "SessionSettlePnl" }],
  ])("exec_type %s is %j", (execType, type) => {
    const row = mapFill({ ...wsItem, exec_type: execType } as typeof wsItem, "ws");
    expect(row?.type).toEqual(type);
    expect(row?.execType).toBe(execType);
  });

  it("funding and settlement show no side or liquidity (D03 §3.3)", () => {
    const funding = mapFill({ ...wsItem, exec_type: "Funding" }, "ws") as FillRowModel;
    expect([sideShown(funding), liquidityOf(funding)]).toEqual([null, "not_a_trade"]);
    expect(sideShown(byExec(ws, "0004"))).toBe("buy");
  });
});

describe("a malformed item is dropped, never guessed", () => {
  it.each([
    { exec_id: "" },
    { exchange_account_id: "Main" },
    { id: "x" },
    { symbol: "BTCUSD" },
    { side: "long" },
    { exec_price: 63410 },
    { exec_qty: "1e2" },
    { ts_ms: "now" },
  ])("%j", (patch) => {
    expect(mapFill({ ...wsItem, ...patch } as unknown as typeof wsItem, "ws")).toBeNull();
  });
});

describe("mergeFill and the order", () => {
  it("the first copy wins; a member only the second carries is added", () => {
    const w = byExec(ws, "0010");
    const r = byExec(rest, "0010");
    expect(mergeFill(w, r)).toEqual({ ...w, tradeGroupId: r.tradeGroupId });
    expect(mergeFill(r, w)).toEqual({ ...r, environment: "live" });
    const both = mergeFill(w, r);
    expect(mergeFill(both, r)).toBe(both);
  });

  it("newest first by time, then id: board 02's two fills of one millisecond", () => {
    const [a, b] = [byExec(ws, "0004"), byExec(ws, "0005")];
    expect(a.tsMs).toBe(b.tsMs);
    expect([a, b].sort(newestFirst).map((r) => r.execId.slice(-4))).toEqual(["0005", "0004"]);
    expect(newestFirst(a, a)).toBe(0);
  });

  it("a stub of a short id is the id", () => {
    expect(headStub("abc")).toBe("abc");
    expect(MAIN).toBe(byExec(ws, "0004").accountId);
  });
});
