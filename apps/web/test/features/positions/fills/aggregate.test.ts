/**
 * E29-S04 (#979) the aggregate (`aggregate.ts`) on the goldens the shipped mappers wrote, against
 * E29-D03 §3.4's arithmetic: the average Σp·q ÷ Σq, the split by quantity, fees per coin from the
 * raw sums, slippage better (a buy below its limit), worse (a sell below its trigger), none (a
 * market order), amended and at the limit; and seeded properties (order-free sums, a split summing
 * to 100, an average between the prices).
 */
import { describe, expect, it } from "vitest";
import {
  addFill,
  averageOf,
  feesOf,
  figure,
  intentOf,
  MINUS,
  NO_FILLS,
  pricePlaces,
  slippageOf,
  splitOf,
  sumFills,
  type FillSums,
} from "../../../../src/features/positions/fills/model/aggregate";
import { mapFill, type FillRowModel } from "../../../../src/features/positions/fills/model/fillRow";
import { cmp, dec, toPlain } from "../../../../src/features/positions/model/decimal";
import { SUB1, SUB2 } from "../support/fakes";
import { GROUP_7C1E, order, orderRows, restItems, rowsOf, TICK } from "./support/fills";

const PLACES = pricePlaces(TICK) ?? 0;
const avg = (s: FillSums): string | null => {
  const a = averageOf(s, PLACES);
  return a === null ? null : figure(a);
};
const fees = (s: FillSums): string[] =>
  feesOf(s).map((f) => `${figure(f.cash, 2, true)} ${f.coin} ${f.direction ?? ""}`.trim());
function slip(s: FillSums, side: "buy" | "sell", terms: Parameters<typeof intentOf>[0]) {
  const out = slippageOf(s, side, intentOf(terms), TICK);
  if (out === null) return null;
  return [
    figure(out.price, PLACES, true),
    figure(out.ticks),
    figure(out.cash, 2),
    out.direction,
  ].join(" ");
}

describe("Aggregate and slippage: an order filled in 4 executions against an intended limit price", () => {
  const rows = orderRows("limit");
  const sums = sumFills(rows);

  it("board 02's order fills in four executions", () => {
    expect(rows).toHaveLength(4);
    expect(order("limit")).toMatchObject({ order_type: "limit", side: "buy", price: "63420.0" });
  });

  it("the average fill price is Σp·q ÷ Σq, weighted by quantity: 63,414.02", () => {
    expect(toPlain(sums.value)).toBe("15853.505");
    expect(avg(sums)).toBe("63,414.02");
  });

  it("the maker/taker split is by quantity, whole percent summing to 100: 24 % maker", () => {
    expect(splitOf(sums)).toEqual({ maker: "24", taker: "76" });
  });

  it("fees per coin from the raw sums, the cash effect with U+2212: −7.39 USDT paid", () => {
    expect(fees(sums)).toEqual([`${MINUS}7.39 USDT paid`]);
    expect(toPlain(sums.fees.get("USDT") ?? dec("0"))).toBe("7.38760775");
  });

  it("slippage versus the intended limit: −5.98 (59.8 ticks), 1.50 USDT better", () => {
    expect(slip(sums, "buy", order("limit"))).toBe(`${MINUS}5.98 59.8 1.50 better`);
  });
});

describe("slippage's other forms (D-7; D03 §3.4 board 05)", () => {
  it("a sell's stop exit is worse below its trigger: +20.00 (200 ticks), 5.00 USDT", () => {
    const exit = order("stop_exit");
    expect(exit).toMatchObject({ order_type: "market", side: "sell", trigger_price: "63900.0" });
    expect(intentOf(exit)).toMatchObject({ kind: "trigger", amended: false });
    expect(slip(sumFills(orderRows("stop_exit")), "sell", exit)).toBe("+20.00 200 5.00 worse");
  });

  it("a market order has no intended price: no slippage, never a zero", () => {
    expect(intentOf(order("market"))).toBeNull();
    expect(slippageOf(sumFills(orderRows("market")), "sell", null, TICK)).toBeNull();
  });

  it("an amended order is measured against its current limit, and says so", () => {
    const amended = order("amended");
    expect(intentOf(amended)).toMatchObject({ kind: "limit", amended: true });
    expect(slip(sumFills(orderRows("amended")), "buy", amended)).toBe(`${MINUS}0.40 4 0.04 better`);
  });

  it("filled at the limit is 0.00, at", () => {
    expect(slip(sumFills(orderRows("at_limit")), "buy", order("at_limit"))).toBe("0.00 0 0.00 at");
  });

  it("a triggered limit order's intent is its limit; a trigger only without one (BQ-8)", () => {
    const both = { order_type: "limit", price: "63420.0", trigger_price: "63500.0" };
    expect(toPlain(intentOf(both)?.price ?? dec("0"))).toBe("63420.0");
    expect(intentOf({ order_type: "market", price: "94942.5" })).toBeNull();
  });

  it("no tick (getInstrument failed) or no trade reads none", () => {
    expect(
      slippageOf(sumFills(orderRows("limit")), "buy", intentOf(order("limit")), null),
    ).toBeNull();
    expect(slippageOf(NO_FILLS, "buy", intentOf(order("limit")), TICK)).toBeNull();
    expect(pricePlaces("0.10")).toBe(2);
    expect(pricePlaces("0")).toBeNull();
  });
});

describe("totals round the raw sums, never the rounded cells (D03:153)", () => {
  it("board 05's position: 3.2125 + 5.2705125 + 3.5129875 is 12.00, not the cells' 11.99", () => {
    const rows = [...orderRows("at_limit"), ...orderRows("stop_exit")];
    const cells = rows.map((r) => figure(dec(r.feeCash ?? "0"), 2));
    expect(cells).toEqual([`${MINUS}3.21`, `${MINUS}5.27`, `${MINUS}3.51`]);
    expect(fees(sumFills(rows))).toEqual([`${MINUS}12.00 USDT paid`]);
    expect(splitOf(sumFills(rows))).toEqual({ maker: "50", taker: "50" });
  });
});

describe("board 04's fan-out: the Owner's total, a Manager's legs (D-8)", () => {
  const legs = rowsOf(restItems(), "rest").filter((r) => r.tradeGroupId === GROUP_7C1E);
  const group = { order_type: "limit", price: "63500.0" };

  it("the Owner's four fills: 63,497.83 · 33 % maker · −16.51 USDT · −2.17 (21.7 ticks) 1.30", () => {
    const sums = sumFills(legs);
    expect([sums.trades, avg(sums), splitOf(sums)?.maker]).toEqual([4, "63,497.83", "33"]);
    expect(fees(sums)).toEqual([`${MINUS}16.51 USDT paid`]);
    expect(slip(sums, "buy", group)).toBe(`${MINUS}2.17 21.7 1.30 better`);
  });

  it("a Manager of Sub-1 and Sub-2: 63,499.00 · 33 % · −8.25 USDT · −1.00 (10 ticks) 0.30", () => {
    const sums = sumFills(legs.filter((r) => r.accountId === SUB1 || r.accountId === SUB2));
    expect([sums.trades, avg(sums), splitOf(sums)?.maker]).toEqual([2, "63,499.00", "33"]);
    expect(fees(sums)).toEqual([`${MINUS}8.25 USDT paid`]);
    expect(slip(sums, "buy", group)).toBe(`${MINUS}1.00 10 0.30 better`);
  });
});

describe("fees and the split never guess (D-9)", () => {
  const [first] = orderRows("limit");
  if (first === undefined) throw new Error("golden");

  it("a fee received reads received; a pending fee or coin adds nothing and is counted", () => {
    const rebate = { ...first, fee: "-0.84", feeCash: "0.84" };
    expect(fees(addFill(NO_FILLS, rebate))).toEqual(["+0.84 USDT received"]);
    const pending = addFill(addFill(NO_FILLS, { ...first, fee: null }), {
      ...first,
      feeCoin: null,
    });
    expect([pending.feesPending, feesOf(pending)]).toEqual([2, []]);
  });

  it("a trade with no liquidity flag makes the split unknown; funding is no trade", () => {
    expect(splitOf(addFill(NO_FILLS, { ...first, maker: null }))).toBeNull();
    const funding: FillRowModel = { ...first, type: { kind: "funding" } };
    const sums = addFill(NO_FILLS, funding);
    expect([sums.trades, sums.fills, splitOf(sums), averageOf(sums, 2)]).toEqual([
      0,
      1,
      null,
      null,
    ]);
  });
});

describe("figure", () => {
  it("groups, signs with U+2212 or a plus, and never signs zero", () => {
    expect(MINUS).toBe("\u2212"); // the character itself, not ASCII "-"
    expect(figure(dec("-7.39"))).toBe("\u22127.39");
    expect(figure(dec("-1234567.891"), 2)).toBe(`${MINUS}1,234,567.89`);
    expect(figure(dec("0.004"), 2, true)).toBe("0.00");
    expect(figure(dec("-0.004"), 2, true)).toBe("0.00");
    expect(figure(dec("20"), 2, true)).toBe("+20.00");
    expect(figure(dec("999")).includes("-")).toBe(false);
  });
});

function one<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("the golden is empty");
  return value;
}

/** mulberry32: a seeded, reproducible stream (C-13.7). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("properties (seeded)", () => {
  const item = one(restItems()[0]);
  const digits = (next: () => number, n: number): string =>
    Array.from({ length: n }, () => Math.floor(next() * 10)).join("");
  function fills(next: () => number): FillRowModel[] {
    return Array.from({ length: 1 + Math.floor(next() * 12) }, (_, i) => {
      const price = `${60000 + Math.floor(next() * 9000)}.${digits(next, 1)}`;
      const qty = `0.${digits(next, 2)}${1 + Math.floor(next() * 9)}`;
      const row = mapFill({ ...item, exec_id: `p${i}`, exec_price: price, exec_qty: qty }, "rest");
      if (row === null) throw new Error(price);
      return { ...row, maker: next() < 0.4, fee: digits(next, 1), key: `k${i}` };
    });
  }
  const view = (s: FillSums) => [avg(s), splitOf(s), fees(s), slip(s, "buy", order("limit"))];

  it.each([1, 7, 979, 20261102])(
    "seed %i: sums are order-free, the split sums to 100, the average lies between the prices",
    (seed) => {
      const next = rng(seed);
      for (let n = 0; n < 200; n += 1) {
        const rows = fills(next);
        const sums = sumFills(rows);
        expect(view(sumFills([...rows].reverse()))).toEqual(view(sums));
        const split = splitOf(sums);
        expect(BigInt(split?.maker ?? "0") + BigInt(split?.taker ?? "0")).toBe(100n);
        const prices = rows.map((r) => dec(r.price));
        const a = averageOf(sums, 8);
        if (a === null) throw new Error("no average");
        const lo = prices.reduce((x, y) => (cmp(x, y) <= 0 ? x : y));
        const hi = prices.reduce((x, y) => (cmp(x, y) >= 0 ? x : y));
        expect([cmp(a, lo) >= 0, cmp(a, hi) <= 0]).toEqual([true, true]);
        expect(averageOf(sumFills([...rows, ...rows]), 8)).toEqual(a); // weights, not counts
      }
    },
  );
});
