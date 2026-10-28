"""The private stream's less travelled paths (24 §14.2 rule 13), on the real B13 interpreter, a fake
venue and a virtual clock: rows read while subscribing wait behind `resyncing`; a refused,
unanswered or broken required subscription recycles the socket and the optional one does not;
`budget_blocked` waits for the window; and a stream that is closing sends nothing more at any
step (each B13 hook checks it). Plus the registry's edges: an unknown environment, a failed
build, a failed owned task, a drain begun after its last task ended, and the bounded key tables.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.models import PrivateStreamStatus
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.metrics import bybit_private_subscribe_refused_total
from candleviewer.observability.context import spawn
from candleviewer.secrets import CredentialBorrower, RequestSignature
from candleviewer.statechart import build
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

#: The bound on a helper thread's join, past which its drain spun (the drain test).
JOIN_S = 5.0

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


def test_a_drain_begun_after_its_last_task_ended_returns() -> None:
    """The registry's `drain` (#913 L1d-2b's code look, B1): a task that has ended stays in the
    registry's set until its done callback (`_ended`) runs on a later turn, so each round of
    `drain` must give the loop that turn. An await of `gather` over tasks that have all ended
    never yields on CPython 3.12, so such a round spins for ever. The drain runs on a loop of its
    own in a helper thread, joined within a bound, so a regression fails here and never hangs the
    run; a spinning drain's set is emptied from here to end its thread. The join's bound
    (`JOIN_S`) is this test's own, a stated exception to 03 Sec.14's rule that the suite's timeout
    is a test's only time bound: that timeout alone would fail the test but leave the spinning
    thread burning a core for the rest of the session."""
    registries: list[ps.PrivateStreams] = []
    drained: list[bool] = []

    async def nothing() -> None:
        return None

    async def drains() -> None:
        streams = make_streams(PrivateVenue(VirtualClock()))
        registries.append(streams)
        task = streams.spawn(nothing(), "private-ws-test")
        await asyncio.sleep(0)  # the task ends in this turn; its callback waits for the next
        assert task.done() and task in streams._tasks
        await streams.drain()
        drained.append(not streams._tasks)

    thread = threading.Thread(target=asyncio.run, args=(drains(),), daemon=True)
    thread.start()
    thread.join(JOIN_S)
    spun = thread.is_alive()
    for streams in registries if spun else ():
        streams._tasks.clear()
    thread.join(JOIN_S)
    assert not spun, "drain spun: the ended task's callback never ran"
    assert drained == [True]


async def test_a_stream_closed_during_the_budgets_wait_dials_nothing() -> None:
    """SEC-G8B-C-03: an open that waited out the budget's delay checks the stream again before it
    dials, so a revoke during the wait dials nothing."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    for _ in range(480):  # the window is full: the next open waits for a slot
        streams.budget.lane("private").reserve()
    conn = _conn(streams)
    opening = spawn(conn.open_socket(), name="open")
    await clock.advance(10)
    conn.halt()  # a revoke lands during the wait
    await clock.advance(300)
    with pytest.raises(ConnectionError, match="closing"):
        await opening
    assert venue.dialled == []


async def test_a_socket_dialled_as_its_caller_is_cancelled_is_closed_not_dropped() -> None:
    """CR-G8B-C-09: a dial that finished as the open was cancelled hands its socket to the
    registry, which closes it: no socket is left open with no owner."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    real = venue.connect
    caller: list[asyncio.Task[Any]] = []

    async def connect(url: str) -> VenueSocket:
        sock = await real(url)
        caller[0].cancel()  # the open is cancelled as its dial finishes
        return sock

    streams._connect = connect  # the registry dials through it
    caller.append(spawn(streams.dial(), name="dial"))
    with pytest.raises(asyncio.CancelledError):
        await caller[0]
    await streams.drain()
    assert venue.socket.closed


async def test_a_chart_that_refuses_connect_frees_the_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-G8B-C-04: should the built chart refuse `CONNECT`, the open raises and the account has
    no stream, so a later open builds one."""

    async def refusing(*args: Any, **kwargs: Any) -> Any:
        built = await build(*args, **kwargs)

        async def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("the chart refused the event")

        monkeypatch.setattr(built.interpreter, "send", refuse)
        return built

    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    monkeypatch.setattr(ps, "build", refusing)
    with pytest.raises(RuntimeError, match="refused the event"):
        await streams.open(account())
    await streams.drain()
    assert streams.count() == 0
    monkeypatch.setattr(ps, "build", build)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    await consumer.stop()
    await streams.aclose()


async def test_aclose_from_another_task_ends_the_read_waiting_there_and_frees_the_account() -> None:
    """CR-G8B-C-06: a read waiting in the consumer's task ends (`StopAsyncIteration`) when another
    task closes the stream, and the account is freed once the registry's close is done, even
    though that `aclose()` was cancelled first."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    stream = await streams.open(account())
    consumer = Consumer(stream)
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    venue.socket.stall_close = True
    closing = spawn(stream.aclose(), name="aclose")
    await clock.settle()
    assert consumer.task.done() and streams.count() == 1  # the read ended; the close is pending
    closing.cancel()
    await clock.advance(ps.CLOSE_TIMEOUT_S * 1.5)
    assert closing.cancelled() and streams.count() == 0 and venue.sockets[0].closed
    await streams.aclose()


@pytest.mark.parametrize("table", ["refused", "closed"])
def test_the_key_marks_are_bounded_oldest_first(table: str) -> None:
    """Both tables, the keys three refusals marked and the keys a revoke or rotation closed, keep
    at most `KEYS_REMEMBERED` keys, the oldest dropped first."""
    streams = make_streams(PrivateVenue(VirtualClock()))
    keys = [str(UUID(int=n)) for n in range(ps.KEYS_REMEMBERED + 1)]  # api_keys ids
    for key_ref in keys:
        if table == "refused":
            streams.mark_refused(key_ref)
        else:
            streams.tombstones.close(key_ref, "key_revoked")
    assert not streams.tombstones.refuses(keys[0])  # dropped as the oldest
    assert streams.tombstones.refuses(keys[1]) and streams.tombstones.refuses(keys[-1])


async def test_closing_a_key_with_no_stream_closes_nothing() -> None:
    streams = make_streams(PrivateVenue(VirtualClock()))
    assert await streams.close_key(account().key_ref, reason="key_revoked") == ()


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
