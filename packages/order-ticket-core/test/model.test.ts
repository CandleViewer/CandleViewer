import { describe, expect, expectTypeOf, it } from "vitest";
import {
  OFFSET_UNITS,
  SIZING_MODES,
  targetAccountIds,
  type BookTop,
  type OffsetUnit,
  type OrderDraft,
  type SizingMode,
  type TicketContext,
} from "../src/index.js";
import { INSTRUMENTS } from "./fixtures.js";

describe("model", () => {
  it("SIZING_MODES_coversTheGeneratedUnion", () => {
    expectTypeOf<(typeof SIZING_MODES)[number]>().toEqualTypeOf<SizingMode>();
    expect(SIZING_MODES).toContain("pct_position");
    expect(new Set(SIZING_MODES).size).toBe(SIZING_MODES.length);
  });

  it("OFFSET_UNITS_coversTheGeneratedUnion", () => {
    expectTypeOf<(typeof OFFSET_UNITS)[number]>().toEqualTypeOf<OffsetUnit>();
    expect(OFFSET_UNITS).toContain("price");
    expect(new Set(OFFSET_UNITS).size).toBe(OFFSET_UNITS.length);
  });

  it("draftAndContext_surviveStructuredClone", () => {
    const draft: OrderDraft = {
      exchangeAccountId: "e30f0000-0000-4000-8000-000000000001",
      profileId: null,
      symbol: "BTCUSDT",
      side: "buy",
      orderType: "limit",
      intent: "entry",
      price: "64000.0",
      timeInForce: "GTC",
      reduceOnly: false,
      closeOnTrigger: false,
      sizing: { mode: "risk_based", risk_per_trade_usd: "40", round_to_lot: true },
      stopLoss: { unit: "ticks", value: "1200", atr_period: 14 },
      takeProfit: null,
      tpslMode: null,
      trigger: null,
      note: null,
    };
    const ctx: TicketContext = {
      env: "demo",
      target: { kind: "account", accountId: "e30f0000-0000-4000-8000-000000000001" },
      instrument: INSTRUMENTS[0] ?? { category: "linear", symbol: "", tick_size: "", qty_step: "" },
      profile: null,
      wallet: { is_paper: false, equity: "10000" },
      ticker: { last_price: "64000.0", bid1_price: "63999.9", ask1_price: "64000.0" },
      risk: null,
      position: { status: "unknown" },
      feeRate: { symbol: "BTCUSDT", taker_fee_rate: "0.00055" },
      armed: false,
    };
    expect(structuredClone({ draft, ctx })).toEqual({ draft, ctx });
    const top: BookTop = ctx.ticker ?? {};
    expect([top.bid1_price, top.ask1_price]).toEqual(["63999.9", "64000.0"]);
  });

  it("targetAccountIds_namesEveryTargetedAccount", () => {
    expect(targetAccountIds({ kind: "account", accountId: "a" })).toEqual(["a"]);
    expect(targetAccountIds({ kind: "group", accountIds: ["a", "b"] })).toEqual(["a", "b"]);
  });
});
