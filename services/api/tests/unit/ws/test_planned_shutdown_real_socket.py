"""#2546: the §9.4 planned shutdown under a real uvicorn server. uvicorn's `Server.shutdown`
fails every open WebSocket with `1012` before the lifespan teardown runs, so
`candleviewer.server` runs `WsRuntime.stop()` first (`PlannedShutdownServer`). The app is
`create_app`'s, as in `test_app_wiring.py`, on an ephemeral loopback port. No network beyond
127.0.0.1; every wait is bounded by `asyncio.timeout`."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from structlog.testing import capture_logs
from uvicorn.config import STARTUP_FAILURE
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin, Subprotocol

from candleviewer import server as entry
from candleviewer.app import _LazyAuditEmitter, create_app
from candleviewer.server import PlannedShutdownServer, uvicorn_kwargs
from candleviewer.ws_wiring import WsRuntime
from tests.unit.ws.test_app_wiring import JSON, ORIGIN, _authenticate, _Kill, _settings

_DEADLINE_S = 10.0
#: The §9.4 start line: the count of open connections and the hint uvicorn gives its own drain.
PLANNED = "planned ws shutdown (CTRL+C again to force quit)"
_ORIGIN = Origin(ORIGIN)
_JSON = [Subprotocol(p) for p in JSON]


@asynccontextmanager
async def _serve(
    server_class: type[uvicorn.Server], grace_ms: int = 0
) -> AsyncIterator[tuple[uvicorn.Server, str]]:
    """A real uvicorn server of `server_class` running `create_app`, and its `/ws` URL."""
    settings = _settings().model_copy(update={"ws_shutdown_grace_ms": grace_ms})
    app = create_app(settings, snapshot_loader=_Kill().load, ws_authenticate=_authenticate)
    kw = uvicorn_kwargs()
    del kw["host"], kw["port"]  # the pre-bound loopback socket below
    config = uvicorn.Config(app, lifespan="off", log_level="warning", **kw)
    config.load()
    server = server_class(config)
    server.lifespan = config.lifespan_class(config)  # as `Server.serve` does before `startup`
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    await server.startup(sockets=[sock])
    try:
        yield server, f"ws://127.0.0.1:{sock.getsockname()[1]}/ws"
    finally:
        if any(s.is_serving() for s in server.servers):  # the test failed before its shutdown
            await server.shutdown()
        sock.close()


@pytest.fixture
def close_rows(monkeypatch: pytest.MonkeyPatch) -> asyncio.Queue[dict[str, Any]]:
    """The `ws.connection.closed` rows the app's gateway writes, in order."""
    rows: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def emit(self: _LazyAuditEmitter, action: str, **kw: Any) -> None:
        if action == "ws.connection.closed":
            rows.put_nowait(kw)

    monkeypatch.setattr(_LazyAuditEmitter, "emit", emit)
    return rows


def _planned(logs: list[Any]) -> list[Any]:
    return [e for e in logs if "planned ws" in e["event"]]


async def _open(ws: ClientConnection) -> None:
    await ws.send(json.dumps({"t": "hello", "id": "h", "p": {"clock_ms": 1}}))
    assert json.loads(await ws.recv())["t"] == "welcome"
    await ws.send(json.dumps({"t": "auth", "id": "a", "p": {"access_token": "tok"}}))
    assert json.loads(await ws.recv())["t"] == "auth_ok"


async def _until_closed(ws: ClientConnection) -> tuple[list[dict[str, Any]], int | None]:
    """Every frame the client receives until the server closes the socket, and the close code."""
    frames: list[dict[str, Any]] = []
    try:
        while True:
            frames.append(json.loads(await ws.recv()))
    except ConnectionClosed as exc:
        return frames, exc.rcvd.code if exc.rcvd is not None else None


async def test_server_shutdown_sends_the_planned_shutdown_before_closing() -> None:
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S), _serve(PlannedShutdownServer) as (server, url):
            async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
                await _open(ws)
                stopping = asyncio.create_task(server.shutdown())
                frames, code = await _until_closed(ws)
                await stopping
    notice, bye = frames
    assert (notice["ch"], notice["p"]["kind"]) == ("system", "shutdown_notice")
    assert (bye["t"], bye["p"]["reason"], bye["p"]["retry_after_ms"]) == ("bye", "shutdown", 7000)
    assert code == 1001
    # one info line, with the open connections: neither a failure nor a cut-short warning
    assert [(e["log_level"], e["event"], e["connections"]) for e in _planned(logs)] == [
        ("info", PLANNED, 1)
    ]


async def test_plain_uvicorn_shutdown_closes_1012_with_no_notice() -> None:
    """Why `PlannedShutdownServer` exists: uvicorn alone gives the client a bare `1012`."""
    async with asyncio.timeout(_DEADLINE_S), _serve(uvicorn.Server) as (server, url):
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
            await _open(ws)
            stopping = asyncio.create_task(server.shutdown())
            frames, code = await _until_closed(ws)
            await stopping
    assert (frames, code) == ([], 1012)


async def test_no_connection_opens_during_the_planned_shutdown() -> None:
    """Listeners close before the notice, so a client cannot connect during the grace and
    then get a bare `1012` when uvicorn's own shutdown follows."""
    async with asyncio.timeout(_DEADLINE_S), _serve(PlannedShutdownServer, 300) as (server, url):
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
            await _open(ws)
            stopping = asyncio.create_task(server.shutdown())
            assert json.loads(await ws.recv())["p"]["kind"] == "shutdown_notice"
            with pytest.raises(OSError):
                await connect(url, subprotocols=_JSON, origin=_ORIGIN)
            _, code = await _until_closed(ws)
            await stopping
    assert code == 1001


async def test_a_second_ctrl_c_cuts_the_grace_short(close_rows: asyncio.Queue[Any]) -> None:
    """`force_exit` during a 60 s grace ends the planned shutdown within uvicorn's 0.1 s poll;
    the client got the notice, then uvicorn's `1012`, and the server says so in its log."""
    async with asyncio.timeout(_DEADLINE_S), _serve(PlannedShutdownServer, 60_000) as (server, url):
        with capture_logs() as logs:
            async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
                await _open(ws)
                stopping = asyncio.create_task(server.shutdown())
                assert json.loads(await ws.recv())["p"]["kind"] == "shutdown_notice"
                server.force_exit = True
                frames, code = await _until_closed(ws)
                await stopping
                row = await close_rows.get()
    assert (frames, code) == ([], 1012)
    assert row["reason"] == "shutdown"  # uvicorn's own 1012, from a server that was shutting down
    started, cut = _planned(logs)
    assert (started["event"], cut["log_level"], cut["event"]) == (
        PLANNED,
        "warning",
        "planned ws shutdown cut short",
    )
    assert (cut["reason"], cut["lifespan_teardown"]) == ("force_exit", "skipped")


async def test_a_forced_exit_before_the_grace_still_marks_the_server_as_shutting_down(
    close_rows: asyncio.Queue[Any],
) -> None:
    """The planned shutdown never starts, yet uvicorn's `1012` is still the server's own."""
    async with asyncio.timeout(_DEADLINE_S), _serve(PlannedShutdownServer, 60_000) as (server, url):
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
            await _open(ws)
            server.force_exit = True
            stopping = asyncio.create_task(server.shutdown())
            frames, code = await _until_closed(ws)
            await stopping
            row = await close_rows.get()
    assert (frames, code) == ([], 1012)  # no notice, no bye
    assert row["reason"] == "shutdown"


async def test_a_failing_planned_shutdown_still_runs_uvicorns(
    monkeypatch: pytest.MonkeyPatch, close_rows: asyncio.Queue[Any]
) -> None:
    async def boom(self: WsRuntime) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(WsRuntime, "stop", boom)
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S), _serve(PlannedShutdownServer) as (server, url):
            async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
                await _open(ws)
                stopping = asyncio.create_task(server.shutdown())
                frames, code = await _until_closed(ws)
                await stopping
                row = await close_rows.get()
    assert (frames, code) == ([], 1012)  # uvicorn's own shutdown still ran
    assert row["reason"] == "shutdown"  # the server was shutting down, though its stop() failed
    started, failed = _planned(logs)
    assert [(e["log_level"], e["event"]) for e in (started, failed)] == [
        ("info", PLANNED),
        ("error", "planned ws shutdown failed"),
    ]
    assert failed["error"] == "RuntimeError"
    assert isinstance(failed["exc_info"], RuntimeError) and str(failed["exc_info"]) == "boom"


async def test_a_1012_the_client_sends_is_a_client_close(close_rows: asyncio.Queue[Any]) -> None:
    """uvicorn forwards a client's own `1012` as it does its own: while the server runs, the
    close audit must say the client closed."""
    async with asyncio.timeout(_DEADLINE_S), _serve(PlannedShutdownServer) as (_, url):
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
            await _open(ws)
            await ws.close(code=1012)
        row = await close_rows.get()
    assert row["reason"] == "client_closed"


def test_main_runs_the_planned_shutdown_server(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[uvicorn.Server] = []

    def run(self: uvicorn.Server, sockets: Any = None) -> None:
        ran.append(self)
        self.started = True
        raise KeyboardInterrupt  # Ctrl+C ends `run` as it does `uvicorn.run`: a clean exit

    monkeypatch.setattr(PlannedShutdownServer, "run", run)
    entry.main([])
    (server,) = ran
    assert isinstance(server, PlannedShutdownServer)
    assert (server.config.app, server.config.ws_max_size) == (
        entry.APP,
        uvicorn_kwargs()["ws_max_size"],
    )


def test_main_exits_with_startup_failure_when_the_server_never_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PlannedShutdownServer, "run", lambda self, sockets=None: None)
    with pytest.raises(SystemExit) as exc:
        entry.main([])
    assert exc.value.code == STARTUP_FAILURE


def test_main_reload_keeps_uvicorns_reloader(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    entry.main(["--reload"])
    ((app, kw),) = calls
    assert (app, kw["reload"]) == (entry.APP, True)
