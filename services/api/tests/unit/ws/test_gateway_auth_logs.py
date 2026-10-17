"""E17-T06 (#571): the gateway's `ws auth failed` line, and the correlation of its lifecycle lines
(`23-ws-protocol.md` §4.3, `20-architecture.md` §12.2).

A failed `auth` used to leave a counter and an `err` frame. It now leaves one `warning` as well,
with the attempt number and a reason from the closed set of `cv_ws_auth_failures_total`. Never the
token, never the authenticator's error text, never a traceback. A line the socket's own tasks log
carries the upgrade's `request_id` by contextvar and its `connection_id` explicitly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator, Mapping
from datetime import timedelta
from typing import Any

import pytest
import structlog
from structlog.testing import capture_logs

from candleviewer.ws.metrics import AUTH_FAILURE_REASONS
from tests.unit.ws.test_auth_revocation_race import _DEADLINE_S, _Rig, _Sock
from tests.unit.ws.test_lifecycle_socket import (
    JSON,
    REJECTED_MARK,
    REQUEST_ID,
    _auth,
    _bye_then_close,
    _hello,
    _recv,
    _World,
)
from tests.unit.ws.test_token_expiry import _USER, _bare_gateway, _Clock, _open


@pytest.fixture
def world() -> Iterator[_World]:
    w = _World()
    with w.client:
        yield w


def _failed(logs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [e for e in logs if e["event"] == "ws auth failed"]


def test_three_failed_auths_log_three_warnings_with_the_attempt_and_no_token(world: _World) -> None:
    with capture_logs() as logs:
        with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            connection_id = _hello(ws)["p"]["connection_id"]
            for i in range(2):
                assert _auth(ws, f"{REJECTED_MARK}-{i}")["p"]["code"] == "auth_failed"
            ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": f"{REJECTED_MARK}-2"}})
            _bye_then_close(ws)
    assert _failed(logs) == [
        {
            "event": "ws auth failed",
            "log_level": "warning",
            "connection_id": connection_id,
            "reason": "rejected",
            "attempt": attempt,
            "reauth": False,
            "source_ip": "testclient",
        }
        for attempt in (1, 2, 3)
    ]
    assert REJECTED_MARK not in repr(logs)  # never the token
    assert "bad token" not in repr(logs)  # nor the authenticator's own error text


def test_the_logged_reason_is_the_closed_set_of_the_failure_counter(world: _World) -> None:
    clock = _Clock()
    expired = _bare_gateway(("sess", _USER, clock.now - timedelta(seconds=30)), clock).client
    with capture_logs() as logs:
        with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            _hello(ws)
            assert _auth(ws, "bad-1")["p"]["code"] == "auth_failed"  # rejected
            ws.send_json({"t": "auth", "id": "m", "p": {}})  # no access_token
            assert _recv(ws)["p"]["code"] == "auth_failed"
            assert _auth(ws)["t"] == "auth_ok"  # a success restarts the count
            assert _auth(ws, "good-other")["p"]["code"] == "auth_failed"  # another user's re-auth
        with expired, expired.websocket_connect("/ws", subprotocols=JSON) as ws:
            assert _open(ws, "any")["p"]["code"] == "auth_failed"  # already expired
    assert [(e["reason"], e["attempt"], e["reauth"]) for e in _failed(logs)] == [
        ("rejected", 1, False),
        ("missing_token", 2, False),
        ("user_mismatch", 1, True),
        ("token_expired", 1, False),
    ]
    assert {e["reason"] for e in _failed(logs)} == AUTH_FAILURE_REASONS
    assert not any("exc_info" in e or "error" in e for e in _failed(logs))  # no traceback, no text


def test_auth_failed_authenticated_and_close_lines_carry_the_upgrade_request_id(
    world: _World,
) -> None:
    headers = {"x-correlation-id": REQUEST_ID}
    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        with world.client.websocket_connect("/ws", subprotocols=JSON, headers=headers) as ws:
            connection_id = _hello(ws)["p"]["connection_id"]
            assert _auth(ws, REJECTED_MARK)["p"]["code"] == "auth_failed"
            assert _auth(ws)["t"] == "auth_ok"
            for i in range(2):  # three failed re-auths close the socket (§4.3)
                assert _auth(ws, f"{REJECTED_MARK}-{i}")["p"]["code"] == "auth_failed"
            ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": f"{REJECTED_MARK}-2"}})
            _bye_then_close(ws)
    for event in ("ws auth failed", "ws authenticated", "ws close"):
        lines = [e for e in logs if e["event"] == event]
        assert lines, event
        assert {(e["request_id"], e["connection_id"]) for e in lines} == {
            (REQUEST_ID, connection_id)
        }, event


async def test_a_failed_auth_is_logged_though_a_revocation_began_closing_the_socket() -> None:
    """The counter and the audit take such a failure (C-2.9), and so does the line."""
    rig, sock = _Rig(), _Sock()
    revoke, _ = rig.revoke_on("sess-A")

    async def revoke_then_fail() -> None:
        await revoke()  # the socket is closing from here on ...
        raise ConnectionError("identity store unreachable")  # ... and this auth fails

    rig.in_resolve = revoke_then_fail
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = await rig.open(sock)
            assert (await rig.auth(sock, "tok-a"))["p"]["reason"] == "session_revoked"
            await handler
    assert [(e["reason"], e["attempt"]) for e in _failed(logs)] == [("rejected", 1)]
    assert "identity store unreachable" not in repr(logs)
