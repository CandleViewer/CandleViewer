"""The size step's own refusals and guards (E29-T04 #913 S4-S; S4-G3's coverage record, ruling Q7).

`oms.sizing` refuses a sizing mode sent without its value, an `atr` stop at or below zero and a
leg with no reference price, reads a market price no `Price` holds as no price, and treats an
`ok` leg that lacks its quantity, stop, risk or anchor as a defect, never as a size. Each is
asserted where the module raises it, on plain values: no rig, no I/O.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.accounts.sizer import FailReason, LegSizing, ResolvedStop, SizingMarket
from candleviewer.oms.errors import ExchangeUnavailable, OrderInvalid
from candleviewer.oms.ports import SizingRequest, StopOffset
from candleviewer.oms.sizing import (
    SIZING_RETRY_AFTER_S,
    EntryIntent,
    EntrySizer,
    _answered,
    own_take_profit,
    resolved_leg,
    sizing_market,
    sizing_overlay,
    stop_overlay,
)
from tests.unit.oms import submit_rig as sr

_STOP = ResolvedStop(price=Decimal(58000), distance=Decimal(2000), fallback=False)
#: An `ok` leg with its quantity, stop and risk but no anchor, and one with nothing at all.
_UNANCHORED = LegSizing(
    outcome="ok", qty=Decimal("0.010"), stop=_STOP, risk_with_fees_usdt=Decimal(20)
)
_BARE = LegSizing(outcome="ok")


def _intent() -> EntryIntent:
    request = sr.entry()
    return EntryIntent(
        symbol=request.symbol, side=request.side, order_type=request.order_type,
        price=request.price, sizing=request.sizing, stop_loss=request.stop_loss,
        take_profit=request.take_profit, time_in_force=request.time_in_force,
        tpsl_mode=request.tpsl_mode, position_idx=request.position_idx,
    )  # fmt: skip


@pytest.mark.parametrize("value", [None, Decimal("NaN")], ids=["missing", "nan"])
def test_a_sizing_mode_sent_without_its_value_is_refused_as_required(
    value: Decimal | None,
) -> None:
    with pytest.raises(OrderInvalid) as refused:
        sizing_overlay(SizingRequest(mode="fixed_qty", qty=value))
    assert [(e.field, e.rule) for e in refused.value.errors] == [("sizing.qty", "required")]


@pytest.mark.parametrize("multiple", ["0", "-1", "NaN"])
def test_an_atr_stop_at_or_below_zero_is_refused_before_it_is_sized(multiple: str) -> None:
    stop = StopOffset(unit="atr", value=Decimal(multiple))
    with pytest.raises(OrderInvalid) as refused:
        stop_overlay(stop, "buy", Decimal(60000), sr.instrument())
    rules = [(e.field, e.rule) for e in refused.value.errors]
    assert rules == [("stop_loss", "native_stop_required")]


def test_a_leg_with_no_reference_price_is_an_exchange_read_to_retry() -> None:
    with pytest.raises(ExchangeUnavailable) as refused:
        _answered(LegSizing(outcome="fail", reason=FailReason.NO_REFERENCE_PRICE))
    assert refused.value.retry_after_s == SIZING_RETRY_AFTER_S


def test_a_market_price_no_price_holds_is_read_as_no_price() -> None:
    last = Decimal(60000)
    assert sizing_market(Decimal(-1), last) == SizingMarket(last_price=last)
    assert sizing_market(Decimal("NaN"), Decimal(0)) == SizingMarket()


@pytest.mark.parametrize(
    ("leg", "why"), [(_BARE, "quantity, stop and risk"), (_UNANCHORED, "anchor")]
)
def test_an_ok_leg_without_its_figures_is_a_defect_never_a_size(leg: LegSizing, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        EntrySizer._size(leg, "fixed_qty", None)


def test_a_leg_without_its_anchor_is_never_judged() -> None:
    profile = sr.profile()
    with pytest.raises(ValueError, match="anchor, stop and quantity"):
        resolved_leg(_intent(), profile, _UNANCHORED, None)
    with pytest.raises(ValueError, match="anchor and stop"):
        own_take_profit("buy", profile, _UNANCHORED, _UNANCHORED, sr.instrument())
