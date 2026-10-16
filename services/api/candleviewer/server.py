"""Process entrypoint: `python -m candleviewer.server [--reload]`.

Builds the uvicorn configuration from `candleviewer.ws.limits` and
`candleviewer.ws.lifecycle` so server-level WebSocket limits cannot drift from
the protocol (`23-ws-protocol.md` §16.2). uvicorn's proxy-header handling is off
(#2275): `MeshOnlyMiddleware` is the only reader of forwarded headers. The server runs the
§9.4 planned WebSocket shutdown before uvicorn's own (`PlannedShutdownServer`).
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
from collections.abc import Sequence
from typing import Any

import structlog
import uvicorn
from uvicorn.config import STARTUP_FAILURE

from candleviewer.observability.context import spawn
from candleviewer.settings import Settings, get_settings
from candleviewer.ws import limits
from candleviewer.ws.lifecycle import HEARTBEAT_INTERVAL_S, HEARTBEAT_TIMEOUT_S

APP = "candleviewer.main:app"


def uvicorn_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    """Keyword arguments for `uvicorn.run`/`uvicorn.Config`.

    Host/port come from `Settings` (`CV_BIND_HOST` is validated against the wildcard
    address, C-12.9); WS limits from `ws/limits.py` (single source). `timeout_graceful_shutdown`
    bounds uvicorn's drain of open connections and tasks (#2565): past it uvicorn cancels what is
    left and still sends the lifespan `shutdown`, so the module teardown always runs. It is one
    term of the stop budget `Settings` checks (`api_stop_budget_s`), and `Settings` refuses a drain
    shorter than one WS close can need (`MIN_DRAIN_TIMEOUT_S`: the flush plus the audit write), so
    a close within its bounds attempts its `ws.connection.closed` row until its own bound before
    anything is cancelled.

    `proxy_headers=False` (#2275): uvicorn never rewrites `scope["client"]` or the scheme
    from forwarded headers, whatever `FORWARDED_ALLOW_IPS` says, so `scope["client"]` is the
    TCP peer. The only forwarded-header setting is MeshOnly's trusted proxy
    (`CV_MESH_TRUSTED_PROXY_HEADER` and `CV_MESH_TRUSTED_PROXY_ADDRESS`).
    """
    cfg = settings if settings is not None else get_settings()
    return {
        "host": cfg.bind_host,
        "port": cfg.bind_port,
        "proxy_headers": False,
        "ws_max_size": limits.SERVER_WS_MAX_SIZE,
        "ws_per_message_deflate": limits.SERVER_WS_PER_MESSAGE_DEFLATE,
        "ws_max_queue": limits.SERVER_WS_MAX_QUEUE,
        "ws_ping_interval": HEARTBEAT_INTERVAL_S,
        "ws_ping_timeout": HEARTBEAT_TIMEOUT_S,
        "limit_concurrency": limits.SERVER_LIMIT_CONCURRENCY,
        "timeout_graceful_shutdown": cfg.uvicorn_drain_timeout_s,
    }


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class PlannedShutdownServer(uvicorn.Server):
    """uvicorn's `Server.shutdown` fails every open WebSocket with `1012` before it sends the
    lifespan `shutdown` event (#2546), so the §9.4 planned shutdown in the lifespan teardown
    would reach no client. This server runs it first: it stops accepting connections, runs the
    app's `WsRuntime.stop()` (`shutdown_notice`, grace, `bye` + `1001`), then uvicorn's own
    shutdown. The lifespan's later `stop()` then only stops the sweeper. It first marks the
    gateway's hub as shutting down, so a `1012` that reaches a socket afterwards is attributed to
    the server (`closed_reason`) however the planned shutdown ends: done, cut short, never
    started (a second Ctrl+C first) or failed. The sequence (grace, close flush, uvicorn's bounded
    drain, module teardown) must fit the container's stop budget; `Settings` refuses a config that
    does not (#2565)."""

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        for server in self.servers:
            server.close()  # a connection opened during the grace would miss the notice
        runtime = _ws_runtime(self.config.loaded_app)
        if runtime is not None:
            runtime.hub.shutting_down = True
            if self.force_exit:
                _log_cut_short(started=False)  # a second Ctrl+C within uvicorn's 0.1 s tick
            else:
                await self._planned(runtime)
        await super().shutdown(sockets)

    async def _planned(self, runtime: Any) -> None:
        """`runtime.stop()`, cut short by a second Ctrl+C (`force_exit`), which uvicorn's own
        drain also polls every 0.1 s. A failure is logged and never skips uvicorn's shutdown or
        the module teardown after it. Cutting it short is logged too (`_log_cut_short`). The
        start line counts the open connections, and the ones that get the notice."""
        logger().info(
            "planned ws shutdown (CTRL+C again to force quit)",
            open_connections=len(runtime.hub),
            notified_connections=runtime.hub.authenticated_count(),
        )
        task = spawn(runtime.stop(), name="ws-planned-shutdown")
        try:
            while not task.done() and not self.force_exit:
                await asyncio.wait({task}, timeout=0.1)
        finally:
            task.cancel()  # a no-op once done; else force_exit, or this coroutine was cancelled
        outcome: list[object] = await asyncio.gather(task, return_exceptions=True)
        failure = outcome[0]
        if isinstance(failure, Exception):
            logger().error(
                "planned ws shutdown failed", error=type(failure).__name__, exc_info=failure
            )
        elif task.cancelled():
            _log_cut_short(started=True)


def _log_cut_short(*, started: bool) -> None:
    """A second Ctrl+C ended the planned shutdown (`started`: after it began, else before). uvicorn
    then skips the lifespan teardown too, and the clients get its bare `1012`."""
    logger().warning(
        "planned ws shutdown cut short",
        reason="force_exit",
        lifespan_teardown="skipped",
        started=started,
    )


def _ws_runtime(app: Any) -> Any:
    """`app.state.ws_runtime`, under uvicorn's own wrappers (`ProxyHeadersMiddleware`, ...)."""
    for _ in range(8):
        runtime = getattr(getattr(app, "state", None), "ws_runtime", None)
        if runtime is not None or app is None:
            return runtime
        app = getattr(app, "app", None)
    return None


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [a for a in args if a != "--reload"]
    if unknown:
        raise SystemExit(f"unsupported arguments: {unknown}")
    if "--reload" in args:  # dev only: uvicorn's reloader runs a plain server per reload
        uvicorn.run(APP, reload=True, **uvicorn_kwargs())
        return
    server = PlannedShutdownServer(uvicorn.Config(APP, **uvicorn_kwargs()))
    with contextlib.suppress(KeyboardInterrupt):
        server.run()
    if not server.started:
        raise SystemExit(STARTUP_FAILURE)  # as `uvicorn.run` exits


if __name__ == "__main__":
    main()
