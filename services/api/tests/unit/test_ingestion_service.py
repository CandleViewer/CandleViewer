"""Tests for the M6 `ingestion` service lifecycle with `CV_FEED=synthetic`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
import structlog

from candleviewer.app import build_app_context
from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.service import IngestionService
from candleviewer.settings import FeedMode, Settings


async def test_ingestion_start_synthetic_populates_bounded_queue() -> None:
    settings = Settings(feed=FeedMode.SYNTHETIC, feed_rate_hz=100.0)
    ctx = build_app_context(settings)
    service = IngestionService()
    await service.start(ctx)
    try:
        assert service.queue is not None
        event = await asyncio.wait_for(service.queue.get(), timeout=1.0)
        assert event is not None
    finally:
        await service.stop(grace_s=1.0)


async def test_ingestion_health_reports_ok_once_started() -> None:
    settings = Settings(feed=FeedMode.SYNTHETIC, feed_rate_hz=100.0)
    ctx = build_app_context(settings)
    service = IngestionService()
    assert service.health().status.value == "stopped"
    await service.start(ctx)
    try:
        assert service.health().status.value == "ok"
    finally:
        await service.stop(grace_s=1.0)


async def test_ingestion_stop_is_clean_and_bounded() -> None:
    settings = Settings(feed=FeedMode.SYNTHETIC, feed_rate_hz=100.0)
    ctx = build_app_context(settings)
    service = IngestionService()
    await service.start(ctx)
    await service.stop(grace_s=1.0)
    assert service.health().status.value == "stopped"


async def test_ingestion_missing_sample_raises_clear_error() -> None:
    settings = Settings(
        feed=FeedMode.SYNTHETIC, feed_sample_path="packages/fixtures/raw/does-not-exist.jsonl"
    )
    ctx = build_app_context(settings)
    service = IngestionService()
    with pytest.raises(Exception, match="not found"):
        await service.start(ctx)


async def test_ingestion_stop_stops_the_catalogue_before_closing_its_resources() -> None:
    """#2561: the catalogue scheduler uses the REST client and pool that the closers release."""
    order: list[str] = []

    class _Catalogue:
        async def stop(self, grace_s: float) -> None:
            order.append("catalogue")

    async def close() -> None:
        order.append("closer")

    service = IngestionService()
    service.attach_instruments(_Catalogue())  # type: ignore[arg-type]  # only `stop` is used
    service.attach_closer(close)
    await service.stop(grace_s=1.0)
    assert order == ["catalogue", "closer"]


#: With a live feed, all `IngestionService.start(ctx)` reads is `ctx.settings.feed`.
_LIVE_CTX: Any = SimpleNamespace(settings=SimpleNamespace(feed=FeedMode.LIVE))


async def test_ingestion_start_starts_an_attached_catalogue() -> None:
    """#2599: `start(ctx)` hooks the #1913 delist teardown into the attached catalogue's swaps
    and starts it; `stop()` stops it."""
    calls: list[str] = []

    class _Catalogue:
        def add_listener(self, listener: Callable[[], Awaitable[None]]) -> None:
            calls.append(f"listener:{getattr(listener, '__name__', '')}")

        async def start(self) -> None:
            calls.append("start")

        async def stop(self, grace_s: float) -> None:
            calls.append("stop")

    service = IngestionService()
    service.attach_instruments(_Catalogue())  # type: ignore[arg-type]  # the lifecycle surface only
    await service.start(_LIVE_CTX)
    try:
        assert calls == ["listener:prune_unlisted", "start"]
    finally:
        await service.stop(grace_s=1.0)
    assert calls[-1] == "stop"


async def test_ingestion_stop_closes_its_resources_even_when_a_stop_step_fails() -> None:
    """#2599: the closers (REST client, pool) run in a `finally`: a failing stop step must not
    leak them."""
    closed: list[str] = []

    class _Catalogue:
        async def stop(self, grace_s: float) -> None:
            raise RuntimeError("stop failed")

    async def close() -> None:
        closed.append("closer")

    service = IngestionService()
    service.attach_instruments(_Catalogue())  # type: ignore[arg-type]  # only `stop` is used
    service.attach_closer(close)
    with pytest.raises(RuntimeError, match="stop failed"):
        await service.stop(grace_s=1.0)
    assert closed == ["closer"]


async def test_ingestion_stop_runs_every_closer_when_one_closer_fails() -> None:
    """#2599 review: the release is best effort per resource: a closer that raises (a torn
    transport) is logged, the later closers still run, and the module reports stopped."""
    closed: list[str] = []

    async def torn() -> None:
        closed.append("rest")
        raise OSError("transport torn")

    async def pool() -> None:
        closed.append("pool")

    service = IngestionService()
    service.attach_closer(torn)
    service.attach_closer(pool)
    await service.start(_LIVE_CTX)
    with structlog.testing.capture_logs() as logs:
        await service.stop(grace_s=1.0)
    assert closed == ["rest", "pool"]
    assert service.health().status.value == "stopped"
    assert [e["event"] for e in logs if e["log_level"] == "error"] == ["ingestion_release_failed"]


async def test_ingestion_stop_keeps_the_stop_step_error_when_a_closer_also_fails() -> None:
    """#2599 review: a closer failing during the release never replaces the stop step's own
    error, and never skips the closers after it."""
    closed: list[str] = []

    class _Catalogue:
        async def stop(self, grace_s: float) -> None:
            raise RuntimeError("stop failed")

    async def torn() -> None:
        raise OSError("transport torn")

    async def pool() -> None:
        closed.append("pool")

    service = IngestionService()
    service.attach_instruments(_Catalogue())  # type: ignore[arg-type]  # only `stop` is used
    service.attach_closer(torn)
    service.attach_closer(pool)
    with pytest.raises(RuntimeError, match="stop failed"):
        await service.stop(grace_s=1.0)
    assert closed == ["pool"]


class _EmptyRepo:
    """Catalogue repository double: nothing persisted (a first deploy)."""

    async def upsert_snapshot(self, rows: Any) -> None:
        return None

    async def record_version(self, row: Any, *, changed_fields: Any) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> list[Any]:
        return []


async def test_ingestion_start_does_not_wait_on_an_unreachable_exchange() -> None:
    """#2599: boot never waits on the exchange beyond the catalogue's start timeout; the
    catalogue keeps retrying in the background and readiness reports it as stale."""
    never = asyncio.Event()

    async def fetch(_now_us: Callable[[], int]) -> InstrumentsFetchResult:
        await never.wait()  # Bybit unreachable: no answer at all
        raise AssertionError("unreachable")

    async def park(_delay: float) -> None:
        await asyncio.Event().wait()

    catalogue = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch, repository=_EmptyRepo(), sleep=park, start_timeout_s=0.0
    )
    service = IngestionService()
    service.attach_instruments(catalogue)
    await service.start(_LIVE_CTX)
    try:
        assert catalogue.snapshot() is None
        report = service.health()
        assert (report.status.value, report.detail) == ("degraded", "catalogue_stale")
    finally:
        await service.stop(grace_s=1.0)
    assert service.health().status.value == "stopped"
