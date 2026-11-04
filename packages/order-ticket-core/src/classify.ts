/**
 * Entry classification, mirroring `placeOrder` (`22`, the native-SL invariant, SR-E29-01): the
 * server classes an order by its effect on the exchange-truth position, never by its label. An
 * order that is not reduce-only, or whose quantity exceeds the position it reduces, is an entry
 * whatever its `intent`, and every entry carries a native stop (C-2.6).
 *
 * The client knows less than the server, so this mirror fails closed (BQ 5 ruling, #984): an
 * explicit `reduce_only` order is classed "not an entry" only when the client holds a known,
 * opposite-side position at least as large as the order's quantity. An unknown position, no
 * position, a same-side position, a quantity the client cannot know before sizing, or one above
 * the position, is an entry. The server stays the authority (C-2.12); this only decides what the
 * ticket blocks and shows.
 */
import { ZERO, div, gt, lte, mul, parseDecimal, sign, type Decimal } from "./decimal.js";
import type { OrderDraft, OrderSide, PositionRead, TicketTarget } from "./model.js";

/** Why an order counts as an entry. */
export type EntryReason =
  /** `reduce_only` is not set: every such order may open or add (SR-E29-01). */
  | "not_reduce_only"
  /** The side is neither `buy` nor `sell` (data that crossed a worker boundary unchecked). */
  | "side_invalid"
  /**
   * The position has not been read, the read failed, or it is not this order's: another symbol
   * or account, or a group target (one read per account lands with S3 / S4). Fail closed.
   */
  | "position_unknown"
  /** The read is known and no opposite-side position is open, so nothing is reduced. */
  | "no_position"
  /** The quantity is not knowable before sizing (a mode but `fixed_qty` or `pct_position`). */
  | "qty_unknown"
  /** The quantity is above the position it reduces. */
  | "exceeds_position";

export type EntryClass =
  | { readonly entry: true; readonly reason: EntryReason }
  | {
      readonly entry: false;
      /** The size of the position the order reduces (a positive decimal). */
      readonly positionSize: Decimal;
      /** The order's quantity (`fixed_qty`'s, or `pct_position`'s share of the position). */
      readonly qty: Decimal;
    };

/** The position side an order on `side` closes: a buy closes a short, a sell a long. */
export const closesSide = (side: OrderSide): "long" | "short" =>
  side === "buy" ? "short" : "long";

/**
 * The size of the known position the draft's side would reduce, `null` when none is, or
 * `"unknown"` when the read cannot be trusted for this order: unread, a group target, or a
 * position (or a draft) on another symbol or account than the single target's (C-2.6, BQ 5).
 */
export function reducibleSize(
  draft: OrderDraft,
  read: PositionRead,
  target: TicketTarget,
): Decimal | null | "unknown" {
  if (read.status === "unknown" || target.kind !== "account") return "unknown";
  if (draft.exchangeAccountId !== target.accountId) return "unknown";
  const position = read.position;
  if (position === null) return null;
  if (position.symbol !== draft.symbol || position.exchange_account_id !== target.accountId) {
    return "unknown";
  }
  if (position.side !== closesSide(draft.side)) return null;
  const size = parseDecimal(position.size);
  return size !== null && sign(size) > 0 ? size : null;
}

/**
 * The quantity a reduce-only draft asks for, when the client can know it before sizing:
 * `fixed_qty`'s `qty`, or `pct_position`'s share of `positionSize` (exact, at the size's scale
 * plus four digits, floored: a share is never rounded up into an entry).
 */
export function knownQty(draft: OrderDraft, positionSize: Decimal): Decimal | null {
  const { sizing } = draft;
  if (sizing.mode === "fixed_qty") {
    const qty = parseDecimal(sizing.qty);
    return qty !== null && sign(qty) > 0 ? qty : null;
  }
  if (sizing.mode === "pct_position") {
    const pct = parseDecimal(sizing.pct);
    if (pct === null || sign(pct) <= 0) return null;
    const share = div(
      mul(positionSize, pct),
      { units: 100n, scale: 0 },
      positionSize.scale + 4,
      "floor",
    );
    return share !== null && gt(share, ZERO) ? share : null;
  }
  return null;
}

/** Classify a draft as an entry or not, as `22` `placeOrder` would, failing closed. */
export function classify(draft: OrderDraft, read: PositionRead, target: TicketTarget): EntryClass {
  if (draft.side !== "buy" && draft.side !== "sell") return { entry: true, reason: "side_invalid" };
  if (!draft.reduceOnly) return { entry: true, reason: "not_reduce_only" };
  const size = reducibleSize(draft, read, target);
  if (size === "unknown") return { entry: true, reason: "position_unknown" };
  if (size === null) return { entry: true, reason: "no_position" };
  const qty = knownQty(draft, size);
  if (qty === null) return { entry: true, reason: "qty_unknown" };
  if (!lte(qty, size)) return { entry: true, reason: "exceeds_position" };
  return { entry: false, positionSize: size, qty };
}
