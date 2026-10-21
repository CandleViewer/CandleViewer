"""§9.6 (#3085): the closes of a view-as context's sockets, on the `RevocationHub`.

A socket is bound to the context it authenticated into (`bind`, at its `auth_ok`).
`close_context` closes the sockets of one session bound to one context, and only those, with the
§9.6 `bye`: `view_as_changed` (4401, reconnect) or `view_as_expired` (4403, no reconnect). It
never remembers the session, which stays live: unlike a revocation's 720 s memory, it never
refuses the socket's reconnect. A failed close is counted and the others still run.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.revocation import RevocationHub, ws_revocation_close_failures_total


class _Socket:
    def __init__(self, fails: bool = False) -> None:
        self.fails, self.closes = fails, list[tuple[str, int]]()

    async def __call__(self, frame: dict[str, Any], code: int) -> None:
        if self.fails:
            raise ConnectionError("the peer is gone")
        self.closes.append((frame["p"]["reason"], code))


@pytest.mark.parametrize(
    ("reason", "code", "reconnect"),
    [("view_as_changed", 4401, True), ("view_as_expired", 4403, False)],
)
def test_the_view_as_close_reasons_carry_their_codes_and_reconnect_flags(
    reason: str, code: int, reconnect: bool
) -> None:
    p = bye_frame(reason)["p"]
    assert (p["code"], p["reconnect"]) == (code, reconnect)


async def test_close_context_closes_only_the_sockets_bound_to_that_context() -> None:
    hub = RevocationHub()
    on_x, on_y, unbound, elsewhere = _Socket(), _Socket(), _Socket(), _Socket()
    for session_id, socket, context in [
        ("s1", on_x, "x"),
        ("s1", on_y, "y"),
        ("s1", unbound, None),
        ("s2", elsewhere, "x"),
    ]:
        hub.register(session_id, socket)
        hub.bind(session_id, socket, context)
    assert await hub.close_context("s1", "x", "view_as_expired") == 1
    assert on_x.closes == [("view_as_expired", 4403)]
    assert (on_y.closes, unbound.closes, elsewhere.closes) == ([], [], [])
    # Every socket stays registered until its own teardown: the session is live.
    assert {s: len(c) for s, c in hub._sockets.items()} == {"s1": 3, "s2": 1}


async def test_close_context_with_no_context_closes_the_unbound_sockets_only() -> None:
    """A start's close (#3085 S13a): every socket the session had before it holds no context."""
    hub = RevocationHub()
    bound, unbound, elsewhere = _Socket(), _Socket(), _Socket()
    for session_id, socket, context in [
        ("s1", bound, "x"),
        ("s1", unbound, None),
        ("s2", elsewhere, None),
    ]:
        hub.register(session_id, socket)
        hub.bind(session_id, socket, context)
    assert await hub.close_context("s1", None, "view_as_changed") == 1
    assert unbound.closes == [("view_as_changed", 4401)]
    assert (bound.closes, elsewhere.closes) == ([], []) and not hub.was_revoked("s1")


async def test_close_context_never_remembers_the_session() -> None:
    hub, socket = RevocationHub(), _Socket()
    hub.register("s1", socket)
    hub.bind("s1", socket, "x")
    await hub.close_context("s1", "x", "view_as_changed")
    assert socket.closes == [("view_as_changed", 4401)] and not hub.was_revoked("s1")


async def test_a_failed_context_close_is_counted_and_a_later_revoke_still_reaches_it() -> None:
    hub, gone, live = RevocationHub(), _Socket(fails=True), _Socket()
    for socket in (gone, live):
        hub.register("s1", socket)
        hub.bind("s1", socket, "x")
    before = ws_revocation_close_failures_total._value.get()
    assert await hub.close_context("s1", "x", "view_as_expired") == 2
    assert ws_revocation_close_failures_total._value.get() == before + 1
    assert live.closes == [("view_as_expired", 4403)]
    # The session stays live, so the socket whose close failed stays registered: a sign-out's
    # revoke still reaches it.
    assert await hub.revoke("s1") == 2


def test_a_binding_needs_a_registration_and_goes_with_it() -> None:
    hub, socket = RevocationHub(), _Socket()
    hub.bind("s1", socket, "x")  # not registered: nothing to bind
    assert hub._contexts == {}
    hub.register("s1", socket)
    hub.bind("s1", socket, "x")
    hub.unregister("s1", socket)
    assert hub._contexts == {}
