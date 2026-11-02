"""A cancel's lane through the Bybit `TradingPort` (E35-T11 slice 3a; 24 Sec.14.2 rule 12,
Sec.14.4; the E29 threat model's AC-31 and OM-D09; the E35 threat model's RE-D6).

Over the transcribed cancel reply (`rest/trading-cancel-reply.json`, ruling R2): a cancel goes on
the order class in its request's lane, `entry` for a rule's own cancel, which only the OMS names
(24 Sec.8.4 "Rule-originated orders" item 3), and `critical` for every request that names none,
so AC-31 holds for each existing caller. The lane never reaches the venue's body. The exchange
fake records the lane each cancel asked for, as the port's tests read it.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import CancelOrderRequest, OrderLane
from candleviewer.exchange.bybit.config import EndpointClass
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import NOW_US, RecordingGovernor, Venue, account, make_port

CANCEL = "rest/trading-cancel-reply.json"


def _cancel(**over: Any) -> CancelOrderRequest:
    """A cancel by `orderId` of an `ext-` order, as the transcribed reply names it."""
    order_id = rest(CANCEL)["result"]["orderId"]
    fields: dict[str, Any] = {
        "account": account(), "symbol": "BTCUSDT", "order_link_id": ext_key(order_id),
        "exchange_order_id": order_id,
    }  # fmt: skip
    return CancelOrderRequest(**(fields | over))


async def _sent(request: CancelOrderRequest) -> tuple[list[tuple[Any, ...]], dict[str, Any]]:
    venue, governor = Venue().on("/v5/order/cancel", rest(CANCEL)), RecordingGovernor()
    ack = await make_port(venue, governor=governor).cancel_order(request)
    assert ack.ok and ack.exchange_order_id == request.exchange_order_id
    [body] = venue.bodies()
    return [(cls, lane) for _, cls, lane, _ in governor.acquired], body


@pytest.mark.parametrize("lane", ["entry", "critical"])
async def test_a_cancel_is_sent_in_its_requests_lane(lane: OrderLane) -> None:
    """RE-D6: a rule's own cancel names `entry`, and the port takes its token there, on the
    order class; a protective cancel names `critical`. Nothing of the lane goes on the wire."""
    acquired, body = await _sent(_cancel(lane=lane))
    assert acquired == [(EndpointClass.ORDER, lane)]
    order_id = rest(CANCEL)["result"]["orderId"]
    assert body == {"category": "linear", "orderId": order_id, "symbol": "BTCUSDT"}
    fake = FakeTradingPort(environment="demo", now_us=lambda: NOW_US)
    await fake.cancel_order(_cancel(lane=lane))  # the fake holds no order: answered refused
    assert [(c.method, c.lane) for c in fake.calls] == [("cancel_order", lane)]


async def test_a_cancel_with_no_lane_named_rides_critical() -> None:
    """AC-31 for every existing caller: a cancel that names no lane (a user's, a cancel-all's
    order, a KILL's, the circuit breaker's) is a `critical` one, at the port and at the fake."""
    request = _cancel()
    assert request.lane == "critical"
    acquired, _ = await _sent(request)
    assert acquired == [(EndpointClass.ORDER, "critical")]
    fake = FakeTradingPort(environment="demo", now_us=lambda: NOW_US)
    await fake.cancel_order(request)
    assert [c.lane for c in fake.calls] == ["critical"]


def test_a_cancel_names_no_lane_but_the_two_order_lanes() -> None:
    """The model refuses any other lane, `poll` included: a read's lane never sends a cancel."""
    for lane in ("poll", "background", "", None):
        with pytest.raises(ValueError, match="lane"):
            _cancel(lane=lane)
