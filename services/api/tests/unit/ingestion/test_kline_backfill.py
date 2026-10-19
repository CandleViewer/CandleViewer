"""Unit tests for `ingestion.kline_backfill` (E08-S06): paging, rate-limit
retry, unconfirmed-tail handling, cache-first reads, and resume-from-cache.
No network, no database — the exchange fetcher and cache are fakes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import (
    KlineBackfillService,
)
from candleviewer.ingestion.kline_coverage import Range

_SYMBOL = "BTCUSDT"
_INTERVAL = "1"


def _kline(*, start: int, confirmed: bool = True) -> KlineEvent:
    return KlineEvent(
        event_id="00000000-0000-7000-8000-000000000001",
        ts_event=start,
        ts_ingest=start,
        source="backfill",
        symbol=_SYMBOL,
        interval=_INTERVAL,  # type: ignore[arg-type]
        start=start,
        end=start + 59_999_999,
        open="100",
        high="101",
        low="99",
        close="100",
        volume="1",
        turnover="100",
        confirmed=confirmed,
    )


@dataclass(slots=True)
class _FakeRow:
    ts_us: int
    confirmed: bool


@dataclass(slots=True)
class _FakeCache:
    """In-memory `KlineCacheLike`."""

    rows: dict[tuple[str, str, int], _FakeRow] = field(default_factory=dict)

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[_FakeRow]:
        matches = [
            r
            for (s, i, ts), r in self.rows.items()
            if s == sym and i == interval and rng.start_us <= ts < rng.end_us
        ]
        return sorted(matches, key=lambda r: r.ts_us)

    async def write_klines(self, rows: Sequence[object]) -> None:
        for row in rows:
            assert isinstance(row, dict)
            key = (row["symbol"], row["interval"], row["ts_us"])
            self.rows[key] = _FakeRow(ts_us=row["ts_us"], confirmed=row["confirmed"])


@dataclass(slots=True)
class _FakeFetcher:
    """In-memory `KlineFetcher` serving from `pages`: a list of full page
    responses, consumed in order regardless of the requested window (tests
    control exactly what each call returns)."""

    pages: list[Sequence[KlineEvent] | Exception]
    calls: list[tuple[int, int]] = field(default_factory=list)

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls.append((start, end))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


class TestBackfillRangeHappyPath:
    async def test_single_page_is_persisted_and_returned(self) -> None:
        fetcher = _FakeFetcher(pages=[[_kline(start=0), _kline(start=60_000_000)]])
        cache = _FakeCache()
        service = KlineBackfillService(fetch_klines=fetcher, cache=cache)

        result = await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        assert not result.partial
        assert [e.start for e in result.fetched] == [0, 60_000_000]
        assert len(cache.rows) == 2

    async def test_progress_callback_invoked_with_increasing_fraction(self) -> None:
        seen: list[float] = []
        fetcher = _FakeFetcher(
            pages=[
                [_kline(start=0)],
                [_kline(start=60_000_000)],
            ]
        )
        cache = _FakeCache()
        service = KlineBackfillService(
            fetch_klines=fetcher,
            cache=cache,
            # #3808: a short page proves only up to its newest bar; 1-row pages are full, so
            # the job pages twice (a short first page used to "prove" the second bar unseen).
            page_limit=1,
            on_progress=lambda *, symbol, interval, fraction, status: seen.append(fraction),
        )

        await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        assert seen == sorted(seen)
        assert seen[-1] == 1.0


class TestCacheHit:
    async def test_fully_covered_range_never_calls_the_exchange(self) -> None:
        fetcher = _FakeFetcher(pages=[[_kline(start=0)]])
        cache = _FakeCache()
        service = KlineBackfillService(fetch_klines=fetcher, cache=cache)
        await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 60_000_000))

        result = await service.read_range(_SYMBOL, _INTERVAL, Range(0, 60_000_000))

        assert result.fetched == []
        assert fetcher.calls == [(0, 59_999_999)]  # only the first call (Bybit `end` inclusive)

    async def test_partially_covered_range_only_fetches_the_tail(self) -> None:
        fetcher = _FakeFetcher(
            pages=[
                [_kline(start=0)],
                [_kline(start=60_000_000)],
            ]
        )
        cache = _FakeCache()
        service = KlineBackfillService(fetch_klines=fetcher, cache=cache)
        await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 60_000_000))

        result = await service.read_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        assert [e.start for e in result.fetched] == [60_000_000]


class TestRateLimited:
    async def test_transient_error_is_retried_with_backoff(self) -> None:
        slept: list[float] = []
        fetcher = _FakeFetcher(
            pages=[
                RuntimeError("10018 rate limited"),
                [_kline(start=0)],
            ]
        )
        cache = _FakeCache()
        service = KlineBackfillService(
            fetch_klines=fetcher,
            cache=cache,
            sleep=lambda s: slept.append(s) or _noop(),  # type: ignore[func-returns-value]
            random_fn=lambda: 0.5,
        )

        result = await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 60_000_000))

        assert not result.partial
        assert len(slept) == 1
        assert slept[0] > 0

    async def test_exhausted_retries_leave_partial_result_usable(self) -> None:
        fetcher = _FakeFetcher(
            pages=[
                [_kline(start=0)],
                RuntimeError("10018 rate limited"),
                RuntimeError("10018 rate limited"),
            ]
        )
        cache = _FakeCache()
        service = KlineBackfillService(
            fetch_klines=fetcher,
            cache=cache,
            page_limit=1,  # a 1-row page is "full": the rest of the window is still a hole
            max_retries=2,
            sleep=_fast_sleep,
            random_fn=lambda: 0.1,
        )

        result = await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        assert result.partial
        assert [e.start for e in result.fetched] == [0]
        assert len(cache.rows) == 1


class TestUnconfirmedTail:
    async def test_unconfirmed_row_is_returned_but_not_cached(self) -> None:
        fetcher = _FakeFetcher(pages=[[_kline(start=0), _kline(start=60_000_000, confirmed=False)]])
        cache = _FakeCache()
        service = KlineBackfillService(fetch_klines=fetcher, cache=cache)

        result = await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        assert [e.start for e in result.fetched] == [0, 60_000_000]
        assert len(cache.rows) == 1
        assert cache.rows[(_SYMBOL, _INTERVAL, 0)].confirmed is True

    async def test_unconfirmed_tail_leaves_a_hole_for_next_call(self) -> None:
        fetcher = _FakeFetcher(
            pages=[
                [_kline(start=0), _kline(start=60_000_000, confirmed=False)],
                [_kline(start=60_000_000)],
            ]
        )
        cache = _FakeCache()
        service = KlineBackfillService(fetch_klines=fetcher, cache=cache)
        await service.backfill_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        result = await service.read_range(_SYMBOL, _INTERVAL, Range(0, 120_000_000))

        assert [e.start for e in result.fetched] == [60_000_000]
        assert cache.rows[(_SYMBOL, _INTERVAL, 60_000_000)].confirmed is True


class TestResume:
    async def test_load_coverage_from_cache_avoids_refetching_covered_span(self) -> None:
        cache = _FakeCache()
        cache.rows[(_SYMBOL, _INTERVAL, 0)] = _FakeRow(ts_us=0, confirmed=True)
        cache.rows[(_SYMBOL, _INTERVAL, 60_000_000)] = _FakeRow(ts_us=60_000_000, confirmed=True)
        fetcher = _FakeFetcher(pages=[[_kline(start=120_000_000)]])
        service = KlineBackfillService(fetch_klines=fetcher, cache=cache)

        await service.load_coverage_from_cache(_SYMBOL, _INTERVAL, Range(0, 120_000_000))
        result = await service.read_range(_SYMBOL, _INTERVAL, Range(0, 180_000_000))

        assert [e.start for e in result.fetched] == [120_000_000]
        assert fetcher.calls == [(120_000_000, 179_999_999)]


async def _noop() -> None:
    return None


async def _fast_sleep(_seconds: float) -> None:
    return None
