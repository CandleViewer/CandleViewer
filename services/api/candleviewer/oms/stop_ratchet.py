"""The amended stop's rules (E29-T04 #913, slice 4): what an amend may change on an entry's
take-profit and stop-loss (the orchestrator's Q3 ruling), and the one loosening check (Q4; 24
Sec.8.8 rule 5's trigger half, Full mode), which the request-side service runs as its pre-check and
the command port's writer runs again before any record or send. E29-T07 reuses `ratchet_refusal`.

**Scope (Q3).** An amend may change TP or SL only on an unfilled, Full-mode entry that is not
reduce-only. A side asked cleared (`None`, or no price above zero: the venue reads `0` as "remove")
is refused: the stop-loss as `native_stop_required` (C-2.6, for good), the take-profit as
`tpsl_clear_unsupported` (B1 cannot record a clear).

**The ratchet (Q4).** A stop never moves away from the market. For a long (`Buy`) a stop below the
held one loosens it; for a short (`Sell`) one above it does. An equal stop does not loosen. The
request is compared with the order's current stop and with each stop-loss record in force for the
position's key in Full mode on the same side. A requested or held stop that is no finite price above
zero refuses (fail closed). A refusal is 403 `risk_limit_breached` at the route, audited
`orders.amend` denied, never E29-T07's `sl.loosen_refused`.

Pure functions, no I/O; prices are compared as `Decimal`, never as `float`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Final, Literal

from candleviewer.storage.repositories.orders import OrderSide, TpslMode
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

from .errors import RULE_NATIVE_STOP_REQUIRED, RULE_REDUCE_ONLY_TPSL

__all__ = [
    "LOOSER_THAN_ORDER",
    "LOOSER_THAN_RECORD",
    "RULE_TPSL_AFTER_FILL",
    "RULE_TPSL_CLEAR_UNSUPPORTED",
    "RULE_TPSL_PARTIAL_MODE",
    "STOP_NOT_A_PRICE",
    "TPSL_SIDES",
    "RatchetReason",
    "loosens",
    "ratchet_refusal",
    "tpsl_scope_refusal",
]

#: The amend's TP/SL sides.
TPSL_SIDES: Final = ("take_profit", "stop_loss")
#: Q3's named rules (400 at the route); `native_stop_required` and `reduce_only_tpsl` are the
#: create's (`errors.py`).
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
    """Q3: the rule an amend's TP/SL change breaks, else None. `requested` holds the sides the
    amend names (`TPSL_SIDES`), `None` for a side asked cleared; an amend naming neither is out of
    scope here and passes. Checked in this order: a reduce-only order, a clear (stop-loss, then
    take-profit), Partial mode, then a fill."""
    named = [side for side in TPSL_SIDES if side in requested]
    if not named:
        return None
    if reduce_only:
        return RULE_REDUCE_ONLY_TPSL
    for side, rule in (
        ("stop_loss", RULE_NATIVE_STOP_REQUIRED),
        ("take_profit", RULE_TPSL_CLEAR_UNSUPPORTED),
    ):
        if side in requested:
            value = requested[side]
            if value is None or not _price(value):
                return rule
    if tpsl_mode != "Full":
        return RULE_TPSL_PARTIAL_MODE
    if filled_qty != 0:
        return RULE_TPSL_AFTER_FILL
    return None


def loosens(side: OrderSide, held: Decimal, requested: Decimal) -> bool:
    """`requested` sits further from the market than `held` for a `side` position: below it for a
    long (`Buy`), above it for a short (`Sell`). Equal never loosens. `ValueError` for any other
    side (fail closed)."""
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
    """Q4, the one loosening check: why `requested`, a new stop-loss for a `side` entry, is
    refused, else None. It is compared with the order's `current` stop (None: the order holds
    none) and with every row of `in_force` that is a stop-loss in force, in Full mode, on the
    same side; other rows are not this check's. A requested or held stop that is no finite price
    above zero refuses (fail closed)."""
    if not _price(requested):
        return STOP_NOT_A_PRICE
    if current is not None:
        if not _price(current):
            return STOP_NOT_A_PRICE
        if loosens(side, current, requested):
            return LOOSER_THAN_ORDER
    for row in in_force:
        if (row.status, row.kind, row.tpsl_mode, row.position_side) != (
            "in_force",
            "stop_loss",
            "Full",
            side,
        ):
            continue
        if not _price(row.trigger_price):
            return STOP_NOT_A_PRICE
        if loosens(side, row.trigger_price, requested):
            return LOOSER_THAN_RECORD
    return None
