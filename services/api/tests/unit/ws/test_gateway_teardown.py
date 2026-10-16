"""#2735: the handler's teardown tail runs on every exit, a real cancellation included.

uvicorn cancels every handler still running once `--timeout-graceful-shutdown` expires, while it
is blocked in `reader()`. Its tail (hub, metric, registries, close audit, lifecycle) must still
run and the `CancelledError` must still reach the caller. The handler is driven on the test's own
loop through a fake socket, so the cancel lands where uvicorn's does. Waits are event-driven and
bounded: no sleeps.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.lifecycle import ConnState
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub
from tests.unit.ws.test_lifecycle_socket import BASE_MS, ORIGIN, SESSION, USER, _Audit
from tests.unit.ws.test_origin_check import _open_sockets

_DEADLINE_S = 5.0
#: uvicorn's own message when `--timeout-graceful-shutdown` expires.
_UVICORN_CANCEL = "Task cancelled, timeout graceful shutdown exceeded"


class _Socket:
    """The slice of Starlette's `WebSocket` the handler uses; the test feeds and reads it."""

    def __init__(self) -> None:
        self.scope: dict[str, Any] = {
            "headers": [(b"origin", ORIGIN.encode())],
            "subprotocols": ["cv.v1.json"],
            "client": ("127.0.0.1", 50000),
        }
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()

    async def send_text(self, text: str) -> None:
        self.sent.put_nowait(json.loads(text))

    async def close(self, code: int = 1000) -> None: ...

    def feed(self, frame: dict[str, Any]) -> None:
        self.inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})


class _Rig:
    """One gateway on the test's loop: every collaborator the teardown tail touches."""

    def __init__(self) -> None:
        self.audit = _Audit()
        self.hub = GatewayHub()
        self.revocation = RevocationHub()
        self.sequencing = SequencingHub()

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            perms = frozenset({Permission.MARKETDATA_READ})
            return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            return SESSION, USER, datetime(2100, 1, 1, tzinfo=UTC)

        services = SubscriptionServices(sequencing=self.sequencing)
        self.registry = ConnectionRegistry(resolve, lambda: BASE_MS, services=services)
        router = make_ws_router(
            authenticate=authenticate,
            registry=self.registry,
            revocation_hub=self.revocation,
            allowed_origins=frozenset({ORIGIN}),
            hub=self.hub,
            audit=self.audit,
            clock=lambda: 0.0,
            wall_ms=lambda: BASE_MS,
            tick_s=0.005,
        )
        (route,) = router.routes
        assert isinstance(route, APIWebSocketRoute)
        self.endpoint = route.endpoint

    async def authenticated(self, sock: _Socket) -> asyncio.Task[None]:
        """Start the handler and take it through `hello` and `auth`: it is then blocked in
        `reader()`, awaiting the next inbound frame."""
        handler = asyncio.create_task(self.endpoint(sock))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        return handler


async def test_cancelled_handler_still_runs_its_whole_teardown() -> None:
    rig, sock = _Rig(), _Socket()
    rig.hub.shutting_down = True  # uvicorn cancels handlers only inside its own shutdown
    sockets_before = _open_sockets()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        assert (len(rig.hub), _open_sockets()) == (1, sockets_before + 1)
        assert (len(rig.registry._conns[USER]), len(rig.sequencing)) == (1, 1)
        assert len(rig.revocation._sockets[SESSION]) == 1
        handler.cancel(msg=_UVICORN_CANCEL)
        with pytest.raises(asyncio.CancelledError):
            await handler
    assert handler.cancelled()  # the handler's own cancellation is never swallowed
    assert len(rig.hub) == 0 and _open_sockets() == sockets_before
    assert not rig.registry._conns and len(rig.sequencing) == 0 and not rig.revocation._sockets
    assert conn.lifecycle.state is ConnState.CLOSED
    (rec,) = rig.audit.records
    assert (rec["action"], rec["reason"], rec["severity"]) == (
        "ws.connection.closed",
        "shutdown",
        "info",
    )
    assert (rec["actor_user_id"], rec["session_id"]) == (USER, SESSION)
    assert not [t for t in asyncio.all_tasks() if t.get_name().endswith("-writer")]
