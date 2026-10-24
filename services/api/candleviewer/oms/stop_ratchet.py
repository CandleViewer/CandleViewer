"""The amended stop's rules (E29-T04 #913, slice 4), pure and `Decimal` only: Q3's scope for an
amend's TP/SL change, and Q4's one loosening check (24 Sec.8.8 rule 5's trigger half, Full mode),
run as the request-side service's pre-check and again by the command port's writer before any
record or send; E29-T07 reuses it. Its refusal is 403 `risk_limit_breached` at the route, audited
`orders.amend` denied, never E29-T07's `sl.loosen_refused`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Final, Literal

from candleviewer.storage.repositories.orders import OrderSide, TpslMode
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

from .errors import RULE_NATIVE_STOP_REQUIRED, RULE_REDUCE_ONLY_TPSL

__all__ = [
    "LOOSER_THAN_ORDER", "LOOSER_THAN_RECORD", "RULE_TPSL_AFTER_FILL",
    "RULE_TPSL_CLEAR_UNSUPPORTED", "RULE_TPSL_PARTIAL_MODE", "STOP_NOT_A_PRICE", "TPSL_SIDES",
    "RatchetReason", "loosens", "ratchet_refusal", "tpsl_scope_refusal",
]  # fmt: skip

TPSL_SIDES: Final = ("take_profit", "stop_loss")
#: Q3's named rules (400 at the route), beside the create's two (`errors.py`).
RULE_TPSL_CLEAR_UNSUPPORTED: Final = "tpsl_clear_unsupported"
RULE_TPSL_AFTER_FILL: Final = "tpsl_after_fill"
RULE_TPSL_PARTIAL_MODE: Final = "tpsl_partial_mode"
#: Why the ratchet refused (Q4).
STOP_NOT_A_PRICE: Final = "stop_not_a_price"
LOOSER_THAN_ORDER: Final = "looser_than_order"
LOOSER_THAN_RECORD: Final = "looser_than_record"
RatchetReason = Literal["stop_not_a_price", "looser_than_order", "looser_than_record"]


def _price(value: Decimal) -> bool:
    """A finite price above zero (finite first: ordering a NaN raises)."""
    return value.is_finite() and value > 0


def tpsl_scope_refusal(
    requested: Mapping[str, Decimal | None],
    *,
    reduce_only: bool,
    tpsl_mode: TpslMode,
    filled_qty: Decimal,
) -> str | None:
    """Q3: the rule an amend's TP/SL change breaks, else None. `requested` holds the sides named,
    None for one asked cleared (as no price above zero: the venue reads `0` as "remove"). Checked in
    order: reduce-only, a clear (stop-loss, then take-profit), Partial mode, a fill."""
    if not any(side in requested for side in TPSL_SIDES):
        return None
    if reduce_only:
        return RULE_REDUCE_ONLY_TPSL
    clears = (
        ("stop_loss", RULE_NATIVE_STOP_REQUIRED),
        ("take_profit", RULE_TPSL_CLEAR_UNSUPPORTED),
    )
    for side, rule in clears:
        if side in requested and ((value := requested[side]) is None or not _price(value)):
            return rule
    if tpsl_mode != "Full":
        return RULE_TPSL_PARTIAL_MODE
    if filled_qty != 0:
        return RULE_TPSL_AFTER_FILL
    return None


def loosens(side: OrderSide, held: Decimal, requested: Decimal) -> bool:
    """`requested` sits further from the market than `held`: below it for a long (`Buy`), above it
    for a short (`Sell`); equal never loosens. `ValueError` for any other side (fail closed)."""
    if side == "Buy":
        return requested < held
    if side == "Sell":
        return requested > held
    raise ValueError("a position side is Buy or Sell")


def ratchet_refusal(
    *,
    side: OrderSide,
    requested: Decimal,
    current: Decimal | None,
    in_force: Iterable[RecordedStopRow],
) -> RatchetReason | None:
    """Q4: why `requested`, a new stop-loss for a `side` entry, is refused, else None. Compared with
    the order's `current` stop (None: it holds none) and each `in_force` row that is a Full-mode
    stop-loss in force on the same side; a stop that is no finite price above zero fails closed."""
    if not _price(requested):
        return STOP_NOT_A_PRICE
    if current is not None:
        if not _price(current):
            return STOP_NOT_A_PRICE
        if loosens(side, current, requested):
            return LOOSER_THAN_ORDER
    same = ("in_force", "stop_loss", "Full", side)
    for row in in_force:
        if (row.status, row.kind, row.tpsl_mode, row.position_side) != same:
            continue
        if not _price(row.trigger_price):
            return STOP_NOT_A_PRICE
        if loosens(side, row.trigger_price, requested):
            return LOOSER_THAN_RECORD
    return None
