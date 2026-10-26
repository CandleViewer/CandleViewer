"""The price band, step 3a of `OrderSubmission` (E29-T04 #913 S4-S; 24 Sec.8.4 item 2, 22
`placeOrder`, rulings Q3 and Q4): a limit entry's price, or a conditional entry's trigger, around
mid else last, and the limit price behind a trigger around that trigger. A refusal is 400
`validation_failed` before sizing, with nothing recorded as sent and nothing sent; a reduce-only
order is never judged. Every admitted entry still reaches the venue with its native stop (C-2.6).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms.errors import (
    RULE_PRICE_BAND,
    ExchangeUnavailable,
    OmsError,
    OrderInvalid,
    problem_for,
)
from candleviewer.oms.ports import RequestRecord, SizingRequest, StopOffset
from candleviewer.oms.submit import READ_RETRY_AFTER_S, OrderTrigger
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import SYMBOL, SubmitRig, build_rig, context, entry, flatten


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SubmitRig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()  # the market's mid at 60000, so the 5 % band is [57000, 63000]
    yield built
    await built.machines.stop()


async def _refused(rig: SubmitRig, request: Any) -> OmsError:
    with pytest.raises(OmsError) as refused:
        await rig.submit(request)
    return refused.value


def _banded(refused: OmsError) -> list[str]:
    """The fields a `price_band` refusal names, once it is shown to be 400 `validation_failed`."""
    assert isinstance(refused, OrderInvalid)
    assert (problem_for(refused).status, problem_for(refused).code) == (400, "validation_failed")
    assert {error.rule for error in refused.errors} == {RULE_PRICE_BAND}
    return [error.field for error in refused.errors]


def _sent_with_stop(rig: SubmitRig) -> PlaceOrderRequest:
    """The one create the venue took, carrying its native stop (C-2.6)."""
    [create] = [c.request for c in rig.port.demo.calls if c.method == "place_order"]
    assert isinstance(create, PlaceOrderRequest) and create.stop_loss is not None
    return create


def _stop(price: str) -> StopOffset:
    return StopOffset(unit="price", value=Decimal(price))


def _trigger(price: str) -> OrderTrigger:
    return OrderTrigger(price=Decimal(price), direction="rise")


@pytest.mark.parametrize(
    "request_",
    [
        pytest.param(entry(price=Decimal("63000.1")), id="buy_above"),
        pytest.param(
            entry(side="sell", price=Decimal("56999.9"), stop_loss=_stop("58000")),
            id="sell_below",
        ),
    ],
)
async def test_band_limit_outside_is_refused_400_and_writes_nothing(
    rig: SubmitRig, request_: Any
) -> None:
    refused = await _refused(rig, request_)
    assert _banded(refused) == ["price"]
    assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)
    assert rig.count("oms_submit_rejected_total", code="validation_failed") == 1
    [denied] = [r for r in rig.records("orders.submit") if isinstance(r, RequestRecord)]
    assert (denied.outcome, denied.detail["step"]) == ("denied", "classify")


async def test_band_refusal_message_names_the_band_never_the_reference(rig: SubmitRig) -> None:
    refused = await _refused(rig, entry(price=Decimal("70000")))
    assert isinstance(refused, OrderInvalid)
    [error] = refused.errors
    assert "5%" in error.message and "60000" not in error.message
    assert "60000" not in refused.detail


@pytest.mark.parametrize(
    ("price", "stop"), [("63000", "58000"), ("57000", "56000")], ids=["upper", "lower"]
)
async def test_band_limit_on_the_edge_is_admitted(rig: SubmitRig, price: str, stop: str) -> None:
    outcome = await rig.submit(entry(price=Decimal(price), stop_loss=_stop(stop)))
    assert outcome.status == 202
    assert _sent_with_stop(rig).price == Decimal(price)


async def test_band_reduce_only_limit_outside_is_not_judged(rig: SubmitRig) -> None:
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    outcome = await rig.submit(flatten(order_type="limit", price=Decimal("90000")))
    assert outcome.status == 202
    assert rig.prices.read == []


@pytest.mark.parametrize(
    ("mid", "last", "admitted"),
    [
        (None, "60000", True),  # no mid: last is the reference
        (None, "70000", False),  # 60000 lies outside last's band
        ("60000", "70000", True),  # mid, when known, wins over last
        ("0", "60000", True),  # a mid at zero is no mid
    ],
)
async def test_band_reference_is_mid_else_last(
    rig: SubmitRig, mid: str | None, last: str, admitted: bool
) -> None:
    rig.prices.price = None if mid is None else Decimal(mid)
    rig.prices.last = Decimal(last)
    if admitted:
        assert (await rig.submit()).status == 202
        _sent_with_stop(rig)
    else:
        assert _banded(await _refused(rig, entry())) == ["price"]
    assert rig.prices.read == [SYMBOL]


@pytest.mark.parametrize("answer", ["none", "raises"])
async def test_band_with_neither_mid_nor_last_is_503_with_retry_after(
    rig: SubmitRig, answer: str
) -> None:
    rig.prices.price = None
    if answer == "raises":
        rig.prices.refuse = TimeoutError()
    refused = await _refused(rig, entry())
    assert isinstance(refused, ExchangeUnavailable)
    assert refused.retry_after_s == READ_RETRY_AFTER_S
    assert problem_for(refused).code == "exchange_unavailable"
    assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "request_",
    [
        pytest.param(entry(price=Decimal("63500"), trigger=_trigger("63500")), id="limit"),
        pytest.param(
            entry(order_type="market", price=None, stop_loss=None, trigger=_trigger("63500")),
            id="market",
        ),
    ],
)
async def test_band_trigger_outside_against_the_reference_is_refused(
    rig: SubmitRig, request_: Any
) -> None:
    assert _banded(await _refused(rig, request_)) == ["trigger.price"]
    assert rig.calls() == []


async def test_band_limit_behind_a_trigger_outside_against_the_trigger_is_refused(
    rig: SubmitRig,
) -> None:
    """57000 lies inside the market's band but outside the trigger's, [57475, 63525]."""
    request = entry(price=Decimal("57000"), stop_loss=_stop("56000"), trigger=_trigger("60500"))
    assert _banded(await _refused(rig, request)) == ["price"]


async def test_band_trigger_and_limit_behind_it_both_outside_name_both(rig: SubmitRig) -> None:
    request = entry(price=Decimal("50000"), stop_loss=_stop("49000"), trigger=_trigger("64000"))
    assert _banded(await _refused(rig, request)) == ["trigger.price", "price"]


async def test_band_limit_behind_a_trigger_inside_its_band_is_admitted(rig: SubmitRig) -> None:
    """58900 is the trigger's lower edge, 62000 x 0.95."""
    request = entry(price=Decimal("58900"), trigger=_trigger("62000"))
    assert (await rig.submit(request)).status == 202
    assert _sent_with_stop(rig).trigger_price == Decimal("62000")


async def test_band_market_order_is_not_judged(rig: SubmitRig) -> None:
    outcome = await rig.submit(entry(order_type="market", price=None, stop_loss=None))
    assert outcome.status == 202
    assert (rig.prices.read, rig.prices.asked) == ([], [SYMBOL])
    _sent_with_stop(rig)


async def test_band_is_judged_before_the_sizer(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sized: list[SizingRequest] = []
    ports = rig.pipeline._ports

    class _Spy:
        def size(self, sizing: SizingRequest, instrument: Any) -> Decimal:
            sized.append(sizing)
            return ports.sizer.size(sizing, instrument)

    monkeypatch.setattr(rig.pipeline, "_ports", replace(ports, sizer=_Spy()))
    await _refused(rig, entry(price=Decimal("70000")))
    assert sized == []
    assert (await rig.submit()).status == 202
    assert len(sized) == 1


async def test_band_setting_is_the_pipelines_band(rig: SubmitRig) -> None:
    wider = rig.make(price_band=Decimal("0.10"))
    request = entry(price=Decimal("65000"), take_profit=_stop("66000"))
    with pytest.raises(OrderInvalid):
        await rig.pipeline.submit(request, context())
    assert (await wider.submit(request, context())).status == 202


@pytest.mark.parametrize("band", ["0.0049", "0.21", "0"])
async def test_band_outside_its_bounds_is_refused_at_construction(
    rig: SubmitRig, band: str
) -> None:
    with pytest.raises(ValueError, match="price_band"):
        rig.make(price_band=Decimal(band))
