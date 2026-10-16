"""Tests for the synthetic feed generator (E02-T12, M6 `ingestion`).

Unit-level: no network, no docker — reads the committed sample file directly
(C-13.5 fixtures rule doesn't apply here; this is a hand-authored dev-loop
sample, not a recorded Bybit fixture).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from candleviewer.exchange.base import Ticker, Trade
from candleviewer.ingestion.synthetic_feed import (
    SyntheticFeedError,
    SyntheticFeedGenerator,
    SyntheticFeedMetrics,
    load_sample_records,
)

_SAMPLE_PATH = Path("packages/fixtures/raw/synthetic_sample.jsonl")


def test_load_sample_records_parses_well_formed_events() -> None:
    records = load_sample_records(_SAMPLE_PATH)
    assert len(records) > 0
    assert any(isinstance(r, Trade) for r in records)
    assert any(isinstance(r, Ticker) for r in records)


def test_load_sample_records_missing_file_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(SyntheticFeedError, match="not found"):
        load_sample_records(tmp_path / "missing.jsonl")


def test_load_sample_records_malformed_line_raises_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    with pytest.raises(SyntheticFeedError, match="invalid JSON"):
        load_sample_records(bad)


def test_load_sample_records_unknown_kind_raises_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"kind": "quote", "data": {}}\n', encoding="utf-8")
    with pytest.raises(SyntheticFeedError, match="unknown synthetic feed record kind"):
        load_sample_records(bad)


def test_load_sample_records_empty_file_raises_clear_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(SyntheticFeedError, match="empty"):
        load_sample_records(empty)


async def test_generator_publishes_events_at_configured_rate() -> None:
    records = load_sample_records(_SAMPLE_PATH)
    queue: asyncio.Queue[Trade | Ticker] = asyncio.Queue(maxsize=32)
    metrics = SyntheticFeedMetrics(CollectorRegistry())
    generator = SyntheticFeedGenerator(records=records, queue=queue, metrics=metrics, rate_hz=50.0)
    await generator.start()
    try:
        published = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert isinstance(published, (Trade, Ticker))
    finally:
        await generator.stop()


async def test_generator_rate_hz_zero_raises() -> None:
    records = load_sample_records(_SAMPLE_PATH)
    queue: asyncio.Queue[Trade | Ticker] = asyncio.Queue(maxsize=8)
    metrics = SyntheticFeedMetrics(CollectorRegistry())
    with pytest.raises(SyntheticFeedError, match="rate_hz"):
        SyntheticFeedGenerator(records=records, queue=queue, metrics=metrics, rate_hz=0.0)


async def test_generator_drops_on_full_queue_without_blocking() -> None:
    records = load_sample_records(_SAMPLE_PATH)
    queue: asyncio.Queue[Trade | Ticker] = asyncio.Queue(maxsize=1)
    metrics = SyntheticFeedMetrics(CollectorRegistry())
    generator = SyntheticFeedGenerator(records=records, queue=queue, metrics=metrics, rate_hz=200.0)
    await generator.start()
    try:
        await asyncio.sleep(0.1)
        # Queue never grows past its bound; excess events are dropped, counted.
        assert queue.qsize() <= 1
        dropped_samples = next(iter(metrics.dropped_total.collect())).samples
        assert any(s.value > 0 for s in dropped_samples)
    finally:
        await generator.stop()


async def test_generator_stop_is_idempotent_and_honours_cancellation() -> None:
    records = load_sample_records(_SAMPLE_PATH)
    queue: asyncio.Queue[Trade | Ticker] = asyncio.Queue(maxsize=8)
    metrics = SyntheticFeedMetrics(CollectorRegistry())
    generator = SyntheticFeedGenerator(records=records, queue=queue, metrics=metrics, rate_hz=50.0)
    await generator.start()
    await generator.stop()
    await generator.stop()  # second stop is a no-op, not an error


def test_checkout_root_is_none_at_the_image_layout() -> None:
    """#2555: the image installs this module at `/app/candleviewer/ingestion/`, four parents
    deep. `main` indexed `parents[4]` at import there, which raised `IndexError` and stopped
    `candleviewer.app` from loading."""
    from candleviewer.ingestion.synthetic_feed import _checkout_root

    assert _checkout_root(Path("/app/candleviewer/ingestion/synthetic_feed.py")) is None
    checkout = Path("/repo/services/api/candleviewer/ingestion/synthetic_feed.py")
    assert _checkout_root(checkout) == Path("/repo")


def test_relative_sample_path_is_kept_outside_a_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    import candleviewer.ingestion.synthetic_feed as feed

    monkeypatch.setattr(feed, "_checkout_root", lambda module: None)
    absent = Path("packages/fixtures/raw/absent.jsonl")
    assert feed._resolve_sample_path(absent) == absent
