"""#3963 scenario "Reconnect re-authenticates and signals a resync" (24 §14.2 rule 13), on the real
B13 interpreter, a fake venue and a virtual clock (`_private_venue.py`).

When the socket drops, the stream reports `down` after the epoch's last row, backs off within
the policy's ceiling, dials again, signs a fresh `auth` through M2 (a later `expires`), sends the
same subscribe ops, and reports `heartbeat` and then `resyncing` before any row of the new
epoch, so the consumer reconciles over REST (C-2.5). The attempt count, which sets the ceiling,
grows across failures and resets only once an epoch has stayed live 30 s; an event armed for an
earlier socket never moves a later one; and a consumer that has not read the last `down` holds
the next dial, which `bybit_private_reconnect_waited_total` counts once (the orchestrator's OQ-D
ruling); a dial the consumer never held is not counted.
"""

from __future__ import annotations

from candleviewer.exchange.base.models import Execution
from candleviewer.exchange.bybit.metrics import (
    bybit_private_reconnect_waited_total,
    bybit_private_ws_auth_total,
    bybit_private_ws_disconnects_total,
)
from candleviewer.exchange.bybit.private_stream import (
    DIAL_TIMEOUT_S,
    REQUIRED_OPS,
    STABLE_RESET_S,
)
from tests._signing import Call
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import raw
from tests.unit.exchange.bybit._private_venue import (
    Consumer,
    PrivateVenue,
    make_streams,
    until,
)
from tests.unit.exchange.bybit._trading import account

SUBSCRIBED = [list(ops) for ops in REQUIRED_OPS] + [["execution.fast.linear"]]


def _subscribes(venue: PrivateVenue, socket: int) -> list[list[str]]:
    return [m["args"] for _, m in venue.sockets[socket].sent if m["op"] == "subscribe"]


def _waited() -> float:
    """The dials so far that waited for their consumer to read the last `down` (process-wide)."""
    value: float = bybit_private_reconnect_waited_total._value.get()
    return value


async def test_a_dropped_socket_reconnects_reauthenticates_and_resyncs() -> None:
    granted = bybit_private_ws_auth_total.labels(result="granted")._value.get()
    dropped = bybit_private_ws_disconnects_total.labels(reason="socket_closed")._value.get()
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, calls=calls)
    consumer = Consumer(await streams.open(account()))
    await until(
        clock, lambda: "resyncing:connected:1" in consumer.statuses(), within_s=5, what="live"
    )
    venue.socket.push(raw("execution"))
    await until(clock, lambda: len(consumer.events()) == 1, within_s=1, what="first row")
    first = clock.now
    venue.socket.drop()
    await until(clock, lambda: len(venue.sockets) == 2, within_s=30, what="redial")
    assert clock.now - first <= 0.5 * 2  # the first backoff's ceiling: attempt 1 of 0.5 s doubling
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=5, what="resync"
    )
    venue.socket.push(raw("execution"))
    await until(clock, lambda: len(consumer.events()) == 2, within_s=1, what="second row")
    assert consumer.shown() == [
        "heartbeat:evidence:1",
        "resyncing:connected:1",
        "execution",
        "down:socket_closed:1",
        "heartbeat:evidence:2",
        "resyncing:reconnected:2",
        "execution",
    ]
    # A fresh `auth` per dial, signed by M2 on the exchange clock: a later `expires` each time.
    auths = venue.sent("auth")
    assert [c[2] for c in calls] == ["sign_ws_auth", "sign_ws_auth"]
    assert auths[1]["args"][1] > auths[0]["args"][1]
    assert _subscribes(venue, 0) == _subscribes(venue, 1) == SUBSCRIBED
    assert venue.sockets[0].closed and not venue.sockets[1].closed
    assert all(isinstance(e.payload, Execution) for e in consumer.events())
    # One `auth` granted per dial, one socket lost, each counted once.
    assert bybit_private_ws_auth_total.labels(result="granted")._value.get() == granted + 2
    lost = bybit_private_ws_disconnects_total.labels(reason="socket_closed")._value.get()
    assert lost == dropped + 1
    await consumer.stop()
    await streams.aclose()


async def test_nothing_of_an_epoch_follows_its_down() -> None:
    """A row the venue sends after the drop never reaches the consumer as the old epoch's."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(
        clock, lambda: "resyncing:connected:1" in consumer.statuses(), within_s=5, what="live"
    )
    old = venue.socket
    old.drop()
    old.push(raw("execution"))  # behind the drop: never read
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="resync"
    )
    down = consumer.shown().index("down:socket_closed:1")
    assert "execution" not in consumer.shown()[down:]
    await consumer.stop()
    await streams.aclose()


async def test_the_backoff_ceiling_grows_across_failures_and_resets_only_after_30_s_live() -> None:
    """INV-B13-b: each failed dial raises the attempt count, which the delay's ceiling doubles
    on; reaching `live` does not reset it at once, only 30 s of it does."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.fail_dials = 4
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(
        clock, lambda: "resyncing:connected:1" in consumer.statuses(), within_s=60, what="live"
    )
    [conn] = streams._conns.values()
    assert conn.attempt == 5  # four failed dials, then the one that went live
    await clock.advance(STABLE_RESET_S - 1)
    venue.socket.drop()  # live for less than 30 s: the count keeps growing
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=60, what="again"
    )
    assert conn.attempt == 6
    await clock.advance(STABLE_RESET_S + 1)  # live 30 s: reset
    assert conn.attempt == 0
    await consumer.stop()
    await streams.aclose()


async def test_an_event_armed_for_an_earlier_socket_never_moves_a_later_one() -> None:
    """The chart defers what a state does not take, so a `SOCKET_CLOSED` left from epoch 1 would
    end epoch 2 in `live`: the runtime drops any event not armed for the current socket."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(
        clock, lambda: "resyncing:connected:1" in consumer.statuses(), within_s=5, what="live"
    )
    venue.socket.drop()
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="2"
    )
    [conn] = streams._conns.values()
    sent: list[str] = []
    interp = conn._interp
    real = interp.send

    def recording(event: str, *args: object, **kwargs: object) -> object:
        sent.append(event)
        return real(event, *args, **kwargs)

    interp.send = recording
    await conn._send_armed(interp, "SOCKET_CLOSED", 1)  # armed for epoch 1
    await clock.advance(30)
    assert sent == [] and len(venue.sockets) == 2 and conn.state() == "open"
    interp.send = real
    await consumer.stop()
    await streams.aclose()


async def test_a_consumer_that_has_not_read_the_last_down_holds_the_next_dial() -> None:
    """A stalled consumer holds one epoch's statuses at most: the stream redials only once the
    epoch's `down` has been read."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    stream = await streams.open(account())
    await clock.advance(5)  # live; nothing read yet
    before = _waited()
    venue.socket.drop()
    await clock.advance(120)
    assert len(venue.sockets) == 1  # the `down` is unread
    assert _waited() == before + 1  # the held dial, counted once however long it waits
    consumer = Consumer(stream)
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="2"
    )
    assert len(venue.sockets) == 2
    assert _waited() == before + 1
    await consumer.stop()
    await streams.aclose()


async def test_a_dial_the_consumer_never_held_is_not_counted_as_waited() -> None:
    """A consumer that reads as it goes has read the `down` before the backoff ends, so the
    redial waits for nothing and `bybit_private_reconnect_waited_total` stays as it was."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(
        clock, lambda: "resyncing:connected:1" in consumer.statuses(), within_s=5, what="live"
    )
    before = _waited()
    venue.socket.drop()
    await until(
        clock, lambda: "resyncing:reconnected:2" in consumer.statuses(), within_s=30, what="2"
    )
    assert "down:socket_closed:1" in consumer.statuses()
    assert _waited() == before
    await consumer.stop()
    await streams.aclose()


async def test_a_dial_that_never_answers_is_let_go_at_5_s_and_the_stream_dials_again() -> None:
    """CR-G8B-C-01: the dial's bound (`DIAL_TIMEOUT_S`) on the injected clock: a dial the venue
    never answers is let go at 5 s, and the stream backs off, dials again and goes live."""
    clock = VirtualClock()
    venue = PrivateVenue(clock, stall_dials=1)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await clock.advance(DIAL_TIMEOUT_S * 0.98)
    assert len(venue.dialled) == 1 and venue.sockets == []
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    assert len(venue.dialled) == 2 and clock.now >= DIAL_TIMEOUT_S
    await consumer.stop()
    await streams.aclose()
