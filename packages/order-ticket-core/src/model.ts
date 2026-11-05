/**
 * The ticket's data model (#984 BQ 14): plain, structured-clone-safe data (strings, booleans,
 * numbers, arrays, plain objects; no class, function or `Map`), so a draft and its context can
 * cross into a worker if E30-K01 places the reducer there. Every wire shape is the generated
 * `@candleviewer/protocol` type (C-4.16); the only shapes declared here are the client's own —
 * the draft being edited and the context it is checked against — and they are built from those
 * types, never a hand-written copy of a DTO.
 */
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];
type Operations = generated.rest.operations;

/** `22` `Decimal`: the wire string. Arithmetic parses it into `decimal.ts`'s `Decimal` first. */
export type WireDecimal = Schemas["Decimal"];
export type SymbolName = Schemas["Symbol"];
export type Environment = Schemas["Environment"];
export type OrderSide = Schemas["OrderSide"];
export type OrderType = Schemas["OrderType"];
export type OrderIntent = Schemas["OrderIntent"];
export type TimeInForce = Schemas["TimeInForce"];
export type TpSlMode = Schemas["TpSlMode"];
export type TriggerSpec = Schemas["TriggerSpec"];
/**
 * `22` `SizingMode`, request-time sugar included: `pct_position` and `profile`. A draft may hold
 * any of them; `validate()` (S2) refuses `pct_position` on every order with
 * `sizing_mode_unsupported` while `22`'s interim stands (BQ 14 ruling), reduce-only included.
 */
export type SizingMode = Schemas["SizingMode"];
/**
 * `22` `OffsetUnit`, `price` included (an absolute level the OMS converts to ticks). A draft may
 * hold any unit; `validate()` (S2) refuses an `r_multiple` stop and an `atr` / `r_multiple`
 * take-profit as `stop_unit_unsupported`, as `placeOrder` does.
 */
export type OffsetUnit = Schemas["OffsetUnit"];
export type Sizing = Schemas["Sizing"];
export type Offset = Schemas["Offset"];
export type Instrument = Schemas["Instrument"];
export type AccountProfile = Schemas["AccountProfile"];
export type WalletBalance = Schemas["WalletBalance"];
export type Ticker = Schemas["Ticker"];
export type RiskSummary = Schemas["RiskSummary"];
export type Position = Schemas["Position"];
export type PlaceOrderRequest = Schemas["PlaceOrderRequest"];

type FeeRateResponse = Operations["getFeeRate"]["responses"][200]["content"]["application/json"];
/** One symbol's row of `getFeeRate` (`22` `/exchange-accounts/{accountId}/fee-rate`). */
export type FeeRate = NonNullable<FeeRateResponse["items"]>[number];

/**
 * The top of the book a market order is priced against, read from the served `Ticker` (BQ 14
 * ruling: no separate field; `TicketContext.ticker` carries it).
 */
export type BookTop = Pick<Ticker, "bid1_price" | "ask1_price">;

/**
 * Every `SizingMode`, in `22`'s order. `satisfies` plus the test's exhaustiveness check keep it
 * equal to the generated union, so a contract change fails the build here.
 */
export const SIZING_MODES = [
  "fixed_qty",
  "fixed_notional",
  "pct_equity",
  "risk_based",
  "pct_position",
  "profile",
] as const satisfies readonly SizingMode[];

/** Every `OffsetUnit`, in `22`'s order. */
export const OFFSET_UNITS = [
  "ticks",
  "percent",
  "r_multiple",
  "atr",
  "price",
] as const satisfies readonly OffsetUnit[];

/** A stop as the trader specifies it: `22`'s `Offset`, unresolved (`24` §9.3.1 resolves it). */
export type StopSpec = Offset;
/** A take-profit as the trader specifies it: `22`'s `Offset` (`24` §9.3.3). */
export type TpSpec = Offset;

/**
 * The order the trader is editing. It mirrors `PlaceOrderRequest`'s fields as the ticket holds
 * them — each optional field explicitly `null` while unset, so a draft is a total, comparable
 * value. A draft may be invalid; `validate()` says why, and only a valid one becomes a request.
 */
export interface OrderDraft {
  readonly exchangeAccountId: string;
  readonly profileId: string | null;
  readonly symbol: SymbolName;
  readonly side: OrderSide;
  readonly orderType: OrderType;
  readonly intent: OrderIntent;
  /** The limit price; `null` for a market order. */
  readonly price: WireDecimal | null;
  readonly timeInForce: TimeInForce | null;
  readonly reduceOnly: boolean;
  readonly closeOnTrigger: boolean;
  readonly sizing: Sizing;
  /**
   * The stop. An entry with none is refused by `validate()` (`native_stop_required`, C-2.6,
   * BQ 5): the ticket pre-fills the profile's stop visibly and never sends an entry without one.
   */
  readonly stopLoss: StopSpec | null;
  readonly takeProfit: TpSpec | null;
  readonly tpslMode: TpSlMode | null;
  readonly trigger: TriggerSpec | null;
  readonly note: string | null;
}

/**
 * The open position on the draft's symbol and account, as far as the client knows. `unknown`
 * (not yet read, or the read failed) counts as no position for every rule that needs one, and
 * an order is then classed an entry: it fails closed (SR-E29-01, the 07:18Z agreement).
 */
export type PositionRead =
  { readonly status: "unknown" } | { readonly status: "known"; readonly position: Position | null };

/** One account (SCR-060), or a trade group's accounts (SCR-061), never empty. */
export type TicketTarget =
  | { readonly kind: "account"; readonly accountId: string }
  | { readonly kind: "group"; readonly accountIds: readonly [string, ...string[]] };

/** Every account id a target names, in its order. */
export function targetAccountIds(target: TicketTarget): readonly string[] {
  return target.kind === "account" ? [target.accountId] : target.accountIds;
}

/**
 * What a draft is checked and sized against. A `null` read is one the client does not hold
 * (unavailable, or not served yet); the mirror then reports itself partial, never guesses.
 * The arm token is never here (BQ 7): S4's injected `ArmTokenSource` reads it per submit attempt.
 */
export interface TicketContext {
  readonly env: Environment;
  /**
   * The account or accounts the order targets (X-A2 ruling), so the web host can name them when
   * it injects the arm and the exposure guard; the package itself never reads `apps/web`.
   */
  readonly target: TicketTarget;
  readonly instrument: Instrument;
  readonly profile: AccountProfile | null;
  readonly wallet: WalletBalance | null;
  /** The served ticker; its `bid1_price` / `ask1_price` are the book top (`BookTop`). */
  readonly ticker: Ticker | null;
  readonly risk: RiskSummary | null;
  readonly position: PositionRead;
  readonly feeRate: FeeRate | null;
  /** Whether one-click trading is armed for this session (`/settings/arm`); never the token. */
  readonly armed: boolean;
}
