"""#2739: a session revoked while its WS `auth` is in flight never gets `auth_ok` (E17 WS-S01).

The #2265 security re-review's S5 and S6: a revocation published inside the `auth` path closed
nothing, because the socket registered with the `RevocationHub` only after `registry.resolve()`.
The socket then got `auth_ok` and was served on the revoked session until its access token
expired. Each test drives one handler on its own loop through a fake socket, and the
`authenticate` or `resolve` stub publishes the revocation at a chosen await of the `auth` path.
The gateway's clocks are fakes and every wait is event-driven and bounded: no sleeps.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.metrics import cv_ws_closes_total
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub
from tests.unit.ws.test_gateway_teardown import _Socket
from tests.unit.ws.test_lifecycle_socket import BASE_MS, ORIGIN, USER, _Audit

_DEADLINE_S = 5.0
_SESSIONS = {"tok-a": "sess-A", "tok-b": "sess-B"}  # access token -> its session
_LATER = datetime(2100, 1, 1, tzinfo=UTC)
#: The close code the hub's own close sends per reason (§9.5): the in-flight refusal must match.
_CODES = {"session_revoked": 4401, "user_disabled": 4403}

Hook = Callable[[], Awaitable[None]]


class _Sock(_Socket):
    """The teardown tests' fake socket, also recording each close code the writer sends."""

    def __init__(self) -> None:
        super().__init__()
        self.codes: list[int] = []

    async def close(self, code: int = 1000) -> None:
        self.codes.append(code)
        await super().close(code)


class _Rig:
    """One gateway on the test's loop. `in_authenticate` runs inside `authenticate` once the
    session service has accepted the token; `in_resolve` runs inside the principal read."""

    def __init__(self, *, max_remembered: int = 4096) -> None:
        self.audit = _Audit()
        self.hub = GatewayHub()
        self.revocation = RevocationHub(wall_ms=lambda: BASE_MS, max_remembered=max_remembered)
        self.in_authenticate: Hook | None = None
        self.in_resolve: Hook | None = None
        self.expires_at = _LATER
        self.now = 0.0

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            session_id = _SESSIONS[token]
            if self.in_authenticate is not None:
                await self.in_authenticate()
            return session_id, USER, self.expires_at

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            if self.in_resolve is not None:
                await self.in_resolve()
            perms = frozenset({Permission.MARKETDATA_READ})
            return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)

        self.registry = ConnectionRegistry(resolve, lambda: BASE_MS)
        router = make_ws_router(
            authenticate=authenticate,
            registry=self.registry,
            revocation_hub=self.revocation,
            allowed_origins=frozenset({ORIGIN}),
            hub=self.hub,
            audit=self.audit,
            clock=lambda: self.now,
            wall_ms=lambda: BASE_MS + int(self.now * 1000),
            tick_s=0.005,
        )
        (route,) = router.routes
        assert isinstance(route, APIWebSocketRoute)
        self.endpoint = route.endpoint

    async def open(self, sock: _Sock) -> asyncio.Task[None]:
        """Start the handler and take it through `hello`."""
        handler: asyncio.Task[None] = asyncio.create_task(self.endpoint(sock))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        return handler

    @staticmethod
    async def auth(sock: _Sock, token: str, fid: str = "a") -> dict[str, Any]:
        """Send one `auth` and return the next frame."""
        sock.feed({"t": "auth", "id": fid, "p": {"access_token": token}})
        frame: dict[str, Any] = await sock.sent.get()
        return frame

    def revoke_on(self, session_id: str, reason: str = "session_revoked") -> tuple[Hook, list[int]]:
        """A hook that publishes the revocation of `session_id`, and the close counts it saw."""
        closed: list[int] = []

        async def hook() -> None:
            closed.append(await self.revocation.revoke(session_id, reason))

        return hook, closed

    def registered(self) -> dict[str, int]:
        """How many closers the hub holds per session id."""
        return {session_id: len(c) for session_id, c in self.revocation._sockets.items()}

    def record_on_read(self, *, fail: bool = False) -> list[dict[str, int]]:
        """Record `registered()` inside each principal read; `fail` then fails the read."""
        seen: list[dict[str, int]] = []

        async def hook() -> None:
            seen.append(self.registered())
            if fail:
                raise ConnectionError("identity store unreachable")

        self.in_resolve = hook
        return seen


def _hang_up(sock: _Sock) -> None:
    sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})


def _bye(frame: dict[str, Any]) -> tuple[str, str, int]:
    return frame["t"], frame["p"]["reason"], frame["p"]["code"]


@pytest.mark.parametrize("reason", list(_CODES))
async def test_s5_a_revocation_during_the_first_auth_closes_the_socket_with_no_auth_ok(
    reason: str,
) -> None:
    """S5: revoked while the first `auth` reads the principal. Before #2739, `revoke()` closed 0
    sockets, and the client got `auth_ok` and every later broadcast."""
    rig, sock = _Rig(), _Sock()
    rig.in_resolve, closed = rig.revoke_on("sess-A", reason)
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        bye = await rig.auth(sock, "tok-a")
        assert _bye(bye) == ("bye", reason, _CODES[reason]), bye
        assert rig.hub.broadcast_system({"kind": "tick"}) == 0  # not authenticated: none sent
        await handler
    assert closed == [1]  # the revocation itself closed the in-flight socket
    assert (sock.codes, sock.sent.empty()) == ([_CODES[reason]], True)  # no auth_ok, no data
    assert rig.registered() == {}


async def test_s6_a_revocation_during_a_reauth_onto_a_rotated_session_closes_the_socket() -> None:
    """S6: on `sess-A`, the client re-`auth`s onto `sess-B`, which is revoked while that re-auth
    reads the principal. No `auth_ok` for `sess-B`, and neither session stays registered."""
    rig, sock = _Rig(), _Sock()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        rig.in_resolve, closed = rig.revoke_on("sess-B")
        bye = await rig.auth(sock, "tok-b", "re")
        assert _bye(bye) == ("bye", "session_revoked", 4401), bye
        assert rig.hub.broadcast_system({"kind": "tick"}) == 0
        await handler
    assert closed == [1]
    assert (sock.codes, sock.sent.empty()) == ([4401], True)
    assert rig.registered() == {}  # `sess-B`'s registration, and `sess-A`'s, are gone


@pytest.mark.parametrize("reason", list(_CODES))
@pytest.mark.parametrize("reauth", [False, True], ids=["first_auth", "reauth"])
async def test_a_revocation_before_the_socket_registers_is_refused_from_the_hubs_memory(
    reauth: bool, reason: str
) -> None:
    """Published inside `authenticate`, after the session service accepted the token but before
    the socket registered: it closes nothing, but the hub remembers it with its reason."""
    rig, sock = _Rig(), _Sock()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        if reauth:
            assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        rig.in_authenticate, closed = rig.revoke_on("sess-B", reason)
        bye = await rig.auth(sock, "tok-b", "b")
        await handler
    assert closed == [0]  # nothing was registered on `sess-B` yet
    assert _bye(bye) == ("bye", reason, _CODES[reason]), bye
    assert (sock.codes, sock.sent.empty()) == ([_CODES[reason]], True)
    assert rig.registered() == {}


async def test_the_registration_closes_it_even_once_the_memory_forgot_the_session() -> None:
    """Past its cap the hub forgets the oldest id. The registration made before the principal
    read still closes the socket, and the gateway sees it closing: no `auth_ok` and no fault."""
    rig, sock = _Rig(max_remembered=1), _Sock()
    revoke_a, closed = rig.revoke_on("sess-A")
    forgotten: list[bool] = []

    async def revoke_then_forget() -> None:
        await revoke_a()
        await rig.revocation.revoke("sess-other")  # over the cap of 1: `sess-A` is forgotten
        forgotten.append(not rig.revocation.was_revoked("sess-A"))

    rig.in_resolve = revoke_then_forget
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        bye = await rig.auth(sock, "tok-a")
        await handler
    assert (closed, forgotten, _bye(bye)) == ([1], [True], ("bye", "session_revoked", 4401))
    assert (sock.codes, sock.sent.empty()) == ([4401], True)
    assert rig.audit.records == []  # it never authenticated: no close row (#2486)


@pytest.mark.parametrize("failure", ["resolve_fails", "token_expired"])
async def test_a_failed_auth_leaves_no_registration_behind(failure: str) -> None:
    rig, sock = _Rig(), _Sock()
    seen = rig.record_on_read(fail=failure == "resolve_fails")
    if failure == "token_expired":
        rig.expires_at = datetime(2020, 1, 1, tzinfo=UTC)  # already past on the gateway's clock
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        err = await rig.auth(sock, "tok-a")
        assert (err["t"], err["p"]["code"]) == ("err", "auth_failed"), err
        assert (seen, rig.registered()) == ([{"sess-A": 1}], {})  # registered for the read only
        assert await rig.revocation.revoke("sess-A") == 0
        _hang_up(sock)
        await handler


@pytest.mark.parametrize("how", ["cancelled", "auth_timeout"])
async def test_an_auth_cut_short_mid_read_leaves_no_registration_behind(how: str) -> None:
    """The handler is cancelled (uvicorn's graceful timeout), or the auth deadline closes the
    socket and the writer's end stops the read, while the principal read is still pending."""
    rig, sock = _Rig(), _Sock()
    parked = asyncio.Event()

    async def park() -> None:
        parked.set()
        await asyncio.Event().wait()  # the principal read never returns

    rig.in_resolve = park
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok-a"}})
        await parked.wait()
        assert rig.registered() == {"sess-A": 1}  # registered before the read
        if how == "cancelled":
            handler.cancel()
            with pytest.raises(asyncio.CancelledError):
                await handler
        else:
            rig.now = 10.0  # the 10 s auth deadline
            assert (await sock.sent.get())["p"]["reason"] == "auth_timeout"
            await handler
    assert rig.registered() == {}


async def test_a_failed_reauth_keeps_the_old_session_registered_and_drops_the_new_one() -> None:
    """A failed re-`auth` keeps the prior identity (§4.3), so that session stays revocable."""
    rig, sock = _Rig(), _Sock()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        (conn,) = rig.hub.of_user(USER)
        seen = rig.record_on_read(fail=True)
        assert (await rig.auth(sock, "tok-b", "re"))["p"]["code"] == "auth_failed"
        assert seen == [{"sess-A": 1, "sess-B": 1}]  # both while the re-auth was in flight
        assert rig.revocation._sockets == {"sess-A": [conn.closer]}
        assert await rig.revocation.revoke("sess-A") == 1
        assert _bye(await sock.sent.get()) == ("bye", "session_revoked", 4401)
        await handler
    assert sock.codes == [4401]


async def test_a_revocation_of_the_old_session_during_a_reauth_still_closes_the_socket() -> None:
    """Until the re-`auth` is accepted the socket serves `sess-A`: that registration is dropped
    only after the check, so no moment has neither session registered."""
    rig, sock = _Rig(), _Sock()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        rig.in_resolve, closed = rig.revoke_on("sess-A")
        bye = await rig.auth(sock, "tok-b", "re")
        await handler
    assert (closed, _bye(bye), sock.codes) == ([1], ("bye", "session_revoked", 4401), [4401])
    assert sock.sent.empty()


async def test_the_normal_path_registers_each_session_once_and_moves_it_on_a_reauth() -> None:
    """Registered from the read on, once; a re-`auth` onto the same session adds nothing, and one
    onto a rotated session holds both until it is accepted, then only the new one."""
    rig, sock = _Rig(), _Sock()
    seen = rig.record_on_read()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        (conn,) = rig.hub.of_user(USER)
        assert rig.revocation._sockets == {"sess-A": [conn.closer]}
        assert len(rig.registry._conns[USER]) == 1  # and with the registry, once (SR-189)
        assert (await rig.auth(sock, "tok-a", "same"))["t"] == "auth_ok"
        assert rig.registered() == {"sess-A": 1}
        assert (await rig.auth(sock, "tok-b", "rotated"))["t"] == "auth_ok"
        assert rig.revocation._sockets == {"sess-B": [conn.closer]}
        assert seen == [{"sess-A": 1}, {"sess-A": 1}, {"sess-A": 1, "sess-B": 1}]
        assert await rig.revocation.revoke("sess-B") == 1
        assert _bye(await sock.sent.get()) == ("bye", "session_revoked", 4401)
        await handler


async def test_the_hubs_close_racing_the_check_closes_once_and_writes_one_close_row() -> None:
    """The hub closes the socket through the registration made for `sess-B`, and the check after
    the read then finds it both closing and remembered: one `bye`, one close, one close row."""
    rig, sock = _Rig(), _Sock()
    before: float = cv_ws_closes_total.labels(reason="session_revoked")._value.get()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "tok-a"))["t"] == "auth_ok"
        rig.in_resolve, _ = rig.revoke_on("sess-B")
        assert (await rig.auth(sock, "tok-b", "re"))["t"] == "bye"
        await handler
    assert (sock.codes, sock.sent.empty()) == ([4401], True)
    assert cv_ws_closes_total.labels(reason="session_revoked")._value.get() == before + 1
    (row,) = rig.audit.records  # the socket's own session: `sess-B` was never accepted
    assert (row["action"], row["reason"], row["session_id"]) == (
        "ws.connection.closed",
        "session_revoked",
        "sess-A",
    )
