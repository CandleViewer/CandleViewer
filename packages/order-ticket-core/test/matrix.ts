/**
 * The validation matrix (#984 test plan: "every rule × pass/fail") as data, so S2b's message
 * tests run the same rows. One row per line: the table reads as a grid.
 */
import {
  type FieldPath,
  type Instrument,
  type OffsetUnit,
  type OrderDraft,
  type RuleId,
  type TicketContext,
} from "../src/index.js";
import { CLOSED_LUNA } from "./fixtures.js";
import { ACCOUNT, BTC, MARKET, ctx, draft, exitDraft, held, off, qty } from "./drafts.js";

type Ctx = Partial<TicketContext>;
type Params = Readonly<Record<string, string>>;
export interface Row {
  readonly rule: RuleId;
  readonly name: string;
  readonly draft: OrderDraft;
  readonly ctx: TicketContext;
  /** `pass`: the rule is absent. Else the field it fails at and (a subset of) its params. */
  readonly expect: "pass" | { readonly field: FieldPath; readonly params: Params };
}

const ok = (rule: RuleId, name: string, d: OrderDraft, c: Ctx = {}): Row => ({
  rule,
  name,
  draft: d,
  ctx: ctx(c),
  expect: "pass",
});
// prettier-ignore
const no = (rule: RuleId, name: string, d: OrderDraft, field: FieldPath, params: Params | null = null, c: Ctx = {}): Row =>
  ({ rule, name, draft: d, ctx: ctx(c), expect: { field, params: params ?? {} } });

const D = draft;
const X = exitDraft;
const mode = (sizing: Omit<OrderDraft["sizing"], "round_to_lot">): Partial<OrderDraft> => ({
  sizing: { ...sizing, round_to_lot: true },
});
const inst = (over: Partial<Instrument>): Ctx => ({ instrument: { ...BTC, ...over } });
/** The BTC row without the named optional filters (absent, not `null`: S1 keeps them unknown). */
const without = (...names: readonly ("min_order_qty" | "min_notional_value")[]): Ctx => ({
  instrument: Object.fromEntries(
    Object.entries(BTC).filter(([key]) => !(names as readonly string[]).includes(key)),
  ) as Instrument,
});
const GROUP = (...accountIds: [string, ...string[]]): Ctx => ({
  target: { kind: "group", accountIds },
});
const LONG: Ctx = { position: held("long", "1.000") };
const UNREAD: Ctx = { position: { status: "unknown" } };
const SHORT: Partial<OrderDraft> = { side: "sell", stopLoss: off("ticks", "9") };
const MIN_LEG = (min: string): Ctx => ({
  profile: { profile: { sizing: { min_leg_notional_usd: min } } } as TicketContext["profile"],
});

// prettier-ignore
export const MATRIX: readonly Row[] = [
  ok("symbol_not_trading", "a Trading instrument", D()),
  no("symbol_not_trading", "Closed", D({ symbol: "LUNAUSDT" }), "symbol", null, {
    instrument: CLOSED_LUNA,
  }),
  no("symbol_not_trading", "delisted", D(), "symbol", null, inst({ delisted: true })),
  no("symbol_not_trading", "a malformed row", D(), "symbol", null, inst({ tick_size: "0" })),
  no("symbol_not_trading", "another symbol's row", D({ symbol: "ETHUSDT" }), "symbol"),

  ok("account_not_targeted", "the target's account", D()),
  ok("account_not_targeted", "one of the group's accounts", D(), GROUP("other", ACCOUNT)),
  no("account_not_targeted", "another account than the target's", D({ exchangeAccountId: "other" }), "exchange_account_id"),
  no("account_not_targeted", "an account the group does not name", D(), "exchange_account_id", null, GROUP("other")),

  ok("side_invalid", "buy", D()),
  no("side_invalid", "a side of hold (L2)", { ...D(), side: "hold" } as unknown as OrderDraft, "side"),

  ok("price_invalid", "a limit price", D()),
  ok("price_invalid", "a market order, no price", D(MARKET)),
  no("price_invalid", "a limit with no price", D({ price: null }), "price"),
  no("price_invalid", "a limit price of 0", D({ price: "0" }), "price"),
  no("price_invalid", "a trigger of abc", D({ trigger: { price: "abc", direction: "rise" } }), "trigger.price"),

  ok("tick_size", "on the 0.10 tick", D({ price: "60000.1" })),
  ok("tick_size", "a trigger on it", D({ trigger: { price: "60100.1", direction: "rise" } })),
  no("tick_size", "off the tick", D({ price: "60000.05" }), "price", { tick: "0.10" }),
  no("tick_size", "a trigger off it", D({ trigger: { price: "1.05", direction: "rise" } }), "trigger.price", { tick: "0.10" }),

  ok("sizing_mode_unsupported", "fixed_qty", D()),
  no("sizing_mode_unsupported", "pct_position, entry", D(mode({ mode: "pct_position", pct: "50" })), "sizing"),
  no("sizing_mode_unsupported", "pct_position, reduce-only (BQ 14)", X("0", mode({ mode: "pct_position", pct: "50" })), "sizing", null, LONG),
  no("sizing_mode_unsupported", "fixed_notional, reduce-only", X("0", mode({ mode: "fixed_notional", notional_usd: "99" })), "sizing", null, LONG),

  ok("sizing_value", "pct_equity 1", D(mode({ mode: "pct_equity", pct: "1" }))),
  ok("sizing_value", "risk_based 0.5 %", D(mode({ mode: "risk_based", risk_per_trade_pct: "0.5" }))),
  no("sizing_value", "pct_equity 101", D(mode({ mode: "pct_equity", pct: "101" })), "sizing"),
  no("sizing_value", "risk_based, no value", D(mode({ mode: "risk_based" })), "sizing"),
  no("sizing_value", "max_notional_usd 0", D(mode({ mode: "profile", max_notional_usd: "0" })), "sizing"),
  no("sizing_value", "fixed_notional, none", D(mode({ mode: "fixed_notional" })), "sizing"),

  ok("min_order_qty", "the minimum", D(qty("0.001"))),
  ok("min_order_qty", "under it, closing the whole position (ruling (a))", X("0.005"), {
    ...inst({ min_order_qty: "0.01" }),
    position: held("long", "0.005"),
  }),
  no("min_order_qty", "0", D(qty("0")), "qty", { min: "0.001", step: "0.001" }),
  no("min_order_qty", "under 0.01", D(qty("0.005")), "qty", { min: "0.01" }, inst({ min_order_qty: "0.01" })),
  no("min_order_qty", "under it, closing part", X("0.004"), "qty", { min: "0.01" }, {
    ...inst({ min_order_qty: "0.01" }),
    position: held("long", "0.005"),
  }),
  ok("min_order_qty", "under one lot, no minimum filter: not known, never guessed", D(qty("0.0005")), without("min_order_qty")),
  no("min_order_qty", "0, no minimum filter", D(qty("0")), "qty", { step: "0.001" }, without("min_order_qty")),
  no("min_order_qty", "none, and no grid", D(mode({ mode: "fixed_qty" })), "qty", null, inst({ qty_step: "x" })),

  ok("qty_step", "on the lot", D(qty("0.012"))),
  no("qty_step", "off the lot", D(qty("0.0125")), "qty", { qty: "0.0125", step: "0.001" }),

  ok("max_order_qty", "at the ceiling", D(qty("100"))),
  no("max_order_qty", "above it", D(qty("100.001")), "qty", { max: "100.000" }),
  ok("max_order_qty", "a market order above it: its own cap is unmirrored (m4)", D({ ...MARKET, ...qty("100.001") })),

  ok("min_notional", "60 over 5 USDT", D()),
  ok("min_notional", "fixed_notional at 5", D(mode({ mode: "fixed_notional", notional_usd: "5" }))),
  ok("min_notional", "an exit (E29-S03)", X("0.001"), { ...inst({ min_notional_value: "100" }), ...LONG }),
  no("min_notional", "a market buy at the ask", D({ ...MARKET, ...qty("0.001") }), "sizing", { min: "100" }, inst({ min_notional_value: "100" })),
  no("min_notional", "the profile's min leg", D(qty("0.001")), "sizing", { min: "75" }, MIN_LEG("75")),
  ok("min_notional", "fixed_notional 1, no exchange minimum: not known", D(mode({ mode: "fixed_notional", notional_usd: "1" })), without("min_notional_value")),
  no("min_notional", "no exchange minimum: the profile's min leg holds", D(qty("0.001")), "sizing", { min: "75" }, { ...without("min_notional_value"), ...MIN_LEG("75") }),
  no("min_notional", "fixed_notional 4", D(mode({ mode: "fixed_notional", notional_usd: "4" })), "sizing", { min: "5" }),

  ok("native_stop_required", "an entry with a stop", D()),
  ok("native_stop_required", "an exit with none", X("0.5"), LONG),
  no("native_stop_required", "an entry with none (C-2.6)", D({ stopLoss: null }), "stop_loss"),
  no("native_stop_required", "reduce-only, unread position", X("0.5"), "stop_loss", null, UNREAD),
  no("native_stop_required", "reduce-only above the position", X("1.5"), "stop_loss", null, LONG),
  no("native_stop_required", "a flatten that opens", D({ intent: "flatten", stopLoss: null }), "stop_loss"),

  ok("stop_unit_unsupported", "an atr stop (S3)", D({ stopLoss: off("atr", "1.5") })),
  ok("stop_unit_unsupported", "a percent TP", D({ takeProfit: off("percent", "2") })),
  no("stop_unit_unsupported", "an r_multiple stop", D({ stopLoss: off("r_multiple", "1") }), "stop_loss"),
  no("stop_unit_unsupported", "an unknown stop unit (L2)", D({ stopLoss: off("bps" as OffsetUnit, "5") }), "stop_loss"),
  no("stop_unit_unsupported", "an unknown TP unit (L2)", D({ takeProfit: off("bps" as OffsetUnit, "5") }), "take_profit"),
  no("stop_unit_unsupported", "an atr TP", D({ takeProfit: off("atr", "2") }), "take_profit"),
  no("stop_unit_unsupported", "an r_multiple TP", D({ takeProfit: off("r_multiple", "2") }), "take_profit"),

  ok("invalid_stop_distance", "200 ticks", D()),
  ok("invalid_stop_distance", "a long's level below", D({ stopLoss: off("price", "59000") })),
  ok("invalid_stop_distance", "a market short's above the bid", D({ ...MARKET, side: "sell", stopLoss: off("price", "61000") })),
  no("invalid_stop_distance", "0 ticks", D({ stopLoss: off("ticks", "0") }), "stop_loss", { kind: "distance", side: "long" }),
  no("invalid_stop_distance", "a long's at entry", D({ stopLoss: off("price", "60000.0") }), "stop_loss", { kind: "level", side: "long" }),
  no("invalid_stop_distance", "a short's below", D({ side: "sell", stopLoss: off("price", "59000") }), "stop_loss", { kind: "level", side: "short" }),

  ok("take_profit_side", "a long's above", D({ takeProfit: off("price", "61000") })),
  no("take_profit_side", "a long's below", D({ takeProfit: off("price", "59000") }), "take_profit", { side: "long" }),
  no("take_profit_side", "a short's above", D({ ...SHORT, takeProfit: off("price", "61000") }), "take_profit", { side: "short" }),
  no("take_profit_side", "-5 ticks", D({ takeProfit: off("ticks", "-5") }), "take_profit", { side: "long" }),

  ok("reduce_only_tpsl", "an exit with neither", X("0.5"), LONG),
  ok("reduce_only_tpsl", "above the position, a stop: the flag alone is shown (L3)", X("1.5", { stopLoss: off("ticks", "9"), takeProfit: off("ticks", "9") }), LONG),
  no("reduce_only_tpsl", "an exit with a stop", X("0.5", { stopLoss: off("ticks", "9") }), "stop_loss", null, LONG),
  no("reduce_only_tpsl", "an exit with a TP", X("0.5", { takeProfit: off("ticks", "9") }), "take_profit", null, LONG),

  ok("post_only_cross", "a buy under the ask", D({ timeInForce: "PostOnly" })),
  ok("post_only_cross", "a sell over the bid", D({ ...SHORT, timeInForce: "PostOnly", price: "60005.0" })),
  no("post_only_cross", "a buy at the ask", D({ timeInForce: "PostOnly", price: "60010.0" }), "time_in_force"),
  no("post_only_cross", "a sell at the bid", D({ ...SHORT, timeInForce: "PostOnly", price: "59990.0" }), "time_in_force"),

  ok("reduce_only_no_position", "an exit inside a long", X("0.5"), LONG),
  no("reduce_only_no_position", "no position", X("0.5"), "reduce_only", { read: "none" }),
  no("reduce_only_no_position", "an unread one", X("0.5"), "reduce_only", { read: "unread" }, UNREAD),

  ok("reduce_only_exceeds_position", "the whole position", X("1"), LONG),
  no("reduce_only_exceeds_position", "more than it", X("1.001"), "reduce_only", null, LONG),
  no("reduce_only_no_position", "another symbol's read (M1)", X("0.5"), "reduce_only", { read: "unread" }, { position: held("long", "1", "ETHUSDT") }),

  ok("intent_mismatch", "entry on an entry", D()),
  ok("intent_mismatch", "scale_out on an exit", X("0.5"), LONG),
  ok("intent_mismatch", "flatten, unread position (reduce-only blocks)", X("0.5", { intent: "flatten" }), UNREAD),
  no("intent_mismatch", "reverse", D({ intent: "reverse" }), "intent"),
  no("intent_mismatch", "algo_child", D({ intent: "algo_child" }), "intent"),
  no("intent_mismatch", "flatten on an entry", D({ intent: "flatten" }), "intent"),
  no("intent_mismatch", "flatten, not reduce-only, unread position (m3)", D({ intent: "flatten" }), "intent", null, UNREAD),
  no("intent_mismatch", "scale_in on an exit", X("0.5", { intent: "scale_in" }), "intent", null, LONG),
];
