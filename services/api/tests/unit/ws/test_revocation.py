"""Revoking a session closes its sockets with 4401 (US-ONB-009, QA #1634); a disabled user's
sockets get `bye user_disabled` and close 4403, no reconnect (23-ws-protocol.md §9.5, #2493)."""

from __future__ import annotations

from typing import Any, get_args

import pytest

from candleviewer.ws.revocation import (
    CLOSE_TOKEN_EXPIRED,
    CLOSE_USER_DISABLED,
    RevocationHub,
    RevokedReason,
    bye_frame,
    user_disabled_bye,
)

_NOW_MS = 1_789_133_600_000
#: Every §9.5 reason except a disabled user keeps the session-revocation close (4401).
_NOT_DISABLED = [reason for reason in get_args(RevokedReason) if reason != "user_disabled"]


class _Socket:
    def __init__(self) -> None:
        self.closes: list[tuple[dict[str, Any], int]] = []

    async def close(self, frame: dict[str, Any], code: int) -> None:
        self.closes.append((frame, code))


async def test_revoke_user_disabled_sends_user_disabled_bye_and_closes_4403() -> None:
    hub = RevocationHub(wall_ms=lambda: _NOW_MS)
    sock = _Socket()
    hub.register("s1", sock.close)
    assert await hub.revoke("s1", "user_disabled") == 1
    assert sock.closes == [(user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)]
    frame, code = sock.closes[0]
    assert (frame["p"]["code"], frame["p"]["reconnect"], code) == (4403, False, 4403)


@pytest.mark.parametrize("reason", _NOT_DISABLED)
async def test_revoke_other_reason_keeps_bye_and_close_4401(reason: str) -> None:
    hub = RevocationHub(wall_ms=lambda: _NOW_MS)
    sock = _Socket()
    hub.register("s1", sock.close)
    assert await hub.revoke("s1", reason) == 1
    assert sock.closes == [(bye_frame(reason), CLOSE_TOKEN_EXPIRED)]
    frame, code = sock.closes[0]
    assert (frame["p"]["code"], frame["p"]["reason"], code) == (4401, reason, 4401)


async def test_revoke_sends_bye_and_closes_4401_only_for_that_session() -> None:
    hub = RevocationHub()
    got: list[tuple[dict[str, Any], int]] = []
    other: list[int] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        got.append((frame, code))

    async def other_closer(frame: dict[str, Any], code: int) -> None:
        other.append(code)

    hub.register("s1", closer)
    hub.register("s2", other_closer)
    assert await hub.revoke("s1", "session_revoked") == 1
    assert got[0][1] == CLOSE_TOKEN_EXPIRED == 4401
    assert got[0][0]["t"] == "bye"
    assert got[0][0]["p"]["reconnect"] is False
    assert other == []


async def test_a_failing_socket_does_not_block_the_rest() -> None:
    hub = RevocationHub()
    closed: list[int] = []

    async def bad(frame: dict[str, Any], code: int) -> None:
        raise RuntimeError("socket gone")

    async def good(frame: dict[str, Any], code: int) -> None:
        closed.append(code)

    hub.register("s", bad)
    hub.register("s", good)
    await hub.revoke("s")
    assert closed == [4401]


async def test_unregistered_session_is_a_noop() -> None:
    assert await RevocationHub().revoke("nope") == 0
