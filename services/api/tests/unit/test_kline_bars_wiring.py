"""BR-07 / SR-E12-10: every kline backfill write reaches `bars_time` through
`submit_kline_bars` (tape-over-kline precedence), composed by `_wire_klines`.

App-level with fakes: the real composition helper, the real `KlineBackfillService` and
`BarWriter`, a fake exchange page and a fake stored-tape lookup. No network, no database.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from candleviewer.app import AppContext, _wire_klines, build_app_context, create_app
from candleviewer.bars.kline_rows import (
    KLINE_SOURCE,
    StoredHigherSource,
    bars_kline_refused_total,
)
from candleviewer.bars.writer import BarWriter, bars_source_overwrite_refused_total
from candleviewer.bars_wiring import KlineBarsSink
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.settings import Settings
from candleviewer.storage.models import TimeRange
from candleviewer.storage.testing import FakeMarketDataRepository
from tests.unit.bars.test_kline_rows import SPEC, T0, W5, _k, _tape_bar

SYM = "BTCUSDT"


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
        self.rows.extend(rows)


def _overwrites() -> float:
    return float(bars_source_overwrite_refused_total.labels(KLINE_SOURCE, "tape")._value.get())


def _unknown() -> float:
    return float(bars_kline_refused_total.labels("precedence_unknown")._value.get())


def _stored(*taken: int) -> StoredHigherSource:
    async def lookup(symbol: str, bar_param: str, ts: list[int]) -> set[int]:
        return {t for t in ts if t in taken}

    return lookup


async def _fetch(
    symbol: str, interval: str, start: int, end: int, limit: int = 1000
) -> Sequence[KlineEvent]:
    """Three confirmed 5-minute klines at T0, T0+W5, T0+2*W5 (the venue's page)."""
    return [_k(t) for t in (T0, T0 + W5, T0 + 2 * W5) if start <= t <= end]


def _backfill(ctx: AppContext) -> KlineBackfillService:
    svc = ctx.ingestion.klines
    assert svc is not None
    bf = svc._backfill
    assert isinstance(bf, KlineBackfillService)
    return bf


async def test_wired_backfill_never_writes_a_kline_row_over_a_tape_row() -> None:
    """Stored tape at T0+W5 and a tape row this process queued at T0+2*W5: only T0 is written
    as a kline row, and each refusal is counted."""
    ctx = build_app_context()
    ctx.storage._market_data = FakeMarketDataRepository()  # as `storage.start()` sets it
    sink = _Sink()
    writer = BarWriter(sink)
    await writer.start()
    await writer.submit([_tape_bar(T0 + 2 * W5)], SPEC, generation=1)
    kline_bars = KlineBarsSink()
    kline_bars.bind(writer, _stored(T0 + W5))
    before = _overwrites()
    _wire_klines(ctx, _fetch, kline_bars=kline_bars)
    await _backfill(ctx).read_range(SYM, "5", Range(T0, T0 + 3 * W5))
    assert await writer.stop() == 0
    klines = [r for r in sink.rows if r["source"] == KLINE_SOURCE]
    assert [r["ts"] for r in klines] == [T0]
    assert {r["ts"] for r in sink.rows if r["source"] == "tape"} == {T0 + 2 * W5}
    # 1 stored-tape refusal + the writer's batch refusal + its single-row retry refusal.
    assert _overwrites() == before + 3
    assert not kline_bars.health.degraded
    # The kline cache (the `/market/klines` tier) still holds every confirmed page row.
    window = TimeRange(start_us=T0, end_us=T0 + 3 * W5)
    cached = await ctx.storage.market_data.read_klines(SYM, "5", window)
    assert len(cached) == 3


async def test_unbound_sink_fails_closed_and_counts_the_refusal() -> None:
    """Before (or without) a bars writer and a stored-tape lookup, precedence cannot be proven:
    the rows are refused and counted, never written; the kline cache is unaffected."""
    ctx = build_app_context()
    ctx.storage._market_data = FakeMarketDataRepository()
    kline_bars = KlineBarsSink()
    before = _unknown()
    _wire_klines(ctx, _fetch, kline_bars=kline_bars)
    await _backfill(ctx).read_range(SYM, "5", Range(T0, T0 + 3 * W5))
    assert _unknown() == before + 3
    assert kline_bars.health.degraded


async def test_month_interval_has_no_bars_time_row() -> None:
    kline_bars = KlineBarsSink()
    before = _unknown()
    await kline_bars(SYM, "M", [_k(T0)])
    assert _unknown() == before and not kline_bars.health.degraded


async def test_a_bars_error_from_the_writer_is_logged_not_raised() -> None:
    """A full bars buffer or a spec cap never fails the kline backfill that fed it."""
    from candleviewer.bars.writer import BarBufferFull

    class _Full:
        async def submit_rows(
            self, rows: list[dict[str, object]], spec: object, *, source: str
        ) -> None:
            raise BarBufferFull("full")

    kline_bars = KlineBarsSink()
    kline_bars.bind(_Full(), _stored())
    await kline_bars(SYM, "5", [_k(T0)])  # no raise


def test_create_app_binds_the_kline_sink_to_the_bars_writer_and_its_health() -> None:
    app = create_app(Settings(ingestion_ws_enabled=True))
    kline_bars = app.state.kline_bars
    assert isinstance(kline_bars, KlineBarsSink)
    assert kline_bars.writer is app.state.bars_runtime.writer
    assert app.state.bars_runtime.precedence is kline_bars.health
    assert _backfill(app.state.app_context)._kline_sink is kline_bars


def test_wire_klines_requires_a_kline_sink() -> None:
    with pytest.raises(TypeError):
        _wire_klines(build_app_context(), _fetch)  # type: ignore[call-arg]  # the missing keyword is the case under test (#5627)
