"""#2565: the drain floor on a real server (`candleviewer.settings.MIN_DRAIN_TIMEOUT_S`).

uvicorn cancels what is still running when its drain ends. A writer stalled on a peer that stopped
reading frees its handler only when uvicorn's own `connection.shutdown()` runs, after
`WsRuntime.stop()` stopped waiting for the flush. The handler then spends its own flush wait and
then the audit write, so a drain shorter than flush + audit cancels it mid-write: its
`ws.connection.closed` row is lost. The stalled peer is emulated as asyncio does while a buffer
cannot flush: `pause_writing()` and a `transport.close()` that does not complete.

The gateway's two bounds are scaled down (the floor is the sum of whatever the gateway spends), so
each case takes a couple of seconds. No network beyond 127.0.0.1; every wait is bounded. Real
timers: the margins that decide each case are set in `_WRITE_S` and are at least 0.45 s.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from websockets.asyncio.client import connect

from candleviewer import ws_wiring
from candleviewer.app import _LazyAuditEmitter, create_app
from candleviewer.server import PlannedShutdownServer, uvicorn_kwargs
from candleviewer.ws import gateway
from tests.unit.ws.test_app_wiring import _authenticate, _Kill, _settings
from tests.unit.ws.test_planned_shutdown_real_socket import _JSON, _ORIGIN, _open

_DEADLINE_S = 10.0
_BOUND_S = 1.0  # the scaled CLOSE_FLUSH_TIMEOUT_S and CLOSE_AUDIT_TIMEOUT_S
# A slow audit write, inside its bound. Counted from `connection.shutdown()`, the handler's row
# lands at flush + write, the audit bound ends at flush + audit, and uvicorn cuts at its 0.1 s
# settle plus the drain (the floor, or one bound below it). The row is 0.45 s inside the audit
# bound (`_BOUND_S - _WRITE_S`) and 0.45 s after the lower cut (`_WRITE_S - 0.1`), so a loop
# stall shorter than that cannot flip a case.
_WRITE_S = 0.55
_FLOOR_S = 2 * _BOUND_S  # flush + audit, as `MIN_DRAIN_TIMEOUT_S` is for the real bounds


@asynccontextmanager
async def _serve(drain_s: float) -> AsyncIterator[tuple[uvicorn.Server, str]]:
    """A real `PlannedShutdownServer` on `create_app` with a planned shutdown of no grace."""
    settings = _settings().model_copy(update={"ws_shutdown_grace_ms": 0})
    app = create_app(settings, snapshot_loader=_Kill().load, ws_authenticate=_authenticate)
    kw = uvicorn_kwargs(settings)
    del kw["host"], kw["port"]  # the pre-bound loopback socket below
    kw["timeout_graceful_shutdown"] = drain_s
    config = uvicorn.Config(app, lifespan="off", log_level="critical", **kw)
    config.load()
    server = PlannedShutdownServer(config)
    server.lifespan = config.lifespan_class(config)  # as `Server.serve` does before `startup`
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    await server.startup(sockets=[sock])
    try:
        yield server, f"ws://127.0.0.1:{sock.getsockname()[1]}/ws"
    finally:
        sock.close()


async def _close_rows_written(drain_s: float, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The close rows a planned shutdown writes for one stalled socket, with this drain."""
    for module, name in ((gateway, "CLOSE_FLUSH_TIMEOUT_S"), (ws_wiring, "CLOSE_FLUSH_TIMEOUT_S")):
        monkeypatch.setattr(module, name, _BOUND_S)
    monkeypatch.setattr(gateway, "CLOSE_AUDIT_TIMEOUT_S", _BOUND_S)
    rows: list[Any] = []

    async def slow_emit(self: _LazyAuditEmitter, action: str, **kw: Any) -> None:
        if action == "ws.connection.closed":
            await asyncio.sleep(_WRITE_S)
            rows.append(kw)

    monkeypatch.setattr(_LazyAuditEmitter, "emit", slow_emit)
    async with asyncio.timeout(_DEADLINE_S), _serve(drain_s) as (server, url):
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN, close_timeout=0.1) as ws:
            await _open(ws)
            (conn,) = server.server_state.connections
            proto: Any = conn  # uvicorn's `Protocols` union: not every member has a transport
            proto.pause_writing()  # the peer stopped reading
            # `close()` cannot flush to that peer, so the connection is not lost either.
            proto.transport.close = lambda: None
            await server.shutdown()
    return rows


async def test_a_drain_at_the_floor_keeps_the_close_row_of_a_stalled_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert len(await _close_rows_written(_FLOOR_S, monkeypatch)) == 1


async def test_a_drain_below_the_floor_cancels_the_close_row_of_a_stalled_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await _close_rows_written(_FLOOR_S - _BOUND_S, monkeypatch) == []
