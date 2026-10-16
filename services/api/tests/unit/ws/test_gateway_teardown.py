"""#2735: the handler's teardown tail runs on every exit, a real cancellation included.

uvicorn cancels every handler still running once `--timeout-graceful-shutdown` expires, and the
cancel can land at any await of the handler. The tail (hub, metric, registries, close audit,
lifecycle) must run wherever it lands, and the `CancelledError` must still reach the caller. Each
test drives the handler on the test's own loop through a fake socket and cancels it at one await:
blocked in `reader()`, behind a writer stuck sending, in the close-flush wait, in the join of a
writer that refuses to die, in the very turn the writer ends, and a second cancel inside the close
audit. A teardown step that raises must neither skip the rest nor replace the cancel. Waits are
event-driven and bounded: no sleeps.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.lifecycle import ConnState
from candleviewer.ws.metrics import cv_ws_connections_in_use
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
        self.stall_sends = False  # the peer stopped reading: the next send sticks
        self.stalled = asyncio.Event()  # set once a send is stuck
        self.stubborn = False  # a stuck send refuses its first cancel, and sticks again
        self.refused = asyncio.Event()  # set when it has refused one
        self.on_close: Callable[[], object] | None = None  # the writer's last act: its close
        self.received = asyncio.Event()  # set as the reader takes a frame, then runs on unyielded
        self.vanished = False  # the peer left: the next send fails as Starlette's does

    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def receive(self) -> dict[str, Any]:
        msg = await self.inbound.get()
        self.received.set()
        return msg

    async def send_text(self, text: str) -> None:
        if self.vanished:
            raise WebSocketDisconnect(1006)
        if self.stall_sends:
            self.stalled.set()
            try:
                await asyncio.Event().wait()  # never set
            except asyncio.CancelledError:
                if not self.stubborn:
                    raise
                self.refused.set()
                await asyncio.Event().wait()  # the second cancel ends it
        self.sent.put_nowait(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        if self.on_close is not None:
            self.on_close()

    def feed(self, frame: dict[str, Any]) -> None:
        self.inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})


class _Rig:
    """One gateway on the test's loop: every collaborator the teardown tail touches."""

    def __init__(self) -> None:
        self.audit = _Audit()
        self.hub = GatewayHub()
        self.hub.shutting_down = True  # uvicorn cancels handlers only inside its own shutdown
        self.revocation = RevocationHub()
        self.sequencing = SequencingHub()
        self.sockets_before = _open_sockets()

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
        `reader()`, awaiting the next inbound frame, and registered everywhere."""
        handler = asyncio.create_task(self.endpoint(sock))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        assert (len(self.hub), len(self.registry._conns[USER]), len(self.sequencing)) == (1, 1, 1)
        assert len(self.revocation._sockets[SESSION]) == 1
        assert _open_sockets() == self.sockets_before + 1
        return handler

    def released(self, conn: Any) -> dict[str, bool]:
        """Per teardown step, whether it took effect; the keys are `gateway._step`'s names."""
        return {
            "hub": len(self.hub) == 0,
            "gauge": _open_sockets() == self.sockets_before,
            "sequencing": len(self.sequencing) == 0,
            "registry": not self.registry._conns,
            "revocation": not self.revocation._sockets,
            "lifecycle": conn.lifecycle.state is ConnState.CLOSED,
        }

    def assert_clean(self, conn: Any, reason: str, severity: str = "info") -> None:
        """Everything is as after a clean close, and the one close row says `reason`."""
        assert all(self.released(conn).values()), self.released(conn)
        assert not [t for t in asyncio.all_tasks() if t.get_name().endswith("-writer")]
        (rec,) = self.audit.records
        assert (rec["action"], rec["reason"], rec["severity"]) == (
            "ws.connection.closed",
            reason,
            severity,
        )
        assert (rec["actor_user_id"], rec["session_id"]) == (USER, SESSION)


async def _cancel(handler: asyncio.Task[None]) -> None:
    """uvicorn's graceful-timeout cancel: the handler must end cancelled, never swallow it."""
    handler.cancel(msg=_UVICORN_CANCEL)
    with pytest.raises(asyncio.CancelledError):
        await handler
    assert handler.cancelled()


def _awaiting(handler: asyncio.Task[None]) -> str:
    """The name of the coroutine `handler` is suspended in."""
    return str(getattr(getattr(handler.get_coro(), "cr_await", None), "__qualname__", ""))


async def test_cancelled_handler_still_runs_its_whole_teardown() -> None:
    """The reported bug: the cancel lands in `reader()`, as uvicorn's does."""
    rig, sock = _Rig(), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        await _cancel(handler)
    rig.assert_clean(conn, "shutdown")


async def test_a_cancel_while_the_writer_is_stuck_sending_still_runs_the_whole_teardown() -> None:
    rig, sock = _Rig(), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        sock.stall_sends = True
        sock.feed({"t": "ping", "id": "p"})  # its `pong` sticks in the writer's send
        await sock.stalled.wait()
        await _cancel(handler)
    rig.assert_clean(conn, "shutdown")


async def test_a_cancel_in_the_close_flush_wait_still_runs_the_whole_teardown() -> None:
    rig, sock = _Rig(), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        sock.stall_sends = True
        conn.close_with("slow_consumer")  # its `bye` sticks in the writer's send
        await sock.stalled.wait()
        sock.received.clear()
        sock.feed({"t": "ping", "id": "p"})  # the reader sees `closing` and returns
        await sock.received.wait()  # the handler ran on, unyielded, to the flush wait:
        assert _awaiting(handler) == "wait"  # `asyncio.wait({write_task}, ...)`
        await _cancel(handler)
    rig.assert_clean(conn, "slow_consumer", "warning")


async def test_a_cancel_while_the_handler_joins_a_stubborn_writer_is_honoured() -> None:
    """The cancel lands in `_join_writer`, with no cancellation in flight to carry it on."""
    rig, sock = _Rig(), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        sock.stall_sends = sock.stubborn = True
        sock.feed({"t": "ping", "id": "p"})  # its `pong` sticks in the writer's send
        await sock.stalled.wait()
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})  # the client leaves
        await sock.refused.wait()  # the handler cancelled the writer, which refused: it joins it
        await _cancel(handler)
    rig.assert_clean(conn, "client_closed")


@pytest.mark.parametrize(
    "real_cancel_first", [True, False], ids=["real_first", "writer_done_first"]
)
async def test_a_real_cancel_in_the_turn_the_writer_ends_is_not_absorbed(
    real_cancel_first: bool,
) -> None:
    """The writer's end cancels the read too (`_WRITER_DONE`); a real cancel racing it is the
    handler's own and must be honoured, whichever lands first. Real first, the read ends with the
    real cancel's message. Writer's done-callback first, one wakeup carries both cancels and the
    benign message: only `uncancel() == 0` tells the handler the real one is still pending."""
    rig, sock = _Rig(), _Socket()
    loop = asyncio.get_running_loop()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        if real_cancel_first:
            sock.on_close = lambda: loop.call_soon(handler.cancel, _UVICORN_CANCEL)
        else:  # one more loop turn: behind the writer's done-callback, queued as `close` returns
            sock.on_close = lambda: loop.call_soon(
                lambda: loop.call_soon(handler.cancel, _UVICORN_CANCEL)
            )
        conn.close_with("slow_consumer")  # the writer sends `bye`, closes, and ends
        with pytest.raises(asyncio.CancelledError):
            await handler
    assert handler.cancelled()
    rig.assert_clean(conn, "slow_consumer", "warning")


async def test_a_second_cancel_inside_the_close_audit_is_honoured_and_the_rest_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one loss: that write is abandoned, as `audit_close` documents (threat model WS-R04)."""
    rig, sock = _Rig(), _Socket()
    emitting = asyncio.Event()

    async def hung_emit(action: str, **kw: Any) -> None:
        emitting.set()
        await asyncio.Event().wait()  # a sink that never answers

    monkeypatch.setattr(rig.audit, "emit", hung_emit)
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        handler.cancel(msg=_UVICORN_CANCEL)  # the first, mid-read
        await emitting.wait()  # the tail now waits on the sink
        await _cancel(handler)  # the second lands inside the emit
    assert all(rig.released(conn).values()), rig.released(conn)  # even the lifecycle closed
    assert rig.audit.records == []  # only that write was lost


@pytest.mark.parametrize(
    "step", ["hub", "gauge", "sequencing", "registry", "revocation", "lifecycle"]
)
async def test_a_raising_teardown_step_never_skips_the_rest_or_replaces_the_cancel(
    step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("step failed")

    rig, sock = _Rig(), _Socket()
    try:
        async with asyncio.timeout(_DEADLINE_S):
            handler = await rig.authenticated(sock)
            (conn,) = rig.hub.of_user(USER)
            target = {
                "hub": (rig.hub, "discard"),
                "gauge": (cv_ws_connections_in_use, "dec"),
                "sequencing": (rig.sequencing, "unregister"),
                "registry": (rig.registry, "unregister"),
                "revocation": (rig.revocation, "unregister"),
                "lifecycle": (conn.lifecycle, "fire"),
            }[step]
            with monkeypatch.context() as patch, capture_logs() as logs:
                patch.setattr(*target, boom)
                await _cancel(handler)  # still ends cancelled, not with the step's RuntimeError
        undone = [name for name, ok in rig.released(conn).items() if not ok]
    finally:
        if step == "gauge":
            cv_ws_connections_in_use.set(rig.sockets_before)  # `dec` was broken: reset it
    assert undone == [step]  # only the raising step is left undone: every other one ran
    assert len(rig.audit.records) == 1  # the close audit between them ran too
    (failed,) = [e for e in logs if e["event"] == "ws teardown step failed"]
    assert (failed["step"], failed["connection_id"], bool(failed["exc_info"])) == (
        step,
        conn.connection_id,
        True,
    )


async def test_a_client_that_vanishes_mid_send_is_not_audited_as_shutdown() -> None:
    """During the shutdown window a send to a client that left ends the writer, and no
    `websocket.disconnect` reaches the reader: the writer's error carries the close code."""
    rig, sock = _Rig(), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.authenticated(sock)
        (conn,) = rig.hub.of_user(USER)
        sock.vanished = True
        sock.feed({"t": "ping", "id": "p"})  # the `pong` finds the client gone
        await handler  # the writer's end stops the read; no cancellation involved
    assert not handler.cancelled() and conn.disconnect_code == 1006
    rig.assert_clean(conn, "client_closed")
