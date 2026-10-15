"""Tests for the M6 `ingestion` service lifecycle with `CV_FEED=synthetic`."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.app import build_app_context
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
