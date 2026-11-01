/**
 * One row of the SCR-063 Working-orders tab (E29-S02 #912), from a wire order (WS `23` §15.1 or
 * REST `22` `Order`), the caller's account directory and the order's creation constants (BQ-6).
 * Columns follow E29-D02 §6.1; every word is `../copy.ts`'s (cited or PROPOSED). Money stays the
 * wire's decimal text: the display rounding is the cell's, never this module's.
 *
 * - **The state (BQ-7).** `lifecycle_state` picks the E29-D01 D2 word; when it is null, `state`
 *   is mapped through `24` §8.2's table; any value this client does not know reads "Working — state
 *   not reported", live, as `23` §15.1 asks. `draft` and `validated` are never shown (D01 D2).
 * - **The trigger (BQ-17).** "Mark falls to 63,950.0": a recorded TP/SL order is pushed with no
 *   direction, so a reduce-only stop loss or take profit takes it from its closing side (a sell
 *   stop falls, a sell take profit rises; a buy mirrors them).
 * - **The native-stop row (BQ-5).** REST `provenance: recorded_stop` names it (a creation constant,
 *   which WS never sends), else D01 D7's rule: a reduce-only stop loss on the exchange. Without a
 *   position to ask, the rule assumes one is open, so a stop is never offered as cancellable when
 *   it may not be (C-2.6); the server's refusal stays the enforcement.
 */
import type { generated } from "@candleviewer/protocol";
import { parseDecimal } from "../../model/decimal";
import { isUuid, type AccountInfo, type Environment } from "../../model/rowMapping";
import {
  AGE_UNITS,
  bindProposed,
  ORDER_TEXT,
  PURPOSE_WORDS,
  STATE_WORDS,
  WORD_SEPARATOR,
} from "../copy";

type Schemas = generated.rest.components["schemas"];
export type WsOrder = generated.ws.Orders["orders"][number];
export type RestOrder = Schemas["Order"];
export type LifecycleState = Schemas["OrderLifecycleState"];
export type OrderState = Schemas["OrderState"];
export type OrderIntent = Schemas["OrderIntent"];
export type OrderProvenance = Schemas["OrderProvenance"];
export type AlgoKind = NonNullable<WsOrder["algo_kind"]>;
export type TriggerBy = NonNullable<WsOrder["trigger_by"]>;
export type TimeInForce = NonNullable<WsOrder["time_in_force"]>;
export type OrderChange = NonNullable<WsOrder["change"]>;

/** `24` §8.2: the B1 chart state each persisted `order_state` stores (one to one, so exact). */
export const LIFECYCLE_OF_STATE: Readonly<Record<OrderState, LifecycleState>> = {
  new: "draft",
  pending_submit: "validated",
  submitted: "submitting",
  accepted: "submitted",
  triggered: "triggered",
  partially_filled: "partially_filled",
  pending_cancel: "cancel_pending",
  pending_amend: "amend_pending",
  unknown: "unknown",
  quarantined: "quarantined",
  untracked: "untracked",
  held: "held",
  filled: "filled",
  cancelled: "cancelled",
  rejected: "rejected",
  expired: "expired",
  killed: "killed",
};

/** How the row is drawn (E29-D04 handoff §C.2's story families, with untracked its own class). */
export type StateFamily =
  "active" | "in_flight" | "checking" | "critical" | "untracked" | "terminal";

const FAMILY: Readonly<Record<LifecycleState, StateFamily>> = {
  draft: "in_flight",
  validated: "in_flight",
  submitting: "in_flight",
  submitted: "active",
  triggered: "active",
  partially_filled: "active",
  cancel_pending: "in_flight",
  amend_pending: "in_flight",
  unknown: "checking",
  quarantined: "critical",
  held: "critical",
  untracked: "untracked",
  filled: "terminal",
  cancelled: "terminal",
  rejected: "terminal",
  expired: "terminal",
  killed: "terminal",
};

const LIFECYCLES = new Set<string>(Object.keys(FAMILY));
const isLifecycle = (v: unknown): v is LifecycleState => typeof v === "string" && LIFECYCLES.has(v);
const isState = (v: unknown): v is OrderState =>
  typeof v === "string" && Object.hasOwn(LIFECYCLE_OF_STATE, v);

/** The two states the OMS does not own: shown, never managed (S9, INV-B1-n). */
export const UNOWNED: ReadonlySet<LifecycleState> = new Set(["held", "untracked"]);

export interface OrderStateModel {
  /** The B1 state the word is for; null when neither field names one this client knows. */
  readonly lifecycle: LifecycleState | null;
  /** Which field gave it (BQ-7). */
  readonly from: "lifecycle_state" | "state" | "none";
  /** D01 D2's word ("Partial" before its figures, `stateLabel`). */
  readonly word: string;
  readonly family: StateFamily;
  /** A known final state: the row lingers about 5 s, then leaves (D01 D13 d). */
  readonly terminal: boolean;
  /** `draft` or `validated`: ticket-local, never in the blotter (D01 D2). */
  readonly hidden: boolean;
}

/** BQ-7: `lifecycle_state`, else `state` through `24` §8.2, else "Working — state not reported". */
export function resolveState(lifecycle: unknown, state: unknown): OrderStateModel {
  let chart: LifecycleState | null = null;
  let from: OrderStateModel["from"] = "none";
  if (lifecycle !== null && lifecycle !== undefined) {
    if (isLifecycle(lifecycle)) {
      chart = lifecycle;
      from = "lifecycle_state";
    }
  } else if (isState(state)) {
    chart = LIFECYCLE_OF_STATE[state];
    from = "state";
  }
  if (chart === null) {
    // `23` §15.1: open-ended for readers; an order in a state this client does not know is live
    return {
      lifecycle: null,
      from,
      word: ORDER_TEXT.notReported.string,
      family: "active",
      terminal: false,
      hidden: false,
    };
  }
  const family = FAMILY[chart];
  const hidden = chart === "draft" || chart === "validated";
  const word = hidden ? "" : STATE_WORDS[chart as keyof typeof STATE_WORDS].string;
  return { lifecycle: chart, from, word, family, terminal: family === "terminal", hidden };
}

/** The trigger of a conditional order (D02 §6.1's Trigger column). */
export interface TriggerModel {
  readonly price: string;
  readonly source: TriggerBy | null;
  readonly direction: "rise" | "fall" | null;
  /** BQ-17: the direction was taken from the closing side, not sent. */
  readonly derived: boolean;
}

/** The side a reduce-only stop or take profit closes towards: BQ-17's derivation, else null. */
export function derivedDirection(
  intent: unknown,
  side: unknown,
  reduceOnly: boolean,
): "rise" | "fall" | null {
  if (!reduceOnly || (side !== "buy" && side !== "sell")) return null;
  if (intent === "stop_loss") return side === "sell" ? "fall" : "rise";
  if (intent === "take_profit") return side === "sell" ? "rise" : "fall";
  return null;
}

/** A positive decimal the wire holds, as sent; `null` for none, zero (Bybit's none) or junk. */
function amount(value: unknown): string | null {
  const parsed = parseDecimal(value);
  return parsed === null || parsed.units <= 0n ? null : (value as string);
}

/** A decimal the wire holds, zero included (a filled quantity). */
function quantity(value: unknown): string | null {
  return parseDecimal(value) === null ? null : (value as string);
}

const TRIGGER_SOURCES: readonly TriggerBy[] = ["LastPrice", "MarkPrice", "IndexPrice"];

function triggerOf(order: WireCommon, reduceOnly: boolean): TriggerModel | null {
  const price = amount(order.trigger_price);
  if (price === null) return null;
  const source = TRIGGER_SOURCES.find((s) => s === order.trigger_by) ?? null;
  const sent =
    order.trigger_direction === "rise" || order.trigger_direction === "fall"
      ? order.trigger_direction
      : null;
  const derived = sent === null ? derivedDirection(order.intent, order.side, reduceOnly) : null;
  return { price, source, direction: sent ?? derived, derived: derived !== null };
}

/** How a figure is written in a sentence: the cell passes `decimalText` at the step's places. */
export type Figure = (decimal: string) => string;
const asSent: Figure = (decimal) => decimal;

const SOURCE_WORDS: Readonly<Record<TriggerBy, () => string>> = {
  LastPrice: () => ORDER_TEXT.lastPrice.string,
  MarkPrice: () => ORDER_TEXT.markPrice.string,
  IndexPrice: () => bindProposed("blotter.ui.trigger.index"),
};

/** "Mark falls to 63,950.0" (D02:269); the PROPOSED forms for an unknown source or direction. */
export function triggerWords(trigger: TriggerModel, figure: Figure = asSent): string {
  const price = figure(trigger.price);
  const source = trigger.source === null ? null : SOURCE_WORDS[trigger.source]();
  if (trigger.direction === null) {
    return bindProposed("blotter.ui.trigger.undirected", {
      Mark: source ?? "Price",
      "63,950.0": price,
    });
  }
  const verb = trigger.direction === "rise" ? ORDER_TEXT.rises.string : ORDER_TEXT.falls.string;
  if (source === null) {
    return bindProposed("blotter.ui.trigger.unsourced", { "falls to": verb, "63,950.0": price });
  }
  return `${source} ${verb} ${price}`;
}

/** The Parent column: a parent order (with its algo's word when known) or a group leg. */
export interface ParentModel {
  readonly kind: "parent" | "leg";
  /** The parent order's id, or the leg's. */
  readonly id: string;
  readonly algo: AlgoKind | null;
}

const ALGO_WORDS: Partial<Readonly<Record<AlgoKind, string>>> = {
  bracket: ORDER_TEXT.bracket.string,
  twap: ORDER_TEXT.twap.string,
};

/**
 * "Bracket · #7c1e", "TWAP · #a04f", "Group leg" (D02:273). A kind no design words (and an unknown
 * one, as WS and REST send none today) shows the short id alone (BQ-6); the full id is the name's.
 */
export function parentWords(parent: ParentModel | null): string {
  if (parent === null) return ORDER_TEXT.none.string;
  if (parent.kind === "leg") return ORDER_TEXT.groupLeg.string;
  const short = `#${parent.id.replace(/-/g, "").slice(0, 4)}`;
  const word = parent.algo === null ? undefined : ALGO_WORDS[parent.algo];
  return word === undefined ? short : `${word}${WORD_SEPARATOR}${short}`;
}

/** "Limit · Take profit" (D-19): the purpose folds into State when Type drops, so it is its own. */
export function typeWords(orderType: unknown, intent: unknown): string {
  const type =
    orderType === "limit"
      ? ORDER_TEXT.limit.string
      : orderType === "market"
        ? ORDER_TEXT.market.string
        : null;
  const purpose = purposeWord(intent);
  if (type === null && purpose === null) return ORDER_TEXT.none.string;
  return [type, purpose].filter((w): w is string => w !== null).join(WORD_SEPARATOR);
}

export function purposeWord(intent: unknown): string | null {
  return typeof intent === "string" && Object.hasOwn(PURPOSE_WORDS, intent)
    ? PURPOSE_WORDS[intent as keyof typeof PURPOSE_WORDS].string
    : null;
}

/** "Reduce-only · Close on trigger" (D02:271), "—" when none. */
export function flagsWords(reduceOnly: boolean, closeOnTrigger: boolean): string {
  const words: readonly (string | null)[] = [
    reduceOnly ? ORDER_TEXT.reduceOnly.string : null,
    closeOnTrigger ? ORDER_TEXT.closeOnTrigger.string : null,
  ];
  const flags = words.filter((w): w is string => w !== null);
  return flags.length === 0 ? ORDER_TEXT.none.string : flags.join(WORD_SEPARATOR);
}

/** "GTC", "IOC", "FOK", "Post-only" (D02:270: `23` §15.1 carries post-only as a TIF value). */
export function tifWords(tif: TimeInForce | null): string {
  if (tif === null) return ORDER_TEXT.none.string;
  return tif === "PostOnly" ? ORDER_TEXT.postOnly.string : tif;
}

export function sideWords(side: "buy" | "sell" | null): string {
  if (side === null) return ORDER_TEXT.none.string;
  return side === "buy" ? ORDER_TEXT.buy.string : ORDER_TEXT.sell.string;
}

const MS_PER_S = 1_000;

/**
 * The Age column (D02:272): "38 s", "4 m", "1 h 12 m", "2 h 05 m"; "—" until known (D01 OQ-9).
 * Whole units, floored; a creation time ahead of `nowMs` (two clocks) reads "0 s". Hours keep
 * counting past a day: the design draws no day unit.
 */
export function formatAge(createdAtMs: number | null, nowMs: number): string {
  if (createdAtMs === null) return ORDER_TEXT.none.string;
  const seconds = Math.max(0, Math.floor((nowMs - createdAtMs) / MS_PER_S));
  const { seconds: s, minutes: m, hours: h } = AGE_UNITS;
  if (seconds < 60) return `${seconds} ${s.string}`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} ${m.string}`;
  const hours = Math.floor(minutes / 60);
  return `${hours} ${h.string} ${String(minutes % 60).padStart(2, "0")} ${m.string}`;
}

/** What the order is protecting (BQ-5): a native stop, a recorded take profit, or neither. */
export interface ProtectiveModel {
  readonly kind: "native_stop" | "recorded_take_profit" | null;
  /** `provenance` (REST, the creation constant) or D01 D7's `rule`. */
  readonly via: "provenance" | "rule" | null;
}

/**
 * Whether an open position (same account, symbol and `position_idx`) still depends on a stop:
 * D01 D7's last clause, which the orders feed alone cannot answer. Omitted, one is assumed.
 */
export type OpenPositionOf = (accountId: string, symbol: string, positionIdx: 0 | 1 | 2) => boolean;

export function protectiveOf(
  row: Pick<
    OrderRowModel,
    | "intent"
    | "reduceOnly"
    | "exchangeOrderId"
    | "provenance"
    | "accountId"
    | "symbol"
    | "positionIdx"
  >,
  openPosition?: OpenPositionOf,
): ProtectiveModel {
  const covered = openPosition?.(row.accountId, row.symbol, row.positionIdx) ?? true;
  if (row.provenance === "recorded_stop") {
    if (row.intent === "take_profit") return { kind: "recorded_take_profit", via: "provenance" };
    if (row.intent === "stop_loss" && covered) return { kind: "native_stop", via: "provenance" };
    return { kind: null, via: null };
  }
  const rule = row.intent === "stop_loss" && row.reduceOnly && row.exchangeOrderId !== null;
  return rule && covered ? { kind: "native_stop", via: "rule" } : { kind: null, via: null };
}

/** An order's creation constants (BQ-6): REST's, and the `change: "created"` frame's stamp. */
export interface OrderConstants {
  readonly createdAtMs: number | null;
  readonly provenance: OrderProvenance | null;
  readonly tradeGroupId: string | null;
}

export const NO_CONSTANTS: OrderConstants = Object.freeze({
  createdAtMs: null,
  provenance: null,
  tradeGroupId: null,
});

export interface OrderRowModel {
  readonly id: string;
  readonly accountId: string;
  readonly accountLabel: string | null;
  readonly environment: Environment | null;
  readonly symbol: string;
  /** The base coin of a USDT symbol, for "0.150 BTC" (D02 §6.1). */
  readonly baseCoin: string;
  readonly side: "buy" | "sell" | null;
  readonly sideLabel: string;
  readonly orderType: "market" | "limit" | null;
  readonly intent: OrderIntent | null;
  /** "Limit · Take profit" (D-19). */
  readonly typeLabel: string;
  /** "Take profit": what folds into State when Type drops ("Working · Stop loss"). */
  readonly purpose: string | null;
  readonly qty: string | null;
  readonly filledQty: string | null;
  readonly avgFillPrice: string | null;
  /** The limit price; `null` for a market order (`isMarket`) or none. */
  readonly price: string | null;
  readonly isMarket: boolean;
  readonly trigger: TriggerModel | null;
  readonly timeInForce: TimeInForce | null;
  readonly tifLabel: string;
  readonly reduceOnly: boolean;
  readonly closeOnTrigger: boolean;
  readonly flagsLabel: string;
  readonly positionIdx: 0 | 1 | 2;
  /** Age's start: REST `created_at`, else the `change: "created"` frame's stamp (D02:272). */
  readonly createdAtMs: number | null;
  readonly parent: ParentModel | null;
  readonly parentLabel: string;
  readonly tradeGroupId: string | null;
  readonly provenance: OrderProvenance | null;
  readonly protective: ProtectiveModel;
  readonly exchangeOrderId: string | null;
  readonly orderLinkId: string | null;
  readonly state: OrderStateModel;
  /** E29-D02 §6.2: a trigger price, not triggered: the "Conditional — not triggered" section. */
  readonly conditional: boolean;
  /** The frame's `change` (BQ-1 reads it with the state and the price); REST has none. */
  readonly change: OrderChange | null;
  readonly updatedAtMs: number | null;
  readonly source: "ws" | "rest";
}

/** The members both feeds share, read defensively: a malformed one is dropped, never guessed. */
interface WireCommon {
  readonly id?: unknown;
  readonly exchange_account_id?: unknown;
  readonly symbol?: unknown;
  readonly side?: unknown;
  readonly order_type?: unknown;
  readonly intent?: unknown;
  readonly state?: unknown;
  readonly lifecycle_state?: unknown;
  readonly qty?: unknown;
  readonly filled_qty?: unknown;
  readonly avg_fill_price?: unknown;
  readonly price?: unknown;
  readonly time_in_force?: unknown;
  readonly reduce_only?: unknown;
  readonly close_on_trigger?: unknown;
  readonly position_idx?: unknown;
  readonly trigger_price?: unknown;
  readonly trigger_by?: unknown;
  readonly trigger_direction?: unknown;
  readonly parent_order_id?: unknown;
  readonly trade_group_leg_id?: unknown;
  readonly trade_group_id?: unknown;
  readonly algo_kind?: unknown;
  readonly provenance?: unknown;
  readonly exchange_order_id?: unknown;
  readonly order_link_id?: unknown;
  readonly environment?: unknown;
  readonly change?: unknown;
  readonly updated_at_ms?: unknown;
}

const USDT = /^([A-Z0-9]{2,20})USDT$/;
const ENVIRONMENTS: readonly Environment[] = ["live", "demo", "testnet"];
const TIFS: readonly TimeInForce[] = ["GTC", "IOC", "FOK", "PostOnly"];
const ALGOS: readonly AlgoKind[] = ["none", "oco", "iceberg", "twap", "chase", "scaled", "bracket"];
const PROVENANCES: readonly OrderProvenance[] = ["placed", "reconciliation", "recorded_stop"];
const CHANGES: readonly OrderChange[] = [
  "created",
  "submitted",
  "ack",
  "fill",
  "amend",
  "cancel",
  "reject",
  "expire",
  "reconcile",
];

const lowerUuid = (value: unknown): string | null => (isUuid(value) ? value.toLowerCase() : null);
const oneOf = <T extends string>(values: readonly T[], value: unknown): T | null =>
  values.find((v) => v === value) ?? null;
const epochMs = (value: unknown): number | null =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;

/** The order's id as the store keys it (lower case), or `null` for an item that names no order. */
export function orderIdOf(item: unknown): string | null {
  return typeof item === "object" && item !== null ? lowerUuid((item as WireCommon).id) : null;
}

/**
 * The row of a wire order, or `null` when it names none (no id, account or symbol). `constants`
 * are BQ-6's; a WS item's own `trade_group_id` (contract-valid, not sent today) is used first.
 */
export function mapOrder(
  item: WsOrder | RestOrder,
  source: "ws" | "rest",
  accounts: ReadonlyMap<string, AccountInfo>,
  constants: OrderConstants = NO_CONSTANTS,
): OrderRowModel | null {
  const wire = item as WireCommon;
  const id = lowerUuid(wire.id);
  const accountId = lowerUuid(wire.exchange_account_id);
  if (id === null || accountId === null || typeof wire.symbol !== "string") return null;
  const account = accounts.get(accountId);
  const side = oneOf(["buy", "sell"] as const, wire.side);
  const orderType = oneOf(["market", "limit"] as const, wire.order_type);
  const intent = typeof wire.intent === "string" ? (wire.intent as OrderIntent) : null;
  const reduceOnly = wire.reduce_only === true;
  const closeOnTrigger = wire.close_on_trigger === true;
  const state = resolveState(wire.lifecycle_state, wire.state);
  const trigger = triggerOf(wire, reduceOnly);
  const tif = oneOf(TIFS, wire.time_in_force);
  const parentId = lowerUuid(wire.parent_order_id);
  const legId = lowerUuid(wire.trade_group_leg_id);
  const algo = oneOf(ALGOS, wire.algo_kind);
  const parent: ParentModel | null =
    parentId !== null
      ? { kind: "parent", id: parentId, algo }
      : legId !== null
        ? { kind: "leg", id: legId, algo: null }
        : null;
  const provenance = oneOf(PROVENANCES, wire.provenance) ?? constants.provenance;
  const price = amount(wire.price);
  const positionIdx = wire.position_idx === 1 || wire.position_idx === 2 ? wire.position_idx : 0;
  const exchangeOrderId =
    typeof wire.exchange_order_id === "string" && wire.exchange_order_id !== ""
      ? wire.exchange_order_id
      : null;
  const environment = oneOf(ENVIRONMENTS, wire.environment) ?? account?.environment ?? null;
  const base = {
    id,
    accountId,
    symbol: wire.symbol,
    intent,
    reduceOnly,
    exchangeOrderId,
    provenance,
    positionIdx,
  } as const;
  return {
    ...base,
    accountLabel: account?.label ?? null,
    environment,
    baseCoin: USDT.exec(wire.symbol)?.[1] ?? "",
    side,
    sideLabel: sideWords(side),
    orderType,
    typeLabel: typeWords(orderType, intent),
    purpose: purposeWord(intent),
    qty: quantity(wire.qty),
    filledQty: quantity(wire.filled_qty),
    avgFillPrice: amount(wire.avg_fill_price),
    price,
    isMarket: orderType === "market" && price === null,
    trigger,
    timeInForce: tif,
    tifLabel: tifWords(tif),
    closeOnTrigger,
    flagsLabel: flagsWords(reduceOnly, closeOnTrigger),
    createdAtMs: constants.createdAtMs,
    parent,
    parentLabel: parentWords(parent),
    tradeGroupId: lowerUuid(wire.trade_group_id) ?? constants.tradeGroupId,
    protective: protectiveOf(base),
    orderLinkId: typeof wire.order_link_id === "string" ? wire.order_link_id : null,
    state,
    conditional: trigger !== null && state.lifecycle !== "triggered",
    change: oneOf(CHANGES, wire.change),
    updatedAtMs: epochMs(wire.updated_at_ms),
    source,
  };
}

/**
 * The State cell's words (D01 D2): "Partial 0.050/0.150" with its figures, else the word. The
 * pending, unconfirmed and rejected amend moments are S-12's deck lines, laid over it by the row.
 */
export function stateLabel(
  row: Pick<OrderRowModel, "state" | "filledQty" | "qty">,
  figure: Figure = asSent,
): string {
  if (row.state.lifecycle !== "partially_filled" || row.filledQty === null || row.qty === null)
    return row.state.word;
  return `${row.state.word} ${figure(row.filledQty)}/${figure(row.qty)}`;
}

/** The Trigger cell: its words, or "—" without a trigger. */
export function triggerLabel(row: Pick<OrderRowModel, "trigger">, figure: Figure = asSent): string {
  return row.trigger === null ? ORDER_TEXT.none.string : triggerWords(row.trigger, figure);
}

/** The Price cell: the limit, "Market" for a market order, else "—" (D02:268). */
export function priceLabel(
  row: Pick<OrderRowModel, "price" | "isMarket">,
  figure: Figure = asSent,
): string {
  if (row.isMarket) return ORDER_TEXT.marketPrice.string;
  return row.price === null ? ORDER_TEXT.none.string : figure(row.price);
}

/** REST `created_at` (RFC 3339) as epoch ms, or `null`. */
export function createdAtOf(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/** What a REST order says once and for all (BQ-6): kept per order id, never over WS state. */
export function constantsOf(item: RestOrder): OrderConstants {
  const wire = item as WireCommon & { readonly created_at?: unknown };
  return {
    createdAtMs: createdAtOf(wire.created_at),
    provenance: oneOf(PROVENANCES, wire.provenance),
    tradeGroupId: lowerUuid(wire.trade_group_id),
  };
}

/** The resolved state of a raw wire item, for the store's rules (`removed`, the linger). */
export function stateOfItem(item: unknown): OrderStateModel {
  const wire = (typeof item === "object" && item !== null ? item : {}) as WireCommon;
  return resolveState(wire.lifecycle_state, wire.state);
}
