"""One conformance suite over both `TradingPort` implementations (G-8, #2877): the exchange's
port, over transcribed replies (ruling R2), and `FakeTradingPort`. Each case asks of both what
the OMS relies on: what they refuse, before anything is sent, and how they answer. Every ack
either port returns in any case here is checked as it leaves (the orchestrator's ruling 3 on
#3972): one that is `ok` names the exchange's order and its `order_link_id`, and only a stop
write, or the one ack of a cancel-all that cancelled nothing, names none. The private stream
(G-8b, #3963) is held to one contract too: the exchange's on a fake venue and a virtual clock
(`_private_venue.py`), the fake's by what a test pushes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base import FakeTradingPort, RateHeadroomPort, TradingPort
from candleviewer.exchange.base.errors import DuplicateClientIdError, ExchangeError
from candleviewer.exchange.base.fakes import FakeCall
from candleviewer.exchange.base.models import (
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    Order,
    OrderAck,
    PrivateStreamStatus,
    TradingStopRequest,
)
from candleviewer.exchange.bybit.trading import ENDPOINTS
from tests._corpus import rest
from tests._signing import CREDENTIAL_ID
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private_venue import PrivateVenue, make_streams
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
MISSING = rest("rest/trading-error-110001.json")
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
    prime_missing_cancel: Callable[[], None]
    prime_batch: Callable[[list[str]], None]
    prime_empty_cancel_all: Callable[[], None]
    prime_position_writes: Callable[[], None]
    #: G-8b: let the private streams run a while; end every open one with its `closed` status.
    advance: Callable[[], Awaitable[None]]
    end_private: Callable[[], Awaitable[None]]
    acks: list[tuple[str, tuple[OrderAck, ...]]] = field(default_factory=list)


def _watch(port: TradingPort, seen: list[tuple[str, tuple[OrderAck, ...]]]) -> None:
    """Record the acks of every call `port` answers, by the call that returned them: an instance
    attribute over each acking method, so the port itself runs unchanged."""
    for name in ACKING:
        call: Callable[..., Awaitable[OrderAck | Sequence[OrderAck]]] = getattr(port, name)

        async def watched(*args: Any, _name: str = name, _call: Any = call, **kwargs: Any) -> Any:
            answer = await _call(*args, **kwargs)
            seen.append((_name, (answer,) if isinstance(answer, OrderAck) else tuple(answer)))
            return answer

        setattr(port, name, watched)


def check_acks_name_their_orders(seen: Sequence[tuple[str, Sequence[OrderAck]]]) -> None:
    """The orchestrator's ruling 3 on #3972, as a property of every call's acks: one that is
    `ok` names the exchange's order and its `order_link_id`, never empty; a stop write names no
    order at all, and so does a cancel-all that cancelled nothing, in its one ack (24 §14.2
    rule 12)."""
    for name, acks in seen:
        for ack in acks:
            named = (ack.order_link_id, ack.exchange_order_id)
            if name == "set_trading_stop":
                assert named == (None, None), (name, ack)
            elif name == "cancel_all" and ack.ok and named == (None, None):
                assert len(acks) == 1, (name, acks)
            elif ack.ok:
                assert ack.exchange_order_id and ack.order_link_id, (name, ack)


def _exchange() -> Harness:
    venue, governor = Venue(), RecordingGovernor()
    clock = VirtualClock()
    private = PrivateVenue(clock)
    streams = make_streams(private)

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

    def prime_missing_cancel() -> None:
        venue.on("/v5/order/cancel", MISSING)

    def prime_batch(links: list[str]) -> None:
        """The batch shape with our ids, every item placed."""
        item = BATCH["result"]["list"][0]
        items = [{**item, "orderLinkId": lk, "orderId": f"e-{n}"} for n, lk in enumerate(links)]
        codes = [{"code": 0, "msg": "OK"} for _ in links]
        venue.on(
            "/v5/order/create-batch",
            {**with_result(BATCH, list=items), "retExtInfo": {"list": codes}},
        )

    def prime_empty_cancel_all() -> None:
        """The transcribed reply with nothing listed (a test input): nothing to cancel."""
        venue.on("/v5/order/cancel-all", with_result(CANCEL_ALL, list=[]))

    def prime_position_writes() -> None:
        venue.on("/v5/position/trading-stop", rest("rest/trading-trading-stop-reply.json"))
        venue.on("/v5/position/set-leverage", rest("rest/trading-set-leverage-reply.json"))

    harness = Harness(
        port=make_port(venue, governor=governor, private_streams=streams),
        sent=lambda: len(venue.sent) + len(governor.acquired) + len(private.dialled),
        lanes=lambda: [lane for _, _, lane, _ in governor.acquired],
        prime_create=prime_create,
        prime_ext_cancel=prime_ext_cancel,
        prime_cancel_all=prime_cancel_all,
        prime_batch_duplicate=prime_batch_duplicate,
        prime_capped_book=prime_capped_book,
        prime_amend=prime_amend,
        prime_missing_cancel=prime_missing_cancel,
        prime_batch=prime_batch,
        prime_empty_cancel_all=prime_empty_cancel_all,
        prime_position_writes=prime_position_writes,
        advance=lambda: clock.advance(1),
        end_private=streams.aclose,
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
        prime_missing_cancel=lambda: None,  # the fake holds no order under the id
        prime_batch=lambda _links: None,  # the fake places every new id
        prime_empty_cancel_all=lambda: None,  # the fake holds no order
        prime_position_writes=lambda: None,  # the fake writes to whatever position it holds
        advance=lambda: asyncio.sleep(0),
        end_private=lambda: _end_fake_streams(port),
    )
    _watch(harness.port, harness.acks)
    return harness


async def _end_fake_streams(port: FakeTradingPort) -> None:
    """What the exchange's port does on shutdown, pushed: the account's `closed` status."""
    status = PrivateStreamStatus(
        account_id=account().account_id, state="closed", reason="shutdown", epoch=0, ts=NOW_US
    )
    port.push(status)


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
    """The runtime shape; the signatures are checked by the `TYPE_CHECKING` assignments beside
    each class (`trading.py`, `fakes.py`), which CI's mypy lane reads."""
    port: TradingPort = harness.port
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
    answered = {name for name, acks in harness.acks for ack in acks if ack.ok}
    assert answered == set(ACKING) - {"set_trading_stop"}
    check_acks_name_their_orders(harness.acks)


def test_the_ack_check_fails_an_ok_ack_without_its_order_and_a_stop_write_naming_one() -> None:
    """The check itself is no tautology: it fails on what ruling 3 forbids."""
    ok = OrderAck(
        ok=True, order_link_id=link(), exchange_order_id=None, latency_ms=0, transport="rest"
    )
    with pytest.raises(AssertionError):
        check_acks_name_their_orders([("place_order", (ok,))])
    unlinked = ok.model_copy(update={"order_link_id": None, "exchange_order_id": "e-1"})
    for name in ("place_order", "place_batch", "amend_order", "cancel_order", "cancel_all"):
        with pytest.raises(AssertionError):
            check_acks_name_their_orders([(name, (unlinked,))])
    with pytest.raises(AssertionError):
        check_acks_name_their_orders([("set_trading_stop", (unlinked,))])
    refused = ok.model_copy(update={"ok": False})
    check_acks_name_their_orders([("place_order", (refused,))])


def test_the_ack_check_takes_one_unnamed_ack_from_a_cancel_all_that_cancelled_nothing() -> None:
    nothing = OrderAck(
        ok=True, order_link_id=None, exchange_order_id=None, latency_ms=0, transport="rest"
    )
    named = nothing.model_copy(update={"order_link_id": link(), "exchange_order_id": "e-1"})
    check_acks_name_their_orders([("cancel_all", (nothing,))])
    with pytest.raises(AssertionError):
        check_acks_name_their_orders([("cancel_all", (named, nothing))])
    with pytest.raises(AssertionError):
        check_acks_name_their_orders([("cancel_order", (nothing,))])


async def test_both_cancel_an_ext_order_by_its_exchange_id(harness: Harness) -> None:
    harness.prime_ext_cancel()
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    ack = await harness.port.cancel_order(request)
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (True, ext_key(ORDER_ID), ORDER_ID)
    assert harness.lanes() == ["critical"]


async def test_both_name_the_order_of_a_refused_cancel_as_an_accepted_one_names_it(
    harness: Harness,
) -> None:
    """A cancel named by its exchange id alone and refused (the order is gone) names the order
    by its `ext-` key, as the accepted cancel does (24 §14.4: `order_link_id` is `None` only
    where no order is named)."""
    harness.prime_missing_cancel()
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    ack = await harness.port.cancel_order(request)
    assert (ack.ok, ack.error_code, ack.order_link_id) == (
        False,
        "ORDER_NOT_FOUND",
        ext_key(ORDER_ID),
    )


async def test_both_cancel_all_in_the_critical_lane(harness: Harness) -> None:
    harness.prime_cancel_all()
    acks = await harness.port.cancel_all(account(), None)
    assert len(acks) == 2 and all(a.ok for a in acks)
    assert harness.lanes() == ["critical"]


async def test_both_answer_a_cancel_all_that_cancels_nothing_with_one_ack_naming_no_order(
    harness: Harness,
) -> None:
    """24 §14.2 rule 12: accepted with nothing to cancel, the call still answers, so the OMS
    has the call's evidence (C-2.9; the exchange's ack carries its record, SR-E29-08)."""
    harness.prime_empty_cancel_all()
    [ack] = await harness.port.cancel_all(account(), "BTCUSDT")
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (True, None, None)
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


async def _critical_create(harness: Harness) -> None:
    request = place(lane="critical")
    harness.prime_create(request.order_link_id)
    await harness.port.place_order(request)


async def _critical_batch(harness: Harness) -> None:
    fresh, taken = link(seq=3), link(seq=4)
    harness.prime_batch_duplicate(fresh, taken)
    await harness.port.place_batch(
        [place(order_link_id=fresh, lane="critical"), place(order_link_id=taken, lane="critical")]
    )


async def _critical_amend(harness: Harness) -> None:
    """A protective amend, as AC-31's (24 §8.8 rule 5); the fake answers it not found."""
    harness.prime_amend(link())
    await harness.port.amend_order(
        AmendOrderRequest(
            account=account(),
            symbol="BTCUSDT",
            order_link_id=link(),
            stop_loss=Decimal("58500"),
            lane="critical",
        )
    )


@pytest.mark.parametrize(
    "send", [_critical_create, _critical_batch, _critical_amend], ids=["create", "batch", "amend"]
)
async def test_both_take_a_create_a_batch_or_an_amend_in_its_requests_lane(
    harness: Harness, send: Callable[[Harness], Awaitable[None]]
) -> None:
    await send(harness)
    assert harness.lanes() == ["critical"]


async def _every_call(port: TradingPort, ref: AccountRef) -> AsyncIterator[Callable[[], Any]]:
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
    yield lambda: port.subscribe_private(ref)  # 24 §14.1: it refuses as every call does


async def test_both_refuse_another_environments_account_before_anything(harness: Harness) -> None:
    async for call in _every_call(harness.port, account(environment="live")):
        with pytest.raises(ValueError, match="another environment"):
            await call()
    assert harness.sent() == 0


@pytest.mark.parametrize(
    "key_ref",
    ["not-a-uuid", "", "  ", str(CREDENTIAL_ID).upper()],
    ids=["text", "empty", "blank", "upper-case"],
)
async def test_both_refuse_a_key_ref_that_is_not_an_api_keys_id(
    harness: Harness, key_ref: str
) -> None:
    """Ruling R13 on both ports, the headroom reading included: OMS tests on the fake meet the
    refusal the exchange's port gives, before anything is taken, signed or sent."""
    ref = account(key_ref=key_ref)
    async for call in _every_call(harness.port, ref):
        with pytest.raises(ValueError, match="api_keys id"):
            await call()
    port = harness.port
    assert isinstance(port, RateHeadroomPort)
    with pytest.raises(ValueError, match="api_keys id"):
        port.headroom(ref, "critical")
    assert harness.sent() == 0


#: A create, and a batch whose first item is valid and whose second is not (24 §14.2 rule 11).
CREATES: dict[str, Callable[[TradingPort, str], Awaitable[object]]] = {
    "create": lambda port, key: port.place_order(place(order_link_id=key)),
    "batch": lambda port, key: port.place_batch(
        [place(order_link_id=link(seq=1)), place(order_link_id=key)]
    ),
}


@pytest.mark.parametrize("create", sorted(CREATES))
@pytest.mark.parametrize(
    "key",
    [ext_key("x-1"), "linear-004", link(environment="live"), link(ACCOUNT_B), "cvp" + link()[3:]],
    ids=["ext", "foreign", "other-environment", "other-account", "paper"],
)
async def test_both_refuse_a_create_without_a_generated_id_of_its_account(
    harness: Harness, create: str, key: str
) -> None:
    with pytest.raises(ValueError, match="order_link_id"):
        await CREATES[create](harness.port, key)
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


async def test_both_refuse_an_amend_that_cannot_name_its_order(harness: Harness) -> None:
    """An amend moves a protective stop (C-2.6): its guard is the cancel's, on both ports."""

    def amend(order_link_id: str, exchange_order_id: str | None) -> AmendOrderRequest:
        return AmendOrderRequest(
            account=account(),
            symbol="BTCUSDT",
            order_link_id=order_link_id,
            exchange_order_id=exchange_order_id,
            stop_loss=Decimal("57000"),
            lane="critical",
        )

    for order_link_id in (ext_key("x-1"), "linear-004"):
        with pytest.raises(ValueError, match="exchange_order_id"):
            await harness.port.amend_order(amend(order_link_id, None))
    with pytest.raises(ValueError, match="another exchange order"):
        await harness.port.amend_order(amend(ext_key("another"), ORDER_ID))
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


async def test_both_place_a_batch_of_exactly_max_batch_size(harness: Harness) -> None:
    """The bound is inclusive: a batch of `max_batch_size` (10) orders is one call, one ack each."""
    links = [link(seq=n) for n in range(harness.port.capabilities.max_batch_size)]
    assert len(links) == 10  # the venue's bound (24 §14.1)
    harness.prime_batch(links)
    acks = await harness.port.place_batch([place(order_link_id=lk) for lk in links])
    assert [(a.ok, a.order_link_id) for a in acks] == [(True, lk) for lk in links]
    assert harness.lanes() == ["entry"]


async def test_both_refuse_a_window_that_ends_before_it_starts(harness: Harness) -> None:
    with pytest.raises(ValueError, match="start is after end"):
        await harness.port.executions(account(), NOW_US, NOW_US - 1)
    with pytest.raises(ValueError, match="start is after end"):
        await harness.port.closed_pnl(account(), NOW_US, NOW_US - 1)
    with pytest.raises(ValueError, match="start is after end"):
        await harness.port.order_history(account(), start=NOW_US, end=NOW_US - 1)
    assert harness.sent() == 0


@pytest.mark.parametrize("leverage", ["0", "-2", "NaN", "Infinity"])
async def test_both_refuse_a_leverage_that_is_not_positive(harness: Harness, leverage: str) -> None:
    with pytest.raises(ValueError, match="positive"):
        await harness.port.set_leverage(account(), "BTCUSDT", Decimal(leverage))
    assert harness.sent() == 0


async def test_both_accept_a_leverage_of_one_in_the_entry_lane(harness: Harness) -> None:
    harness.prime_position_writes()
    await harness.port.set_leverage(account(), "BTCUSDT", Decimal(1))
    assert harness.lanes() == ["entry"]


async def test_both_write_a_stop_in_the_critical_lane(harness: Harness) -> None:
    """SR-E29-14: the protective write is always critical, on the fake that T04's tests read
    as on the exchange's port."""
    harness.prime_position_writes()
    stop = TradingStopRequest(account=account(), symbol="BTCUSDT", stop_loss=Decimal("58000"))
    ack = await harness.port.set_trading_stop(stop)
    assert ack.ok and harness.lanes() == ["critical"]


async def test_both_write_a_partial_stop_with_its_size_in_the_critical_lane(
    harness: Harness,
) -> None:
    """G-8b (24 §8.9, §14.4): a Partial-mode stop carries its size and is still a protective,
    critical write; both answer one `ok` ack that names no order."""
    harness.prime_position_writes()
    stop = TradingStopRequest(
        account=account(),
        symbol="BTCUSDT",
        tpsl_mode="partial",
        stop_loss=Decimal("58000"),
        sl_size=Decimal("0.01"),
    )
    ack = await harness.port.set_trading_stop(stop)
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (True, None, None)
    assert harness.lanes() == ["critical"]


# -- a stop is never removed implicitly (C-2.6; the orchestrator's ruling 2 on #2877) ------------

#: Stop values the venue would read as a cancel (`0`), or that are no stop at all.
NOT_POSITIVE = ["0", "-1", "-0.0"]


def _partial(**fields: Any) -> TradingStopRequest:
    return TradingStopRequest(account=account(), symbol="BTCUSDT", tpsl_mode="partial", **fields)


def _sized(side: str, value: Decimal) -> TradingStopRequest:
    """A valid Partial-mode stop with `value` put in its size afterwards: `model_copy` skips the
    model's own refusal, as the port must refuse whatever built the request."""
    if side == "sl":
        valid = _partial(stop_loss=Decimal("58000"), sl_size=Decimal("0.01"))
        return valid.model_copy(update={"sl_size": value})
    valid = _partial(take_profit=Decimal("65000"), tp_size=Decimal("0.01"))
    return valid.model_copy(update={"tp_size": value})


#: Every path that sends a stop-loss or a stop size, given the value it sends.
STOP_PATHS: dict[str, Callable[[TradingPort, Decimal], Awaitable[object]]] = {
    "place_order": lambda port, v: port.place_order(place(stop_loss=v)),
    "place_batch": lambda port, v: port.place_batch(
        [place(order_link_id=link(seq=1)), place(order_link_id=link(seq=2), stop_loss=v)]
    ),
    "amend_order": lambda port, v: port.amend_order(
        AmendOrderRequest(account=account(), symbol="BTCUSDT", order_link_id=link(), stop_loss=v)
    ),
    "set_trading_stop": lambda port, v: port.set_trading_stop(
        TradingStopRequest(account=account(), symbol="BTCUSDT", stop_loss=v)
    ),
    "sl_size": lambda port, v: port.set_trading_stop(_sized("sl", v)),
    "tp_size": lambda port, v: port.set_trading_stop(_sized("tp", v)),
    # The ruling on SEC-G8B-A-01: a `trailingStop` of `0` cancels the trail at the venue.
    "trailing_distance": lambda port, v: port.set_trading_stop(
        TradingStopRequest(
            account=account(), symbol="BTCUSDT", stop_loss=Decimal("58000"), trailing_distance=v
        )
    ),
}


@pytest.mark.parametrize("value", NOT_POSITIVE)
@pytest.mark.parametrize("path", sorted(STOP_PATHS))
async def test_both_refuse_a_stop_that_is_not_positive_before_anything(
    harness: Harness, path: str, value: str
) -> None:
    """The venue reads a stop-loss of `0` as "cancel the stop": no path sends one, nor a stop
    size that is not positive (a batch's every item included), and nothing is sent, no token
    taken and nothing signed for it."""
    with pytest.raises(ValueError, match="positive number"):
        await STOP_PATHS[path](harness.port, Decimal(value))
    assert harness.sent() == 0


@pytest.mark.parametrize("path", sorted(STOP_PATHS))
async def test_both_still_send_a_positive_stop_on_every_path(harness: Harness, path: str) -> None:
    harness.prime_create(link())
    harness.prime_batch([link(seq=1), link(seq=2)])
    harness.prime_amend(link())
    harness.prime_position_writes()
    value = Decimal(
        {"sl_size": "0.01", "tp_size": "0.01", "trailing_distance": "100"}.get(path, "58000")
    )
    await STOP_PATHS[path](harness.port, value)
    assert harness.sent() > 0


#: Sizes no model admits (pydantic refuses them), which only a `model_copy` carries.
NOT_FINITE = ["NaN", "Infinity", "-Infinity"]


@pytest.mark.parametrize("value", NOT_FINITE)
@pytest.mark.parametrize("side", ["sl", "tp"])
async def test_both_refuse_a_stop_size_that_is_not_finite_before_anything(
    harness: Harness, side: str, value: str
) -> None:
    """A non-finite size is no positive number either: refused on the `model_copy` path, the
    one that can carry it, with nothing sent."""
    with pytest.raises(ValueError, match="positive number"):
        await harness.port.set_trading_stop(_sized(side, Decimal(value)))
    assert harness.sent() == 0


@pytest.mark.parametrize("side", ["sl", "tp"])
async def test_both_refuse_a_size_on_a_full_mode_stop_before_anything(
    harness: Harness, side: str
) -> None:
    """24 §14.4: a size goes with a Partial-mode stop only. A Full-mode stop a `model_copy` gave
    a size is refused before anything is sent, so `tpSize` and `slSize` never go with `Full`."""
    full = _sized(side, Decimal("0.01")).model_copy(update={"tpsl_mode": "full"})
    with pytest.raises(ValueError, match="Full-mode stop"):
        await harness.port.set_trading_stop(full)
    assert harness.sent() == 0


async def test_both_answer_a_cancel_naming_our_id_and_another_exchange_id_not_found(
    harness: Harness,
) -> None:
    """An exit named by both ids is sent by the exchange id alone (24 §14.2 rule 11), so a
    stale exchange id finds no order even though the link names one held."""
    request = place()
    harness.prime_create(request.order_link_id)
    await harness.port.place_order(request)
    harness.prime_missing_cancel()
    stale = CancelOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=request.order_link_id,
        exchange_order_id="another-order",
    )
    ack = await harness.port.cancel_order(stale)
    assert (ack.ok, ack.error_code, ack.order_link_id) == (
        False,
        "ORDER_NOT_FOUND",
        request.order_link_id,
    )


#: The lane of each call, written out (24 §14.2 rule 12, SR-E29-14): `None` is the request's.
LANES: dict[str, str | None] = {
    "place_order": None, "place_batch": None, "amend_order": None, "cancel_order": None,
    "cancel_all": "critical", "set_trading_stop": "critical",
    "set_leverage": "entry",
    "open_orders": "poll", "order_history": "poll", "positions": "poll", "executions": "poll",
    "closed_pnl": "poll", "wallet": "poll", "fee_rate": "poll", "account_info": "poll",
}  # fmt: skip


async def test_the_fakes_lanes_are_the_exchange_ports_endpoint_table() -> None:
    """The fake records each call's lane, which T04's tests read; it cannot drift from the
    exchange's port's table. Creates, batches and amends here ask for `critical`, not the
    default, so a fake that ignored the request's lane would show."""
    port = FakeTradingPort(environment="demo", now_us=lambda: NOW_US)
    created = place(lane="critical")
    await port.place_order(created)
    await port.place_batch([place(order_link_id=link(seq=1), lane="critical")])
    amend = AmendOrderRequest(
        account=account(), symbol="BTCUSDT", order_link_id=created.order_link_id,
        qty=Decimal("0.02"), lane="critical",
    )  # fmt: skip
    await port.amend_order(amend)
    async for call in _every_call(port, account()):
        try:
            await call()
        except ExchangeError:  # an unseeded account read, or a duplicate: recorded first
            pass
    recorded: dict[str, str] = {}
    for call_made in port.calls:  # each method's first call: a create, batch or amend asked
        recorded.setdefault(call_made.method, call_made.lane)  # for `critical` above
    assert set(recorded) == set(LANES) == set(ENDPOINTS)
    for name, lane in LANES.items():
        assert recorded[name] == (lane or "critical"), name
        assert ENDPOINTS[name].lane == lane, name


# -- the private stream (G-8b, #3963; 24 §14.1, §14.2 rule 13) -----------------------------------


async def test_both_refuse_another_environments_private_stream_before_anything(
    harness: Harness,
) -> None:
    with pytest.raises(ValueError, match="another environment"):
        await harness.port.subscribe_private(account(environment="live"))
    await harness.advance()
    assert harness.sent() == 0


async def test_both_give_an_account_one_private_stream_at_a_time(harness: Harness) -> None:
    """SR-E29-02: one consumer per account; closing the stream, even unread, frees it."""
    stream = await harness.port.subscribe_private(account())
    with pytest.raises(ValueError, match="already has a private stream"):
        await harness.port.subscribe_private(account())
    await stream.aclose()
    again = await harness.port.subscribe_private(account())
    await again.aclose()
    await harness.end_private()


async def test_both_end_a_private_stream_after_its_closed_status(harness: Harness) -> None:
    stream = await harness.port.subscribe_private(account())
    await harness.advance()
    await harness.end_private()
    async with asyncio.timeout(5):  # a guard only: every item is queued before the reads
        seen = [item async for item in stream]
    last = seen[-1]
    assert isinstance(last, PrivateStreamStatus)
    assert (last.state, last.reason) == ("closed", "shutdown")
    assert not [i for i in seen[:-1] if isinstance(i, PrivateStreamStatus) and i.state == "closed"]
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
