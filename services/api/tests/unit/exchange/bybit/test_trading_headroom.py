"""The rate headroom a lane would meet, read without a token (G-8, #2877 ruling 4; 24 §14.1).

`BybitTradingPort.headroom(account, lane)` reads the process governor's buckets for the class the
lane's requests draw (the order class for `critical` and `entry`, the account-reads class for
`poll`, 24 §14.2 rule 12): the spare tokens and the wait the next request would face, an IP hold
included. It takes no token and sends nothing, and the next call of that lane does what it says:
no wait, a wait of that length, or a refusal with nothing sent once the wait passes the lane's
(24 §8.7). Virtual time: the governor, the port and the sleeper share one clock; no network.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from candleviewer.exchange.base import RateHeadroomPort
from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.models import CancelOrderRequest, RateHeadroom, RateLane
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.trading import BybitTradingPort
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import (
    FakeClock,
    RecordingGovernor,
    Venue,
    account,
    link,
    make_port,
    place,
    with_result,
)

UID = "100001"
CANCEL = rest("rest/trading-cancel-reply.json")
CREATED = with_result(rest("rest/trading-create-reply.json"), orderLinkId=link())
REALTIME = with_result(rest("rest/trading-order-realtime.json"), nextPageCursor="")
LANES: tuple[RateLane, ...] = ("critical", "entry", "poll")
#: One call of each lane: an exit, a create, a read.
CALLS: dict[RateLane, Callable[[BybitTradingPort], Awaitable[Any]]] = {
    "critical": lambda port: port.cancel_order(
        CancelOrderRequest(
            account=account(), symbol="BTCUSDT", exchange_order_id=CANCEL["result"]["orderId"]
        )
    ),
    "entry": lambda port: port.place_order(place()),
    "poll": lambda port: port.open_orders(account()),
}


def _venue() -> Venue:
    return (
        Venue()
        .on("/v5/order/cancel", CANCEL)
        .on("/v5/order/create", CREATED)
        .on("/v5/order/realtime", REALTIME)
    )


def _governed(capacity: float) -> tuple[FakeClock, RecordingGovernor]:
    clock = FakeClock()
    governor = RecordingGovernor(
        default_capacity=capacity, default_refill_per_s=1.0, clock=clock.now, sleep=clock.sleep
    )
    return clock, governor


def _class(lane: RateLane) -> EndpointClass:
    return EndpointClass.ACCOUNT if lane == "poll" else EndpointClass.ORDER


def test_the_port_reads_its_headroom_through_the_small_protocol() -> None:
    """The runtime shape; the signature is checked by `trading.py`'s `TYPE_CHECKING`
    assignment to `RateHeadroomPort`, which CI's mypy lane reads."""
    port: RateHeadroomPort = make_port(Venue())
    assert isinstance(port, RateHeadroomPort)


async def test_reading_the_headroom_takes_no_token_and_sends_nothing() -> None:
    clock, governor = _governed(3.0)
    venue = _venue()
    port = make_port(venue, governor=governor, clock=clock)

    readings = [port.headroom(account(), lane) for lane in LANES for _ in range(3)]

    assert {(r.tokens, r.wait_s) for r in readings} == {(3.0, 0.0)}
    assert (governor.acquired, venue.sent) == ([], [])
    await CALLS["critical"](port)  # the call takes its one token; the reading took none
    assert port.headroom(account(), "critical") == RateHeadroom(
        lane="critical", tokens=2.0, wait_s=0.0
    )
    assert port.headroom(account(), "poll").tokens == 3.0  # the reads' class is untouched


def _drained(lane: RateLane) -> tuple[FakeClock, Venue, BybitTradingPort]:
    """A port whose lane's bucket is drained: it refills in 1 s."""
    clock, governor = _governed(1.0)
    venue = _venue()
    port = make_port(venue, governor=governor, clock=clock)
    governor.drain(UID, _class(lane), 1.0)
    return clock, venue, port


@pytest.mark.parametrize("lane", ["critical", "poll"])
async def test_a_lane_whose_wait_covers_the_reading_waits_exactly_that_long(
    lane: RateLane,
) -> None:
    """1 s is within `critical`'s and `poll`'s 5 s: the call waits the read wait, then sends."""
    clock, venue, port = _drained(lane)
    reading = port.headroom(account(), lane)
    assert (reading.lane, reading.tokens, reading.wait_s) == (lane, 0.0, 1.0)
    await CALLS[lane](port)
    assert sum(clock.sleeps) == pytest.approx(reading.wait_s) and len(venue.sent) == 1


async def test_a_lane_whose_wait_the_reading_passes_is_refused_with_nothing_sent() -> None:
    """1 s is past `entry`'s 0.75 s: the reading says so, and the call is refused unsent."""
    _, venue, port = _drained("entry")
    reading = port.headroom(account(), "entry")
    assert (reading.lane, reading.tokens, reading.wait_s) == ("entry", 0.0, 1.0)
    with pytest.raises(RateBudgetExceededError, match="nothing was sent"):
        await CALLS["entry"](port)
    assert venue.sent == []


async def test_a_spare_token_means_the_next_call_does_not_wait() -> None:
    clock, governor = _governed(2.0)
    venue = _venue()
    port = make_port(venue, governor=governor, clock=clock)
    for lane in LANES:
        assert port.headroom(account(), lane).wait_s == 0.0
        await CALLS[lane](port)
    assert clock.sleeps == [] and len(venue.sent) == 3


def test_each_lane_reads_the_class_its_requests_draw() -> None:
    clock, governor = _governed(1.0)
    port = make_port(Venue(), governor=governor, clock=clock)
    governor.drain(UID, EndpointClass.ORDER, 1.0)
    assert [port.headroom(account(), lane).wait_s for lane in LANES] == [1.0, 1.0, 0.0]
    governor.drain(UID, EndpointClass.ACCOUNT, 1.0)
    assert port.headroom(account(), "poll").wait_s == 1.0


async def test_an_ip_hold_is_in_every_lanes_wait_and_refuses_what_it_outlasts() -> None:
    clock, governor = _governed(10.0)
    venue = _venue()
    port = make_port(venue, governor=governor, clock=clock)
    governor.hold_ip(600.0)

    assert [port.headroom(account(), lane).wait_s for lane in LANES] == [600.0] * 3
    with pytest.raises(RateBudgetExceededError, match="nothing was sent"):
        await CALLS["critical"](port)
    assert venue.sent == [] and clock.sleeps == []


def test_a_bucket_that_does_not_refill_never_frees_a_token() -> None:
    clock = FakeClock()
    governor = RecordingGovernor(
        default_capacity=1.0, default_refill_per_s=0.0, clock=clock.now, sleep=clock.sleep
    )
    port = make_port(Venue(), governor=governor, clock=clock)
    governor.drain(UID, EndpointClass.ORDER, 1.0)
    assert port.headroom(account(), "entry").wait_s == float("inf")


def test_the_reading_refuses_another_environments_account() -> None:
    governor = RecordingGovernor()
    port = make_port(Venue(), governor=governor)
    with pytest.raises(ValueError, match="another environment"):
        port.headroom(account(environment="live"), "entry")
