/**
 * Draft and context builders for the validation tests: one valid base (a BTCUSDT limit buy from
 * the recorded capture, tick 0.10, lot 0.001, max 100, min notional 5) and small overrides.
 */
import type {
  Instrument,
  OffsetUnit,
  OrderDraft,
  Position,
  PositionRead,
  Ticker,
  TicketContext,
} from "../src/index.js";
import { INSTRUMENTS } from "./fixtures.js";

export const BTC: Instrument = INSTRUMENTS[0] as Instrument;
export const ACCOUNT = "e30f0000-0000-4000-8000-000000000001";
export const TARGET = { kind: "account", accountId: ACCOUNT } as const;

export const TICKER: Ticker = {
  symbol: "BTCUSDT",
  last_price: "60000.0",
  bid1_price: "59990.0",
  ask1_price: "60010.0",
};

export function draft(over: Partial<OrderDraft> = {}): OrderDraft {
  return {
    exchangeAccountId: ACCOUNT,
    profileId: null,
    symbol: "BTCUSDT",
    side: "buy",
    orderType: "limit",
    intent: "entry",
    price: "60000.0",
    timeInForce: "GTC",
    reduceOnly: false,
    closeOnTrigger: false,
    sizing: { mode: "fixed_qty", qty: "0.010", round_to_lot: true },
    stopLoss: { unit: "ticks", value: "200", atr_period: 14 },
    takeProfit: null,
    tpslMode: null,
    trigger: null,
    note: null,
    ...over,
  };
}

export function ctx(over: Partial<TicketContext> = {}): TicketContext {
  return {
    env: "demo",
    target: TARGET,
    instrument: BTC,
    profile: null,
    wallet: null,
    ticker: TICKER,
    risk: null,
    position: { status: "known", position: null },
    feeRate: null,
    armed: false,
    ...over,
  };
}

/** A known position of `side` and `size` on BTCUSDT. */
export function held(side: Position["side"], size: string, symbol = "BTCUSDT"): PositionRead {
  return {
    status: "known",
    position: {
      id: "p1",
      exchange_account_id: ACCOUNT,
      symbol,
      side,
      size,
      is_paper: false,
    },
  };
}

/** A reduce-only sell closing (part of) a long: not an entry, so no stop and no TP. */
export function exitDraft(qty: string, over: Partial<OrderDraft> = {}): OrderDraft {
  return draft({
    side: "sell",
    reduceOnly: true,
    intent: "scale_out",
    stopLoss: null,
    sizing: { mode: "fixed_qty", qty, round_to_lot: true },
    price: "60020.0",
    ...over,
  });
}

/** An `Offset` with `22`'s default ATR period; a `fixed_qty` sizing; a market order. */
export const off = (unit: OffsetUnit, value: string) => ({ unit, value, atr_period: 14 });
export const qty = (q: string): Partial<OrderDraft> => ({
  sizing: { mode: "fixed_qty", qty: q, round_to_lot: true },
});
export const MARKET: Partial<OrderDraft> = { orderType: "market", price: null };
