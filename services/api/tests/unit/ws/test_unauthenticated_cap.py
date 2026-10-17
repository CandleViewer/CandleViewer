"""#2155 item 3: a process-wide cap on sockets that have not authenticated yet (§4.3).

A socket counts from `accept` to its first `auth_ok`, is released however else it ends, and a
re-`auth` never counts. Past the cap a socket is accepted and closed at once, `bye
server_shedding_load` + `1013`, before any frame is read; it never counts, `cv_ws_closes_total`
counts it and a capped `warning` with no identity logs it. Fake socket, event-driven waits.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import Mock

import pytest
from structlog.testing import capture_logs

import candleviewer.ws.gateway as gateway
from candleviewer.ws.gateway import GatewayHub
from candleviewer.ws.lifecycle import REFUSAL_LOG_LIMIT, Lifecycle
from candleviewer.ws.limits import AUTH_TIMEOUT_S, MAX_UNAUTHENTICATED_SOCKETS
from candleviewer.ws.metrics import cv_ws_closes_total
from tests.unit.ws._auth_rig import (
    DEADLINE_S,
    EXITS,
    NOTHING_LEFT,
    Rig,
    Sock,
    bye_of,
    end_through,
    hang_up,
)

_SHED = "server_shedding_load"


def _sheds() -> float:
    return float(cv_ws_closes_total.labels(reason=_SHED)._value.get())


async def _shed(rig: Rig) -> dict[str, Any]:
    """Open one socket past the cap: its `bye`, once the handler has returned on its own."""
    sock = Sock()
    handler = rig.start(sock)
    bye = await sock.sent.get()
    await handler
    assert (bye_of(bye), sock.codes, sock.sent.empty()) == (("bye", _SHED, 1013), [1013], True)
    return bye


async def _close_all(socks: list[Sock], handlers: list[asyncio.Task[None]]) -> None:
    for sock in socks:
        hang_up(sock)
    await asyncio.gather(*handlers)


async def _spend_good_dup(rig: Rig) -> None:
    """`good-dup`'s user takes its one connect of the minute (`max_auths_per_min=1`)."""
    sock = Sock()
    handler = await rig.open(sock)
    assert (await rig.auth(sock, "good-dup"))["t"] == "auth_ok"
    await _close_all([sock], [handler])


async def test_the_65th_socket_awaiting_auth_is_shed_with_1013_and_counted_once() -> None:
    """Default cap: 64 sockets await auth, the 65th gets the shedding `bye` (retry after the auth
    window, reconnect) and `1013` and is never counted or served. One `warning` names the cap and
    the peer address, never an identity."""
    rig, socks = Rig(tick_s=0.05), [Sock() for _ in range(MAX_UNAUTHENTICATED_SOCKETS)]
    before = _sheds()
    async with asyncio.timeout(DEADLINE_S):
        handlers = [await rig.open(sock) for sock in socks]
        with capture_logs() as logs:
            bye = await _shed(rig)
        assert (rig.hub.unauthenticated, len(rig.hub), _sheds()) == (64, 64, before + 1)
        await _close_all(socks, handlers)
    assert (bye["p"]["reconnect"], bye["p"]["retry_after_ms"]) == (True, AUTH_TIMEOUT_S * 1000)
    (line,) = [e for e in logs if e["event"] == "ws socket shed"]
    fields = ("reason", "limit", "retry_after_ms", "source_ip", "user_id")
    assert [line.get(k) for k in fields] == [_SHED, 64, 10_000, "127.0.0.1", None]
    assert GatewayHub().max_unauthenticated == MAX_UNAUTHENTICATED_SOCKETS == 64
    assert rig.leftovers() == NOTHING_LEFT


async def test_sheds_past_the_log_cap_are_all_counted_and_summarised_once() -> None:
    """Every shed counts; a window logs the first `REFUSAL_LOG_LIMIT`, then one summary (§2.5)."""
    rig, first, before = Rig(max_unauthenticated=1), Sock(), _sheds()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(first)
        with capture_logs() as logs:
            for _ in range(REFUSAL_LOG_LIMIT + 5):
                await _shed(rig)
        await _close_all([first], [handler])
    lines = [e["event"] for e in logs if "shed" in e["event"]]
    assert lines == ["ws socket shed"] * REFUSAL_LOG_LIMIT + ["ws socket sheds suppressed"]
    assert (_sheds(), rig.leftovers()) == (before + REFUSAL_LOG_LIMIT + 5, NOTHING_LEFT)


async def test_a_setup_raise_leaves_nothing_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raise injected in the setup before the `try` that frees the slot leaves nothing counted."""
    rig = Rig(max_unauthenticated=1)
    monkeypatch.setattr(Lifecycle, "fire", Mock(side_effect=RuntimeError("setup")))
    with pytest.raises(RuntimeError, match="setup"):
        await rig.endpoint(Sock())
    assert rig.leftovers() == NOTHING_LEFT


@pytest.mark.parametrize("how", [*EXITS, "enrolment_refused"])
async def test_the_count_drops_however_the_socket_ends(how: str) -> None:
    """Released at `auth_ok` and on every other exit: a close by either side, a fault (`1011`),
    an auth call past its bound, a connect-rate refusal, a cancellation, an enrolment-only
    refusal (`4403`, #2295, never registered); the next socket gets in."""
    rig, sock, later = Rig(max_unauthenticated=1, max_auths_per_min=1, hangs=True), Sock(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        await _spend_good_dup(rig)
        handler = await rig.open(sock)
        await _shed(rig)  # the cap is reached
        await end_through(rig, sock, handler, how)
        assert rig.leftovers() == NOTHING_LEFT
        await _close_all([later], [await rig.open(later)])
    assert rig.leftovers() == NOTHING_LEFT


async def test_an_authenticated_socket_and_its_reauth_do_not_count() -> None:
    """Once a socket has `auth_ok` it stops counting, and an in-place re-`auth` in flight takes no
    slot: a new socket gets in meanwhile, and only it counts."""
    rig, first, second = Rig(max_unauthenticated=1), Sock(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handlers = [await rig.open(first)]
        assert (await rig.auth(first, "good-1"))["t"] == "auth_ok"
        assert (rig.hub.unauthenticated, len(rig.hub)) == (0, 1)
        gate = rig.hold("authenticate")
        first.feed({"t": "auth", "id": "re", "p": {"access_token": "good-1"}})
        await rig.parked["authenticate"].wait()
        handlers.append(await rig.open(second))  # admitted, not shed
        gate.set()
        assert (await first.sent.get())["t"] == "auth_ok"
        assert rig.hub.unauthenticated == 1
        await _close_all([first, second], handlers)
    assert rig.leftovers() == NOTHING_LEFT


async def test_many_sockets_through_mixed_ends_leave_nothing_counted() -> None:
    """Six waves of four sockets at a cap of four, each shedding a fifth and taking every exit
    three times in all, then a wave the auth window closes: nothing is left counted, live or
    registered, and each refusal was counted once."""
    rig, before = Rig(max_unauthenticated=4, max_auths_per_min=1, hangs=True), _sheds()
    async with asyncio.timeout(DEADLINE_S):
        await _spend_good_dup(rig)
        for wave in range(6):
            socks = [Sock() for _ in range(4)]
            handlers = [await rig.open(sock) for sock in socks]
            await _shed(rig)
            exits = [EXITS[(wave * 4 + i) % len(EXITS)] for i in range(4)]
            await asyncio.gather(*map(end_through, [rig] * 4, socks, handlers, exits))
            assert rig.leftovers() == NOTHING_LEFT, (wave, exits)
        socks = [Sock() for _ in range(4)]
        handlers = [await rig.open(sock) for sock in socks]
        rig.now += AUTH_TIMEOUT_S
        for sock in socks:
            assert bye_of(await sock.sent.get()) == ("bye", "auth_timeout", 4401)
        await asyncio.gather(*handlers)
    assert (rig.leftovers(), _sheds()) == (NOTHING_LEFT, before + 6)


@pytest.mark.parametrize("peer", ["stops_reading", "vanished"])
async def test_a_shed_whose_peer_cannot_take_the_bye_still_ends(
    peer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shed `bye` and close get the close flush deadline: a peer that stopped reading costs
    at most that, one that left costs nothing, and the refusal is counted either way."""
    monkeypatch.setattr(gateway, "CLOSE_FLUSH_TIMEOUT_S", 0.01)
    rig, first, shed, before = Rig(max_unauthenticated=1), Sock(), Sock(), _sheds()
    setattr(shed, peer, True)
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(first)
        await rig.start(shed)
        await _close_all([first], [handler])
    assert (shed.codes, shed.sent.empty(), rig.leftovers()) == ([], True, NOTHING_LEFT)
    assert _sheds() == before + 1


async def test_a_cancellation_during_a_shed_propagates() -> None:
    """A cancellation while the shed `bye` is parked is honoured, never swallowed."""
    rig, first, shed = Rig(max_unauthenticated=1), Sock(), Sock()
    shed.stops_reading = True
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(first)
        shedding = rig.start(shed)
        await shed.stalled.wait()
        shedding.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shedding
        assert rig.hub.unauthenticated == 1  # the shed socket never counted
        await _close_all([first], [handler])
    assert rig.leftovers() == NOTHING_LEFT
