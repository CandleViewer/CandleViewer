/**
 * The order-flow grids' words (E47-S02, #1358 BQ-12). PROPOSED, every string: no merged design fixes them yet
 * (E18-D04 #498 the footprint announcement policy, E21-D06 #506 the ladder, E47-D06 #1305 the canvas a11y design).
 * Each is a deviation row for those tickets to confirm or replace; prices and sizes read through `format.ts`, so a
 * price reads as SCR-045 reads it.
 */

export type BookSide = "bid" | "ask";
export type OrderSide = "buy" | "sell";
/** The order environments a keyboard order can target (C-2.11; testnet places no orders from the ladder). */
export type OrderEnv = "live" | "demo";

/** A value the row cannot show (a data fault): said as words, drawn as SCR-045's dash. */
export const UNAVAILABLE = { said: "not available", shown: "—" } as const;

/** Footprint cell sentence parts (CMP-109; 05 §4.3: the imbalance state as a word). */
export const CELL = {
  bid: (v: string): string => `bid ${v}`,
  ask: (v: string): string => `ask ${v}`,
  delta: (v: string): string => `delta ${v}`,
  /** Said only when flagged (05 §4.3); an unflagged cell says nothing about imbalance (a11y lens L-6). */
  imbalance: { bid: "bid imbalance", ask: "ask imbalance" },
  estimated: "estimated",
} as const;

/** Ladder row sentence parts (CMP-108). */
export const LADDER = {
  side: { bid: "bid side", ask: "ask side", spread: "inside the spread" },
  ownOrder: (side: OrderSide, qty: string): string => `your ${side} order ${qty} working`,
  ownOrders: (n: number): string => `${n} of your orders working`,
  position: (side: "long" | "short", qty: string): string => `your ${side} position ${qty}`,
  /** The visible twins of the own-order and position words (a11y lens M-3: not only in the name). */
  ownShown: (side: OrderSide, qty: string): string => `${side === "buy" ? "Buy" : "Sell"} ${qty}`,
  ownsShown: (n: number): string => `${n} orders`,
  positionShown: (side: "long" | "short", qty: string): string =>
    `${side === "long" ? "Long" : "Short"} ${qty}`,
  /** The empty ladder's line, in place of a grid with no rows (a11y lens L-4). */
  empty: "No price levels in the book",
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
  /** Lead with the order type, then the side ("Limit buy", "Aggressive buy"; a11y lens M-1). */
  kind: { limit: "Limit", aggressive: "Aggressive" },
  /** The environment as the top bar's badge says it (05 §4.1, C-2.11). */
  env: { live: "LIVE", demo: "DEMO" },
  head: (kind: string, side: OrderSide, symbol: string, env: string, price: string): string =>
    `${kind} ${side} ${symbol}, ${env}, at ${price}`,
  /** A colon parts a name from its quantity, so a name ending in a digit never runs into it. */
  leg: (account: string, qty: string): string => `${account}: ${qty}`,
  qty: (qty: string, unit: string | undefined): string =>
    unit === undefined ? qty : `${qty} ${unit}`,
  total: (accounts: number, qty: string): string =>
    `${accounts} ${accounts === 1 ? "account" : "accounts"}, total ${qty}`,
  /** Said instead of any account when a leg is outside the caller's access: no name, no id. */
  refused: "Order not shown: an account is not available to you",
  empty: "Order not shown: no account selected",
  zero: "Order not shown: a quantity is zero",
  duplicate: "Order not shown: an account is listed twice",
  envMismatch: "Order not shown: an account is in a different environment",
  ambiguous: "Order not shown: account names are ambiguous",
  invalid: "Order not shown: a price or quantity is not valid",
} as const;

/** The fill line, assertive (05 §6.2: order filled is a discrete event). The state leads (a11y lens M-2). */
export const FILL = {
  state: { full: "Filled", partial: "Partially filled" },
  line: (state: string, side: OrderSide, qty: string, symbol: string, price: string): string =>
    `${state}: ${side === "buy" ? "bought" : "sold"} ${qty} ${symbol} at ${price}`,
  account: (line: string, account: string): string => `${line}, ${account}`,
  /** The tail of a batch longer than `FILL_BATCH_CEILING`. */
  more: (n: number): string => `${n} more ${n === 1 ? "fill" : "fills"}`,
} as const;

export const GRID_NAME = {
  ladder: (symbol: string): string => `${symbol} order book ladder`,
} as const;
