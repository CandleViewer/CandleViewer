"""#2565: uvicorn's drain is bounded, so the lifespan `shutdown` (the module teardown) always runs.

Without `timeout_graceful_shutdown`, `Server.shutdown` waits for every open request to finish. One
that never does keeps the lifespan `shutdown` from running until the container runtime SIGKILLs
the process. A real loopback server, one request that never answers, a drain timeout of 1 s.
No network beyond 127.0.0.1; the wait is bounded by `asyncio.timeout`.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from typing import Any

import uvicorn
from uvicorn.lifespan.off import LifespanOff

from candleviewer.server import PlannedShutdownServer, uvicorn_kwargs
from candleviewer.settings import Settings

_DEADLINE_S = 10.0


class _RecordingLifespan(LifespanOff):
    """`lifespan="off"`, recording the `shutdown` the server sends once the drain is over."""

    shutdown_sent = False

    async def shutdown(self) -> None:
        self.shutdown_sent = True


async def test_a_hung_request_cannot_keep_the_lifespan_shutdown_from_running() -> None:
    in_flight, cancelled = asyncio.Event(), asyncio.Event()

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        in_flight.set()
        try:
            await asyncio.Event().wait()  # never answers
        except asyncio.CancelledError:
            cancelled.set()
            raise

    kwargs = uvicorn_kwargs(Settings(uvicorn_drain_timeout_s=1))
    del kwargs["host"], kwargs["port"]  # the pre-bound loopback socket below
    config = uvicorn.Config(app, lifespan="off", log_level="critical", **kwargs)
    config.load()
    server = PlannedShutdownServer(config)
    lifespan = _RecordingLifespan(config)
    server.lifespan = lifespan  # as `Server.serve` does before `startup`
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    await server.startup(sockets=[sock])
    _, writer = await asyncio.open_connection("127.0.0.1", sock.getsockname()[1])
    try:
        async with asyncio.timeout(_DEADLINE_S):
            writer.write(b"GET / HTTP/1.1\r\nHost: test\r\n\r\n")
            await writer.drain()
            await in_flight.wait()
            await server.shutdown()  # unbounded without `timeout_graceful_shutdown`
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        sock.close()
    assert lifespan.shutdown_sent
    assert cancelled.is_set()  # uvicorn cancelled the request task at the drain timeout
