"""The view-as classification of an amend (E29-T04 #913, the closing slice's CG10): which amends
are protective, so a viewing session may make them (22 "View-as session", Protective writes; 24
Sec.8.10; the ruling on the protective-write registry, 2026-10-20). Every component must be
protective. On `amendOrder` that is its stop-loss alone, given as a price: one that attaches the
order's missing stop, keeps it (re-arms the trigger in force) or tightens it. A take-profit, a
quantity, a price or a trigger is not, whatever the order-entry gate says of it, and nor is a stop
given as a distance, which only the exit service resolves (fail closed)."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.oms.exits import AmendTerms, protective_amend
from candleviewer.oms.ports import OffsetUnit, StopOffset
from candleviewer.oms.stop_ratchet import loosens
from candleviewer.storage.repositories.orders import OrderRow, OrderSide

D = Decimal


def _row(**over: Any) -> OrderRow:
    """The rig's limit buy entry: 0.010 at 60000, its stop 58000 and its take-profit 64000."""
    base: dict[str, Any] = dict.fromkeys(f.name for f in fields(OrderRow))
    base |= {
        "side": "Buy", "qty": D("0.010"), "price": D("60000"), "trigger_price": None,
        "stop_loss": D("58000"), "take_profit": D("64000"), "reduce_only": False,
    }  # fmt: skip
    return OrderRow(**(base | over))


def _stop(value: str, unit: OffsetUnit = "price") -> dict[str, StopOffset | None]:
    return {"stop_loss": StopOffset(unit, D(value))}


_TP = {"take_profit": StopOffset("price", D("64500"))}


@pytest.mark.parametrize(
    ("over", "terms", "admitted"),
    [
        ({}, AmendTerms(sides=_stop("58500")), True),
        ({}, AmendTerms(sides=_stop("58000")), True),
        ({"stop_loss": None}, AmendTerms(sides=_stop("57000")), True),
        ({"side": "Sell", "stop_loss": D("62000")}, AmendTerms(sides=_stop("61500")), True),
        ({}, AmendTerms(sides=_stop("57999")), False),
        ({"side": "Sell", "stop_loss": D("62000")}, AmendTerms(sides=_stop("62001")), False),
        ({}, AmendTerms(sides=_TP), False),
        ({}, AmendTerms(sides=_stop("58500") | _TP), False),
        ({}, AmendTerms(qty=D("0.005")), False),
        ({}, AmendTerms(qty=D("0.005"), sides=_stop("58500")), False),
        ({}, AmendTerms(price=D("60100"), sides=_stop("58500")), False),
        ({}, AmendTerms(trigger_price=D("61000"), sides=_stop("58500")), False),
        ({"reduce_only": True}, AmendTerms(trigger_price=D("59000")), False),
        ({}, AmendTerms(sides=_stop("10", "ticks")), False),
        ({}, AmendTerms(sides=_stop("1", "percent")), False),
        ({}, AmendTerms(sides=_stop("60000", "ticks")), False),  # as a price, it would tighten
        ({}, AmendTerms(sides=_stop("60000", "percent")), False),
        ({}, AmendTerms(sides={"stop_loss": None}), False),
        ({}, AmendTerms(sides=_stop("0")), False),
        ({"stop_loss": None}, AmendTerms(sides=_stop("0")), False),  # no held stop to judge by
        ({"stop_loss": None}, AmendTerms(sides=_stop("-5")), False),
        ({}, AmendTerms(sides=_stop("NaN")), False),
        ({"stop_loss": D("NaN")}, AmendTerms(sides=_stop("58500")), False),
        ({}, AmendTerms(), False),
    ],
    ids=[
        "tightens", "keeps", "attaches-a-missing-stop", "tightens-a-short", "loosens",
        "loosens-a-short", "take-profit", "stop-and-take-profit", "quantity-cut",
        "stop-and-quantity", "stop-and-price", "stop-and-trigger", "reduce-only-trigger",
        "stop-in-ticks", "stop-in-percent", "stop-in-ticks-a-price-would-tighten",
        "stop-in-percent-a-price-would-tighten", "stop-cleared", "stop-at-zero",
        "stop-at-zero-attached", "stop-below-zero-attached", "stop-no-number",
        "held-stop-no-number", "nothing",
    ],
)  # fmt: skip
def test_an_amend_is_protective_only_when_its_stop_alone_adds_keeps_or_tightens_protection(
    over: dict[str, Any], terms: AmendTerms, admitted: bool
) -> None:
    assert protective_amend(_row(**over), terms) is admitted


_PRICES = st.decimals(min_value=D("0.01"), max_value=D("1000000"), places=2)
_SIDES: tuple[OrderSide, ...] = ("Buy", "Sell")


@given(side=st.sampled_from(_SIDES), held=_PRICES, asked=_PRICES)
def test_a_stop_that_loosens_is_never_protective_and_any_other_is(
    side: OrderSide, held: Decimal, asked: Decimal
) -> None:
    """C-2.6: a viewing session never loosens a stop. A long's stop may only rise and a short's only
    fall (the ratchet's own `loosens`); equal re-arms the trigger in force."""
    row = _row(side=side, stop_loss=held)
    loose = loosens(side, held, asked)
    assert protective_amend(row, AmendTerms(sides=_stop(str(asked)))) is not loose
