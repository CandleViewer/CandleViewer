"""One conformance suite over both `TradingPort` implementations (G-8, #2877): the exchange's
port, over transcribed replies (ruling R2), and `FakeTradingPort`. Each case asks of both what
the OMS relies on: what they refuse, before anything is sent, and how they answer. Every ack
either port returns in any case here is checked as it leaves (the orchestrator's ruling 3 on
#3972): one that is `ok` names the exchange's order, and only a stop write names none.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base import FakeTradingPort, RateHeadroomPort, TradingPort
from candleviewer.exchange.base.errors import DuplicateClientIdError
from candleviewer.exchange.base.fakes import FakeCall
from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    Order,
    OrderAck,
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
AMENDED = rest("rest/trading-amend-reply.json")
ORDER_ID = CANCEL["result"]["orderId"]
BATCH = rest("rest/trading-create-batch-reply.json")
CANCEL_ALL = rest("rest/trading-cancel-all-reply.json")
REALTIME = rest("rest/trading-order-realtime.json")
DUPLICATE = rest("rest/trading-error-110072.json")
#: The fake's cancel-all cap in these cases: one call takes two orders, as the venue takes 500.
FAKE_CANCEL_ALL_LIMIT = 2
#: The calls that answer with acks; every one but the stop write names an order.
ACKING = (
    "place_order",
    "place_batch",
    "amend_order",
    "cancel_order",
    "cancel_all",
    "set_trading_stop",
)


@dataclass
class Harness:
    """One port, the means to prime it, and what it sent or recorded."""

    port: TradingPort
    sent: Callable[[], int]
    lanes: Callable[[], list[str]]
    prime_create: Callable[[str], None]
    prime_ext_cancel: Callable[[], None]
    prime_cancel_all: Callable[[], None]
    prime_batch_duplicate: Callable[[str, str], None]
    prime_capped_book: Callable[[], None]
    prime_amend: Callable[[str], None]
    acks: list[tuple[str, OrderAck]] = field(default_factory=list)


def _watch(port: TradingPort, seen: list[tuple[str, OrderAck]]) -> None:
    """Record every ack `port` returns, by the call that returned it: an instance attribute over
    each acking method, so the port itself runs unchanged."""
    for name in ACKING:
        call: Callable[..., Awaitable[OrderAck | Sequence[OrderAck]]] = getattr(port, name)

        async def watched(*args: Any, _name: str = name, _call: Any = call, **kwargs: Any) -> Any:
            answer = await _call(*args, **kwargs)
            acks = [answer] if isinstance(answer, OrderAck) else list(answer)
            seen.extend((_name, ack) for ack in acks)
            return answer

        setattr(port, name, watched)


def check_acks_name_their_orders(seen: Sequence[tuple[str, OrderAck]]) -> None:
    """The orchestrator's ruling 3 on #3972, as a property of every ack a port returns: one that
    is `ok` names the exchange's order, never empty; a stop write names no order at all."""
    for name, ack in seen:
        if name == "set_trading_stop":
            assert (ack.order_link_id, ack.exchange_order_id) == (None, None)
        elif ack.ok:
            assert ack.exchange_order_id, (name, ack)


def _exchange() -> Harness:
    venue, governor = Venue(), RecordingGovernor()

    def prime_create(order_link_id: str) -> None:
        created = with_result(rest("rest/trading-create-reply.json"), orderLinkId=order_link_id)
        venue.on("/v5/order/create", created, rest("rest/trading-error-110072.json"))

    def prime_ext_cancel() -> None:
        venue.on("/v5/order/cancel", CANCEL)

    def prime_cancel_all() -> None:
        venue.on("/v5/order/cancel-all", CANCEL_ALL)

    def prime_batch_duplicate(fresh: str, taken: str) -> None:
        """The batch shape with our ids: the first item placed, the second a duplicate."""
        item = BATCH["result"]["list"][0]
        items = [{**item, "orderLinkId": fresh, "orderId": "e-1"}, {**item, "orderLinkId": taken}]
        codes = [{"code": 0, "msg": "OK"}, {"code": 110072, "msg": DUPLICATE["retMsg"]}]
        items[1]["orderId"] = ""
        reply = {**with_result(BATCH, list=items), "retExtInfo": {"list": codes}}
        venue.on("/v5/order/create-batch", reply)

    def prime_capped_book() -> None:
        """Three open orders; the first cancel-all takes two, the second the last one."""
        left = {**REALTIME["result"]["list"][0], "orderId": "e-left"}
        taken = {"orderId": left["orderId"], "orderLinkId": left["orderLinkId"]}
        venue.on("/v5/order/cancel-all", CANCEL_ALL, with_result(CANCEL_ALL, list=[taken]))
        venue.on(
            "/v5/order/realtime",
            with_result(REALTIME, list=[left], nextPageCursor=""),
            with_result(REALTIME, list=[], nextPageCursor=""),
        )

    def prime_amend(order_link_id: str) -> None:
        venue.on("/v5/order/amend", with_result(AMENDED, orderLinkId=order_link_id))

    harness = Harness(
        port=make_port(venue, governor=governor),
        sent=lambda: len(venue.sent) + len(governor.acquired),
        lanes=lambda: [lane for _, _, lane, _ in governor.acquired],
        prime_create=prime_create,
        prime_ext_cancel=prime_ext_cancel,
        prime_cancel_all=prime_cancel_all,
        prime_batch_duplicate=prime_batch_duplicate,
        prime_capped_book=prime_capped_book,
        prime_amend=prime_amend,
    )
    _watch(harness.port, harness.acks)
    return harness


def _fake() -> Harness:
    port = FakeTradingPort(
        environment="demo", now_us=lambda: NOW_US, cancel_all_limit=FAKE_CANCEL_ALL_LIMIT
    )

    def seed_ext() -> None:
        port.seed_order(_order(ext_key(ORDER_ID), ORDER_ID), uid="100001")

    def seed_two() -> None:
        port.seed_order(_order(link(seq=7), "fake-a"), uid="100001")
        port.seed_order(_order(link(seq=8), "fake-b"), uid="100001")

    def seed_taken(_fresh: str, taken: str) -> None:
        port.seed_order(_order(taken, "fake-taken"), uid="100001")

    def seed_three() -> None:
        seed_two()
        port.seed_order(_order(link(seq=9), "fake-c"), uid="100001")

    calls: list[FakeCall] = port.calls
    harness = Harness(
        port=port,
        sent=lambda: len(calls),
        lanes=lambda: [c.lane for c in calls],
        prime_create=lambda _link: None,
        prime_ext_cancel=seed_ext,
        prime_cancel_all=seed_two,
        prime_batch_duplicate=seed_taken,
        prime_capped_book=seed_three,
        prime_amend=lambda _link: None,  # the fake amends the order a create landed
    )
    _watch(harness.port, harness.acks)
    return harness


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
def harness(request: pytest.FixtureRequest) -> Iterator[Harness]:
    """One port per case; every ack it returned is checked as the case ends (ruling 3, #3972)."""
    built = _exchange() if request.param == "exchange" else _fake()
    yield built
    check_acks_name_their_orders(built.acks)


def test_both_satisfy_the_port(harness: Harness) -> None:
    port: TradingPort = harness.port  # mypy checks the assignment; isinstance the runtime shape
    assert isinstance(port, TradingPort)
    assert port.capabilities.environment == "demo"
    assert port.capabilities.supports_ws_order_entry is False


def test_both_read_a_lanes_headroom_without_sending_anything(harness: Harness) -> None:
    """#2877 ruling 4: the small protocol beside `TradingPort`, which B1's `rate` verdict reads
    until E34-T02's `reserve()`; a fresh budget has a spare token and no wait in every lane."""
    port = harness.port
    assert isinstance(port, RateHeadroomPort)
    readings = [port.headroom(account(), lane) for lane in ("critical", "entry", "poll")]
    assert [r.lane for r in readings] == ["critical", "entry", "poll"]
    assert all(r.tokens >= 1 and r.wait_s == 0.0 for r in readings)
    with pytest.raises(ValueError, match="another environment"):
        port.headroom(account(environment="live"), "entry")
    assert harness.sent() == 0


async def test_both_accept_a_create_then_refuse_its_id_again(harness: Harness) -> None:
    request = place()
    harness.prime_create(request.order_link_id)
    ack = await harness.port.place_order(request)
    assert (ack.ok, ack.order_link_id, ack.transport) == (True, request.order_link_id, "rest")
    assert ack.exchange_order_id
    with pytest.raises(DuplicateClientIdError):
        await harness.port.place_order(request)


async def test_every_ok_ack_of_an_order_call_names_its_exchange_order(harness: Harness) -> None:
    """Ruling 3 on #3972 over each order call that answers `ok`: a create, a batch, an amend, a
    cancel and a cancel-all (the fixture checks every other case's acks the same way)."""
    request = place()
    harness.prime_create(request.order_link_id)
    await harness.port.place_order(request)
    fresh, taken = link(seq=3), link(seq=4)
    harness.prime_batch_duplicate(fresh, taken)
    await harness.port.place_batch([place(order_link_id=fresh), place(order_link_id=taken)])
    harness.prime_amend(request.order_link_id)
    amend = AmendOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=request.order_link_id,
        qty=Decimal("0.02"),
    )
    await harness.port.amend_order(amend)
    harness.prime_ext_cancel()
    await harness.port.cancel_order(
        CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    )
    harness.prime_cancel_all()
    await harness.port.cancel_all(account(), None)
    answered = {name for name, ack in harness.acks if ack.ok}
    assert answered == set(ACKING) - {"set_trading_stop"}
    check_acks_name_their_orders(harness.acks)


def test_the_ack_check_fails_an_ok_ack_without_its_order_and_a_stop_write_naming_one() -> None:
    """The check itself is no tautology: it fails on what ruling 3 forbids."""
    ok = OrderAck(
        ok=True, order_link_id=link(), exchange_order_id=None, latency_ms=0, transport="rest"
    )
    with pytest.raises(AssertionError):
        check_acks_name_their_orders([("place_order", ok)])
    named = ok.model_copy(update={"order_link_id": None, "exchange_order_id": "e-1"})
    with pytest.raises(AssertionError):
        check_acks_name_their_orders([("set_trading_stop", named)])
    refused = ok.model_copy(update={"ok": False})
    check_acks_name_their_orders([("place_order", refused)])


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


async def test_both_leave_what_one_cancel_all_cannot_take_for_a_repeat(harness: Harness) -> None:
    """24 §14.2 rule 12: a cancel-all is no proof of a flat book (the venue takes 500 orders a
    call, at random beyond that), so the OMS repeats it until `open_orders` is empty."""
    harness.prime_capped_book()
    first = await harness.port.cancel_all(account(), None)
    left = await harness.port.open_orders(account())
    assert len(first) == 2 and all(a.ok for a in first) and len(left) == 1
    second = await harness.port.cancel_all(account(), None)
    assert len(second) == 1 and await harness.port.open_orders(account()) == []


async def test_both_answer_a_batch_item_whose_id_was_taken_with_a_duplicate_ack(
    harness: Harness,
) -> None:
    """24 §14.4's item contract: one ack per request, in order; a duplicate item is an `ok`
    false `DUPLICATE_CLIENT_ID` ack for the OMS to look up, never raised."""
    fresh, taken = link(seq=3), link(seq=4)
    harness.prime_batch_duplicate(fresh, taken)
    acks = await harness.port.place_batch([place(order_link_id=fresh), place(order_link_id=taken)])
    assert [(a.ok, a.order_link_id) for a in acks] == [(True, fresh), (False, taken)]
    assert (acks[1].error_code, acks[1].retryable) == ("DUPLICATE_CLIENT_ID", False)


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
