/**
 * BQ 11's one table: each `validate()` rule → every message it may render through `messageFor`.
 * A key is a deck `ticket.order.v.*` key or the key an existing `by_code` row names
 * (`BY_CODE_KEYS`); `PENDING` is a rule (or variant) the deck has no sentence for yet (a deck
 * question on #919). The `satisfies` makes it exhaustive: a new `RuleId` fails the build.
 */
import type { DeckKey, RuleId } from "../src/index.js";

export const PENDING_ROW = "PENDING (deck question, #919)" as const;
type Outcome = DeckKey | typeof PENDING_ROW;

export const RULE_KEYS = {
  symbol_not_trading: [PENDING_ROW],
  account_not_targeted: [PENDING_ROW],
  // `refusal.leverage_unavailable` keys the preview's code, not this rule's: pending (#919).
  max_leverage: [PENDING_ROW],
  side_invalid: [PENDING_ROW],
  price_invalid: [PENDING_ROW],
  tick_size: ["ticket.order.v.price.tick"],
  sizing_mode_unsupported: [PENDING_ROW],
  sizing_value: [PENDING_ROW],
  // With no instrument grid the lot is unknown, so the sentence cannot be filled: pending.
  min_order_qty: ["ticket.order.v.qty.lot", PENDING_ROW],
  qty_step: ["ticket.reject.reason.lot"],
  // `ticket.reject.reason.lot` names the step, not a ceiling: not sentence-true here.
  max_order_qty: [PENDING_ROW],
  min_notional: ["ticket.order.v.notional.min"],
  native_stop_required: ["ticket.order.v.sl.required"],
  stop_unit_unsupported: [PENDING_ROW],
  // A stop or target at or past zero (`non_positive`) has no true sentence yet: pending.
  invalid_stop_distance: [
    "ticket.order.refusal.invalid_stop_distance",
    "ticket.order.v.sl.side.long",
    "ticket.order.v.sl.side.short",
    PENDING_ROW,
  ],
  take_profit_side: ["ticket.order.v.tp.side.long", "ticket.order.v.tp.side.short", PENDING_ROW],
  reduce_only_invalid: [PENDING_ROW],
  reduce_only_tpsl: [PENDING_ROW],
  post_only_cross: ["ticket.order.v.post_only.cross"],
  // An unread position is not "no open position" (code lens m2): pending.
  reduce_only_no_position: ["ticket.order.v.reduce_only.no_position", PENDING_ROW],
  reduce_only_exceeds_position: [PENDING_ROW],
  intent_mismatch: [PENDING_ROW],
} as const satisfies Record<RuleId, readonly Outcome[]>;
