"""Synthetic feed generator (M6 `ingestion`, E02-T12).

Reads a small JSONL sample from `packages/fixtures/raw/` and replays it as
normalised `Trade`/`Ticker` events (`candleviewer.exchange.base`) onto a
bounded queue at a configurable rate, so engineers and CI can exercise the
ingestion path without exchange credentials (`CV_FEED=synthetic`,
`20-architecture.md` Sec.7.3).

TEST DOUBLE — NOT REAL INGESTION (Semgrep-visible marker below). This
generator has no exchange knowledge (C-2.2) and does not reconstruct an order
book (that is E08/M7); it must never grow into a second ingestion
implementation. E08 owns the real exchange WS/REST adapter.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from candleviewer.exchange.base import Ticker, Trade
from candleviewer.ingestion.errors import IngestionError
from candleviewer.observability.context import spawn
from candleviewer.observability.latency import StageRecorder, StageStamps
from candleviewer.observability.metrics import CollectorRegistry, Counter

# cv-semgrep: synthetic-feed-test-double — this module is a bounded test
# double for local/CI development, never the live exchange ingestion path.
SYNTHETIC_FEED_MARKER = "cv-synthetic-feed-test-double"

_DEFAULT_QUEUE_MAXSIZE = 256


class SyntheticFeedError(IngestionError):
    """Raised when the synthetic feed sample cannot be read or is malformed."""


def _parse_record(raw: dict[str, Any]) -> Trade | Ticker:
    kind = raw.get("kind")
    if kind == "trade":
        return Trade.model_validate(raw["data"])
    if kind == "ticker":
        return Ticker.model_validate(raw["data"])
    raise SyntheticFeedError(f"unknown synthetic feed record kind: {kind!r}")


def _checkout_root(module: Path) -> Path | None:
    """Monorepo layout: services/api/candleviewer/ingestion/synthetic_feed.py ->
    repo root is four `.parent` hops up. Used only as a *fallback* resolution
    for the documented default `CV_FEED_SAMPLE_PATH` when the process's cwd is
    `services/api` (the `AGENTS.md` §4 "Run API locally" cwd) rather than the
    repo root (the Docker image's `/app`, where the relative path already
    resolves) — an absolute `CV_FEED_SAMPLE_PATH` always wins outright.

    `None` outside a checkout (#2555): the image installs this module at
    `/app/candleviewer/ingestion/`, which has only four parents, and indexing
    `parents[4]` at import raised `IndexError`, so `candleviewer.app` could not load.
    """
    parents = module.resolve().parents
    return parents[4] if len(parents) > 4 else None


def _resolve_sample_path(path: Path) -> Path:
    root = _checkout_root(Path(__file__))
    if path.is_absolute() or path.exists() or root is None:
        return path
    fallback = root / path
    return fallback if fallback.exists() else path


def load_sample_records(path: Path) -> list[Trade | Ticker]:
    """Read and validate every JSONL line in `path` into a normalised event.

    Raises `SyntheticFeedError` (never a bare `json.JSONDecodeError`/`KeyError`)
    on a malformed sample, so a bad fixture fails fast with a clear message.
    """
    path = _resolve_sample_path(path)
    if not path.exists():
        raise SyntheticFeedError(f"synthetic feed sample not found: {path}")
    records: list[Trade | Ticker] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SyntheticFeedError(
                    f"{path}:{line_no}: invalid JSON in synthetic feed sample"
                ) from exc
            try:
                records.append(_parse_record(raw))
            except (KeyError, ValueError) as exc:
                raise SyntheticFeedError(
                    f"{path}:{line_no}: malformed synthetic feed record"
                ) from exc
    if not records:
        raise SyntheticFeedError(f"synthetic feed sample is empty: {path}")
    return records


class SyntheticFeedMetrics:
    """Prometheus counters the generator increments on every publish.

    Same counter names the real exchange ingestion path (E08) will use, so
    dashboards built against synthetic data (E04) keep working once real
    ingestion lands (see ticket "Observability" note).
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self.published_total = Counter(
            "cv_bus_publish_total",
            "Normalised domain events published to the bus, by event type.",
            labelnames=("event_type",),
            registry=registry,
        )
        self.dropped_total = Counter(
            "cv_bus_publish_dropped_total",
            "Normalised domain events dropped by the bounded-queue overflow policy.",
            labelnames=("event_type",),
            registry=registry,
        )


class SyntheticFeedGenerator:
    """Replays normalised events from a sample file at a configurable rate.

    Publishes onto a caller-owned `asyncio.Queue` (bounded — M5 `bus`
    conventions). On overflow it *drops* the event rather than blocking or
    growing unboundedly (documented overflow policy, C-2.18): the synthetic
    feed's purpose is to exercise consumers under a known, capped memory
    footprint, never to guarantee delivery of every synthetic tick.
    """

    def __init__(
        self,
        records: list[Trade | Ticker],
        queue: asyncio.Queue[Trade | Ticker],
        metrics: SyntheticFeedMetrics,
        rate_hz: float,
        *,
        rng: random.Random | None = None,
        latency: StageRecorder | None = None,
        clock_offset_ms: Callable[[], int | None] = lambda: 0,
        now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        if rate_hz <= 0:
            raise SyntheticFeedError("synthetic feed rate_hz must be > 0")
        self._records = records
        self._queue = queue
        self._metrics = metrics
        self._rate_hz = rate_hz
        self._rng = rng or random.Random()  # noqa: S311 - jitter timing only, never security
        self._task: asyncio.Task[None] | None = None
        # E04-T06: per-stage latency on the real publish path. The synthetic
        # source has no exchange clock, so its offset provider defaults to 0
        # (the live feed passes ClockGuard's offset instead).
        self._latency = latency
        self._clock_offset_ms = clock_offset_ms
        self._now_ms = now_ms

    def _interval_s(self) -> float:
        """Period between publishes, with +/-20% jitter (never exactly periodic)."""
        base = 1.0 / self._rate_hz
        jitter = self._rng.uniform(-0.2, 0.2)
        return max(base * (1.0 + jitter), 0.001)

    async def _publish_one(self, record: Trade | Ticker) -> None:
        event_type = type(record).__name__.lower()
        t_recv = self._now_ms()
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self._metrics.dropped_total.labels(event_type=event_type).inc()
            return
        self._metrics.published_total.labels(event_type=event_type).inc()
        if self._latency is not None:
            # Synthetic events are exchange-stamped on receipt and have no
            # parse/derive work; fan-out (queue hand-off) is the real cost.
            self._latency.on_event(
                StageStamps(t_recv, t_recv, t_recv, t_recv, self._now_ms()),
                self._clock_offset_ms(),
            )

    async def _run(self) -> None:
        index = 0
        count = len(self._records)
        while True:
            record = self._records[index % count]
            await self._publish_one(record)
            index += 1
            await asyncio.sleep(self._interval_s())

    async def start(self) -> None:
        """Start the background replay loop. Idempotent."""
        if self._task is None or self._task.done():
            self._task = spawn(self._run(), name="synthetic-feed")

    async def stop(self) -> None:
        """Cancel the replay loop and await its (honoured) cancellation."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None


async def iter_sample(path: Path) -> AsyncIterator[Trade | Ticker]:
    """Async-iterate the sample once, for tests/inspection without a queue."""
    for record in load_sample_records(path):
        yield record
