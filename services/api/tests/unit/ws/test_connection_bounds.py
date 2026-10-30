"""A peer that stopped reading is closed; registrations are always released (#415).

A close whose writer is still parked on a send at its flush deadline (the pipeline's, §8.4) ends
it, and until the first `auth_ok` `auth_timeout_s` plus the flush bound from `accept` does the
same, so the socket is torn down and its slot freed; the expiry counts
(`cv_ws_overflow_total{reason="close_flush_deadline"}`). The rigs run the budgeted pipeline
(#2409); the bare connection below keeps the flag-off flush timer. A socket that ends in time
leaves no flush timer and counts nothing. An `auth` undoes only the SR-189 registration it made,
one that finds its socket closing registers nothing, and teardown releases what was registered.
Fake socket and clock; the bounds are short loop timers, awaited through the handler (no
sleeps)."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from candleviewer.settings import CLOSE_FLUSH_TIMEOUT_S
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.limits import AUTH_TIMEOUT_S
from candleviewer.ws.metrics import cv_ws_closes_total, cv_ws_overflow_total
from tests.unit.ws._auth_rig import BASE_MS, NOTHING_LEFT, Rig, Sock, hang_up

BOUND_S = 0.01  # the close flush bound, and the auth window, of the rigs below (loop clock)


def _count(counter: Any, reason: str) -> float:
    return float(counter.labels(reason=reason)._value.get())


def _expired() -> tuple[float, float]:
    """(flush deadlines passed, `slow_consumer` closes) so far."""
    return _count(cv_ws_overflow_total, "close_flush_deadline"), _count(
        cv_ws_closes_total, "slow_consumer"
    )


async def _ended(handler: asyncio.Task[None], within: float = 2.0) -> None:
    async with asyncio.timeout(within):  # the bounds are 10 to 50 ms: it ends well before
        await handler


async def test_a_close_whose_peer_stopped_reading_ends_at_its_flush_deadline() -> None:
    """The session is revoked, its sealed `bye` parks on a peer that stopped reading, and at the
    pipeline's flush deadline the writer ends and the socket is torn down."""
    rig, sock = Rig(options={"backpressure": BackpressureConfig(close_flush_s=BOUND_S)}), Sock()
    handler = await rig.open(sock)
    assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
    (conn,) = rig.hub._live
    assert conn.flush_timer is None  # the bound from `accept` ended at `auth_ok`
    sock.stops_reading = True
    flushes, slow = _expired()
    await rig.revocation.revoke("sess-good-1")
    await _ended(handler)
    assert (sock.sent.empty(), sock.codes) == (True, [])  # its `bye` and close never went out
    assert _expired() == (flushes + 1, slow)
    assert rig.leftovers() == NOTHING_LEFT


@pytest.mark.parametrize("first", ["hello", "ping"], ids=["no-auth", "a-close-comes-first"])
async def test_a_socket_whose_writer_never_drains_until_auth_ok_is_closed(first: str) -> None:
    """Its `welcome` parks on a peer that stopped reading and no `auth` comes: `auth_timeout_s`
    plus the flush bound after `accept` it is closed `slow_consumer` and its slot freed. A close
    before then (a first frame that is not `hello`) ends it at its own, earlier flush bound."""
    window = BOUND_S if first == "hello" else 10.0  # the earlier bound decides
    flush = BackpressureConfig(close_flush_s=BOUND_S)
    rig, sock = Rig(options={"auth_timeout_s": window, "backpressure": flush}), Sock()
    sock.stops_reading = True
    flushes, slow = _expired()
    handler = rig.start(sock)
    sock.feed({"t": first, "id": "h"})
    await _ended(handler, within=1.0)
    assert (sock.sent.empty(), sock.codes) == (True, [])  # not even its first reply went out
    assert _expired() == (flushes + 1, slow + (first == "hello"))
    assert rig.leftovers() == NOTHING_LEFT


@pytest.mark.parametrize("closes", [False, True], ids=["hang-up-until-auth-ok", "close-in-time"])
async def test_a_socket_that_ends_in_time_leaves_no_flush_timer(
    closes: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A socket that hangs up until the first `auth_ok`, or whose close (a third failed `auth`)
    flushes in time, leaves no flush timer: the bound from `accept` is the one armed (the close's
    flush is the pipeline's deadline, §8.4), it is cancelled, and none is armed after teardown."""
    rig, sock = Rig(), Sock()
    handler = await rig.open(sock)
    (conn,) = rig.hub._live
    armed = [conn.flush_timer]  # the bound from `accept`
    arm = conn.arm_flush_deadline

    def kept(delay: float) -> None:
        arm(delay)
        if conn.flush_timer is not armed[-1]:
            armed.append(conn.flush_timer)

    monkeypatch.setattr(conn, "arm_flush_deadline", kept)
    flushes, slow = _expired()
    for _ in range(3 if closes else 0):
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "bad"}})
    if not closes:
        hang_up(sock)
    await _ended(handler)
    assert conn.flush_timer is None and len(armed) == 1
    assert all(timer is not None and timer.cancelled() for timer in armed)
    arm(1.0)
    assert conn.flush_timer is None  # none after teardown
    assert (sock.codes, _expired()) == ([4401] if closes else [], (flushes, slow))


async def test_the_bound_until_auth_ok_leaves_the_close_its_flush_bound() -> None:
    """With the production auth window and close flush bound, the bound from `accept` is the window
    plus the flush bound away, so the watchdog's `auth_timeout` close at the window keeps its whole
    flush bound; a later bound does not replace it (the earliest stands)."""
    rig, sock = Rig(), Sock()
    t0 = asyncio.get_running_loop().time()
    handler = await rig.open(sock)
    (conn,) = rig.hub._live
    assert conn.flush_timer is not None
    bound = AUTH_TIMEOUT_S + CLOSE_FLUSH_TIMEOUT_S  # armed at `accept`, which comes after `t0`
    assert bound <= conn.flush_timer.when() - t0 < bound + 1.0  # 1 s of slack before `accept`
    first = conn.flush_timer
    conn.arm_flush_deadline(100.0)  # a later bound
    assert conn.flush_timer is first and not first.cancelled()
    hang_up(sock)
    await _ended(handler)


async def test_a_flush_bound_that_passes_after_the_writer_ended_counts_nothing() -> None:
    """The bound can pass in the turn in which the writer ends, before teardown cancels it: that
    writer's flush made it in time, so nothing is counted as an expired flush, and no bound is
    armed once one has passed."""
    conn = _Connection(
        cast(Any, Sock()),
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: BASE_MS,
        auth_timeout_s=AUTH_TIMEOUT_S,
        close_flush_s=0.0,
    )
    passed = asyncio.Event()

    def ended() -> bool:  # `Task.cancel()` of a writer that has finished
        passed.set()
        return False

    conn.end_writer = ended
    flushes, slow = _expired()
    conn.close_with("shutdown")  # its flush bound is due at once
    async with asyncio.timeout(1.0):
        await passed.wait()
    assert (conn.flush_passed, conn.flush_timer, _expired()) == (True, None, (flushes, slow))
    conn.arm_flush_deadline(1.0)
    assert conn.flush_timer is None  # none is armed once one has passed


@pytest.mark.parametrize("hangs", [False, True], ids=["refused", "call-timed-out"])
async def test_a_failed_auth_on_a_closing_socket_leaves_no_registration_behind(hangs: bool) -> None:
    """The session is revoked, and an `auth` already on its way fails, refused or past its call
    bound (while the `bye` is parked, so the socket is still being read): it made no
    registration, so it undoes none, and teardown releases the socket's own."""
    flush = {"backpressure": BackpressureConfig(close_flush_s=5 * BOUND_S)}
    rig, sock = Rig(hangs=hangs, options=flush if hangs else None), Sock()
    handler = await rig.open(sock)
    assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
    assert (len(rig.registry._conns), len(rig.sequencing)) == (1, 1)
    sock.stops_reading = hangs
    await rig.revocation.revoke("sess-good-1")
    sock.feed({"t": "auth", "id": "late", "p": {"access_token": "hang" if hangs else "bad"}})
    await _ended(handler)
    assert rig.leftovers() == NOTHING_LEFT


async def test_an_auth_that_finds_its_socket_closing_registers_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first `auth` whose session is revoked while its principal is read registers nothing
    once the read returns, and gets no `auth_ok`."""
    rig, sock = Rig(), Sock()
    handler = await rig.open(sock)
    registered: list[Any] = []
    register = rig.registry.register

    def spied(authz: Any, *args: Any) -> None:
        registered.append(authz)
        register(authz, *args)

    monkeypatch.setattr(rig.registry, "register", spied)
    gate = rig.hold("resolve")
    sock.feed({"t": "auth", "id": "a", "p": {"access_token": "good-3"}})
    await rig.parked["resolve"].wait()
    await rig.revocation.revoke("sess-good-3")
    gate.set()
    await _ended(handler)
    assert [sock.sent.get_nowait()["t"] for _ in range(sock.sent.qsize())] == ["bye"]
    assert registered == [] and rig.leftovers() == NOTHING_LEFT


async def test_teardown_releases_the_registration_whatever_reset_authz() -> None:
    """Teardown releases the registered one even when `authz` no longer names it."""
    rig, sock = Rig(), Sock()
    handler = await rig.open(sock)
    assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
    (conn,) = rig.hub._live
    conn.authz = None  # dropped by some path, not unregistered
    hang_up(sock)
    await _ended(handler)
    assert rig.leftovers() == NOTHING_LEFT
