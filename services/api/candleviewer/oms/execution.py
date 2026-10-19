"""`apply_execution`: an order's cumulative fill values after one execution (E29-T03, #847).

Pure: no I/O, no clock, no interpreter (a fill is a per-order event, never a hot path; C-2.20).
Fields follow 24-internal-schemas.md Sec.8.1 and the numeric(38,18) columns of 21 Sec.3.3.4.
Every input and total must fit numeric(38,18) as it stands (`require_money`), so each sum and
product is exact under `_EXACT`, a local context with `Inexact` trapped; the thread's context is
never used. `avg_price` is the one division, of the exact totals, rounded once (half-even) to 18
places, so fills in any order give the same result (INV-B1-a). A fill the order cannot absorb
raises `ExecutionRefused` (OM-T04) and is never clamped (INV-1). The `exec_id` dedupe (24 Sec.8.2
S4) is the caller's. The OMS facade sets `apply_fields` into the B1 binding (`set_fill_core`)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from decimal import Context, Decimal, Inexact, InvalidOperation, Overflow
from fractions import Fraction
from typing import Final

from candleviewer.storage.repositories.orders import require_money

from .errors import ExecutionRefused

#: numeric(38,18) keeps 18 places; two such values multiply to at most 76 digits.
_SCALE: Final = 18
_EXACT: Final = Context(prec=80, traps=[InvalidOperation, Overflow, Inexact])
#: A bound on hostile data (OM-T04), not a fee model: no fee or rebate passes 1% of the value.
MAX_FEE_RATE: Final = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Fill:
    """One execution (24 Sec.8.1): `qty` at `price`, `fee` at `fee_rate`; both < 0 for a rebate."""

    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_rate: Decimal


@dataclass(frozen=True, slots=True)
class OrderFills:
    """An order's `qty` and its cumulative fill values (21 Sec.3.3.4)."""

    qty: Decimal
    filled_qty: Decimal = Decimal(0)
    cum_exec_value: Decimal = Decimal(0)
    fee_paid: Decimal = Decimal(0)
    avg_price: Decimal | None = None

    @property
    def leaves_qty(self) -> Decimal:
        return _EXACT.subtract(self.qty, self.filled_qty)


def apply_execution(order: OrderFills, fill: Fill) -> OrderFills:
    """*order*'s totals after *fill*; `ExecutionRefused` when the fill cannot apply (OM-T04)."""
    _require_fit(order, fill)
    if order.qty <= 0 or not 0 <= order.filled_qty <= order.qty:
        raise ExecutionRefused("the order's qty or filled_qty is out of range")
    if fill.qty <= 0 or fill.price <= 0:
        raise ExecutionRefused("an execution needs a qty and a price above zero")
    filled = _EXACT.add(order.filled_qty, fill.qty)
    if filled > order.qty:
        raise ExecutionRefused("the execution takes filled_qty past qty (INV-1)")
    notional = _EXACT.multiply(fill.price, fill.qty)
    if fill.fee.copy_abs() > _EXACT.multiply(notional, MAX_FEE_RATE) or (
        fill.fee != 0 and (fill.fee < 0) != (fill.fee_rate < 0)
    ):
        raise ExecutionRefused("the fee is past MAX_FEE_RATE of the value or against fee_rate")
    value = _EXACT.add(order.cum_exec_value, notional)
    fee = _EXACT.add(order.fee_paid, fill.fee)
    totals = OrderFills(order.qty, filled, value, fee, _average(value, filled))
    _require_fit(totals)
    return totals


def apply_fields(
    order: Mapping[str, Decimal], fill: Mapping[str, Decimal]
) -> dict[str, Decimal | None]:
    """`apply_execution` over `OrderFills` and `Fill` field maps, with `leaves_qty` added."""
    after = apply_execution(OrderFills(**order), Fill(**fill))
    return asdict(after) | {"leaves_qty": after.leaves_qty}


def _require_fit(*rows: Fill | OrderFills) -> None:
    """Each money field fits numeric(38,18) exactly; the error names the field, never a value."""
    try:
        for row in rows:
            for field in fields(row):
                value = getattr(row, field.name)
                if value is not None:
                    require_money(field.name, value)
    except (TypeError, ValueError) as exc:
        raise ExecutionRefused(str(exc)) from exc


def _average(value: Decimal, qty: Decimal) -> Decimal:
    """The exact quotient, rounded once (half-even) to 18 places: `round` of a `Fraction`."""
    units = round(Fraction(value) / Fraction(qty) * 10**_SCALE)
    return Decimal(units).scaleb(-_SCALE, _EXACT)
