"""§9.6 (#3085): what a WebSocket `auth` does with its session's view-as binding.

The `view_as` port answers each read in turn (`_Bindings`): an `auth` reads the binding once
after `authenticate` and once more after registering, so a start or an end that lands during it
is seen (as SR-189 re-reads the roles). A held context refuses the `auth` with `view_as_expired`
(4403) and no strike; a context other than the socket's (none or another one) closes
`view_as_changed` (4401), so a read of no context never widens a viewing socket. A refresh keeps
the context, and its re-`auth` the socket. The socket is bound to its context on the hub, so the
context's end closes it. Each test drives one handler through the shared rig: no sleeps.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.ws.metrics import cv_ws_auth_failures_total
from tests.unit.ws._auth_rig import DEADLINE_S, LATER, Rig, Sock, bye_of, hang_up

_X, _Y = uuid4(), uuid4()


def _bound(context_id: UUID, phase: ViewAsPhase = ViewAsPhase.LIVE) -> ViewAsBinding:
    return ViewAsBinding(
        context_id=context_id, target_user_id=uuid4(), expires_at=LATER, phase=phase
    )


class _Bindings:
    """The `view_as` port: each read takes the next answer, the last one for good."""

    def __init__(self, *answers: ViewAsBinding | None) -> None:
        self.answers, self.read = list(answers), list[str]()

    async def __call__(self, session_id: str) -> ViewAsBinding | None:
        self.read.append(session_id)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


async def _first_frame_after_auth(bindings: _Bindings, *tokens: str) -> list[dict[str, object]]:
    """The frame each `auth` of `tokens` gets on one socket, until a `bye`."""
    rig, sock = Rig(options={"view_as": bindings}), Sock()
    frames: list[dict[str, object]] = []
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        for n, token in enumerate(tokens):
            frames.append(frame := await rig.auth(sock, token, fid=f"a{n}"))
            if frame["t"] == "bye":
                break
        hang_up(sock)
        await handler
    return frames


def _failures() -> float:
    """Every failed `auth` counted so far, whatever its reason (a strike is one of them)."""
    return sum(sample.value for sample in cv_ws_auth_failures_total.collect()[0].samples)


async def test_a_held_context_refuses_the_auth_with_view_as_expired_and_no_strike() -> None:
    before = _failures()
    (frame,) = await _first_frame_after_auth(_Bindings(_bound(_X, ViewAsPhase.HELD)), "good-1")
    assert bye_of(frame) == ("bye", "view_as_expired", 4403)
    assert _failures() == before  # a refused context is no failed auth (§9.6)


async def test_a_reauth_into_another_context_closes_view_as_changed() -> None:
    bindings = _Bindings(_bound(_X), _bound(_X), _bound(_Y))
    ok, bye = await _first_frame_after_auth(bindings, "good-1", "good-1")
    assert ok["t"] == "auth_ok" and bye_of(bye) == ("bye", "view_as_changed", 4401)


async def test_a_reauth_that_reads_no_context_closes_view_as_changed_never_widens() -> None:
    """S4-SEC-08: `None` is never the viewer's scope for a socket bound to a context."""
    bindings = _Bindings(_bound(_X), _bound(_X), None)
    ok, bye = await _first_frame_after_auth(bindings, "good-1", "good-1")
    assert ok["t"] == "auth_ok" and bye_of(bye) == ("bye", "view_as_changed", 4401)


async def test_a_start_during_the_auth_is_read_again_and_closes_view_as_changed() -> None:
    rig, sock = Rig(options={"view_as": _Bindings(None, _bound(_X))}), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert bye_of(await rig.auth(sock, "good-1")) == ("bye", "view_as_changed", 4401)
        # The registration the first read let through is undone before the close.
        assert rig.registered() == {} and not rig.registry._conns
        hang_up(sock)
        await handler


async def test_an_end_during_the_auth_is_read_again_and_refuses_it() -> None:
    held = _bound(_X, ViewAsPhase.HELD)
    (frame,) = await _first_frame_after_auth(_Bindings(_bound(_X), held), "good-1")
    assert bye_of(frame) == ("bye", "view_as_expired", 4403)


async def test_a_refresh_keeps_the_socket_on_its_context_under_the_successor() -> None:
    rig, sock = Rig(options={"view_as": _Bindings(_bound(_X))}), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        assert (await rig.auth(sock, "good-1@r", fid="re"))["t"] == "auth_ok"
        assert rig.registered() == {"sess-good-1@r": 1}
        assert list(rig.revocation._contexts.values()) == [str(_X)]
        hang_up(sock)
        await handler


async def test_a_context_end_closes_the_socket_bound_to_it_and_no_other() -> None:
    rig = Rig(options={"view_as": _Bindings(_bound(_X))})
    viewing, other = Sock(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handlers = [await rig.open(viewing), await rig.open(other)]
        assert (await rig.auth(viewing, "good-1"))["t"] == "auth_ok"
        assert (await rig.auth(other, "good-2"))["t"] == "auth_ok"
        closed = await rig.revocation.close_context("sess-good-1", str(_Y), "view_as_expired")
        assert closed == 0 and rig.registered() == {"sess-good-1": 1, "sess-good-2": 1}
        closed = await rig.revocation.close_context("sess-good-1", str(_X), "view_as_expired")
        assert closed == 1 and bye_of(await viewing.sent.get()) == (
            "bye",
            "view_as_expired",
            4403,
        )
        await handlers[0]  # the closed socket's own teardown ends its registration
        assert rig.registered() == {"sess-good-2": 1}
        assert not rig.revocation.was_revoked("sess-good-1")  # its reconnect is never refused
        hang_up(other)
        await handlers[1]
