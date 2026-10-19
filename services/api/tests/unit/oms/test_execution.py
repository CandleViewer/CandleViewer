"""`apply_execution` (E29-T03 #847): exact totals, one rounding, INV-1, OM-T04 refusals."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.oms.errors import ExecutionRefused
from candleviewer.oms.execution import Fill, OrderFills, apply_execution

D = Decimal
MAX = "99999999999999999999.999999999999999999"  # numeric(38,18)'s largest value


def _fill(qty: str, price: str, fee: str = "0", rate: str = "") -> Fill:
    """A fill whose `fee_rate`, unless given, has its fee's sign (a rebate's is negative)."""
    return Fill(D(qty), D(price), D(fee), D(rate or ("-0.0001" if fee[0] == "-" else "0.0002")))


def test_apply_execution_partial_partial_full_sums_exactly() -> None:
    order = OrderFills(D("1"))
    steps = [("0.3", "63000", "0.1"), ("0.3", "63010.5", "-0.02"), ("0.4", "63020.25", "0.3")]
    seen = []
    for qty, price, fee in steps:
        order = apply_execution(order, _fill(qty, price, fee))
        seen.append((order.filled_qty, order.leaves_qty))
    assert seen == [(D("0.3"), D("0.7")), (D("0.6"), D("0.4")), (D("1"), 0)]
    sums = (order.cum_exec_value, order.fee_paid, order.avg_price)  # 18900 + 18903.15 + 25208.1
    assert sums == (D("63011.25"), D("0.38"), D("63011.250000000000000000"))


def test_apply_execution_divides_once_rounding_half_even_to_18_places() -> None:
    thirds = apply_execution(apply_execution(OrderFills(D("3")), _fill("1", "1")), _fill("2", "2"))
    assert thirds.avg_price == D("1.666666666666666667")
    tie = OrderFills(D("2"), D("1"), D("0.000000000000000002"))
    assert apply_execution(tie, _fill("1", "0.000000000000000003")).avg_price == D("2E-18")


@pytest.mark.parametrize(
    ("order", "fill"),
    [
        (OrderFills(D("1"), D("0.9"), D("9")), _fill("0.2", "10")),  # an overfill: never clamped
        (OrderFills(D("0")), _fill("1", "1")),
        (OrderFills(D("1"), D("2")), _fill("1", "1")),
        (OrderFills(D("1"), D("-1")), _fill("1", "1")),
        (OrderFills(D("1")), _fill("0", "1")),
        (OrderFills(D("1")), _fill("1", "-1")),
        (OrderFills(D("1")), _fill("0.0000000000000000001", "1")),
        (OrderFills(D("1")), _fill("0.5", "0.000000000000000003")),
        (OrderFills(D("1")), _fill("1", "1", "NaN")),
        (OrderFills(D("1")), _fill("1", "1E+21")),
        (OrderFills(D("1")), _fill("1", "1", "-0.02")),  # a rebate past MAX_FEE_RATE
        (OrderFills(D("1")), _fill("1", "100", "-0.5", "0.0002")),  # a rebate at a positive rate
        (OrderFills(D(MAX)), _fill(MAX, MAX)),  # cum_exec_value past numeric(38,18), not Inexact
        (OrderFills(D("1")), Fill(cast(Decimal, 1.0), D("1"), D("0"), D("0"))),  # a float
    ],
)
def test_apply_execution_refuses_hostile_input(order: OrderFills, fill: Fill) -> None:
    with pytest.raises(ExecutionRefused):
        apply_execution(order, fill)


def _filled(order: OrderFills, fill: Fill) -> Decimal | None:
    """`filled_qty` after *fill*, or None when `apply_execution` refuses it."""
    try:
        return apply_execution(order, fill).filled_qty
    except ExecutionRefused:
        return None


_QTY = st.decimals(min_value=D("0.001"), max_value=D("5"), places=3)


@settings(max_examples=60, deadline=None, derandomize=True)
@given(qty=_QTY, fills=st.lists(st.tuples(_QTY, _QTY), max_size=8))
def test_apply_execution_keeps_inv_1(qty: Decimal, fills: list[tuple[Decimal, Decimal]]) -> None:
    filled = D(0)
    for fill_qty, price in fills:
        after = _filled(OrderFills(qty, filled), Fill(fill_qty, price, D(0), D(0)))
        assert after in (None, filled + fill_qty)  # applied exactly, never clamped
        assert (after is None) is (filled + fill_qty > qty)  # refused only past qty
        filled = after or filled
