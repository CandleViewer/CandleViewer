"""The private stream's bounds and isolation (24 §14.2 rule 13; C-2.11, C-2.18, C-2.20, SR-040a,
SR-E29-02), on the real B13 interpreter, a fake venue and a virtual clock.

One stream per account and at most 64 (`stream_cap`, told apart from a refused token, OQ-2); a
full queue ends the epoch as `slow_consumer`; an oversize frame recycles the socket, a too-deep
or unreadable one is `resyncing(rejected_frame)` with the socket kept; `aclose()` and the
consumer's cancellation close the socket; the stream sends `auth`, `subscribe` and `ping` only,
on its own environment's host; frames never reach the interpreter (C-2.20) and the plain phase
never reads it (INV-B13-d); and account B's push on A's socket is dropped and counted.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from uuid import UUID

import pytest

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.models import Order
from candleviewer.exchange.base.reconnect import ws_conn_budget_refused_total
from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.metrics import (
    bybit_private_frames_rejected_total,
    bybit_private_rows_refused_total,
    bybit_private_ws_streams,
)
from candleviewer.exchange.bybit.private_stream import DATA_SLOTS, FRAME_BYTES, _PrivateConn
from tests._signing import Call
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import linear_order, push, raw, row
from tests.unit.exchange.bybit._private_venue import Consumer, PrivateVenue, make_streams, until
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, account, link

ACCOUNT_C = AccountId(UUID("7d3e1f40-9152-4c8d-8e6f-4a5b6c7d8e9f"))


async def _live(venue: PrivateVenue, **kwargs: Any) -> tuple[Any, Consumer]:
    streams = make_streams(venue, **kwargs)
    consumer = Consumer(await streams.open(account()))
    await until(venue.clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    return streams, consumer


def _value(metric: Any, **labels: str) -> float:
    value: float = metric.labels(**labels)._value.get()
    return value


async def test_an_account_has_one_stream_until_it_is_closed() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer = await _live(venue)
    with pytest.raises(ValueError, match="already has a private stream"):
        await streams.open(account())
    assert len(venue.dialled) == 1
    await consumer.stop()
    again = Consumer(await streams.open(account()))
    await until(clock, lambda: len(again.statuses()) == 2, within_s=5, what="again")
    await again.stop()
    await streams.aclose()


async def test_the_stream_cap_refuses_as_a_budget_told_apart_from_a_refused_token() -> None:
    """OQ-2: past the cap the open is a retryable `RateBudgetExceededError` whose `reason` is
    `stream_cap`, counted in `ws_conn_budget_refused_total{scope="streams"}` too, which a refused
    REST token (`reason` `token_bucket`) never touches; nothing is signed or dialled."""
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, calls=calls, max_streams=2)
    first = await streams.open(account(ACCOUNT_A))
    second = await streams.open(account(ACCOUNT_B))
    assert bybit_private_ws_streams._value.get() == 2
    await clock.advance(5)
    signed, dialled = len(calls), len(venue.dialled)
    capped = _value(ws_conn_budget_refused_total, scope="streams")
    with pytest.raises(RateBudgetExceededError) as refused:
        await streams.open(account(ACCOUNT_C))
    assert (refused.value.reason, refused.value.retryable) == ("stream_cap", True)
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    assert _value(ws_conn_budget_refused_total, scope="streams") == capped + 1
    assert (len(calls), len(venue.dialled)) == (signed, dialled)
    token = RateBudgetExceededError("no rate token within the lane's wait; nothing was sent")
    assert token.reason == "token_bucket"  # what the REST governor raises: another reason
    assert bybit_private_ws_streams._value.get() == 2  # the refused one never counted
    for stream in (first, second):
        await stream.aclose()
    assert bybit_private_ws_streams._value.get() == 0
    await streams.aclose()


async def test_a_full_queue_ends_the_epoch_as_a_slow_consumer_then_resyncs() -> None:
    """C-2.18: an event that finds the queue full ends the epoch, announced, never dropped
    silently; the next epoch's `resyncing` lets REST cover the gap."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    stream = await streams.open(account())
    await clock.advance(1)  # live; nothing read
    rows = [row("position")] * 1000
    venue.socket.push(*[push("position.linear", *rows)] * 3)  # 3,000 events: past 2,048
    await clock.advance(1)
    consumer = Consumer(stream)
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=60, what="2"
    )
    shown = consumer.shown()
    assert shown.count("position") == 2000 <= DATA_SLOTS  # two whole frames; the third is refused
    assert shown[shown.index("down:slow_consumer:1") - 1] == "position"
    await consumer.stop()
    await streams.aclose()


@pytest.mark.parametrize("max_size", [FRAME_BYTES, None], ids=["socket-refuses", "stream-refuses"])
async def test_an_oversize_frame_recycles_the_socket_counted_as_oversize(
    max_size: int | None,
) -> None:
    """SEC-G8B-C-01: production's socket refuses a frame above 1 MiB (its library closes the
    socket 1009 and the read raises `FrameTooLarge`, `test_key_ws_probe_real_socket.py`); a
    socket that hands one over whole meets the stream's own bound. Either way the socket recycles
    and the frame counts as `oversize`, and every read is bounded by `FRAME_BYTES`
    (CR-G8B-C-10)."""
    clock = VirtualClock()
    venue = PrivateVenue(clock, max_size=max_size)
    streams, consumer = await _live(venue)
    before = _value(bybit_private_frames_rejected_total, reason="oversize")
    venue.socket.push("x" * (FRAME_BYTES + 1))
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="2"
    )
    assert "down:socket_closed:1" in consumer.statuses()
    assert _value(bybit_private_frames_rejected_total, reason="oversize") == before + 1
    assert set(venue.bounds) == {FRAME_BYTES}
    await consumer.stop()
    await streams.aclose()


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        ('{"topic":"order.linear","data":' + "[" * 40 + "]" * 40 + "}", "depth_limit"),
        ("not json", "malformed"),
        ('{"topic":"greeks","creationTime":1672364262474,"data":[]}', "unknown_frame"),
        (push("order.linear", linear_order(price="abc")), "malformed"),
    ],
    ids=["too-deep", "not-json", "unsubscribed-topic", "unreadable-row"],
)
async def test_a_frame_it_cannot_read_is_a_resync_and_the_socket_stays(
    frame: str, reason: str
) -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer = await _live(venue)
    before = _value(bybit_private_frames_rejected_total, reason=reason)
    venue.socket.push(frame, frame, raw("execution"))  # two rejections: one resync pending at most
    await clock.advance(1)
    assert consumer.shown()[2:] == ["resyncing:rejected_frame:1", "execution"]
    assert _value(bybit_private_frames_rejected_total, reason=reason) == before + 2
    assert len(venue.sockets) == 1
    await consumer.stop()
    await streams.aclose()


async def test_aclose_and_the_consumers_cancellation_both_close_the_socket() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer = await _live(venue)
    await consumer.stream.aclose()
    await clock.settle()
    assert venue.sockets[0].closed and streams.count() == 0
    stream = await streams.open(account())
    reading = asyncio.ensure_future(stream.__anext__())
    await clock.advance(1)
    for _ in range(2):  # heartbeat, resyncing
        await reading
        reading = asyncio.ensure_future(stream.__anext__())
        await clock.settle()
    reading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reading
    await streams.drain()
    assert venue.sockets[1].closed and streams.count() == 0
    await clock.advance(120)
    assert len(venue.sockets) == 2  # closed: never redialled
    await streams.aclose()


async def test_aclose_before_any_read_closes_the_stream() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    stream = await streams.open(account())
    await stream.aclose()
    await streams.drain()
    await clock.advance(60)
    assert streams.count() == 0 and all(s.closed for s in venue.sockets)
    await streams.aclose()


async def test_the_stream_sends_auth_subscribe_and_ping_only() -> None:
    """SR-040a: no order entry over WS, nor any other op, on any socket of the stream."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer = await _live(venue)
    await clock.advance(30)
    venue.socket.drop()
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="2"
    )
    await clock.advance(30)
    assert {op for s in venue.sockets for op in s.ops()} == {"auth", "subscribe", "ping"}
    await consumer.stop()
    await streams.aclose()


@pytest.mark.parametrize("environment", ["demo", "live"])
async def test_a_stream_dials_its_own_environments_private_host_only(
    environment: Environment,
) -> None:
    """C-2.11: demo on `stream-demo`, live on `stream`; an account of another environment is
    refused before anything is signed, dialled or built."""
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, calls=calls, environment=environment)
    other: Environment = "live" if environment == "demo" else "demo"
    with pytest.raises(ValueError, match="another environment"):
        await streams.open(account(environment=other))
    assert (venue.dialled, calls, streams.count()) == ([], [], 0)
    stream = await streams.open(account(environment=environment))
    await clock.advance(1)
    assert venue.dialled == [PRIVATE_WS_URLS[environment]]
    await stream.aclose()
    await streams.aclose()


async def test_frames_never_reach_the_interpreter() -> None:
    """C-2.20: 1,000 pushes and 100 pongs, and B13 is sent nothing."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer = await _live(venue)
    [conn] = streams._conns.values()
    sent: list[str] = []
    real = conn._interp.send

    def recording(event: str, *args: Any, **kwargs: Any) -> Any:
        sent.append(event)
        return real(event, *args, **kwargs)

    conn._interp.send = recording
    for _ in range(1000):
        venue.socket.push(raw("position"))
    venue.socket.push(*[raw("pong")] * 100)
    await clock.advance(1)
    assert sent == [] and len(consumer.events()) == 1000
    conn._interp.send = real
    await consumer.stop()
    await streams.aclose()


def test_the_phase_hot_paths_read_is_plain_never_the_interpreter() -> None:
    """INV-B13-d, as `test_b13_ws_conn.py` pins it for the public manager."""
    source = inspect.getsource(_PrivateConn.state)
    assert "_interp" not in source and "current_state" not in source


async def test_bs_push_on_as_socket_is_dropped_and_counted_and_as_own_is_delivered() -> None:
    """#3963 scenario 1 at the stream: streams open for A and B; a push carrying B's order on
    A's socket is dropped, counted, and never delivered as A's."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    mine = Consumer(await streams.open(account(ACCOUNT_A)))
    theirs = Consumer(await streams.open(account(ACCOUNT_B)))
    await until(
        clock, lambda: len(mine.statuses()) == len(theirs.statuses()) == 2, within_s=5, what="l"
    )
    a_socket = venue.sockets[0]
    before = _value(bybit_private_rows_refused_total, topic="order", reason="account")
    a_socket.push(
        push("order.linear", linear_order(orderLinkId=link(ACCOUNT_B))),
        push("order.linear", linear_order(orderLinkId=link(ACCOUNT_A))),
    )
    await clock.advance(1)
    [delivered] = mine.events()
    assert delivered.account_id == ACCOUNT_A and theirs.events() == []
    assert isinstance(delivered.payload, Order)
    assert delivered.payload.order_link_id == link(ACCOUNT_A)
    assert _value(bybit_private_rows_refused_total, topic="order", reason="account") == before + 1
    for consumer in (mine, theirs):
        await consumer.stop()
    await streams.aclose()


def test_the_stream_reads_frames_as_large_as_its_connector_takes() -> None:
    assert FRAME_BYTES == key_ws_probe.STREAM_FRAME_BYTES
