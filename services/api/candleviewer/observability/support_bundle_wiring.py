"""Real collectors + metrics for the support bundle (E04-S02).

Logs come from an in-memory ring buffer (stdout is the only log sink), redacted as on stdout: by
its own `RedactionFilter`, and a stdlib record's rendered message once more (#415); the bundle
scan is still the fail-closed gate.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from prometheus_client import generate_latest

from candleviewer.observability.health_probes import HealthRegistry
from candleviewer.observability.logging import RedactionFilter
from candleviewer.observability.metrics import CollectorRegistry, Metrics
from candleviewer.observability.redaction import _redact_str_value
from candleviewer.observability.support_bundle import (
    BundleJob,
    BundleSources,
    SupportBundleService,
)

_RING_MAX = 20000


class LogRingBuffer(logging.Handler):
    """Bounded newest-last buffer of redacted, formatted log lines.

    A stdlib record's message is rendered here, after the filter ran (an argument that is not a
    `str`, such as a websockets frame, is turned into text only now), so the rendered message
    passes the same redaction as stdout's `event` (#415). A structlog record's message is its
    event dict, which the processor chain has redacted already, as on stdout. Each record is one
    line, a line break written as `\\n`, as in its traceback (#415).
    """

    def __init__(self, maxlen: int = _RING_MAX) -> None:
        super().__init__()
        self.addFilter(RedactionFilter())
        self._buf: deque[tuple[float, str]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if not (isinstance(record.msg, dict) and hasattr(record, "_logger")):
                message = _redact_str_value(message)
            line = f"{record.levelname} {record.name} {message}"
            # a stdlib record's traceback and stack, as `RedactionFilter` stored them; one line
            if record.exc_text:
                line += f" exception={record.exc_text!r}"
            if record.stack_info:
                line += f" stack={record.stack_info!r}"
            # one physical line: the bundle's logs.ndjson keeps a record per line, and its scan
            # reads a label and its value on two lines of a message together (#415)
            self._buf.append((record.created, line.replace("\r", "\\r").replace("\n", "\\n")))
        except Exception:
            return

    def window(self, start: datetime, end: datetime) -> list[str]:
        lo, hi = start.timestamp(), end.timestamp()
        return [line for ts, line in reversed(self._buf) if lo <= ts <= hi]  # newest-first


class _Service(SupportBundleService):
    """Captures the running loop so thread-side collectors can await Postgres."""

    def __init__(self, *a: Any, on_loop: Callable[[asyncio.AbstractEventLoop], None], **k: Any):
        super().__init__(*a, **k)
        self._on_loop = on_loop

    def start(self, start: datetime, end: datetime, on_complete: Any = None) -> BundleJob:
        self._on_loop(asyncio.get_running_loop())
        return super().start(start, end, on_complete)


def build_support_bundle_service(
    *,
    registry: CollectorRegistry,
    metrics: Metrics,
    health: HealthRegistry,
    events_query: Callable[[datetime, datetime], Coroutine[Any, Any, list[dict[str, Any]]]] | None,
    config: Mapping[str, Any],
    build_info: Mapping[str, Any],
    out_dir: Path,
) -> SupportBundleService:
    ring = LogRingBuffer()
    logging.getLogger().addHandler(ring)
    loop_ref: list[asyncio.AbstractEventLoop] = []
    gens = metrics.get("support_bundle_generations_total")
    dur = metrics.get("support_bundle_duration_seconds").child()
    size = metrics.get("support_bundle_bytes").child()

    def health_report() -> Mapping[str, Any]:
        snap = health.snapshot()
        if snap is None:
            return {"overall": "unknown", "components": []}
        return {
            "overall": snap.overall.value,
            "taken_at": snap.taken_at.isoformat(),
            "components": [
                {"name": c.name, "state": c.state.value, "detail": c.detail}
                for c in snap.components
            ],
        }

    def alerts() -> list[dict[str, Any]]:
        snap = health.snapshot()
        if snap is None:
            return []
        return [
            {"component": c.name, "state": c.state.value, "detail": c.detail}
            for c in snap.components
            if c.state.value not in ("healthy", "not_deployed")
        ]

    def events(start: datetime, end: datetime) -> list[dict[str, Any]]:
        if events_query is None or not loop_ref:
            return []
        fut = asyncio.run_coroutine_threadsafe(events_query(start, end), loop_ref[0])
        return fut.result(timeout=30)

    def on_event(result: str, data: dict[str, Any]) -> None:
        gens.labels(result).inc()
        if result == "ok":
            dur.observe(float(data.get("seconds", 0.0)))
            size.observe(float(data.get("size_bytes") or 0))

    sources = BundleSources(
        logs=ring.window,
        metrics=lambda: generate_latest(registry).decode("utf-8"),
        health=health_report,
        system_events=events,
        alerts=alerts,
        build_info=lambda: dict(build_info),
        config=lambda: dict(config),
    )
    return _Service(
        sources,
        out_dir,
        on_event=on_event,
        on_loop=lambda lp: loop_ref.__setitem__(slice(None), [lp]),
    )
