"""One conformance suite over both `TradingPort` implementations (G-8, #2877): the exchange's
port, over transcribed replies (ruling R2), and `FakeTradingPort`. Each case asks of both what
the OMS relies on: what they refuse, before anything is sent, and how they answer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base import FakeTradingPort, TradingPort
from candleviewer.exchange.base.errors import DuplicateClientIdError
from candleviewer.exchange.base.fakes import FakeCall
from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    Order,
    TradingStopRequest,
)
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import (
    ACCOUNT_B,
    NOW_US,
    RecordingGovernor,
    Venue,
    account,
    link,
    make_port,
    place,
    with_result,
)

CANCEL = rest("rest/trading-cancel-reply.json")
ORDER_ID = CANCEL["result"]["orderId"]


@dataclass
class Harness:
    """One port, the means to prime it, and what it sent or recorded."""

    port: TradingPort
    sent: Callable[[], int]
    lanes: Callable[[], list[str]]
    prime_create: Callable[[str], None]
    prime_ext_cancel: Callable[[], None]
    prime_cancel_all: Callable[[], None]


def _exchange() -> Harness:
    venue, governor = Venue(), RecordingGovernor()

    def prime_create(order_link_id: str) -> None:
        created = with_result(rest("rest/trading-create-reply.json"), orderLinkId=order_link_id)
        venue.on("/v5/order/create", created, rest("rest/trading-error-110072.json"))

    def prime_ext_cancel() -> None:
        venue.on("/v5/order/cancel", CANCEL)

    def prime_cancel_all() -> None:
        venue.on("/v5/order/cancel-all", rest("rest/trading-cancel-all-reply.json"))

    return Harness(
        port=make_port(venue, governor=governor),
        sent=lambda: len(venue.sent) + len(governor.acquired),
        lanes=lambda: [lane for _, _, lane, _ in governor.acquired],
        prime_create=prime_create,
        prime_ext_cancel=prime_ext_cancel,
        prime_cancel_all=prime_cancel_all,
    )


def _fake() -> Harness:
    port = FakeTradingPort(environment="demo", now_us=lambda: NOW_US)

    def seed_ext() -> None:
        port.seed_order(_order(ext_key(ORDER_ID), ORDER_ID), uid="100001")

    def seed_two() -> None:
        port.seed_order(_order(link(seq=7), "fake-a"), uid="100001")
        port.seed_order(_order(link(seq=8), "fake-b"), uid="100001")

    calls: list[FakeCall] = port.calls
    return Harness(
        port=port,
        sent=lambda: len(calls),
        lanes=lambda: [c.lane for c in calls],
        prime_create=lambda _link: None,
        prime_ext_cancel=seed_ext,
        prime_cancel_all=seed_two,
    )


def _order(order_link_id: str, exchange_order_id: str) -> Order:
    return Order(
        order_link_id=order_link_id,
        exchange_order_id=exchange_order_id,
        account_id=account().account_id,
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        qty=Decimal("1"),
        price=Decimal("60000"),
        state="new",
        filled_qty=Decimal(0),
        leaves_qty=Decimal("1"),
        avg_fill_price=None,
        created_at=NOW_US,
        terminal_at=None,
    )


@pytest.fixture(params=["exchange", "fake"])
def harness(request: pytest.FixtureRequest) -> Harness:
    return _exchange() if request.param == "exchange" else _fake()


def test_both_satisfy_the_port(harness: Harness) -> None:
    port: TradingPort = harness.port  # mypy checks the assignment; isinstance the runtime shape
    assert isinstance(port, TradingPort)
    assert port.capabilities.environment == "demo"
    assert port.capabilities.supports_ws_order_entry is False


async def test_both_accept_a_create_then_refuse_its_id_again(harness: Harness) -> None:
    request = place()
    harness.prime_create(request.order_link_id)
    ack = await harness.port.place_order(request)
    assert (ack.ok, ack.order_link_id, ack.transport) == (True, request.order_link_id, "rest")
    assert ack.exchange_order_id
    with pytest.raises(DuplicateClientIdError):
        await harness.port.place_order(request)


async def test_both_cancel_an_ext_order_by_its_exchange_id(harness: Harness) -> None:
    harness.prime_ext_cancel()
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    ack = await harness.port.cancel_order(request)
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (True, ext_key(ORDER_ID), ORDER_ID)
    assert harness.lanes() == ["critical"]


async def test_both_cancel_all_in_the_critical_lane(harness: Harness) -> None:
    harness.prime_cancel_all()
    acks = await harness.port.cancel_all(account(), None)
    assert len(acks) == 2 and all(a.ok for a in acks)
    assert harness.lanes() == ["critical"]


async def test_both_take_a_create_or_an_amend_in_its_requests_lane(harness: Harness) -> None:
    request = place(lane="critical")
    harness.prime_create(request.order_link_id)
    await harness.port.place_order(request)
    assert harness.lanes() == ["critical"]


async def _every_call(port: TradingPort, live: bool) -> AsyncIterator[Callable[[], Any]]:
    ref = account(environment="live") if live else account()
    yield lambda: port.place_order(place(ref))
    yield lambda: port.place_batch([place(ref)])
    yield lambda: port.amend_order(
        AmendOrderRequest(account=ref, symbol="BTCUSDT", order_link_id=link(), qty=Decimal(1))
    )
    yield lambda: port.cancel_order(
        CancelOrderRequest(account=ref, symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    )
    yield lambda: port.cancel_all(ref, None)
    yield lambda: port.set_trading_stop(TradingStopRequest(account=ref, symbol="BTCUSDT"))
    yield lambda: port.set_leverage(ref, "BTCUSDT", Decimal(5))
    yield lambda: port.open_orders(ref)
    yield lambda: port.order_history(ref)
    yield lambda: port.positions(ref)
    yield lambda: port.executions(ref, NOW_US - 1, NOW_US)
    yield lambda: port.closed_pnl(ref, NOW_US - 1, NOW_US)
    yield lambda: port.wallet(ref)
    yield lambda: port.fee_rate(ref, "BTCUSDT")
    yield lambda: port.account_info(ref)


async def test_both_refuse_another_environments_account_before_anything(harness: Harness) -> None:
    async for call in _every_call(harness.port, live=True):
        with pytest.raises(ValueError, match="another environment"):
            await call()
    assert harness.sent() == 0


@pytest.mark.parametrize(
    "key",
    [ext_key("x-1"), "linear-004", link(environment="live"), link(ACCOUNT_B)],
    ids=["ext", "foreign", "other-environment", "other-account"],
)
async def test_both_refuse_a_create_without_a_generated_id_of_its_account(
    harness: Harness, key: str
) -> None:
    with pytest.raises(ValueError, match="order_link_id"):
        await harness.port.place_order(place(order_link_id=key))
    assert harness.sent() == 0


async def test_both_refuse_an_exit_that_cannot_name_its_order(harness: Harness) -> None:
    for order_link_id in (ext_key("x-1"), None, "linear-004"):
        request = CancelOrderRequest(
            account=account(), symbol="BTCUSDT", order_link_id=order_link_id
        )
        with pytest.raises(ValueError, match="exchange_order_id"):
            await harness.port.cancel_order(request)
    mismatched = CancelOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=ext_key("another"),
        exchange_order_id=ORDER_ID,
    )
    with pytest.raises(ValueError, match="another exchange order"):
        await harness.port.cancel_order(mismatched)
    assert harness.sent() == 0


async def test_both_refuse_a_lookup_by_anything_but_a_generated_id(harness: Harness) -> None:
    for key in (ext_key("x-1"), "linear-004"):
        with pytest.raises(ValueError, match="generated id"):
            await harness.port.open_orders(account(), order_link_id=key)
        with pytest.raises(ValueError, match="generated id"):
            await harness.port.order_history(account(), order_link_id=key)
    assert harness.sent() == 0


async def test_both_take_the_id_filters_by_keyword_only(harness: Harness) -> None:
    port: Any = harness.port  # untyped on purpose: these calls break the signature
    with pytest.raises(TypeError):
        await port.open_orders(account(), "BTCUSDT", link())
    with pytest.raises(TypeError):
        await port.order_history(account(), link())
    assert harness.sent() == 0


async def test_both_refuse_a_batch_outside_its_bounds(harness: Harness) -> None:
    with pytest.raises(ValueError, match="batch"):
        await harness.port.place_batch([])
    with pytest.raises(ValueError, match="batch"):
        await harness.port.place_batch([place(order_link_id=link(seq=n)) for n in range(11)])
    assert harness.sent() == 0


async def test_both_refuse_a_window_that_ends_before_it_starts(harness: Harness) -> None:
    with pytest.raises(ValueError, match="start is after end"):
        await harness.port.executions(account(), NOW_US, NOW_US - 1)
    with pytest.raises(ValueError, match="start is after end"):
        await harness.port.closed_pnl(account(), NOW_US, NOW_US - 1)
    with pytest.raises(ValueError, match="start is after end"):
        await harness.port.order_history(account(), start=NOW_US, end=NOW_US - 1)
    assert harness.sent() == 0


async def test_both_refuse_a_leverage_that_is_not_positive(harness: Harness) -> None:
    with pytest.raises(ValueError, match="positive"):
        await harness.port.set_leverage(account(), "BTCUSDT", Decimal(0))
    assert harness.sent() == 0
