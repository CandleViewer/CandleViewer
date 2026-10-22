"""#3963 scenario "Heartbeat" (24 §14.2 rule 13, G-8b ruling 4), on the real B13 interpreter.

A dedicated task pings every 5 s; any frame re-arms an absolute 10 s deadline held outside the
chart (INV-B13-e), and past it B13 takes `PONG_DEADLINE`: `down(pong_timeout)`, then a new dial.
Each pong is `heartbeat` evidence for the account's health (`AccountHealth.ws_heartbeat`), one
pending at most.
"""

from __future__ import annotations

from typing import Any

from candleviewer.exchange.bybit.private_stream import WATCHDOG_S, PrivateStreams
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import raw
from tests.unit.exchange.bybit._private_venue import Consumer, PrivateVenue, make_streams, until
from tests.unit.exchange.bybit._trading import account


async def _live(venue: PrivateVenue) -> tuple[PrivateStreams, Consumer, float]:
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(venue.clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    return streams, consumer, venue.clock.now


async def _end(streams: PrivateStreams, consumer: Consumer) -> None:
    await consumer.stop()
    await streams.aclose()


async def test_a_ping_goes_out_every_5_s_from_its_own_task() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer, live = await _live(venue)
    await clock.advance(15.5)
    pings = [at - live for at, m in venue.socket.sent if m["op"] == "ping"]
    assert pings == [5.0, 10.0, 15.0]
    assert all(m == {"op": "ping"} for _, m in venue.socket.sent if m["op"] == "ping")
    await _end(streams, consumer)


async def test_each_pong_is_heartbeat_evidence_one_pending_at_most() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer, _ = await _live(venue)
    await clock.advance(20.5)
    heartbeats = [s for s in consumer.statuses() if s.startswith("heartbeat")]
    assert heartbeats == ["heartbeat:evidence:1"] * 5  # the auth reply, then four pongs
    await _end(streams, consumer)


async def test_a_pong_or_a_push_keeps_the_socket_and_10_s_of_silence_ends_it() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer, _ = await _live(venue)
    await clock.advance(60)  # pongs every 5 s
    assert len(venue.sockets) == 1
    venue.pongs = False
    for _ in range(4):  # pushes alone keep it, 6 s apart
        venue.socket.push(raw("position"))
        await clock.advance(6)
    assert len(venue.sockets) == 1
    silent = clock.now
    await until(clock, lambda: "down:pong_timeout:1" in consumer.statuses(), within_s=11, what="d")
    assert clock.now - silent <= WATCHDOG_S
    venue.pongs = True
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="2"
    )
    assert len(venue.sockets) == 2 and venue.sockets[0].closed
    await _end(streams, consumer)


async def test_the_deadline_is_absolute_held_outside_the_chart_and_pong_never_sent_to_it() -> None:
    """INV-B13-e: the runtime holds an absolute deadline on its monotonic clock, re-armed by
    each frame (the last pong here); the chart is sent no event while the socket is healthy."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams, consumer, live = await _live(venue)
    [conn] = streams._conns.values()
    sent: list[str] = []
    real = conn._interp.send

    def recording(event: str, *args: Any, **kwargs: Any) -> Any:
        sent.append(event)
        return real(event, *args, **kwargs)

    conn._interp.send = recording
    await clock.advance(12)
    assert conn._deadline == live + 10.0 + WATCHDOG_S  # the pong at +10 s re-armed it
    assert sent == []
    conn._interp.send = real
    await _end(streams, consumer)
