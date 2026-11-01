/**
 * The order-flow grids' words (E47-S02, #1358 BQ-12). PROPOSED, every string: no merged design fixes them yet
 * (E18-D04 #498 the footprint announcement policy, E21-D06 #506 the ladder, E47-D06 #1305 the canvas a11y design).
 * Each is a deviation row for those tickets to confirm or replace; prices and sizes read through `format.ts`, so a
 * price reads as SCR-045 reads it.
 */

export type BookSide = "bid" | "ask";
export type OrderSide = "buy" | "sell";

/** Footprint cell sentence parts (CMP-109; 05 §4.3: the imbalance state as a word). */
export const CELL = {
  bid: (v: string): string => `bid ${v}`,
  ask: (v: string): string => `ask ${v}`,
  delta: (v: string): string => `delta ${v}`,
  imbalance: { bid: "bid imbalance", ask: "ask imbalance", none: "no imbalance" },
  estimated: "estimated",
} as const;

/** Ladder row sentence parts (CMP-108). */
export const LADDER = {
  side: { bid: "bid side", ask: "ask side", spread: "inside the spread" },
  ownOrder: (side: OrderSide, qty: string): string => `your ${side} order ${qty} working`,
  ownOrders: (n: number): string => `${n} of your orders working`,
  position: (side: "long" | "short", qty: string): string => `your ${side} position ${qty}`,
} as const;

/** Heatmap cell readout on focus (CMP-111; 05 §4.1: price, size and side). */
export const HEATMAP = {
  size: (v: string): string => `resting ${v}`,
  side: { bid: "bid side", ask: "ask side" },
} as const;

/** The persistent side legend (CMP-113's text convention; 05 §4.1). */
export const LEGEND = {
  name: "Book sides",
  bid: "Bid: resting buy liquidity, left column, below the best price",
  ask: "Ask: resting sell liquidity, right column, above the best price",
} as const;

/** Visible words on the marks (05 §4.3: the word, not hue alone). */
export const MARK = {
  imbalance: { bid: "Bid imbalance", ask: "Ask imbalance" },
  side: { bid: "Bid", ask: "Ask" },
} as const;

/** The keyboard-order read-back (05 §3.3.5: the resolved per-account quantities, before commit). */
export const READBACK = {
  kind: { limit: "limit", aggressive: "aggressive" },
  head: (side: OrderSide, kind: string, symbol: string, price: string): string =>
    `${side === "buy" ? "Buy" : "Sell"} ${kind} ${symbol} at ${price}`,
  leg: (account: string, qty: string): string => `${account} ${qty}`,
  total: (accounts: number, qty: string): string =>
    `${accounts} ${accounts === 1 ? "account" : "accounts"}, total ${qty}`,
  /** Said instead of any account when a leg is outside the caller's access: no name, no id. */
  refused: "Order not shown: an account is not available to you",
  empty: "Order not shown: no account selected",
  zero: "Order not shown: a quantity is zero",
} as const;

/** The fill line, assertive (05 §6.2: order filled is a discrete event). */
export const FILL = {
  line: (side: OrderSide, qty: string, symbol: string, price: string, account: string): string =>
    `Filled: ${side === "buy" ? "bought" : "sold"} ${qty} ${symbol} at ${price}, ${account}`,
  partial: "partial",
} as const;

export const GRID_NAME = {
  ladder: (symbol: string): string => `${symbol} order book ladder`,
} as const;
