"""The private stream's less travelled paths (24 §14.2 rule 13), on the real B13 interpreter, a fake
venue and a virtual clock: rows read while subscribing wait behind `resyncing`; a refused,
unanswered or broken required subscription recycles the socket and the optional one does not;
`budget_blocked` waits for the window; and a stream that is closing sends nothing more at any
step (each B13 hook checks it). Plus the registry's edges: an unknown environment, a failed
build, a failed owned task, and the bounded key marks.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.models import PrivateStreamStatus
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.metrics import bybit_private_subscribe_refused_total
from candleviewer.secrets import CredentialBorrower, RequestSignature
from tests._signing import CREDENTIAL_ID, Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import push, raw, row
from tests.unit.exchange.bybit._private_venue import (
    DROP,
    REFUSED_SUBSCRIBE,
    Consumer,
    PrivateVenue,
    VenueSocket,
    make_streams,
    until,
)
from tests.unit.exchange.bybit._trading import SIGNER_ID, account

RECONNECTED = "resyncing:reconnected:2"
FIRST_LIVE_2 = "resyncing:connected:2"


def _refused(topic: str) -> float:
    value: float = bybit_private_subscribe_refused_total.labels(topic=topic)._value.get()
    return value


class _Scripted(PrivateVenue):
    """A venue that also sends `extra[op]` frames right after its reply to the first such op."""

    extra: dict[str, list[str]]

    def answer(self, sock: VenueSocket, message: dict[str, Any]) -> None:
        super().answer(sock, message)
        frames = self.extra.pop(str(message.get("op")), None) if hasattr(self, "extra") else None
        for frame in frames or ():
            if frame == DROP:
                sock.drop()
            else:
                sock.push(frame)


async def test_rows_read_while_subscribing_wait_behind_resyncing() -> None:
    """A push between the subscribe acknowledgements is delivered after `resyncing`, and a frame
    the stream cannot read then is counted only: the coming `resyncing` covers it."""
    clock = VirtualClock()
    venue = _Scripted(clock)
    venue.extra = {"subscribe": [raw("execution"), "not json"]}
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.items) == 3, within_s=5, what="live and the row")
    assert consumer.shown() == ["heartbeat:evidence:1", "resyncing:connected:1", "execution"]
    await consumer.stop()
    await streams.aclose()


@pytest.mark.parametrize(
    ("script", "reason"),
    [([REFUSED_SUBSCRIBE], "subscribe_refused"), ([None], "subscribe_refused")],
    ids=["refused", "unanswered"],
)
async def test_a_required_subscription_refused_or_unanswered_recycles_the_socket(
    script: list[str | None], reason: str
) -> None:
    """INV-B13-c: a partial required subscription never reaches `live`; the epoch is down."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.subscribe.extend(script)
    before = _refused("order+execution+position")
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    # Epoch 1 never went live, so epoch 2's `live` is the stream's first: `connected`.
    await until(clock, lambda: FIRST_LIVE_2 in consumer.statuses(), within_s=60, what="again")
    assert consumer.statuses()[:2] == ["heartbeat:evidence:1", f"down:{reason}:1"]
    assert _refused("order+execution+position") == before + 1
    await consumer.stop()
    await streams.aclose()


@pytest.mark.parametrize("script", [REFUSED_SUBSCRIBE, None], ids=["refused", "unanswered"])
async def test_the_optional_fast_fills_refused_or_unanswered_leave_the_socket_live(
    script: str | None,
) -> None:
    """Ruling 2: the third op is counted and the socket stays; a late acknowledgement on the
    live socket is no frame to resync on."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.subscribe.extend([raw("subscribe-ok"), raw("subscribe-ok"), script])
    before = _refused("execution.fast")
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=10, what="live")
    venue.socket.push(raw("subscribe-ok"))  # late
    await clock.advance(1)
    assert consumer.statuses() == ["heartbeat:evidence:1", "resyncing:connected:1"]
    assert _refused("execution.fast") == before + 1 and len(venue.sockets) == 1
    await consumer.stop()
    await streams.aclose()


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ([DROP], "socket_closed"),
        ([push("position.linear", *[row("position")] * 1000)] * 3, "slow_consumer"),
    ],
    ids=["dropped", "overflow"],
)
async def test_a_subscription_broken_by_the_socket_or_the_queue_is_down(
    extra: list[str], reason: str
) -> None:
    clock = VirtualClock()
    venue = _Scripted(clock)
    venue.extra = {"subscribe": extra}
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    # Epoch 1 never went live, so epoch 2's `live` is the stream's first: `connected`.
    await until(clock, lambda: FIRST_LIVE_2 in consumer.statuses(), within_s=60, what="again")
    assert consumer.statuses()[:2] == ["heartbeat:evidence:1", f"down:{reason}:1"]
    await consumer.stop()
    await streams.aclose()


async def test_a_frame_before_the_auth_reply_is_passed_over() -> None:
    clock = VirtualClock()
    venue = _Scripted(clock)
    venue.auth.append(raw("pong"))  # answered first with a pong; the grant follows
    venue.extra = {"auth": [raw("auth-ok")]}
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    assert len(venue.sockets) == 1
    await consumer.stop()
    await streams.aclose()


async def test_an_auth_reply_on_a_live_socket_is_a_rejected_frame() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    venue.socket.push(raw("auth-ok"))
    await clock.advance(1)
    assert consumer.statuses()[-1] == "resyncing:rejected_frame:1"
    await consumer.stop()
    await streams.aclose()


async def test_an_exhausted_budget_blocks_the_connect_until_the_window_frees() -> None:
    """B13's `budget_blocked` (INV-B13-a): no dial while no private slot is left; the chart asks
    again every second, and dials once the window has a slot."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    for _ in range(480):
        streams.budget.lane("private").reserve()
    consumer = Consumer(await streams.open(account()))
    await clock.advance(299)
    assert venue.dialled == [] and consumer.statuses() == []  # no `down`: never authenticated
    [conn] = streams._conns.values()
    assert conn.state() == "degraded"
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    assert len(venue.dialled) == 1
    await consumer.stop()
    await streams.aclose()


async def test_a_redial_waits_out_the_budgets_delay() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    for _ in range(479):  # the window is full now
        streams.budget.lane("private").reserve()
    dropped = clock.now
    venue.socket.drop()
    await until(clock, lambda: RECONNECTED in consumer.statuses(), within_s=400, what="again")
    assert clock.now - dropped >= 299
    await consumer.stop()
    await streams.aclose()


# -- a closing stream sends nothing more, at every hook B13 can run -----------------------------


def _conn(streams: ps.PrivateStreams) -> ps._PrivateConn:
    return ps._PrivateConn(streams, account(), CREDENTIAL_ID, None)


async def test_every_hook_of_a_closing_stream_refuses_or_does_nothing() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    conn = _conn(streams)
    conn.halt()
    for hook in (conn.open_socket, conn.authenticate, conn.subscribe):
        with pytest.raises(ConnectionError, match="closing"):
            await hook()
    conn.start_session(object())
    conn.schedule_backoff(object())
    assert (venue.dialled, conn.state()) == ([], "closed")


async def test_a_dial_that_completes_while_closing_is_closed_unused() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    conn = _conn(streams)
    real = venue.connect

    async def connect(url: str) -> VenueSocket:
        sock = await real(url)
        conn.halt()  # a revoke lands during the dial
        return sock

    streams._connect = connect  # the registry dials through it
    with pytest.raises(ConnectionError, match="closing"):
        await conn.open_socket()
    assert venue.socket.closed and venue.socket.sent == []


async def test_a_revoke_during_m2s_borrow_sends_no_auth() -> None:
    """SR-E27-17 at the hook: the stream checks it is closing after M2 signs, before sending."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    calls: list[Call] = []
    conn_box: list[ps._PrivateConn] = []

    async def sign(key_id: UUID, message: Any, purpose: Any) -> RequestSignature:
        signed = await fake_capability(SIGNER_ID, calls).sign(key_id, message, purpose=purpose)
        conn_box[0].halt()
        return signed

    streams = make_streams(venue, credentials=CredentialBorrower(sign))
    conn = _conn(streams)
    conn_box.append(conn)
    conn._sock = await venue.connect("wss://x")
    with pytest.raises(ConnectionError, match="not granted"):
        await conn.authenticate()
    assert (len(calls), venue.socket.sent) == (1, [])


async def test_an_auth_on_a_dead_socket_is_a_transport_error_never_a_refusal() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    conn = _conn(streams)
    conn._sock = await venue.connect("wss://x")
    venue.socket.closed = True
    with pytest.raises(ConnectionError, match="not granted"):
        await conn.authenticate()
    assert conn._refusals == 0


# -- the registry's edges -------------------------------------------------------------------------


def test_the_registry_refuses_an_environment_with_no_private_stream() -> None:
    venue = PrivateVenue(VirtualClock())
    with pytest.raises(ValueError, match="unknown environment"):
        make_streams(venue, environment="mainnet")


async def test_a_failed_build_releases_the_account(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("the factory could not build")

    monkeypatch.setattr(ps, "build", failing)
    streams = make_streams(PrivateVenue(VirtualClock()))
    with pytest.raises(RuntimeError, match="could not build"):
        await streams.open(account())
    await streams.drain()
    assert streams.count() == 0


async def test_an_owned_task_that_fails_is_logged_by_its_type_only() -> None:
    streams = make_streams(PrivateVenue(VirtualClock()))

    async def failing() -> None:
        raise ValueError("a detail that must not be logged")

    with capture_logs() as logs:
        streams.spawn(failing(), "private-ws-test")
        await streams.drain()
    [logged] = [e for e in logs if e["event"] == "bybit_private_task_failed"]
    assert logged["error"] == "ValueError" and "detail" not in str(logs)


def test_the_key_marks_are_bounded_oldest_first() -> None:
    streams = make_streams(PrivateVenue(VirtualClock()))
    for n in range(ps.KEYS_REMEMBERED + 1):
        streams.mark_refused(f"key-{n}")
    assert streams.reopen("key-0") is False  # dropped as the oldest
    assert streams.reopen(f"key-{ps.KEYS_REMEMBERED}") is True


async def test_closing_a_key_with_no_stream_closes_nothing() -> None:
    streams = make_streams(PrivateVenue(VirtualClock()))
    assert await streams.close_key("no-such-key", reason="key_revoked") == ()


async def test_the_status_bound_is_made_visible_if_it_is_ever_exceeded() -> None:
    """A defect guard: the design holds five statuses unread at most (`_Queue`); a ninth is
    logged as an error, and still queued, never dropped."""
    queue = ps._Queue()
    status = PrivateStreamStatus(
        account_id=account().account_id, state="down", reason="socket_closed", epoch=1, ts=0
    )
    with capture_logs() as logs:
        for _ in range(ps.STATUS_SLOTS + 1):
            queue.put_status(status)
    assert [e["event"] for e in logs] == ["bybit_private_status_slots_exceeded"]
    seen = [await queue.get() for _ in range(ps.STATUS_SLOTS + 1)]
    assert len(seen) == ps.STATUS_SLOTS + 1
    await asyncio.wait_for(queue.drained(), 1)
