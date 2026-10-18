"""#3100: the token-expiry and heartbeat closes run on a timer the connection owns, flag off and on.

From the first `auth_ok` the connection arms one loop timer at its next deadline (`close_in`): the
token expiry on either clock and the heartbeat deadline, read again at least every
`CLOSE_RECHECK_TICKS` ticks. It runs the writer's own check (`_Connection.watch`), so the close is
queued at the deadline on the injected clock even while the writer is parked in a send. Flag on,
its flush deadline starts then (`23-ws-protocol.md` §8.4); flag off, the reader's next frame starts
the flush (§4.4). The first close wins (§8.6). Teardown cancels the timer (C-2.18, TG5).

The real router runs on the test's own loop behind `_Wire`, whose `hold()` parks the writer's send:
no threads, no sleeps. While the writer is parked only the timer reads the watchdog, so a spy on
`due` says when it has read the clock the test moved.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import Severity
from candleviewer.ws import gateway
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.lifecycle import bye_frame
from tests.unit.ws.test_lifecycle_socket import BASE_MS, _Clock
from tests.unit.ws.test_pipeline_outbound import _DEADLINE_S, _JSON, _closes, _Rig, _rows, _Wire

_FLAG = pytest.mark.parametrize("flag_on", [False, True], ids=["flag_off", "flag_on"])
#: Each deadline's close, its code and when it falls: a token expiring at 30 s (before the heartbeat
#: deadline at 45 s), else a token that outlives every test.
_DEADLINES = pytest.mark.parametrize(
    ("reason", "code", "at"), [("token_expired", 4401, 30.0), ("heartbeat_timeout", 1001, 45.0)]
)
_Conn = gateway._Connection
_FAR = 10_000.0
_FLUSH_S = 0.05  # the flush that a parked send never beats


def _at(s: float) -> datetime:
    """The token expiry `s` seconds into the fake clock (`_Clock.wall_ms`)."""
    return datetime.fromtimestamp((BASE_MS + s * 1000) / 1000, tz=UTC)


async def _parked(
    flag_on: bool, expires_s: float, **cfg: Any
) -> tuple[_Rig, _Wire, asyncio.Task[None], _Conn]:
    """`auth_ok` at 0 s for a token expiring at `expires_s`, then the writer parked in the send of
    one `system` frame, as for a peer that stopped reading."""
    rig, sock = _Rig(BackpressureConfig(**cfg) if flag_on else None), _Wire()
    rig.expires_at = _at(expires_s)
    handler, conn = await rig.open(sock)
    sock.hold()
    rig.hub.broadcast_system({"kind": "tick", "n": 0})
    await sock.parked.wait()
    return rig, sock, handler, conn


def _spy_closes(
    conn: _Conn, sock: _Wire, mp: pytest.MonkeyPatch
) -> tuple[asyncio.Event, list[dict[str, Any]]]:
    """Each `close_with` call from here on, with the clock, what it left queued and the flush
    deadline; the event is set at the first."""
    called, close_with = asyncio.Event(), conn.close_with
    seen: list[dict[str, Any]] = []

    def spy(reason: str, **kw: Any) -> None:
        close_with(reason, **kw)
        pipe = conn.pipeline
        queued = conn.outbound.qsize() if pipe is None else len(pipe.queue)
        seen.append({"reason": reason, "now": conn.clock(), "sent": len(sock.raw)})
        seen[-1].update(queued=queued, deadline=None if pipe is None else pipe.deadline)
        called.set()

    mp.setattr(conn, "close_with", spy)
    return called, seen


def _spy_due(conn: _Conn, mp: pytest.MonkeyPatch) -> asyncio.Event:
    """Set each time the watchdog is read: with the writer parked, only by the close timer."""
    read, due = asyncio.Event(), conn.due

    def spy() -> str | None:
        read.set()
        return due()

    mp.setattr(conn, "due", spy)
    return read


class _Pings(list[dict[str, Any]]):
    """`_Wire.pings`, with an event set by the first idle `ping` (`s-hb-*`) the writer sends."""

    def __init__(self) -> None:
        super().__init__()
        self.idle = asyncio.Event()

    def append(self, frame: dict[str, Any]) -> None:
        super().append(frame)
        if frame["id"].startswith("s-hb-"):
            self.idle.set()


class _LogDown:
    """`gateway._log()` with a log sink that fails on `ws close timer failed` and drops the rest."""

    def __getattr__(self, level: str) -> Callable[..., None]:
        def log(event: str, **_kw: Any) -> None:
            if event == "ws close timer failed":
                raise TypeError("log sink down")

        return log


class _Halt(BaseException):
    """Neither an `Exception` nor a cancellation: the timer lets it through untouched."""


def _bye_fails(reason: str, error: BaseException, mp: pytest.MonkeyPatch) -> asyncio.Event:
    """`gateway.lifecycle_bye` raising `error` once, for `reason`'s `bye`: inside the real
    `close_with`, once it has begun the close. Every other `bye` is built as before; the event
    is set when it raises."""
    raised = asyncio.Event()

    def bye(r: str, **kw: Any) -> dict[str, Any]:
        if r == reason and not raised.is_set():
            raised.set()
            raise error
        return bye_frame(r, **kw)

    mp.setattr(gateway, "lifecycle_bye", bye)
    return raised


@contextlib.contextmanager
def _loop_escapes() -> Iterator[list[BaseException]]:
    """What the loop's exception handler is given while the block runs: an exception that a
    callback let go. The handler that was set before is restored on the way out."""
    loop = asyncio.get_running_loop()
    escaped: list[BaseException] = []
    was = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: escaped.append(ctx["exception"]))
    try:
        yield escaped
    finally:
        loop.set_exception_handler(was)


async def _quiet_then_closed(
    rig: _Rig, sock: _Wire, conn: _Conn, mp: pytest.MonkeyPatch, quiet: float, at: float
) -> dict[str, Any]:
    """With the writer parked, the timer reads the clock at the old deadline `quiet` and closes
    nothing, then closes at the new one, `at`. Returns that close; the send is then released."""
    sock.hold()
    rig.hub.broadcast_system({"kind": "tick"})
    await sock.parked.wait()
    read, (called, seen) = _spy_due(conn, mp), _spy_closes(conn, sock, mp)
    rig.clock.now = quiet
    await read.wait()
    assert not conn.closing
    rig.clock.now = at
    await called.wait()
    sock.release()
    assert seen[0]["now"] == at
    return seen[0]


@_FLAG
@_DEADLINES
async def test_a_parked_writer_is_closed_at_the_deadline_and_its_flush_starts_then(
    flag_on: bool, reason: str, code: int, at: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The close is queued at the deadline while the send it would wait for never returns: a token
    expiry seals it (nothing queued is kept), a heartbeat lapse keeps what any close keeps. Flag on,
    its flush deadline starts then and abandons the send; flag off, the reader's next frame starts
    the flush (§4.4), which does. The audit row reads the deadline's reason."""
    monkeypatch.setattr(gateway, "CLOSE_FLUSH_TIMEOUT_S", _FLUSH_S)
    before = _closes(reason)
    async with asyncio.timeout(_DEADLINE_S):
        expires = at if reason == "token_expired" else _FAR
        rig, sock, handler, conn = await _parked(flag_on, expires, close_flush_s=_FLUSH_S)
        for n in (1, 2):
            rig.hub.broadcast_system({"kind": "tick", "n": n})  # queued behind the parked send
        called, seen = _spy_closes(conn, sock, monkeypatch)
        sent, moved = len(sock.raw), asyncio.get_running_loop().time()
        rig.clock.now = at
        await called.wait()
        if not flag_on:
            sock.feed({"t": "ping", "id": "late"})  # the reader returns, closing: the flush starts
        await handler
    close = seen[0]
    assert (close["reason"], close["now"], close["sent"]) == (reason, at, sent)  # still parked
    kept = {"token_expired": 0, "heartbeat_timeout": 2}[reason]  # the two `system` frames
    assert close["queued"] == kept + (0 if flag_on else 3)  # flag off: `bye`, marker, code
    assert conn.sealed is (reason == "token_expired") and conn.bye_frame is not None
    assert (conn.bye_frame["p"]["reason"], conn.bye_frame["p"]["code"]) == (reason, code)
    if flag_on:  # the deadline started at the expiry, while the send was still parked
        assert close["deadline"] is not None and moved + _FLUSH_S <= close["deadline"]
        after = {"trigger": "flush_deadline", "flush_abandoned": True}
        assert rig.audit.records[0]["after_state"] == after
    assert len(sock.raw) == sent and sock.closed_with is None  # the send never returned
    assert _rows(rig) == [("ws.connection.closed", reason, Severity.INFO)]
    assert _closes(reason) == before + 1


@_FLAG
@_DEADLINES
@pytest.mark.parametrize("first", ["deadline", "shutdown"])
async def test_the_first_close_wins_and_is_counted_and_audited_once(
    flag_on: bool, reason: str, code: int, at: float, first: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.6, the first close wins. The timer's close is counted and audited once, though the
    writer's own check finds the same deadline once its send returns. After another close the
    timer changes only what that check would: a token expiry seals it (§4.3), a heartbeat lapse
    does nothing. The `bye`, its code and the flush deadline stay the first close's."""
    reasons = (reason, "shutdown")
    before = {r: _closes(r) for r in reasons}
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            expires = at if reason == "token_expired" else _FAR
            rig, sock, handler, conn = await _parked(flag_on, expires)
            if first == "shutdown":
                conn.close_with("shutdown")
            deadline = None if conn.pipeline is None else conn.pipeline.deadline
            called, seen = _spy_closes(conn, sock, monkeypatch)
            rig.clock.now = at
            await called.wait()  # the timer's close, or its call that changes nothing
            assert seen[0]["reason"] == reason and seen[0]["now"] == at
            if first == "shutdown" and conn.pipeline is not None:
                assert conn.pipeline.deadline == deadline  # never a second window
            sock.release()
            frames = await sock.next(2)  # the frame the send held, then the `bye`
            await handler
    winner, end = (reason, code) if first == "deadline" else ("shutdown", 1001)
    assert [f["t"] for f in frames] == ["d", "bye"] and frames[1]["p"]["reason"] == winner
    assert sock.closed_with == end and sock.sent.empty()
    assert [c["reason"] for c in seen[:2]] == [reason, reason]  # the writer's check: no change
    sealed = reason == "token_expired" and first == "shutdown"
    counted = {reason: int(first == "deadline" or sealed), "shutdown": int(first == "shutdown")}
    assert {r: _closes(r) - before[r] for r in reasons} == counted
    assert [e["reason"] for e in logs if e["event"] == "ws close"] == [winner]
    assert [e["reason"] for e in logs if e["event"] == "ws close sealed"] == [reason] * sealed
    assert [row[:2] for row in _rows(rig)] == [("ws.connection.closed", winner)]


@_FLAG
async def test_a_reauth_moves_the_expiry_the_timer_closes_at(
    flag_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-`auth` at 10 s moves the expiry from 30 s to 50 s (the heartbeat deadline to 55 s)."""
    rig, sock = _Rig(BackpressureConfig() if flag_on else None), _Wire()
    rig.expires_at = _at(30.0)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        rig.clock.now, rig.expires_at = 10.0, _at(50.0)
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": "tok"}})
        (ok,) = await sock.next()
        assert ok["p"]["token_expires_at_ms"] == BASE_MS + 50_000
        close = await _quiet_then_closed(rig, sock, conn, monkeypatch, quiet=30.0, at=50.0)
        await handler
    assert close["reason"] == "token_expired"


@_FLAG
async def test_inbound_traffic_moves_the_heartbeat_deadline_the_timer_closes_at(
    flag_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer still queues the idle `ping` after 20 s of outbound silence (§9.1; its own check,
    kept). A frame read at 21 s moves the heartbeat deadline from 45 s to 66 s."""
    rig, sock, pings = _Rig(BackpressureConfig() if flag_on else None), _Wire(), _Pings()
    sock.pings, rig.expires_at = pings, _at(_FAR)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        rig.clock.now = 20.0
        await pings.idle.wait()
        rig.clock.now = 21.0
        sock.feed({"t": "ping", "id": "p"})
        assert [f["t"] for f in await sock.next()] == ["pong"]  # read at 21 s
        close = await _quiet_then_closed(rig, sock, conn, monkeypatch, quiet=45.0, at=66.0)
        await handler
    assert close["reason"] == "heartbeat_timeout"


async def test_a_deadline_crossed_in_the_writers_turn_holds_back_the_frame_it_popped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on, the writer's check after its pop (kept): a deadline crossed inside its own turn,
    here while `service` runs, holds back the frame it popped; the `bye` is next."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    rig.expires_at = _at(30.0)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        assert conn.pipeline is not None
        pipe, service = conn.pipeline, conn.pipeline.service

        def slow_service(now: float) -> None:
            service(now)
            if len(pipe.queue):  # the turn that pops the frame below
                rig.clock.now = 30.0

        monkeypatch.setattr(pipe, "service", slow_service)
        rig.hub.broadcast_system({"kind": "tick"})
        (bye,) = await sock.next()
        await handler
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "token_expired", 4401)


@_FLAG
@pytest.mark.parametrize("failure", ["check", "log", "close", "cancel", "halt"])
async def test_a_check_that_raises_on_the_timer_fails_closed_and_never_spins(
    flag_on: bool, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check that raises on the timer (`check`, a `KeyError`) fails closed with `internal_error`,
    and a log sink that fails too (`log`, a `TypeError`) skips no close. Nothing reaches the loop's
    exception handler, and the check runs once: the clock is past the heartbeat deadline, so a
    re-armed timer would run again at once. A fail-closed close that fails inside `close_with`
    (`close`, an `OSError`) leaves no close, so the socket ends as on a writer fault: `bye
    internal_error` + `1011`. A cancellation (`cancel`) fails closed, then reaches the loop's
    handler; any other `BaseException` (`halt`) passes through and closes nothing."""
    monkeypatch.setattr(gateway, "CLOSE_FLUSH_TIMEOUT_S", _FLUSH_S)
    loop, escaped, calls = asyncio.get_running_loop(), [], []
    was = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: escaped.append(ctx["exception"]))
    errors = {"cancel": asyncio.CancelledError(), "halt": _Halt()}
    error: BaseException = errors.get(failure, KeyError("down"))
    try:
        with capture_logs() as logs:
            async with asyncio.timeout(_DEADLINE_S):
                rig, sock, handler, conn = await _parked(flag_on, _FAR, close_flush_s=_FLUSH_S)
                ran = asyncio.Event()

                def failing() -> bool:
                    calls.append(failure)
                    ran.set()
                    raise error

                monkeypatch.setattr(conn, "watch", failing)
                if failure == "log":
                    monkeypatch.setattr(gateway, "_log", _LogDown)
                if failure == "close":
                    _bye_fails("internal_error", OSError("down"), monkeypatch)
                rig.clock.now = 45.0  # past the heartbeat deadline
                await ran.wait()
                closed = failure != "halt"
                assert conn.closing is closed and conn.close_timer is None
                if failure == "close":
                    sock.release()  # the handler's own `bye` and `1011` go out
                elif not closed:
                    sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
                elif not flag_on:
                    sock.feed({"t": "ping", "id": "late"})  # the reader returns: the flush starts
                await handler
    finally:
        loop.set_exception_handler(was)
    assert escaped == ([error] if failure in ("cancel", "halt") else [])
    assert calls == [failure]  # run once: never re-armed
    row = ("internal_error", Severity.WARNING) if closed else ("client_closed", Severity.INFO)
    assert _rows(rig) == [("ws.connection.closed", *row)]
    if failure == "close":
        bye = sock.sent.get_nowait()
        assert (bye["p"]["reason"], sock.closed_with) == ("internal_error", 1011)
    failed = [e for e in logs if e["event"] == "ws close timer failed"]
    if failure == "check":
        assert [(e["connection_id"], e["error"], e["exc_info"]) for e in failed] == [
            (conn.connection_id, type(error).__name__, error)
        ]


@pytest.mark.parametrize(
    ("flag_on", "site"),
    [
        (False, "bye"),
        (True, "bye"),
        (True, "clear"),
        (False, "cancel"),
        (True, "cancel"),
        (True, "clear_cancel"),
    ],
    ids=[
        "flag_off-bye",
        "flag_on-bye",
        "flag_on-clear",
        "flag_off-cancel",
        "flag_on-cancel",
        "flag_on-clear_cancel",
    ],
)
async def test_a_fault_inside_the_timers_close_ends_the_socket_as_a_writer_fault(
    flag_on: bool, site: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2: the deadline's own close faults inside the real `close_with`, once it has begun:
    building its `bye` (`bye`), or with the flag on clearing the lanes (`clear`, so no flush
    deadline starts). No close took, so the socket ends as on a writer fault: the writer is
    cancelled, the handler sends `bye internal_error` + `1011`, and the row reads
    `internal_error`. A cancellation raised while building the `bye` (`cancel`) or clearing the
    lanes (`clear_cancel`) ends it the same way, then is re-raised: it reaches the loop's handler
    once. On this path the handler joins the writer before it sends its own `bye` (C-2.18, TG5),
    so the writer is done when that `bye` goes out."""
    before = _closes("internal_error")
    cancel = "cancel" in site
    error: BaseException = asyncio.CancelledError() if cancel else OSError(site)
    order: list[tuple[str, bool]] = []  # each join, and each frame sent from here: writer done?
    with _loop_escapes() as escaped, capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            rig, sock, handler, conn = await _parked(flag_on, _FAR)
            name = f"{conn.connection_id}-writer"
            (writer,) = [t for t in asyncio.all_tasks() if t.get_name() == name]
            join, send = gateway._join_writer, conn.send_frame

            async def spy_join(task: asyncio.Task[None]) -> BaseException | None:
                out = await join(task)
                order.append(("join", writer.done()))
                return out

            async def spy_send(frame: dict[str, Any]) -> None:
                order.append((frame["t"], writer.done()))
                await send(frame)

            monkeypatch.setattr(gateway, "_join_writer", spy_join)
            monkeypatch.setattr(conn, "send_frame", spy_send)
            if site in ("bye", "cancel"):
                faulted = _bye_fails("heartbeat_timeout", error, monkeypatch)
            else:
                assert conn.pipeline is not None
                faulted, queue = asyncio.Event(), conn.pipeline.queue
                clear = queue.clear

                def clear_once(**kw: Any) -> int:
                    if not faulted.is_set():
                        faulted.set()
                        raise error
                    return clear(**kw)

                monkeypatch.setattr(queue, "clear", clear_once)
            rig.clock.now = 45.0  # past the heartbeat deadline
            await faulted.wait()
            sock.release()  # the handler's own `bye` and `1011` go out
            (bye,) = await sock.next()
            await handler
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "internal_error", 1011)
    assert sock.sent.empty() and conn.timer_fault is error
    assert escaped == ([error] if cancel else [])  # a cancellation: to the loop, once
    # The writer is already done when the handler reaches its tail (its end cancels the blocked
    # read through `_writer_done`; a read that returned first would be followed by the wait at
    # `if conn.closing`), so the ("join", ...) entry and its place pin the order; ("bye", True)
    # is an observation, not a pin.
    assert order == [("join", True), ("bye", True)]
    assert _rows(rig) == [("ws.connection.closed", "internal_error", Severity.WARNING)]
    assert _closes("internal_error") == before + 1
    (fault,) = [e for e in logs if e["event"] == "ws connection fault"]
    assert fault["exc_info"] is error


# -- the handle itself (no idle tick in these rigs: only the test replaces a handle) ---------------


async def test_a_reauth_rearms_the_timer_and_cancels_the_one_it_replaces() -> None:
    rig, sock = _Rig(tick_s=3600.0), _Wire()
    rig.expires_at = _at(30.0)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        old = conn.close_timer
        assert isinstance(old, asyncio.TimerHandle) and not old.cancelled()
        assert conn.close_in() == 30.0
        rig.expires_at = _at(40.0)
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": "tok"}})
        await sock.next()
        new = conn.close_timer
        assert old.cancelled() and isinstance(new, asyncio.TimerHandle) and not new.cancelled()
        assert conn.close_in() == 40.0  # before the heartbeat deadline at 45 s
        assert new.when() - old.when() == pytest.approx(10, abs=1)  # armed at the new expiry
        handler.cancel()
        await asyncio.wait({handler})


@_FLAG
async def test_teardown_cancels_the_timer_and_none_is_armed_after_it(
    flag_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teardown stops the timer first, before its first await (`_join_writer`), so no deadline
    can close a connection that is ending; none is armed after it."""
    rig, sock = _Rig(BackpressureConfig() if flag_on else None, tick_s=3600.0), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        timer, join = conn.close_timer, gateway._join_writer
        assert timer is not None and not timer.cancelled()
        assert (conn.tick_s, conn.recheck_s) == (3600.0, gateway.CLOSE_RECHECK_TICKS * 3600.0)
        stopped: list[bool] = []

        async def first_await(task: asyncio.Task[None]) -> BaseException | None:
            stopped.append(conn.timer_stopped and conn.close_timer is None)
            return await join(task)

        monkeypatch.setattr(gateway, "_join_writer", first_await)
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler
    assert stopped == [True] and timer.cancelled() and conn.close_timer is None
    conn.arm_close_timer()
    assert conn.close_timer is None  # nothing can fire after the connection ends
    assert [row[:2] for row in _rows(rig)] == [("ws.connection.closed", "client_closed")]


async def test_the_timer_is_armed_at_the_next_deadline_on_either_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`close_in` reads each deadline as `due` compares it: the token expiry on the monotonic and
    the wall clock, and the heartbeat deadline. The timer is armed at it, or at `recheck_s` if
    that is sooner, and replaces the one before. After a check that found nothing due the rest is
    waited to the millisecond (`CLOSE_REARM_MIN_S`, pinned by value). After one that raised it is
    a tick, on the defensive path that no real flow reaches (the fail-closed close sets
    `closing`); only a stubbed `close_with` does."""
    clock = _Clock()
    kw: dict[str, Any] = {"encoding": _JSON, "clock": clock, "wall_ms": clock.wall_ms}
    conn = _Conn(cast(Any, _Wire()), **kw, auth_timeout_s=10.0)
    assert (conn.tick_s, conn.recheck_s) == (gateway.WATCHDOG_TICK_S, 1.0)  # the defaults
    dog = conn.watchdog
    clock.now, dog.last_inbound, dog.auth_deadline = 10.0, 5.0, None  # the heartbeat at 50 s
    dog.token_expires_at, conn.token_expires_at_ms = 30.0, BASE_MS + 40_000
    assert conn.close_in() == 20.0  # the monotonic expiry
    dog.token_expires_at, conn.token_expires_at_ms = 40.0, BASE_MS + 35_000
    assert conn.close_in() == 25.0  # the wall clock's
    dog.token_expires_at, conn.token_expires_at_ms = 60.0, BASE_MS + 60_000
    assert conn.close_in() == 40.0  # the heartbeat deadline
    loop = asyncio.get_running_loop()
    timers: list[asyncio.TimerHandle] = []
    for recheck, delay in ((3600.0, 40.0), (1.0, 1.0)):
        conn.recheck_s, start = recheck, loop.time()
        conn.arm_close_timer()
        timer = conn.close_timer
        assert isinstance(timer, asyncio.TimerHandle)
        assert start + delay <= timer.when() <= loop.time() + delay
        timers.append(timer)
    assert timers[0].cancelled() and not timers[1].cancelled()
    timers[1].cancel()  # as if it fired: its turn, 0.4 ms before the heartbeat deadline
    monkeypatch.setattr(conn, "watch", lambda: False)  # a check that found nothing due
    clock.now, start = 50.0 - 0.0004, loop.time()
    conn._close_timer_fired()
    # Pinned by value: uvloop rounds a delay to whole milliseconds, so a floor under 1 ms is a
    # `call_soon` (a spin) and one over it lands the close late.
    assert gateway.CLOSE_REARM_MIN_S == 0.001
    rest, ms = conn.close_timer, gateway.CLOSE_REARM_MIN_S
    assert isinstance(rest, asyncio.TimerHandle)
    assert start + ms <= rest.when() <= loop.time() + ms  # the rest, to the millisecond

    def raising() -> bool:
        raise KeyError("down")

    # The defensive re-arm (defence in depth): after a check that raised, the fail-closed close
    # sets `closing` first, so no real flow re-arms (the fail-closed tests above). A stubbed
    # `close_with` that took nothing reaches it, and it waits a tick, never sooner.
    rest.cancel()
    monkeypatch.setattr(conn, "watch", raising)
    monkeypatch.setattr(conn, "close_with", lambda *_a, **_k: None)
    with capture_logs():  # captured, not rendered: a rendered traceback would outlast a tick
        start = loop.time()
        conn._close_timer_fired()
    floored = conn.close_timer
    assert isinstance(floored, asyncio.TimerHandle)
    assert start + conn.tick_s <= floored.when() <= loop.time() + conn.tick_s
    conn.stop_close_timer()
    conn.arm_close_timer()
    assert floored.cancelled() and conn.close_timer is None
