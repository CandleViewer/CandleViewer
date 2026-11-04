/**
 * Running sums over fills and what they show (E29-S04 #979; E29-D03 D-6, D-7, §3.4, §3.9; BQ-8).
 * Σ price × qty, Σ qty and Σ maker qty over the trades, and Σ fee per coin over every fill, so a
 * new fill costs constant work; from them the average, the maker/taker split by quantity and
 * slippage against the intended price in price, ticks and USDT. Exact decimals (`decimal.ts`),
 * never a float, and D03:153's one display rounding: averages and slippage one decimal more than
 * the tick, money two places, the split whole percent summing to 100, the minus U+2212, and every
 * total from the raw sums, never from rounded cells.
 *
 * In order scope Filled and Avg price are the order's own (`filled_qty`, `avg_fill_price`, D-6);
 * the split, the fees and the slippage come from the fills. Funding and settlement rows count in
 * the fees only: their price and quantity are no trade's (D03 §3.6).
 */
import type { generated } from "@candleviewer/protocol";
import {
  abs,
  add,
  div,
  isZero,
  mul,
  neg,
  normalise,
  parseDecimal,
  round,
  sign,
  sub,
  toPlain,
  ZERO,
  type Decimal,
} from "../../model/decimal";
import { TRADE_KINDS, type FillRowModel } from "./fillRow";

export interface FillSums {
  readonly fills: number;
  readonly trades: number;
  /** Σ q and Σ p·q over the trades. */
  readonly qty: Decimal;
  readonly value: Decimal;
  readonly makerQty: Decimal;
  /** Trades whose liquidity flag is missing: the split is then "—", never a guess (D-9). */
  readonly unknownLiquidity: number;
  /** Σ of the wire's fee per coin, positive when paid. */
  readonly fees: ReadonlyMap<string, Decimal>;
  /** Fills whose fee or coin is not reported: no coin is assumed, the total is provisional. */
  readonly feesPending: number;
  readonly firstMs: number | null;
  readonly lastMs: number | null;
}

export const NO_FILLS: FillSums = Object.freeze({
  fills: 0,
  trades: 0,
  qty: ZERO,
  value: ZERO,
  makerQty: ZERO,
  unknownLiquidity: 0,
  fees: new Map<string, Decimal>(),
  feesPending: 0,
  firstMs: null,
  lastMs: null,
});

/** `sums` with one more fill: O(1) (the fee map holds a coin or two). */
export function addFill(sums: FillSums, row: FillRowModel): FillSums {
  const price = parseDecimal(row.price);
  const qty = parseDecimal(row.qty);
  const trade = TRADE_KINDS.has(row.type.kind) && price !== null && qty !== null;
  const fee = parseDecimal(row.fee);
  let fees = sums.fees;
  if (fee !== null && row.feeCoin !== null) {
    const next = new Map(sums.fees);
    next.set(row.feeCoin, add(sums.fees.get(row.feeCoin) ?? ZERO, fee));
    fees = next;
  }
  return {
    fills: sums.fills + 1,
    trades: sums.trades + (trade ? 1 : 0),
    qty: trade ? add(sums.qty, qty) : sums.qty,
    value: trade ? add(sums.value, mul(price, qty)) : sums.value,
    makerQty: trade && row.maker === true ? add(sums.makerQty, qty) : sums.makerQty,
    unknownLiquidity: sums.unknownLiquidity + (trade && row.maker === null ? 1 : 0),
    fees,
    feesPending: sums.feesPending + (fee === null || row.feeCoin === null ? 1 : 0),
    firstMs: sums.firstMs === null ? row.tsMs : Math.min(sums.firstMs, row.tsMs),
    lastMs: sums.lastMs === null ? row.tsMs : Math.max(sums.lastMs, row.tsMs),
  };
}

export const sumFills = (rows: readonly FillRowModel[]): FillSums => rows.reduce(addFill, NO_FILLS);

/** D03:153: one decimal more than the tick (a 0.1 tick shows 63,414.02); `null` for no tick. */
export function pricePlaces(tick: string | null): number | null {
  const t = parseDecimal(tick);
  return t === null || t.units <= 0n ? null : normalise(t).scale + 1;
}

/** Σ p·q ÷ Σ q at `places`; `null` with no trade. */
export const averageOf = (sums: FillSums, places: number): Decimal | null =>
  div(sums.value, sums.qty, places);

/**
 * The maker/taker split by quantity (D03:153): whole percent, maker rounded half away from zero
 * and taker its complement, so the two always sum to 100; `null` with no trade or a missing flag.
 */
export function splitOf(sums: FillSums): { readonly maker: string; readonly taker: string } | null {
  if (sums.unknownLiquidity > 0) return null;
  const pct = div(mul(sums.makerQty, { units: 100n, scale: 0 }), sums.qty, 0);
  if (pct === null) return null;
  const maker = pct.units > 100n ? 100n : pct.units < 0n ? 0n : pct.units;
  return { maker: maker.toString(), taker: (100n - maker).toString() };
}

export interface FeeTotal {
  readonly coin: string;
  /** −Σ fee, the cash effect (BQ-11). */
  readonly cash: Decimal;
  readonly direction: "paid" | "received" | null;
}

/** One total per coin, in coin order; a pending fee adds none (`feesPending` says so). */
export function feesOf(sums: FillSums): readonly FeeTotal[] {
  return [...sums.fees.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([coin, fee]) => {
      const s = sign(fee);
      return { coin, cash: neg(fee), direction: s > 0 ? "paid" : s < 0 ? "received" : null };
    });
}

/** What an order says of its intended price: `22` `OrderWithEvents`'s own members (C-4.16). */
export type OrderTerms = Pick<
  generated.rest.components["schemas"]["OrderWithEvents"],
  "order_type" | "price" | "trigger_price" | "events"
>;

export interface Intent {
  readonly kind: "limit" | "trigger";
  readonly price: Decimal;
  /** An `amend_ack` was recorded: measured against the current price (D-7, G2). */
  readonly amended: boolean;
}

/**
 * BQ-8: a limit order's limit price; else its trigger price (a stop-market exit); none for a
 * market order without a trigger, whose slippage reads "—" (D-7). A market order's `price` is
 * never an intent: the venue may carry a protection price there.
 */
export function intentOf(order: OrderTerms): Intent | null {
  const amended = (order.events ?? []).some((e) => e.kind === "amend_ack");
  const limit = order.order_type === "limit" ? parseDecimal(order.price) : null;
  if (limit !== null && limit.units > 0n) return { kind: "limit", price: limit, amended };
  const trigger = parseDecimal(order.trigger_price);
  if (trigger !== null && trigger.units > 0n) return { kind: "trigger", price: trigger, amended };
  return null;
}

export interface Slippage {
  /** Signed, positive worse (D-7), at one decimal more than the tick. */
  readonly price: Decimal;
  /** The magnitude in ticks, at one place without trailing zeros ("59.8", "200"). */
  readonly ticks: Decimal;
  /** The magnitude in the quote coin, two places, from the raw sums. */
  readonly cash: Decimal;
  readonly direction: "better" | "worse" | "at";
  readonly intent: Intent;
}

/**
 * Slippage of the trades in `sums` against `intent` (D-7; D03 §3.4's arithmetic): worse is a buy
 * above it or a sell below it. `null` without an intent, a tick or a trade ("—").
 */
export function slippageOf(
  sums: FillSums,
  side: "buy" | "sell",
  intent: Intent | null,
  tick: string | null,
): Slippage | null {
  const places = pricePlaces(tick);
  const t = parseDecimal(tick);
  if (intent === null || places === null || t === null || isZero(sums.qty)) return null;
  const paid = sub(sums.value, mul(intent.price, sums.qty)); // Σ (p − intent) · q
  const worse = side === "buy" ? paid : neg(paid);
  const price = div(worse, sums.qty, places);
  const ticks = div(abs(worse), mul(sums.qty, t), 1);
  if (price === null || ticks === null) return null;
  const s = sign(worse);
  return {
    price,
    ticks: normalise(ticks),
    cash: round(abs(worse), 2),
    direction: s > 0 ? "worse" : s < 0 ? "better" : "at",
    intent,
  };
}

/** U+2212, the minus of every signed figure (D03:153, D02 D-7). */
export const MINUS = "−";

/**
 * Display text of `d` (`places` omitted: its own scale): "," grouping, U+2212 for a minus, "+" on a
 * positive value when asked, zero unsigned. `packages/ui`'s `decimalText` is internal, and these
 * figures are composed into sentences, so the rule is restated here.
 */
export function figure(d: Decimal, places?: number, plus = false): string {
  const shown = places === undefined ? d : round(d, places);
  const text = toPlain(abs(shown));
  const [whole = "", fraction] = text.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  const s = sign(shown);
  return `${s < 0 ? MINUS : s > 0 && plus ? "+" : ""}${body}`;
}
