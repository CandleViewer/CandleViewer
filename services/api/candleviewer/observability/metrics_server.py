"""Private-bind `/metrics` listener and runtime wiring (E04-T03 PR 2, US-OBS-001).

The listener serves the process-wide registry on `CV_METRICS_BIND` and refuses
to start on a public interface (`20-architecture.md` 13.1: an exposed
`/metrics` leaks order rates and trading activity). The loop-lag sampler,
cardinality check and fallback-snapshot ticker run alongside it.
"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Final

import structlog
import uvicorn
from fastapi import FastAPI, Response

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Metrics,
    generate_latest,
)
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.metrics_runtime import (
    GcPauseTimer,
    run_cardinality_check,
    run_fallback_snapshots,
    run_loop_lag_sampler,
)

#: Tailscale CGNAT range; private for our purposes though not `is_private`.
_CGNAT: Final = ipaddress.ip_network("100.64.0.0/10")


class MetricsBindError(ValueError):
    """`CV_METRICS_BIND` is malformed or names a non-private interface."""


def parse_private_bind(bind: str) -> tuple[str, int]:
    """Split `host:port`; reject anything that is not loopback/private/mesh."""
    host, sep, port_s = bind.rpartition(":")
    if not sep or not host or not port_s.isdigit() or not 0 < int(port_s) < 65536:
        raise MetricsBindError(f"CV_METRICS_BIND must be host:port, got {bind!r}")
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError as exc:
        raise MetricsBindError(f"CV_METRICS_BIND host must be an IP literal, got {host!r}") from exc
    if addr.is_unspecified or not (addr.is_loopback or addr.is_private or addr in _CGNAT):
        raise MetricsBindError(f"CV_METRICS_BIND {host!r} is not a private interface")
    return host.strip("[]"), int(port_s)


def make_metrics_app(registry: CollectorRegistry) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


def _task_ended(task: asyncio.Task[None]) -> None:
    """Logs a task that dies as it dies, not when `stop()` finds it (AGENTS.md section 5.2: no
    silent task). A cancelled task is `stop()`'s doing, not a failure."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        structlog.get_logger(__name__).error(
            "metrics_task_failed", task=task.get_name(), error=type(exc).__name__
        )


class MetricsRuntime:
    """Owns the private listener, the three background metric tasks and the GC pause timer."""

    def __init__(self, metrics: Metrics, bind: str) -> None:
        self._host, self._port = parse_private_bind(bind)
        self.metrics = metrics
        self._r0 = register_r0(metrics)
        self.gc_timer = GcPauseTimer(self._r0["cv_gc_pause_seconds"], self._r0["cv_gc_heap_blocks"])
        self._server: uvicorn.Server | None = None
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def address(self) -> tuple[str, int]:
        return self._host, self._port

    def start(self) -> None:
        config = uvicorn.Config(
            make_metrics_app(self.metrics.registry),
            host=self._host,
            port=self._port,
            log_config=None,
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        loop_lag = self._r0["event_loop_lag_seconds"]
        self._tasks = [
            spawn(self._server.serve(), name="metrics-listener"),
            spawn(run_loop_lag_sampler(loop_lag, self.metrics.clock), name="metrics-loop-lag"),
            spawn(run_cardinality_check(self.metrics), name="metrics-cardinality"),
            spawn(run_fallback_snapshots(self.metrics), name="metrics-fallback"),
        ]
        for task in self._tasks:
            task.add_done_callback(_task_ended)
        self.gc_timer.install()

    async def stop(self) -> None:
        """Ask the listener to exit, cancel the samplers, await all four: a dead task never keeps
        another from being awaited (its failure was logged when it happened), and a cancellation
        of the caller of `stop()` propagates."""
        self.gc_timer.remove()
        tasks, self._tasks = self._tasks, []
        if self._server is not None:
            self._server.should_exit = True
        self._server = None
        for task in tasks[1:]:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
