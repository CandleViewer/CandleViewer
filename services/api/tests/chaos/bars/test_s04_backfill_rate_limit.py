"""Scenario 4 - 5xx and 10018 during a kline backfill. C-13.6 #5 (rate limit), #1 (storm guard).

Declared (E12-Q06 AC4, US-MKT-008 scenario 3): a throttled or failing page never fails the job
and never blocks the chart. The service backs off with full jitter (1 s .. 60 s, SR-E12-08),
tells the UI `loading_older_bars` (words, not a colour), keeps every page already persisted
readable while it waits, and stops after five consecutive limits with a partial result that a
later job resumes (only the remaining holes are fetched).

The venue is a fake `KlineFetcher` serving the **recorded** corpus (`kline_BTCUSDT_1_page{0,1,2}`,
450 one-minute bars, parsed by the production `parse_kline_page`) newest-first in 15-bar pages,
so 30 pages stand for the ticket's 30-day range at smoke scale. The failures are scripted by
call number. Time is a recording `sleep` on a virtual clock; jitter is a seeded RNG.

Metric mapping (BQ-8): the ticket's `backfill_rate_limited_total` is
`kline_backfill_rate_limited_total`; the REST client's `bybit_rate_limited_total{code}` and the
reconnect-storm guard are scenarios 5 and 7 of the ingestion suite, not repeated here.

Negative control: the delay-bounds helper fails on an immediate retry and on a delay past 60 s.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import RateLimitError, ServiceUnavailableError
from candleviewer.exchange.base.models import KlineEvent

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.klines import parse_kline_page
from candleviewer.ingestion.kline_backfill import STATUS_LOADING_OLDER, KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import (
    kline_backfill_pages_total,
    kline_backfill_rate_limited_total,
    symbol_label,
)
from tests._corpus import rest
from tests.chaos.bars.conftest import SEED
from tests.chaos.ingestion._rig import metric

pytestmark = pytest.mark.chaos

SYM, IV = "BTCUSDT", "1"
BAR_US = 60_000_000
PAGE_BARS = 15
NOW_MS = 1_700_100_000_000  # after every corpus bar closed
MIN_DELAY_S, MAX_DELAY_S = 1.0, 60.0
MAX_CONSECUTIVE = 5  # SR-E12-08


def _corpus() -> list[KlineEvent]:
    events: list[KlineEvent] = []
    for page in range(3):
        raw = rest(f"rest/kline_{SYM}_{IV}_page{page}.json")
        events += parse_kline_page(
            raw, symbol=SYM, interval=IV, tick_size=Decimal("0.1"), now_ms=NOW_MS
        )
    return sorted(events, key=lambda e: e.start)


CORPUS = _corpus()
WINDOW = Range(CORPUS[0].start, CORPUS[-1].start + BAR_US)
N_PAGES = len(CORPUS) // PAGE_BARS


@dataclass
class _Venue:
    """Bybit-shaped port: the newest `limit` bars of `[start, end]`; `script(call_no)` may fail."""

    script: Mapping[int, Exception] = field(default_factory=dict)
    calls: int = 0

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls += 1
        if (error := self.script.get(self.calls)) is not None:
            raise error
        return [e for e in CORPUS if start <= e.start <= end][-limit:]


@dataclass
class _Row:
    ts_us: int
    confirmed: bool


@dataclass
class _Cache:
    rows: dict[int, _Row] = field(default_factory=dict)

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[_Row]:
        return [r for t, r in sorted(self.rows.items()) if rng.start_us <= t < rng.end_us]

    async def write_klines(self, rows: Sequence[object]) -> None:
        for row in rows:
            assert isinstance(row, dict)
            self.rows[int(row["ts_us"])] = _Row(int(row["ts_us"]), bool(row["confirmed"]))


class _Wait:
    """Virtual `sleep`: advances a virtual clock, records each delay and what was readable."""

    def __init__(self, cache: _Cache) -> None:
        self._cache = cache
        self.now = 0.0
        self.delays: list[float] = []
        self.readable: list[int] = []

    async def __call__(self, seconds: float) -> None:
        self.now += seconds
        self.delays.append(seconds)
        self.readable.append(len(await self._cache.read_klines(SYM, IV, WINDOW)))


class _Run:
    async def _instant(self, seconds: float) -> None:
        self.wait.delays.append(0.0)  # the naive collaborator: it waits for nothing

    def __init__(
        self, venue: _Venue, *, max_limits: int = MAX_CONSECUTIVE, naive_sleep: bool = False
    ) -> None:
        self.venue, self.cache = venue, _Cache()
        self.wait = _Wait(self.cache)
        self.progress: list[tuple[float, str]] = []
        self.service = KlineBackfillService(
            fetch_klines=venue,
            cache=self.cache,
            sleep=self._instant if naive_sleep else self.wait,
            random_fn=random.Random(SEED).random,  # noqa: S311  (seeded jitter)
            on_progress=lambda *, symbol, interval, fraction, status: self.progress.append(
                (fraction, status)
            ),
            page_limit=PAGE_BARS,
            max_consecutive_rate_limits=max_limits,
            now_us=lambda: NOW_MS * 1_000,
        )


def _limit() -> RateLimitError:
    return RateLimitError("rate limited (10018)")


def _limited() -> float:
    return metric(kline_backfill_rate_limited_total, symbol=symbol_label(SYM), interval=IV)


def _pages(result: str) -> float:
    return metric(kline_backfill_pages_total, symbol=symbol_label(SYM), interval=IV, result=result)


def assert_backoff_within_bounds(delays: Sequence[float], caps: Sequence[float]) -> None:
    """Each delay is a full-jitter draw in `[1 s, min(60 s, cap)]`: not at once, not past 60 s."""
    assert len(delays) == len(caps)
    for delay, cap in zip(delays, caps, strict=True):
        assert MIN_DELAY_S <= delay <= min(MAX_DELAY_S, cap), f"delay {delay} outside [1, {cap}]"


async def test_s04_every_third_page_rate_limited_still_completes_with_the_full_range() -> None:
    limited = {n: _limit() for n in range(3, 60, 3)}
    run = _Run(_Venue(script=limited))
    before, throttled = _limited(), _pages("rate_limited")
    result = await run.service.backfill_range(SYM, IV, WINDOW)
    injected = [n for n in limited if n <= run.venue.calls]
    assert not result.partial and result.stop_reason == ""
    assert [e.start for e in result.fetched] == [e.start for e in CORPUS]  # none lost, in order
    assert len(run.cache.rows) == len(CORPUS)
    assert result.pages == N_PAGES
    assert _limited() - before == len(injected) > 3
    assert _pages("rate_limited") - throttled == len(injected)
    assert_backoff_within_bounds(
        run.wait.delays, [1.0] * len(injected)
    )  # one limit in a row: cap 1 s


async def test_s04_consecutive_limits_back_off_with_full_jitter_inside_the_bounds() -> None:
    burst = {2: _limit(), 3: _limit(), 4: _limit(), 5: _limit()}  # four in a row: 4 < 5, survives
    run = _Run(_Venue(script=burst))
    result = await run.service.backfill_range(SYM, IV, WINDOW)
    assert not result.partial
    assert_backoff_within_bounds(run.wait.delays, [1.0, 2.0, 4.0, 8.0])
    assert len(set(run.wait.delays[1:])) == 3, "jitter: the delays are not one fixed step"
    assert run.wait.delays[1:] != sorted(run.wait.delays[1:], reverse=True)
    assert run.wait.now == pytest.approx(sum(run.wait.delays))


async def test_s04_the_ui_is_told_loading_and_earlier_pages_stay_readable_while_waiting() -> None:
    limited = {n: _limit() for n in (4, 9, 14)}
    run = _Run(_Venue(script=limited))
    with capture_logs() as logs:
        await run.service.backfill_range(SYM, IV, WINDOW)
    loading = [p for p in run.progress if p[1] == STATUS_LOADING_OLDER]
    assert len(loading) == len(limited)
    assert {f for f, _ in loading} == {-1.0}  # "indeterminate": the text carries the meaning
    assert [e["event"] for e in logs].count("kline_backfill_rate_limited") == len(limited)
    # interactive: each wait found the pages fetched so far already in the cache, and growing
    assert run.wait.readable == sorted(run.wait.readable)
    assert run.wait.readable[0] >= 3 * PAGE_BARS
    assert run.progress[-1][1] == "done"


async def test_s04_five_consecutive_limits_stop_the_job_with_a_resumable_partial_result() -> None:
    wall = {n: _limit() for n in range(4, 4 + MAX_CONSECUTIVE)}  # pages 1-3 land, then 5 limits
    run = _Run(_Venue(script=wall))
    result = await run.service.backfill_range(SYM, IV, WINDOW)
    assert result.partial and result.stop_reason == "rate_limited"
    assert result.pages == 3
    assert len(run.cache.rows) == len(result.fetched) == 3 * PAGE_BARS  # kept, not rolled back
    assert run.progress[-1][1] == "partial"
    assert len(run.wait.delays) == MAX_CONSECUTIVE - 1  # the fifth limit stops, it does not wait
    calls = run.venue.calls
    again = await run.service.backfill_range(SYM, IV, WINDOW)  # the limit has lifted
    assert not again.partial
    assert again.pages == N_PAGES - 3, "the resumed job refetched pages it already holds"
    assert run.venue.calls - calls == N_PAGES - 3
    assert len(run.cache.rows) == len(CORPUS)


async def test_s04_a_5xx_burst_is_retried_with_backoff_and_the_page_is_not_skipped() -> None:
    errors = {2: ServiceUnavailableError("503"), 3: ServiceUnavailableError("503")}
    run = _Run(_Venue(script=errors))
    retries = _pages("retry")
    result = await run.service.backfill_range(SYM, IV, WINDOW)
    assert not result.partial
    assert [e.start for e in result.fetched] == [e.start for e in CORPUS]
    assert _pages("retry") - retries == 2
    assert_backoff_within_bounds(run.wait.delays, [1.0, 2.0])


async def test_s04_negative_control_the_bounds_helper_rejects_a_naive_retry() -> None:
    with pytest.raises(AssertionError, match="outside"):
        assert_backoff_within_bounds([0.0, 0.0], [1.0, 2.0])  # retry at once: a storm
    with pytest.raises(AssertionError, match="outside"):
        assert_backoff_within_bounds([61.0], [64.0])  # past the 60 s ceiling
    with pytest.raises(AssertionError, match="outside"):
        assert_backoff_within_bounds([1.5], [1.0])  # not the jittered range of the first limit


async def test_s04_negative_control_a_zero_delay_sleep_fails_the_bounds_check() -> None:
    """A service that retries without waiting (naive sleep) is caught by the real run's check."""
    run = _Run(_Venue(script={n: _limit() for n in (2, 3)}), naive_sleep=True)
    await run.service.backfill_range(SYM, IV, WINDOW)
    assert len(run.wait.delays) == 2
    with pytest.raises(AssertionError, match="outside"):
        assert_backoff_within_bounds(run.wait.delays, [1.0, 2.0])
