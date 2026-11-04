/**
 * `validate()`: the ticket's client-side checks, mirroring `22` `placeOrder`'s refusals where the
 * client holds the inputs, plus the checks only the exchange makes (post-only, a market that is
 * not trading). It returns **every** failure, ordered by the ticket's Tab order (`D02`:345;
 * E30-D05: the error summary lists one entry per blocking error in DOM field order), so the
 * SCR-060 summary can list them all; it never stops at the first.
 *
 * Fail closed: a check whose input the client lacks (a filter the instrument row omits, no book
 * top, an unread position) is never assumed to pass silently. It is listed in `unmirrored`, the
 * result is `partial`, and where the gap is the native-stop rule's (an unread position), the
 * order is classed an entry and must carry a stop (C-2.6; BQ 5 ruling). The server stays the
 * authority on everything (C-2.12): a draft this passes may still be refused, never the reverse
 * for a rule mirrored exactly.
 *
 * Server rules the client cannot mirror yet (the price band, the instrument's price limits, the
 * leverage cap, margin) are always listed in `unmirrored`, so no result claims `exact` while any
 * is unmirrored. A failure carries its data as plain `params`; `messages.ts` (S2b) maps it to the
 * deck's copy. Pure: no clock, randomness or I/O; plain data in, plain data out.
 */
import type { ErrorCode } from "@candleviewer/protocol";
import { classify, type EntryClass } from "./classify.js";
import {
  eq,
  gt,
  gte,
  lt,
  lte,
  max,
  mul,
  parseDecimal,
  sign,
  toPlain,
  type Decimal,
} from "./decimal.js";
import { isOnLot, isOnTick, parseInstrument, type InstrumentGrid } from "./instrument.js";
import {
  targetAccountIds,
  type Offset,
  type OffsetUnit,
  type OrderDraft,
  type OrderIntent,
  type OrderSide,
  type TicketContext,
} from "./model.js";

/**
 * The field a failure names, as `22`'s `errors[].field` names it where the server lists one:
 * a quantity bound is `qty`, the sizer's minimum notional `sizing` (S4 matches `errors[]` on it).
 */
export type FieldPath =
  | "symbol"
  | "exchange_account_id"
  | "side"
  | "trigger.price"
  | "price"
  | "qty"
  | "sizing"
  | "stop_loss"
  | "take_profit"
  | "time_in_force"
  | "reduce_only"
  | "intent";

/**
 * The fields in the ticket's Tab order (`D02`:345: order type and trigger, price, size, stop,
 * take-profit, TIF and post-only, reduce-only). The symbol and account are the panel header, so
 * they lead; the intent has no control of its own on SCR-060, so it closes the list.
 */
export const FIELD_ORDER: readonly FieldPath[] = [
  "symbol",
  "exchange_account_id",
  "side",
  "trigger.price",
  "price",
  "qty",
  "sizing",
  "stop_loss",
  "take_profit",
  "time_in_force",
  "reduce_only",
  "intent",
];

/**
 * Each rule and the `22` code the server answers for it (`null`: only the exchange judges it).
 * A rule id is `22`'s `errors[].rule` (or `ValidationFailure` reason) where `placeOrder` has
 * one, else a client rule (marked) named for the exchange check it anticipates.
 */
const RULE_CODES = {
  /** Client: the instrument is not `Trading`, delisted, malformed or another symbol's. */
  symbol_not_trading: null,
  /**
   * Client: the draft's account is not one the ticket's target names (S1 review note). The server
   * answers an ungranted account with its own 403 / 404, not a validation code.
   */
  account_not_targeted: null,
  /** Client: a side other than `buy` / `sell` (the worker boundary drops type guarantees). */
  side_invalid: "validation_failed",
  /** A limit price or trigger price that is absent or not a positive decimal. */
  price_invalid: "validation_failed",
  /** `tick_size_violation`: a price off the tick. */
  tick_size: "tick_size_violation",
  /** `pct_position` on any order (`22`'s interim); a mode but `fixed_qty` on reduce-only. */
  sizing_mode_unsupported: "validation_failed",
  /** The chosen mode's value is absent or out of range (`pct` and percents in (0, 100]). */
  sizing_value: "validation_failed",
  /** `lot_size_violation` / `min_order_qty`: a quantity below the minimum (or not positive). */
  min_order_qty: "lot_size_violation",
  /** `lot_size_violation`: a quantity off the lot step. */
  qty_step: "lot_size_violation",
  /** `lot_size_violation` / `max_order_qty`: a quantity above the exchange's ceiling. */
  max_order_qty: "lot_size_violation",
  /** `lot_size_violation` / the minimum notional missed (`sizing:below_min_notional`). */
  min_notional: "lot_size_violation",
  /** `validation_failed` / `native_stop_required`: an entry with no stop spec (C-2.6, BQ 5). */
  native_stop_required: "validation_failed",
  /** `stop_unit_unsupported`: an `r_multiple` stop, or an `atr` / `r_multiple` take-profit. */
  stop_unit_unsupported: "validation_failed",
  /** `invalid_stop_distance`: no distance, or a stop level on the wrong side of the entry. */
  invalid_stop_distance: "validation_failed",
  /** `validation_failed` / `take_profit_side`. */
  take_profit_side: "validation_failed",
  /** `validation_failed` / `reduce_only_tpsl`: a reduce-only order names a stop or take-profit. */
  reduce_only_tpsl: "validation_failed",
  /** Client (the exchange's post-only rule): a post-only limit at or through the book top. */
  post_only_cross: null,
  /** Client: reduce-only with no known position on the side it closes. */
  reduce_only_no_position: null,
  /** Client: reduce-only with a quantity above the position it reduces (it would be an entry). */
  reduce_only_exceeds_position: null,
  /** `validation_failed` / `intent_mismatch`. */
  intent_mismatch: "validation_failed",
} satisfies Record<string, RuleCode>;

type RuleCode = Extract<
  ErrorCode,
  "validation_failed" | "tick_size_violation" | "lot_size_violation"
> | null;
export type RuleId = keyof typeof RULE_CODES;
/** Every rule id, in the table's order. */
export const RULE_IDS = Object.keys(RULE_CODES) as readonly RuleId[];

/** One failure: a `22` `errors[]` item, its code, and the data its message shows. */
export interface ValidationFailure {
  readonly field: FieldPath;
  readonly rule: RuleId;
  /** The `22` code the server answers for this rule, or `null` when only the exchange judges it. */
  readonly code: RuleCode;
  /** Plain decimal strings and tags (`side`: `long` / `short`; `read`; `kind`), no copy. */
  readonly params: Readonly<Record<string, string>>;
}

/** An input a check needed and the client lacks; the check was skipped, never assumed to pass. */
export type Unmirrored =
  | "instrument"
  | "instrument.min_order_qty"
  | "instrument.min_notional_value"
  | "instrument.max_order_qty"
  | "instrument.max_mkt_order_qty"
  | "position"
  | "reference_price"
  | "ticker.book_top"
  /** Server rules not mirrored yet, listed on every result (code lens M1, BQ 1). */
  | "price_band"
  | "instrument.price_limits"
  | "max_leverage"
  | "margin";

/** `22`'s price band, `min_price` / `max_price`, the leverage cap and margin: not served yet. */
export const ALWAYS_UNMIRRORED: readonly Unmirrored[] = [
  "price_band",
  "instrument.price_limits",
  "max_leverage",
  "margin",
];

/**
 * `blocked`: a client-mirrored rule fails. `clear_exact`: none fails and every check had its
 * inputs. `clear_partial`: none fails but some check was skipped (`unmirrored`). Neither clear
 * state is an approval: the server decides (C-2.12).
 */
export type ValidationStatus = "blocked" | "clear_exact" | "clear_partial";

export interface ValidationResult {
  readonly status: ValidationStatus;
  /** Every failure, in `FIELD_ORDER`, each field's in rule order. */
  readonly failures: readonly ValidationFailure[];
  readonly classification: EntryClass;
  /** `exact` when every check had its inputs; else `partial`, the gaps in `unmirrored`. */
  readonly exactness: "exact" | "partial";
  readonly unmirrored: readonly Unmirrored[];
}

/** Record a failure with its message data. */
type Fail = (field: FieldPath, rule: RuleId, params?: Readonly<Record<string, string>>) => void;

/** The intents that only reduce, and the ones that only open (`22` `placeOrder`, SR-E29-01). */
const REDUCING_INTENTS: ReadonlySet<OrderIntent> = new Set([
  "stop_loss",
  "take_profit",
  "scale_out",
  "flatten",
]);
const OPENING_INTENTS: ReadonlySet<OrderIntent> = new Set(["entry", "scale_in"]);
/** Server-assigned intents `placeOrder` refuses outright. */
const SERVER_INTENTS: ReadonlySet<OrderIntent> = new Set(["reverse", "algo_child"]);

const HUNDRED: Decimal = { units: 100n, scale: 0 };

const positive = (text: string | null | undefined): Decimal | null => {
  const value = parseDecimal(text);
  return value !== null && sign(value) > 0 ? value : null;
};

/** A positive decimal no greater than 100: a percent. */
const percent = (text: string | undefined): Decimal | null => {
  const value = positive(text);
  return value !== null && lte(value, HUNDRED) ? value : null;
};

/**
 * What an `Offset` unit measures. The `Record` is exhaustive (a new `OffsetUnit` fails the build);
 * a unit outside it (a draft that crossed the worker boundary unchecked) is `unknown`, refused.
 */
const UNIT_KINDS: Readonly<Record<OffsetUnit, "distance" | "level" | "r" | "atr">> = {
  ticks: "distance",
  percent: "distance",
  price: "level",
  r_multiple: "r",
  atr: "atr",
};
const unitKind = (unit: OffsetUnit) =>
  Object.hasOwn(UNIT_KINDS, unit) ? UNIT_KINDS[unit] : "unknown";

const sideKey = (side: OrderSide): "long" | "short" => (side === "buy" ? "long" : "short");

/**
 * The price an entry is judged against: a limit's price, a conditional market order's trigger,
 * else the book top it would take (a buy the ask, a sell the bid), else the last price.
 */
function referencePrice(
  draft: OrderDraft,
  ctx: TicketContext,
  price: Decimal | null,
): Decimal | null {
  if (draft.orderType === "limit") return price;
  if (draft.trigger !== null) return positive(draft.trigger.price);
  const ticker = ctx.ticker;
  if (ticker === null) return null;
  return (
    positive(draft.side === "buy" ? ticker.ask1_price : ticker.bid1_price) ??
    positive(ticker.last_price)
  );
}

/** An `Offset` level on the right side of `ref`: below it for a buy's stop, above for a sell's. */
function levelBeyond(level: Decimal, ref: Decimal, below: boolean): boolean {
  return below ? lt(level, ref) : gt(level, ref);
}

/** Validate a draft against its context: every failure, in field order (see the module note). */
export function validate(draft: OrderDraft, ctx: TicketContext): ValidationResult {
  const failures: ValidationFailure[] = [];
  const unmirrored = new Set<Unmirrored>(ALWAYS_UNMIRRORED);
  const fail: Fail = (field, rule, params = {}) => {
    failures.push({ field, rule, code: RULE_CODES[rule], params });
  };

  const classification = classify(draft, ctx.position, ctx.target);
  const reason = classification.entry ? classification.reason : null;
  if (ctx.position.status === "unknown" || reason === "position_unknown")
    unmirrored.add("position");
  const side = sideKey(draft.side);
  const isLimit = draft.orderType === "limit";

  // symbol: a market the ticket can price against and the exchange will take.
  const grid: InstrumentGrid | null =
    ctx.instrument.symbol === draft.symbol ? parseInstrument(ctx.instrument) : null;
  if (grid === null) unmirrored.add("instrument");
  else {
    for (const name of grid.missing) {
      if (name !== "max_leverage") unmirrored.add(`instrument.${name}`);
    }
  }
  if (grid === null || !grid.tradable) fail("symbol", "symbol_not_trading");
  // exchange_account_id: the draft's account must be one the target names (a stale draft kept
  // across a retarget is refused, never validated against another account's context).
  if (!targetAccountIds(ctx.target).includes(draft.exchangeAccountId)) {
    fail("exchange_account_id", "account_not_targeted");
  }
  if (reason === "side_invalid") fail("side", "side_invalid");
  const tick = grid === null ? null : { tick: toPlain(grid.tickSize) };

  // trigger.price: a conditional order's trigger, on the tick.
  if (draft.trigger !== null) {
    const trigger = positive(draft.trigger.price);
    if (trigger === null) fail("trigger.price", "price_invalid");
    else if (grid !== null && tick !== null && !isOnTick(grid, trigger)) {
      fail("trigger.price", "tick_size", tick);
    }
  }

  // price: a limit's price, on the tick. A market order's price is ignored (S4 drops it).
  const price = isLimit ? positive(draft.price) : null;
  if (isLimit) {
    if (price === null) fail("price", "price_invalid");
    else if (grid !== null && tick !== null && !isOnTick(grid, price)) {
      fail("price", "tick_size", tick);
    }
  }
  const ref = referencePrice(draft, ctx, price);

  // sizing: the mode, its values, and a fixed quantity's lot, bounds and notional.
  validateSizing(draft, ctx, grid, ref, classification, fail, unmirrored);

  // stop_loss: the native-stop invariant first (C-2.6), then the unit and the distance.
  // A reduce-only order that is not shown to reduce is told about its reduce-only flag alone,
  // never to drop a stop it may need once it opens (the flag is the fix).
  const reduceOnlyBlocked =
    draft.reduceOnly &&
    (reason === "position_unknown" || reason === "no_position" || reason === "exceeds_position");
  const stop = draft.stopLoss;
  if (draft.reduceOnly && stop !== null) {
    if (!reduceOnlyBlocked) fail("stop_loss", "reduce_only_tpsl");
  } else if (stop === null) {
    if (classification.entry) {
      fail("stop_loss", "native_stop_required");
    }
  } else if (unitKind(stop.unit) === "r" || unitKind(stop.unit) === "unknown") {
    fail("stop_loss", "stop_unit_unsupported");
  } else {
    checkStop(stop, draft.side, ref, fail, unmirrored);
  }

  // take_profit: never on reduce-only; only `price`, `ticks` or `percent`; on the profit side.
  const tp = draft.takeProfit;
  if (tp !== null) {
    if (draft.reduceOnly) {
      if (!reduceOnlyBlocked) fail("take_profit", "reduce_only_tpsl");
    } else if (unitKind(tp.unit) !== "distance" && unitKind(tp.unit) !== "level") {
      fail("take_profit", "stop_unit_unsupported");
    } else {
      const level = positive(tp.value);
      const wrongSide =
        level === null ||
        (tp.unit === "price" && ref !== null && !levelBeyond(level, ref, draft.side === "sell"));
      if (tp.unit === "price" && level !== null && ref === null) unmirrored.add("reference_price");
      if (wrongSide) {
        fail("take_profit", "take_profit_side", { side });
      }
    }
  }

  // time_in_force: a post-only limit must rest, not take (the exchange's rule; book top).
  if (isLimit && draft.timeInForce === "PostOnly" && price !== null) {
    const touch = positive(draft.side === "buy" ? ctx.ticker?.ask1_price : ctx.ticker?.bid1_price);
    if (touch === null) unmirrored.add("ticker.book_top");
    else if (draft.side === "buy" ? gte(price, touch) : lte(price, touch)) {
      fail("time_in_force", "post_only_cross");
    }
  }

  // reduce_only: it needs a known position on the side it closes, no larger than it.
  if (draft.reduceOnly) {
    if (reason === "position_unknown" || reason === "no_position") {
      const read = reason === "no_position" ? "none" : "unread";
      fail("reduce_only", "reduce_only_no_position", { read });
    } else if (reason === "exceeds_position") {
      fail("reduce_only", "reduce_only_exceeds_position");
    }
  }

  // intent: it must agree with the effect; the server-assigned ones are never the client's.
  // A reducing intent on an order that is not reduce-only is always refused (`22`:6580-6584);
  // otherwise not judged while the effect is unknown (an untrusted read, a bad side).
  const intent = draft.intent;
  const judged = reason !== "position_unknown" && reason !== "side_invalid";
  const mismatch =
    SERVER_INTENTS.has(intent) ||
    (!draft.reduceOnly && REDUCING_INTENTS.has(intent)) ||
    (judged && (classification.entry ? REDUCING_INTENTS.has(intent) : OPENING_INTENTS.has(intent)));
  if (mismatch) fail("intent", "intent_mismatch");

  const ordered = failures
    .map((failure, index) => ({ failure, index }))
    .sort(
      (a, b) =>
        FIELD_ORDER.indexOf(a.failure.field) - FIELD_ORDER.indexOf(b.failure.field) ||
        a.index - b.index,
    )
    .map(({ failure }) => failure);
  const gaps = [...unmirrored].sort();
  return {
    status: ordered.length > 0 ? "blocked" : gaps.length === 0 ? "clear_exact" : "clear_partial",
    failures: ordered,
    classification,
    exactness: gaps.length === 0 ? "exact" : "partial",
    unmirrored: gaps,
  };
}

/**
 * A stop in `ticks`, `percent`, `atr` or `price`: a positive distance (or level), and a `price`
 * level below a buy's reference or above a sell's (`invalid_stop_distance`). An `atr` stop is
 * resolved by the sizing mirror (S3) through the profile's fallback; only its value is checked.
 */
function checkStop(
  stop: Offset,
  side: OrderSide,
  ref: Decimal | null,
  fail: Fail,
  unmirrored: Set<Unmirrored>,
): void {
  const level = positive(stop.value);
  if (level === null) {
    fail("stop_loss", "invalid_stop_distance", { kind: "distance", side: sideKey(side) });
    return;
  }
  if (stop.unit !== "price") return;
  if (ref === null) {
    unmirrored.add("reference_price");
    return;
  }
  if (!levelBeyond(level, ref, side === "buy")) {
    fail("stop_loss", "invalid_stop_distance", { kind: "level", side: sideKey(side) });
  }
}

/**
 * The sizing field. `pct_position` is refused on every order while `22`'s interim stands (BQ 14
 * ruling), and a reduce-only order takes `fixed_qty` only. A mode's own value must be present and
 * in range. A `fixed_qty` quantity is held to the lot, the minimum (waived for a reduce-only order
 * closing the whole position: `22`, ruling (a) of 2026-11-01), the ceiling and, for an entry, the
 * minimum notional (an exit is never refused for its notional, E29-S03). The quantity another mode
 * produces is the sizing mirror's (S3); the minimum notional of `fixed_notional` is checked here.
 */
function validateSizing(
  draft: OrderDraft,
  ctx: TicketContext,
  grid: InstrumentGrid | null,
  ref: Decimal | null,
  classification: EntryClass,
  fail: Fail,
  unmirrored: Set<Unmirrored>,
): void {
  const { sizing } = draft;
  if (sizing.mode === "pct_position" || (draft.reduceOnly && sizing.mode !== "fixed_qty")) {
    fail("sizing", "sizing_mode_unsupported");
    return;
  }
  const valueOk =
    sizing.mode === "pct_equity"
      ? percent(sizing.pct) !== null
      : sizing.mode === "risk_based"
        ? positive(sizing.risk_per_trade_usd) !== null ||
          percent(sizing.risk_per_trade_pct) !== null
        : true;
  const capOk = sizing.max_notional_usd === undefined || positive(sizing.max_notional_usd) !== null;
  if (!valueOk || !capOk) fail("sizing", "sizing_value");

  // The notional floor: the higher of the exchange's and the profile's. An absent exchange
  // minimum is not known (S1: `null`, listed in `unmirrored`), so only the profile's is held,
  // and the check is skipped when neither is known.
  const minLeg = positive(ctx.profile?.profile.sizing?.min_leg_notional_usd);
  const notionalFloor = (g: InstrumentGrid): Decimal | null =>
    g.minNotional === null ? minLeg : minLeg !== null ? max(minLeg, g.minNotional) : g.minNotional;

  if (sizing.mode === "fixed_notional") {
    const notional = positive(sizing.notional_usd);
    const floor = grid === null ? null : notionalFloor(grid);
    if (notional === null) fail("sizing", "sizing_value");
    else if (floor !== null && lt(notional, floor)) {
      fail("sizing", "min_notional", { min: toPlain(floor) });
    }
    return;
  }
  if (sizing.mode !== "fixed_qty") return;

  const qty = positive(sizing.qty);
  // An absent minimum quantity is not known (S1: `null`, listed in `unmirrored`): no `min` param.
  const minQty = grid?.minOrderQty ?? null;
  const lot = {
    ...(minQty === null ? {} : { min: toPlain(minQty) }),
    ...(grid === null ? {} : { step: toPlain(grid.qtyStep) }),
  };
  if (qty === null) {
    fail("qty", "min_order_qty", lot);
    return;
  }
  if (grid === null) return;
  if (!isOnLot(grid, qty)) fail("qty", "qty_step", { ...lot, qty: toPlain(qty) });
  const closesWhole = !classification.entry && eq(qty, classification.positionSize);
  if (minQty !== null && lt(qty, minQty) && !closesWhole) fail("qty", "min_order_qty", lot);
  // A market order's ceiling is `max_mkt_order_qty`, which `Instrument` lacks (G-b): the check
  // is skipped and listed, never run against `max_order_qty`, so it cannot over-block (m4).
  if (draft.orderType === "market") unmirrored.add("instrument.max_mkt_order_qty");
  else if (grid.maxOrderQty !== null && gt(qty, grid.maxOrderQty)) {
    fail("qty", "max_order_qty", { max: toPlain(grid.maxOrderQty) });
  }
  if (!classification.entry) return;
  if (ref === null) {
    unmirrored.add("reference_price");
    return;
  }
  const floor = notionalFloor(grid);
  if (floor !== null && lt(mul(qty, ref), floor)) {
    fail("sizing", "min_notional", { min: toPlain(floor) });
  }
}
