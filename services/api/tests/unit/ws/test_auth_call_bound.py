"""#2155 item 1: each call an `auth` makes is bounded (C-2.18; `23-ws-protocol.md` §4.3).

`authenticate`, the principal read and a first `auth`'s SR-189 re-read each get
`auth_call_timeout_s`. Past it: `bye internal_error` + `1011`, a re-`auth`'s too, no strike, no
`auth.login_failed` row and no registration left. The bound is on the loop's clock: a test whose
call `hangs` past it gets a 10 ms one from the rig, which parks the call on an event.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from prometheus_client import Counter
from structlog.testing import capture_logs

from candleviewer.audit.models import Severity
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.limits import AUTH_CALL_TIMEOUT_S, AUTH_TIMEOUT_S
from candleviewer.ws.metrics import cv_ws_auth_failures_total, cv_ws_closes_total
from candleviewer.ws_wiring import PRINCIPAL_LOAD_TIMEOUT_S
from tests.unit.ws._auth_rig import DEADLINE_S, NOTHING_LEFT, Rig, Sock, bye_of, hang_up

_FAULT = ("bye", "internal_error", 1011)


def _count(counter: Counter, reason: str) -> float:
    return float(counter.labels(reason=reason)._value.get())


def _timed_out(logs: Sequence[Mapping[str, Any]]) -> list[tuple[Any, Any]]:
    return [(e["call"], e["reauth"]) for e in logs if e["event"] == "ws auth call timed out"]


@pytest.mark.parametrize("call", ["authenticate", "resolve", "recheck"])
async def test_auth_call_times_out_first_auth_closes_with_internal_error(call: str) -> None:
    """No `auth_ok` and no `err auth_failed`, but the server fault's `bye`; what the `auth`
    registered (#2739's hub entry, SR-189's registry entry) is gone when that `bye` is out."""
    rig, sock = Rig(hangs=True), Sock()
    rig.hold(call)  # never released
    failures = _count(cv_ws_auth_failures_total, "rejected")
    faults = _count(cv_ws_closes_total, "internal_error")
    with capture_logs() as logs:
        async with asyncio.timeout(DEADLINE_S):
            handler = await rig.open(sock)
            assert bye_of(await rig.auth(sock, "good-1")) == _FAULT
            assert rig.leftovers()[2:] == (0, 0, {})  # registry, sequencing, hub
            await handler
    assert (sock.codes, sock.sent.empty(), rig.leftovers()) == ([1011], True, NOTHING_LEFT)
    assert _timed_out(logs) == [(call, False)]
    assert not [e for e in logs if e["event"] == "ws auth failed"]  # not a failed `auth`
    assert _count(cv_ws_auth_failures_total, "rejected") == failures
    assert _count(cv_ws_closes_total, "internal_error") == faults + 1
    assert rig.audit.records == []  # no `auth.login_failed`; unauthenticated: no close row


@pytest.mark.parametrize("call", ["authenticate", "resolve"])
async def test_auth_call_times_out_reauth_closes_with_internal_error(call: str) -> None:
    """A re-`auth` onto a rotated session ends the socket the same way, not as a failed re-`auth`
    that keeps the prior identity. The rotated session's registration (made before its principal
    read, #2739) goes at once; the socket's own goes with the close, whose row reads
    `internal_error` at `warning`."""
    rig, sock = Rig(hangs=True), Sock()
    with capture_logs() as logs:
        async with asyncio.timeout(DEADLINE_S):
            handler = await rig.open(sock)
            assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
            rig.hold(call)
            assert bye_of(await rig.auth(sock, "good-1@rotated", "re")) == _FAULT
            assert rig.registered() == {"sess-good-1": 1}
            await handler
    assert (sock.codes, sock.sent.empty(), rig.leftovers()) == ([1011], True, NOTHING_LEFT)
    assert _timed_out(logs) == [(call, True)]
    rows = [(r["action"], r["reason"], r["severity"]) for r in rig.audit.records]
    assert rows == [("ws.connection.closed", "internal_error", Severity.WARNING)]


async def test_a_timeout_error_the_call_raises_itself_is_a_failed_auth() -> None:
    """Only the bound's own expiry is a server fault: a `TimeoutError` the session service raises
    at once (its store's own timeout, say) is a failed `auth`, as any other error it raises."""
    rig, sock = Rig(), Sock()
    failures = _count(cv_ws_auth_failures_total, "rejected")
    with capture_logs() as logs:
        async with asyncio.timeout(DEADLINE_S):
            handler = await rig.open(sock)
            err = await rig.auth(sock, "raises-timeout")
            hang_up(sock)
            await handler
    assert (err["t"], err["p"]["code"], sock.codes) == ("err", "auth_failed", [])
    assert _count(cv_ws_auth_failures_total, "rejected") == failures + 1
    assert _timed_out(logs) == []


async def test_a_cancellation_during_an_auth_call_propagates_and_leaves_nothing() -> None:
    """uvicorn's graceful-timeout cancel while a bounded call is pending reaches the caller as a
    `CancelledError`, never a timeout, and the teardown still runs."""
    rig, sock = Rig(), Sock()  # production's bound: it never fires here
    rig.hold("resolve")
    with capture_logs() as logs:
        async with asyncio.timeout(DEADLINE_S):
            handler = await rig.open(sock)
            sock.feed({"t": "auth", "id": "a", "p": {"access_token": "good-1"}})
            await rig.parked["resolve"].wait()
            assert rig.registered() == {"sess-good-1": 1}  # registered before the read
            handler.cancel()
            with pytest.raises(asyncio.CancelledError):
                await handler
    assert (sock.sent.empty(), rig.leftovers(), _timed_out(logs)) == (True, NOTHING_LEFT, [])


def test_the_auth_call_bound_sits_between_the_loader_bound_and_the_auth_window() -> None:
    """6 s: a slow principal store still gives its own deny-all answer first (5 s, #2505), and a
    first `auth` stalled in one call is answered before its 10 s window ends."""
    default = inspect.signature(make_ws_router).parameters["auth_call_timeout_s"].default
    assert default == AUTH_CALL_TIMEOUT_S == 6.0
    assert PRINCIPAL_LOAD_TIMEOUT_S < AUTH_CALL_TIMEOUT_S < AUTH_TIMEOUT_S
