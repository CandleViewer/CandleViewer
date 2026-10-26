"""The price band, step 3a of `OrderSubmission` (E29-T04; 24 Sec.8.4, rulings Q3, Q4): a refusal is
400 `validation_failed` before sizing and any write; reduce-only is never judged; C-2.6 holds."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms.errors import (
    RULE_PRICE_BAND,
    ExchangeUnavailable,
    OmsError,
    OrderInvalid,
    problem_for,
)
from candleviewer.oms.ports import RequestRecord, StopOffset
from candleviewer.oms.submit import READ_RETRY_AFTER_S, OrderTrigger
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import (
    SYMBOL,
    SubmitRig,
    build_rig,
    context,
    entry,
    flatten,
    profile,
)


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
    assert isinstance(refused, OrderInvalid)
    assert problem_for(refused).code == "validation_failed"
    assert {error.rule for error in refused.errors} == {RULE_PRICE_BAND}
    return [error.field for error in refused.errors]


def _sent_with_stop(rig: SubmitRig) -> PlaceOrderRequest:
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
            entry(side="sell", price=Decimal("63000.1"), stop_loss=_stop("64000")), id="sell_above"
        ),
        pytest.param(
            entry(side="sell", price=Decimal("56999.9"), stop_loss=_stop("58000")), id="sell_below"
        ),
    ],
)
async def test_band_limit_outside_is_refused_400_and_writes_nothing(
    rig: SubmitRig, request_: Any
) -> None:
    refused = await _refused(rig, request_)
    assert _banded(refused) == ["price"]
    assert isinstance(refused, OrderInvalid)
    [error] = refused.errors
    assert "5%" in error.message and "60000" not in error.message + refused.detail
    assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)
    assert rig.count("oms_submit_rejected_total", code="validation_failed") == 1
    [denied] = [r for r in rig.records("orders.submit") if isinstance(r, RequestRecord)]
    assert (denied.outcome, denied.detail["step"]) == ("denied", "classify")


@pytest.mark.parametrize(("price", "stop"), [("63000", "59900"), ("57000", "56000")])
async def test_band_limit_on_the_edge_is_admitted(rig: SubmitRig, price: str, stop: str) -> None:
    request = entry(price=Decimal(price), stop_loss=_stop(stop), take_profit=None)
    assert (await rig.submit(request)).status == 202
    assert _sent_with_stop(rig).price == Decimal(price)


@pytest.mark.parametrize(
    "order", [{"order_type": "limit", "price": Decimal("90000")}, {"trigger": _trigger("90000")}]
)
async def test_band_reduce_only_outside_is_not_judged(rig: SubmitRig, order: Any) -> None:
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    assert (await rig.submit(flatten(**order))).status == 202
    assert rig.prices.read == []


@pytest.mark.parametrize(
    ("mid", "last", "outcome"),
    [
        (None, "60000", "admitted"),  # no mid: last is the reference
        (None, "70000", "refused"),  # 60000 lies outside last's band
        ("60000", "70000", "admitted"),  # mid, when known, wins over last
        ("0", "60000", "admitted"),  # a mid at zero is no mid
        (None, None, "unavailable"),
        ("60000", None, "read_fails"),
    ],
)
async def test_band_reference_is_mid_else_last_else_503(
    rig: SubmitRig, mid: str | None, last: str | None, outcome: str
) -> None:
    rig.prices.price = None if mid is None else Decimal(mid)
    rig.prices.last = None if last is None else Decimal(last)
    rig.prices.refuse = TimeoutError() if outcome == "read_fails" else None
    if outcome == "admitted":
        assert (await rig.submit()).status == 202
    elif outcome == "refused":
        assert _banded(await _refused(rig, entry())) == ["price"]
    else:
        refused = await _refused(rig, entry())
        assert isinstance(refused, ExchangeUnavailable)
        assert refused.retry_after_s == READ_RETRY_AFTER_S
        assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)
    assert rig.prices.read == [SYMBOL]


@pytest.mark.parametrize(
    ("order", "named"),
    [
        ({"price": "63500", "trigger": "63500"}, ["trigger.price"]),
        ({"price": None, "trigger": "63500", "order_type": "market"}, ["trigger.price"]),
        (
            {"price": "57000", "trigger": "60500"},
            ["price"],
        ),  # in the market's band, not [57475, 63525]
        ({"price": "50000", "trigger": "64000"}, ["trigger.price", "price"]),  # both named
        ({"price": "58900", "trigger": "62000"}, None),  # the trigger's lower edge: admitted
        ({"price": None, "trigger": "61000", "order_type": "market"}, None),  # one market read
    ],
)
async def test_band_judges_a_trigger_against_the_market_and_its_limit_against_the_trigger(
    rig: SubmitRig, order: dict[str, Any], named: list[str] | None
) -> None:
    kw: dict[str, Any] = {"trigger": _trigger(order["trigger"]), "stop_loss": _stop("57000")}
    kw |= {"price": None if order["price"] is None else Decimal(order["price"])}
    kw |= {"order_type": order.get("order_type", "limit")}
    if named is not None:
        assert _banded(await _refused(rig, entry(**kw))) == named
        assert rig.calls() == []
    else:
        assert (await rig.submit(entry(**kw))).status == 202
        assert _sent_with_stop(rig).trigger_price == Decimal(order["trigger"])
        assert (len(rig.prices.read), rig.prices.asked) == (1, [])


@pytest.mark.parametrize(
    ("price", "trigger"), [("0", None), ("-1", None), ("NaN", None), (None, "0")]
)
async def test_band_leaves_a_price_it_cannot_judge_to_the_later_checks(
    rig: SubmitRig, price: str | None, trigger: str | None
) -> None:
    kw: dict[str, Any] = {} if price is None else {"price": Decimal(price)}
    kw |= {} if trigger is None else {"trigger": _trigger(trigger)}
    refused = await _refused(rig, entry(**kw))
    assert isinstance(refused, OrderInvalid)
    assert RULE_PRICE_BAND not in {error.rule for error in refused.errors}
    assert rig.calls() == []


async def test_band_market_order_is_not_judged(rig: SubmitRig) -> None:
    """A market entry is never judged; its one market read is the size step's (3a, then 3c)."""
    rig.prices.price = Decimal("90000")  # no band around any limit: the order has none
    request = entry(order_type="market", price=None, stop_loss=None, take_profit=None)
    assert (await rig.submit(request)).status == 202
    assert (rig.prices.read, rig.prices.asked) == ([SYMBOL], [])


async def test_band_is_judged_before_the_sizer(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizer = rig.pipeline._sizer
    spy = Mock(wraps=sizer.size)
    monkeypatch.setattr(sizer, "size", spy)
    await _refused(rig, entry(price=Decimal("70000")))
    spy.assert_not_called()
    assert rig.figures.reads == []
    assert (await rig.submit()).status == 202
    spy.assert_called_once()


async def test_band_setting_is_the_pipelines_band(rig: SubmitRig) -> None:
    held = profile(sl_offset_value="0.10", leverage="5", max_leverage_cap="5")  # a stop below mid
    rig.profiles.held[(cr.ACCOUNT, None)] = held
    request = entry(price=Decimal("65000"), stop_loss=_stop("59000"), take_profit=_stop("66000"))
    assert _banded(await _refused(rig, request)) == ["price"]
    assert (await rig.make(price_band=Decimal("0.10")).submit(request, context())).status == 202


@pytest.mark.parametrize(
    "band",
    [Decimal("0.0049"), Decimal("0.21"), Decimal("0"), Decimal("NaN"), 0.05],
    ids=["below", "above", "zero", "nan", "float"],
)
async def test_band_outside_its_bounds_is_refused_at_construction(
    rig: SubmitRig, band: Any
) -> None:
    with pytest.raises(ValueError, match="price_band"):
        rig.make(price_band=band)
