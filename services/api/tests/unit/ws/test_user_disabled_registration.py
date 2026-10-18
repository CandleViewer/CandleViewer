"""#3413 (SR-029, UL1-E2): a registration after the per-user close gets `bye user_disabled`, 4403.

A new socket's `auth` passed `authenticate` and read its principal before the disable, on a
session the hub was never told about (the user's own refresh rotated it), and registers only
after the per-user close. Neither the hub's in-flight check (#2739) nor that close reaches it;
the registry's memory of the disable does. One handler per test on the test's loop, through the
#2739 rig; the clocks are fakes and every wait is an event: no sleeps.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from structlog.testing import capture_logs

from candleviewer.ws.permissions import DISABLED_MEMORY_S
from candleviewer.ws.revocation import ws_revoked_total
from tests.unit.ws.test_auth_revocation_race import _DEADLINE_S, _bye, _hang_up, _Rig, _Sock
from tests.unit.ws.test_lifecycle_socket import BASE_MS, USER

#: The rig's registry stamps the disable at `BASE_MS`; this token was issued a minute before.
_BEFORE_MS = BASE_MS - 60_000


def _issued_at(rig: _Rig, issued_ms: int) -> None:
    """The rig's token becomes one issued at `issued_ms`: it expires one lifetime later."""
    expires_ms = issued_ms + int(DISABLED_MEMORY_S * 1000)
    rig.expires_at = datetime.fromtimestamp(expires_ms / 1000, UTC)


def _disable_after_the_read(rig: _Rig) -> None:
    """The per-user close runs while the first principal read is in flight, after its version
    was taken, so before the socket registers. Once: the re-check's re-read leaves it alone."""

    async def disable() -> None:
        rig.in_resolve = None
        assert await rig.registry.user_disabled(USER) == 0  # nothing registered: none closed

    rig.in_resolve = disable


async def test_a_registration_after_the_per_user_close_gets_bye_user_disabled_and_4403() -> None:
    """AC1: never `auth_ok`, nothing after the `bye`; the socket leaves no registration."""
    rig, sock = _Rig(), _Sock()
    _issued_at(rig, _BEFORE_MS)
    _disable_after_the_read(rig)
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        bye = await rig.auth(sock, "tok-a")
        assert bye["t"] == "bye", bye  # before the wait: an `auth_ok` leaves the socket open
        await handler
    assert _bye(bye) == ("bye", "user_disabled", 4403), bye
    assert (bye["p"]["reconnect"], sock.codes, sock.sent.empty()) == (False, [4403], True)
    assert (rig.registry._conns, rig.registered()) == ({}, {})


async def test_a_token_issued_after_the_disable_is_accepted() -> None:
    """AC4: the user was re-enabled and signed in again after the disable."""
    rig, sock = _Rig(), _Sock()
    await rig.registry.user_disabled(USER)  # at `BASE_MS` on the registry's clock
    _issued_at(rig, BASE_MS + 1)
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        _hang_up(sock)
        await handler
    assert sock.codes == []


async def test_the_refusal_is_counted_and_logged_without_the_token() -> None:
    """AC5: `cv_ws_revoked_total{reason="user_disabled"}` and one warning, never the token."""
    rig, sock = _Rig(), _Sock()
    _issued_at(rig, _BEFORE_MS)
    _disable_after_the_read(rig)
    revoked = ws_revoked_total.labels(reason="user_disabled")
    before = revoked._value.get()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = await rig.open(sock)
            assert (await rig.auth(sock, "tok-a"))["t"] == "bye"
            await handler
    (line,) = [e for e in logs if e["event"] == "ws auth refused"]
    assert (line["log_level"], line["reason"], line["user_id"]) == (
        "warning",
        "user_disabled",
        str(USER),
    )
    assert "tok-a" not in repr(logs)
    assert revoked._value.get() == before + 1
