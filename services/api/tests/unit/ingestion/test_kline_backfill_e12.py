"""E12-S05 backfill hardening: SR-E12-08 ceilings, SR-E12-09 page rejection, rate-limit
backoff with jitter (fake sleep, no wall clock), `loading_older_bars`, one job per key,
background job before paging finishes, kline sink. No network, no database."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.domain.klines import KlinePageRejected
from candleviewer.exchange.base.errors import RateLimitError, ServiceUnavailableError
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import (
    MAX_PAGES_PER_JOB,
    STATUS_LOADING_OLDER,
    KlineBackfillService,
)
from candleviewer.ingestion.kline_coverage import Range

SYM, IV = "BTCUSDT", "1"
W = 60_000_000  # 1-minute bar, µs


def _k(start: int, confirmed: bool = True) -> KlineEvent:
    return KlineEvent(
        event_id="00000000-0000-7000-8000-000000000001",  # type: ignore[arg-type]
        ts_event=start, ts_ingest=start, source="backfill", symbol=SYM,
        interval=IV,  # type: ignore[arg-type]
        start=start, end=start + W - 1, open="100", high="101", low="99", close="100",  # type: ignore[arg-type]
        volume="1", turnover="100", confirmed=confirmed,  # type: ignore[arg-type]
    )  # fmt: skip


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


class _Bybit:
    """Bybit-shaped port: the NEWEST `limit` bars of `[start, end]`, scripted errors first."""

    def __init__(self, n_bars: int, errors: Sequence[Exception] = ()) -> None:
        self.bars = [_k(i * W) for i in range(n_bars)]
        self.errors = list(errors)
        self.calls: list[tuple[int, int]] = []

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls.append((start, end))
        if self.errors:
            raise self.errors.pop(0)
        inside = [b for b in self.bars if start <= b.start <= end]
        return inside[-limit:]


class _Sleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


def _svc(fetch: object, cache: _Cache | None = None, **kw: object) -> KlineBackfillService:
    return KlineBackfillService(
        fetch_klines=fetch, cache=cache or _Cache(), sleep=kw.pop("sleep", _Sleep()),  # type: ignore[arg-type]
        random_fn=lambda: 0.5, **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def _rl() -> RateLimitError:
    return RateLimitError("rate limited", exchange_ret_code=10018)


def _outage(code: int) -> ServiceUnavailableError:
    return ServiceUnavailableError("service unavailable", exchange_ret_code=code)


async def test_backfill_pages_newest_first_until_window_covered_with_progress() -> None:
    progress: list[tuple[float, str]] = []
    port = _Bybit(2_500)
    svc = _svc(
        port,
        page_limit=1000,
        on_progress=lambda **kw: progress.append((kw["fraction"], kw["status"])),
    )
    result = await svc.backfill_range(SYM, IV, Range(0, 2_500 * W))
    assert not result.partial and result.pages == 3
    assert [e.start for e in result.fetched] == [i * W for i in range(2_500)]
    assert port.calls[0] == (0, 2_500 * W - 1)  # first page = newest 1000 (chart tail)
    fetching = [f for f, s in progress if s == "fetching"]
    assert len(fetching) == 3 and fetching == sorted(fetching)
    assert progress[-1] == (1.0, "done")


async def test_backfill_page_ceiling_stops_job_and_keeps_partial() -> None:
    port = _Bybit(50)
    svc = _svc(port, page_limit=10, max_pages=3)
    result = await svc.backfill_range(SYM, IV, Range(0, 50 * W))
    assert result.partial and result.stop_reason == "page_ceiling"
    assert len(port.calls) == 3 and len(result.fetched) == 30


def test_backfill_page_ceiling_cannot_be_raised_above_sr_e12_08() -> None:
    svc = _svc(_Bybit(1), max_pages=10_000)
    assert svc._max_pages == MAX_PAGES_PER_JOB == 400


async def test_backfill_rate_limit_backs_off_with_jitter_and_emits_loading_state() -> None:
    sleep, statuses = _Sleep(), []
    port = _Bybit(5, errors=[_rl(), _rl()])
    svc = _svc(port, sleep=sleep, on_progress=lambda **kw: statuses.append(kw["status"]))
    result = await svc.backfill_range(SYM, IV, Range(0, 5 * W))
    assert not result.partial and len(result.fetched) == 5
    # full jitter, random=0.5: 1 + (min(60, 2**n) - 1) * 0.5
    assert sleep.calls == [1.0, 1.5]
    assert statuses.count(STATUS_LOADING_OLDER) == 2


@pytest.mark.parametrize("code", [10016, 10019])
async def test_backfill_retries_the_venues_outage_as_a_transient_fault_never_a_rate_limit(
    code: int,
) -> None:
    """#2863: after the client's attempts a 10016/10019 page is `SERVICE_UNAVAILABLE`, which the
    backfill retries under `max_retries` as it does a 5xx, never on the rate-limit path: no
    loading-older state, and nothing counts toward the rate-limit ceiling (SR-E12-08)."""
    sleep, statuses = _Sleep(), []
    port = _Bybit(5, errors=[_outage(code), _outage(code)])
    svc = _svc(port, sleep=sleep, on_progress=lambda **kw: statuses.append(kw["status"]))
    result = await svc.backfill_range(SYM, IV, Range(0, 5 * W))
    assert not result.partial and len(result.fetched) == 5
    assert STATUS_LOADING_OLDER not in statuses and len(port.calls) == 3


async def test_backfill_aborts_after_five_consecutive_rate_limits_keeping_partial() -> None:
    cache = _Cache()
    port = _Bybit(20)
    svc = _svc(port, cache, page_limit=10)
    await svc.backfill_range(SYM, IV, Range(10 * W, 20 * W))  # prior data
    port.errors = [_rl() for _ in range(5)]
    result = await svc.backfill_range(SYM, IV, Range(0, 20 * W))
    assert result.partial and result.stop_reason == "rate_limited"
    assert len(port.calls) == 1 + 5
    assert sorted(cache.rows) == [i * W for i in range(10, 20)]


async def test_backfill_rate_limit_counter_resets_after_a_good_page() -> None:
    port = _Bybit(30, errors=[_rl()] * 4)
    svc = _svc(port, page_limit=10)
    port_errors_after_first = [_rl()] * 4

    async def fetch(*a: object, **kw: object) -> Sequence[KlineEvent]:
        page = await port(*a, **kw)  # type: ignore[arg-type]
        if port_errors_after_first and not port.errors:
            port.errors, port_errors_after_first[:] = list(port_errors_after_first), []
        return page

    svc._fetch_klines = fetch
    result = await svc.backfill_range(SYM, IV, Range(0, 30 * W))
    assert not result.partial and len(result.fetched) == 30


async def test_backfill_bad_page_rejected_and_prior_pages_kept() -> None:
    cache = _Cache()
    port = _Bybit(30)
    page_no = 0

    async def fetch(*a: object, **kw: object) -> Sequence[KlineEvent]:
        nonlocal page_no
        page_no += 1
        if page_no == 2:
            raise KlinePageRejected("tampered", "high_below_body")
        return await port(*a, **kw)  # type: ignore[arg-type]

    result = await _svc(fetch, cache, page_limit=10).backfill_range(SYM, IV, Range(0, 30 * W))
    assert result.partial and result.stop_reason == "page_rejected"
    assert page_no == 2  # never retried
    assert sorted(cache.rows) == [i * W for i in range(20, 30)]


async def test_backfill_transient_errors_exhausted_is_fetch_failed() -> None:
    port = _Bybit(5, errors=[OSError("503")] * 3)
    result = await _svc(port, max_retries=3).backfill_range(SYM, IV, Range(0, 5 * W))
    assert result.partial and result.stop_reason == "fetch_failed"


class _Gate:
    """Port that blocks every call until released (to observe a job mid-flight)."""

    def __init__(self, n: int) -> None:
        self.inner = _Bybit(n)
        self.release = asyncio.Event()
        self.entered = asyncio.Event()

    async def __call__(self, *a: object, **kw: object) -> Sequence[KlineEvent]:
        self.entered.set()
        await self.release.wait()
        return await self.inner(*a, **kw)  # type: ignore[arg-type]


async def test_start_backfill_is_background_and_one_job_per_symbol_interval() -> None:
    gate = _Gate(5)
    svc = _svc(gate)
    first = svc.start_backfill(SYM, IV, Range(0, 5 * W))
    await gate.entered.wait()
    # Chart is interactive: the caller got a task back and the job is still paging.
    assert svc.job_running(SYM, IV) and not first.done()
    assert svc.start_backfill(SYM, IV, Range(0, 5 * W)) is first  # SR-E12-08: one job
    gate.release.set()
    result = await first
    assert len(result.fetched) == 5 and len(gate.inner.calls) == 1
    await asyncio.sleep(0)
    assert not svc.job_running(SYM, IV)


async def test_concurrent_reads_for_same_key_are_serialised_not_duplicated() -> None:
    port = _Bybit(5)
    svc = _svc(port)
    a, b = await asyncio.gather(
        svc.read_range(SYM, IV, Range(0, 5 * W)), svc.read_range(SYM, IV, Range(0, 5 * W))
    )
    assert len(port.calls) == 1  # second waits, then hits the cache
    assert len(a.fetched) + len(b.fetched) == 5


async def test_aclose_cancels_running_jobs() -> None:
    gate = _Gate(5)
    svc = _svc(gate)
    task = svc.start_backfill(SYM, IV, Range(0, 5 * W))
    await gate.entered.wait()
    await svc.aclose()
    assert task.cancelled()


async def test_crashed_job_is_logged_and_released() -> None:
    class _BadCache(_Cache):
        async def write_klines(self, rows: Sequence[object]) -> None:
            raise RuntimeError("disk")

    svc = _svc(_Bybit(2), _BadCache())
    task = svc.start_backfill(SYM, IV, Range(0, 2 * W))
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)
    assert not svc.job_running(SYM, IV)


async def test_kline_sink_receives_only_confirmed_klines() -> None:
    seen: list[int] = []

    async def sink(symbol: str, interval: str, events: Sequence[KlineEvent]) -> None:
        seen.extend(e.start for e in events)

    port = _Bybit(3)
    port.bars[-1] = _k(2 * W, confirmed=False)
    result = await _svc(port, kline_sink=sink).backfill_range(SYM, IV, Range(0, 3 * W))
    assert seen == [0, W]
    assert result.fetched[-1].confirmed is False


async def test_fully_cached_request_never_calls_exchange_and_coverage_exposed() -> None:
    port = _Bybit(5)
    svc = _svc(port)
    await svc.backfill_range(SYM, IV, Range(0, 5 * W))
    port.calls.clear()
    result = await svc.read_range(SYM, IV, Range(0, 5 * W))
    assert port.calls == [] and result.fetched == []
    index = svc.coverage(SYM, IV)
    assert index is not None and index.holes(Range(0, 5 * W)) == []
    assert svc.coverage("ETHUSDT", IV) is None


async def test_gap_page_rejected_leaves_span_uncovered_and_is_refetched() -> None:
    """#2044 F1: a page with a missing bar (adapter raises `gap`) is never marked covered;
    the next job re-fetches exactly that span once the exchange serves it whole."""
    cache = _Cache()
    port = _Bybit(10)
    bad = [True]

    async def fetch(*a: object, **kw: object) -> Sequence[KlineEvent]:
        if bad[0]:
            raise KlinePageRejected("missing bar", "gap")
        return await port(*a, **kw)  # type: ignore[arg-type]

    svc = _svc(fetch, cache)
    first = await svc.backfill_range(SYM, IV, Range(0, 10 * W))
    assert first.partial and first.stop_reason == "page_rejected"
    index = svc.coverage(SYM, IV)
    assert index is not None and index.holes(Range(0, 10 * W)) == [Range(0, 10 * W)]
    bad[0] = False
    second = await svc.backfill_range(SYM, IV, Range(0, 10 * W))
    assert not second.partial and len(cache.rows) == 10
    assert index.holes(Range(0, 10 * W)) == []


async def test_hostile_numeric_page_ends_page_rejected_with_metric_and_zero_retries() -> None:
    """#2044 S1: a `1e999999` price through the real parser (with a tick size) is a rejected
    page — counted, logged, never retried against MARKET_DATA, never `fetch_failed`."""
    import copy
    from decimal import Decimal

    from candleviewer.exchange.bybit.klines import parse_kline_page  # adapter-under-test
    from candleviewer.ingestion.metrics import kline_backfill_pages_rejected_total
    from tests._corpus import rest

    page = copy.deepcopy(rest("rest/kline_BTCUSDT_1_page0.json"))
    page["result"]["list"][3][2] = "1e999999"
    calls = 0

    async def fetch(*a: object, **kw: object) -> Sequence[KlineEvent]:
        nonlocal calls
        calls += 1
        return parse_kline_page(page, symbol=SYM, interval=IV, tick_size=Decimal("0.1"))

    sleep = _Sleep()
    counter = kline_backfill_pages_rejected_total.labels(
        symbol=SYM, interval=IV, reason="unparseable"
    )
    before = counter._value.get()
    result = await _svc(fetch, sleep=sleep).backfill_range(SYM, IV, Range(0, 10 * W))
    assert result.partial and result.stop_reason == "page_rejected"
    assert calls == 1 and sleep.calls == []
    assert counter._value.get() == before + 1


async def test_empty_page_after_the_newest_bar_records_no_coverage() -> None:
    """#3808: an empty page proves nothing about bars that may not exist yet; a later job
    fetches them once the venue has them."""
    port = _Bybit(10)  # newest bar: 9
    svc = _svc(port)
    first = await svc.backfill_range(SYM, IV, Range(20 * W, 30 * W))
    index = svc.coverage(SYM, IV)
    assert first.fetched == [] and index is not None and index.covered_ranges() == []
    port.bars = [_k(i * W) for i in range(30)]  # time passes: bars 10..29 now exist
    again = await svc.backfill_range(SYM, IV, Range(20 * W, 30 * W))
    assert [e.start for e in again.fetched] == [i * W for i in range(20, 30)]


async def test_short_page_past_the_newest_bar_covers_only_up_to_it() -> None:
    """#3808 Gherkin: a short page for a window past the venue's newest bar covers up to it."""
    svc = _svc(_Bybit(10))
    await svc.backfill_range(SYM, IV, Range(5 * W, 30 * W))
    index = svc.coverage(SYM, IV)
    assert index is not None and index.covered_ranges() == [Range(5 * W, 10 * W)]


async def test_part_past_the_newest_bar_stays_a_hole_while_older_history_fills() -> None:
    """A full newest page leaves an older gap and one past the newest bar: the job still pages
    the older history, and the known newest bar proves the empty span before listing."""
    port = _Bybit(30)
    port.bars = port.bars[5:]  # no bars before bar 5 (not listed yet)
    svc = _svc(port, page_limit=10)
    await svc.backfill_range(SYM, IV, Range(0, 40 * W))
    index = svc.coverage(SYM, IV)
    assert index is not None and index.covered_ranges() == [Range(0, 30 * W)]
    assert len(port.calls) == 4


async def test_newest_bar_is_a_per_key_maximum_an_older_page_never_lowers() -> None:
    """#3808: after an older full page, the empty gap below a newer returned bar is proven."""
    port = _Bybit(30)
    port.bars = port.bars[:10] + port.bars[20:]  # the venue has no bars in [10W, 20W)
    svc = _svc(port, page_limit=10)
    await svc.backfill_range(SYM, IV, Range(0, 30 * W))
    index = svc.coverage(SYM, IV)
    assert index is not None and index.covered_ranges() == [Range(0, 30 * W)]
    assert len(port.calls) == 3


async def test_newest_bar_map_is_bounded_with_the_tracked_keys() -> None:
    """#3808 / SR-E12-08: the newest-bar map is evicted with its key, and a key evicted while its
    own page was in flight (an untracked read) gets no entry back."""
    port = _Bybit(2)

    async def fetch(
        symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        if symbol == "AAAUSDT":  # five other keys are read meanwhile: this one is evicted
            for i in range(5):
                await svc.read_range(f"S{i}USDT", IV, Range(0, 2 * W))
        return await port(symbol, interval, start, end, limit)

    svc = _svc(fetch, max_tracked_keys=3)
    assert len((await svc.read_range("AAAUSDT", IV, Range(0, 2 * W))).fetched) == 2
    assert svc.tracked_keys == len(svc._newest) == 3 and set(svc._newest) <= set(svc._coverage)


async def test_backfill_never_covers_the_bar_containing_now_or_later() -> None:
    """#3808: coverage stops at the open time of the bar containing the injected now, even
    when the venue serves later bars as closed (clock skew)."""
    svc = _svc(_Bybit(10), now_us=lambda: 7 * W + W // 2)
    await svc.backfill_range(SYM, IV, Range(0, 10 * W))
    index = svc.coverage(SYM, IV)
    assert index is not None and index.covered_ranges() == [Range(0, 7 * W)]


@settings(max_examples=80, deadline=None)
@given(
    n=st.integers(0, 40), limit=st.integers(1, 12), start=st.integers(0, 50),
    span=st.integers(1, 30), now_bar=st.integers(0, 60),
)  # fmt: skip
def test_property_coverage_ends_by_newest_bar_and_now_and_hides_no_bar(
    n: int, limit: int, start: int, span: int, now_bar: int
) -> None:
    """#3808 invariant, any window: coverage never passes min(the venue's newest bar, the bar
    containing now), and every venue bar inside a covered range is cached."""
    port, cache = _Bybit(n), _Cache()
    svc = _svc(port, cache, page_limit=limit, now_us=lambda: now_bar * W + W // 2)
    asyncio.run(svc.backfill_range(SYM, IV, Range(start * W, (start + span) * W)))
    index = svc.coverage(SYM, IV)
    assert index is not None
    covered = index.covered_ranges()
    assert all(r.end_us <= min(n, now_bar) * W for r in covered)
    inside = {b.start for b in port.bars for r in covered if r.start_us <= b.start < r.end_us}
    assert inside <= set(cache.rows)
