"""E24-T01 (#665): downsampler, backfill paging/retry and the read side, over in-memory fakes."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.domain.open_interest import OiFetchFailed, OiPage, OiPoint, OiRowRejected
from candleviewer.exchange.bybit.open_interest import parse_oi_page
from candleviewer.orderflow.deriv_limits import DerivInvalidRequest, DerivSymbolUnlisted
from candleviewer.orderflow.open_interest import (
    MAX_ATTEMPTS,
    MAX_PAGES_PER_JOB,
    OiBackfill,
    OpenInterestService,
    TickerDownsampler,
    TimeWindow,
    find_gaps,
)
from candleviewer.storage.questdb.oi_store import InMemoryOiStore
from tests._corpus import rest

S = 1_000_000
STEP = 300 * S
PAGES = [
    parse_oi_page(
        rest(f"rest/open_interest_BTCUSDT_5min_page{i}.json"),
        symbol="BTCUSDT",
        interval="5min",
        now_ms=1_800_000_000_000,
    )
    for i in (0, 1)
]
FIRST, LAST = PAGES[1][-1].ts_us, PAGES[0][0].ts_us
WINDOW = TimeWindow(FIRST, LAST)
NOW_S = LAST / S + 60


class _Fetcher:
    """Serves the corpus pages by cursor, after `fail` planted failures."""

    def __init__(self, fail: list[Exception] | None = None) -> None:
        self.fail = list(fail or [])
        self.calls: list[str | None] = []

    async def __call__(
        self, symbol: str, interval: str, start_us: int, end_us: int, cursor: str | None
    ) -> OiPage:
        self.calls.append(cursor)
        if self.fail:
            raise self.fail.pop(0)
        return PAGES[0] if cursor is None else PAGES[1]


class _Sleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _backfill(store: InMemoryOiStore, fetcher: _Fetcher, sleep: _Sleep | None = None) -> OiBackfill:
    return OiBackfill(
        store=store, fetcher=fetcher, sleep=sleep or _Sleep(), random_fn=lambda: 0.5,
        clock_s=lambda: 0.0,
    )  # fmt: skip


def test_oi_downsampler_caps_one_row_per_second() -> None:
    d = TickerDownsampler()
    one = Decimal("10")
    kept = [d.offer("BTCUSDT", ts, one, one) for ts in (S, S + 100_000, 2 * S - 1, 2 * S)]
    assert [p.ts_us if p else None for p in kept] == [S, None, None, 2 * S]
    assert kept[0] == OiPoint(S, "BTCUSDT", one, one, "1s", "ws_ticker")
    assert d.offer("ETHUSDT", S, one, one) is not None  # per symbol


def test_oi_downsampler_skips_a_ticker_without_oi_and_never_writes_zero() -> None:
    d = TickerDownsampler()
    assert d.offer("BTCUSDT", S, None, Decimal(1)) is None
    assert d.offer("BTCUSDT", S + 1, Decimal(1), Decimal(2)) is not None
    d.forget("BTCUSDT")
    assert d.offer("BTCUSDT", S, Decimal(1), Decimal(2)) is not None


def test_oi_downsampler_keeps_oi_without_a_value_as_null() -> None:
    point = TickerDownsampler().offer("BTCUSDT", S, Decimal("61180"), None)
    assert point is not None
    assert (point.open_interest, point.open_interest_value) == (Decimal("61180"), None)
    assert (point.interval, point.source) == ("1s", "ws_ticker")


@given(st.lists(st.integers(min_value=0, max_value=10**8), max_size=200))
def test_oi_downsampler_output_is_strictly_increasing_in_seconds(ts: list[int]) -> None:
    d = TickerDownsampler()
    out = [p for t in ts if (p := d.offer("BTCUSDT", t, Decimal(1), Decimal(1))) is not None]
    secs = [p.ts_us // S for p in out]
    assert secs == sorted(set(secs))
    assert len(out) <= len({t // S for t in ts})


async def test_oi_backfill_pages_until_complete_and_rerun_writes_no_duplicates() -> None:
    store, fetcher = InMemoryOiStore(), _Fetcher()
    backfill = _backfill(store, fetcher)
    assert await backfill.run_job("BTCUSDT", "5min", WINDOW) == 260
    assert fetcher.calls == [None, PAGES[0].next_cursor]
    assert len(store) == 260
    assert await backfill.run_job("BTCUSDT", "5min", WINDOW) == 260
    assert len(store) == 260  # the dedup key absorbs the re-run
    points = await store.read_points("BTCUSDT", "5min", "rest", WINDOW, 1000)
    assert all(p.source == "rest" and p.open_interest_value is None for p in points)


@pytest.mark.parametrize(
    "failure",
    [
        OiFetchFailed("RateLimitError", retryable=True, http_status=200, ret_code=10018),
        OiFetchFailed("TransportError", retryable=True, http_status=503, ret_code=None),
    ],
    ids=["10018", "503"],
)
async def test_oi_backfill_5xx_and_10018_retry_with_backoff_live_rows_continue(
    failure: OiFetchFailed,
) -> None:
    store, sleep = InMemoryOiStore(), _Sleep()
    backfill = _backfill(store, _Fetcher([failure, failure]), sleep)
    tap = TickerDownsampler()
    live = tap.offer("BTCUSDT", LAST + S, Decimal(5), Decimal(6))
    assert live is not None
    await store.write_points([live])  # the ticker tap writes on its own path
    with capture_logs() as logs:
        assert await backfill.run_job("BTCUSDT", "5min", WINDOW) == 260
    assert sleep.delays == [1.1, 2.2]  # 1 s, 2 s, each +20 % x 0.5 jitter
    assert len(await store.read_points("BTCUSDT", "1s", "ws_ticker", TimeWindow(0, 2**62), 9)) == 1
    warned = [e for e in logs if e["event"] == "oi_backfill_failed"]
    assert [(e["attempt"], e["http_status"], e["interval"]) for e in warned] == [
        (1, failure.http_status, "5min"), (2, failure.http_status, "5min"),
    ]  # fmt: skip
    assert all(e["symbol"] == "BTCUSDT" and e["log_level"] == "warning" for e in warned)


async def test_oi_backfill_gives_up_after_max_attempts_and_on_non_retryable() -> None:
    boom = OiFetchFailed("X", retryable=True, http_status=503, ret_code=None)
    fetcher = _Fetcher([boom] * MAX_ATTEMPTS)
    store = InMemoryOiStore()
    assert await _backfill(store, fetcher).run_job("BTCUSDT", "5min", WINDOW) == 0
    assert len(fetcher.calls) == MAX_ATTEMPTS and len(store) == 0
    once = _Fetcher([OiFetchFailed("Auth", retryable=False, http_status=403, ret_code=None)])
    assert await _backfill(store, once).run_job("BTCUSDT", "5min", WINDOW) == 0
    assert len(once.calls) == 1
    bad = _Fetcher([OiRowRejected("bad", "symbol")])
    assert await _backfill(store, bad).run_job("BTCUSDT", "5min", WINDOW) == 0


async def _drain(backfill: OiBackfill) -> None:
    """Run the worker until every queued job settled (no sleeps: `Queue.join`)."""
    worker = asyncio.create_task(backfill.run())
    try:
        await backfill._queue.join()
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker


async def test_oi_backfill_request_is_bounded_and_queues_an_older_window_only_once() -> None:
    backfill = _backfill(InMemoryOiStore(), _Fetcher())
    assert backfill.request("BTCUSDT", "5min", WINDOW)
    assert not backfill.request("BTCUSDT", "5min", WINDOW)  # pending
    assert backfill.keys() == [("BTCUSDT", "5min")]  # a pending key counts
    await _drain(backfill)
    assert not backfill.request("BTCUSDT", "5min", WINDOW)  # nothing older than completed
    assert backfill.request("BTCUSDT", "5min", TimeWindow(FIRST - STEP, LAST))
    assert not backfill.request("BTCUSDT", "1s", WINDOW)  # the ticker series is never fetched
    assert backfill.keys() == [("BTCUSDT", "5min")]


@pytest.mark.parametrize(
    "failure",
    [
        [OiFetchFailed("X", retryable=True, http_status=503, ret_code=None)] * MAX_ATTEMPTS,
        [OiRowRejected("bad", "symbol")],
    ],
    ids=["retries-exhausted", "page-rejected"],
)
async def test_oi_backfill_failed_job_lets_the_next_request_requeue(
    failure: list[Exception],
) -> None:
    store, fetcher = InMemoryOiStore(), _Fetcher(failure)
    backfill = _backfill(store, fetcher)
    assert backfill.request("BTCUSDT", "5min", WINDOW)
    await _drain(backfill)
    assert len(store) == 0 and backfill._floor == {}
    assert backfill.request("BTCUSDT", "5min", WINDOW)  # not blocked by the failed attempt
    await _drain(backfill)
    assert len(store) == 260
    assert not backfill.request("BTCUSDT", "5min", WINDOW)  # completed now: the floor holds


async def test_oi_backfill_job_raising_keeps_the_worker_and_the_floor() -> None:
    class _Broken(InMemoryOiStore):
        async def write_points(self, rows: Sequence[OiPoint]) -> None:
            raise RuntimeError("store down")

    backfill = _backfill(_Broken(), _Fetcher())
    assert backfill.request("BTCUSDT", "5min", WINDOW)
    with capture_logs() as logs:
        await _drain(backfill)
    assert [e["event"] for e in logs if e["log_level"] == "error"] == ["oi_backfill_job_failed"]
    assert backfill.request("BTCUSDT", "5min", WINDOW)  # the store error raised no floor


async def test_oi_backfill_page_budget_exhausted_with_cursor_is_not_completed() -> None:
    class _Endless(_Fetcher):
        async def __call__(
            self, symbol: str, interval: str, start_us: int, end_us: int, cursor: str | None
        ) -> OiPage:
            self.calls.append(cursor)
            return PAGES[0]  # always carries a next cursor

    fetcher = _Endless()
    backfill = _backfill(InMemoryOiStore(), fetcher)
    assert await backfill.run_once("BTCUSDT", "5min", WINDOW) is False
    assert len(fetcher.calls) == MAX_PAGES_PER_JOB
    assert backfill._floor == {}  # the floor does not rise
    assert backfill.request("BTCUSDT", "5min", WINDOW)  # so the next request re-queues


def test_find_gaps_reports_inner_leading_and_open_tail_spans() -> None:
    pts = [OiPoint(t, "X", Decimal(1), None, "5min", "rest") for t in (STEP, 2 * STEP, 4 * STEP)]
    gaps = find_gaps(pts, start_us=0, end_us=7 * STEP, interval="5min", tail=True)
    assert gaps == ((2 * STEP, 4 * STEP), (4 * STEP, 7 * STEP))
    assert find_gaps(pts, start_us=0, end_us=5 * STEP, interval="5min", tail=True) == (
        (2 * STEP, 4 * STEP),
    )
    assert find_gaps([], start_us=0, end_us=11 * S, interval="1s", tail=False) == ()


def _service(
    store: InMemoryOiStore, listed: bool | None = True, backfill: OiBackfill | None = None
) -> OpenInterestService:
    return OpenInterestService(
        store=store, listed=lambda s: listed, backfill=backfill, clock_s=lambda: NOW_S
    )


async def test_oi_endpoint_reports_gap_in_coverage() -> None:
    store = InMemoryOiStore()
    await _backfill(store, _Fetcher()).run_job("BTCUSDT", "5min", WINDOW)
    hole = PAGES[0][10].ts_us
    store._rows.pop((hole, "BTCUSDT", "5min", "rest"))
    series = await _service(store).series(
        "BTCUSDT", interval="5min", start_us=FIRST, end_us=LAST + 1, limit=500, cursor=None
    )
    assert series.coverage == (FIRST, LAST) and series.source == "rest"
    assert (hole - STEP, hole + STEP) in series.gaps
    assert len(series.points) == 259 and not series.has_more


async def test_oi_series_pages_with_a_series_bound_cursor_ascending() -> None:
    store = InMemoryOiStore()
    await _backfill(store, _Fetcher()).run_job("BTCUSDT", "5min", WINDOW)
    svc = _service(store)
    first = await svc.series(
        "BTCUSDT", interval="5min", start_us=FIRST, end_us=LAST + 1, limit=100, cursor=None
    )
    assert first.has_more and first.next_cursor is not None
    nxt = await svc.series(
        "BTCUSDT", interval="5min", start_us=FIRST, end_us=LAST + 1, limit=500,
        cursor=first.next_cursor,
    )  # fmt: skip
    ts = [p.ts_us for p in first.points + nxt.points]
    assert ts == sorted(ts) and len(ts) == 260
    with pytest.raises(DerivInvalidRequest) as info:
        await svc.series(
            "BTCUSDT", interval="1h", start_us=FIRST, end_us=LAST, limit=5,
            cursor=first.next_cursor,
        )  # fmt: skip
    assert info.value.code == "invalid_cursor"


class _SpyStore(InMemoryOiStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    async def coverage(self, symbol: str, interval: str, source: str) -> tuple[int, int] | None:
        self.reads += 1
        return await super().coverage(symbol, interval, source)


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"start_us": 0, "end_us": 401 * 86_400 * S}, "invalid_time_range"),
        ({"start_us": 2 * S, "end_us": S}, "invalid_time_range"),
        ({"limit": 501}, "validation_failed"),
        ({"interval": "2min"}, "validation_failed"),
        ({"cursor": "x" * 513}, "invalid_cursor"),
        ({"cursor": "@@@"}, "invalid_cursor"),
    ],
)
async def test_oi_out_of_bounds_request_raises_before_any_store_read(
    kw: dict[str, object], code: str
) -> None:
    store = _SpyStore()
    params: dict[str, object] = {
        "interval": "5min", "start_us": None, "end_us": None, "limit": 10, "cursor": None, **kw
    }  # fmt: skip
    with pytest.raises(DerivInvalidRequest) as info:
        await _service(store).series("BTCUSDT", **params)  # type: ignore[arg-type]
    assert info.value.code == code
    assert store.reads == 0 or code == "invalid_cursor"


async def test_oi_unlisted_symbol_raises_and_first_request_queues_one_backfill() -> None:
    with pytest.raises(DerivSymbolUnlisted):
        await _service(InMemoryOiStore(), listed=False).series(
            "BTCUSDT", interval="5min", start_us=None, end_us=None, limit=10, cursor=None
        )
    backfill = _backfill(InMemoryOiStore(), _Fetcher())
    for listed, queued in ((None, 0), (True, 1), (True, 1)):
        svc = _service(InMemoryOiStore(), listed=listed, backfill=backfill)
        series = await svc.series(
            "BTCUSDT", interval="5min", start_us=None, end_us=None, limit=10, cursor=None
        )
        assert series.points == () and series.coverage is None and series.gaps
        assert backfill._queue.qsize() == queued


async def test_oi_requeue_after_coverage_asks_only_the_span_older_than_the_stored_floor() -> None:
    store = InMemoryOiStore()
    await _backfill(store, _Fetcher()).run_job("BTCUSDT", "5min", WINDOW)
    backfill = _backfill(InMemoryOiStore(), _Fetcher())
    await _service(store, backfill=backfill).series(
        "BTCUSDT", interval="5min", start_us=FIRST - 10 * STEP, end_us=LAST + 1, limit=10,
        cursor=None,
    )  # fmt: skip
    queued = backfill._queue.get_nowait()  # up to, not including, the oldest stored point
    assert queued == ("BTCUSDT", "5min", TimeWindow(FIRST - 10 * STEP, FIRST - 1))


class _Venue:
    """A long newest-first history that honours `[start_us, end_us]`, `per_page` rows a page."""

    def __init__(self, rows: int, per_page: int) -> None:
        self.ts = [k * STEP for k in range(1, rows + 1)]
        self.per_page = per_page
        self.calls = 0

    async def __call__(
        self, symbol: str, interval: str, start_us: int, end_us: int, cursor: str | None
    ) -> OiPage:
        self.calls += 1
        hits = [t for t in reversed(self.ts) if start_us <= t <= end_us]
        at = int(cursor or 0)
        more = at + self.per_page < len(hits)
        return OiPage(
            [OiPoint(t, symbol, Decimal(t // STEP), None, interval, "rest")
             for t in hits[at : at + self.per_page]],
            next_cursor=str(at + self.per_page) if more else None,
        )  # fmt: skip


async def test_oi_page_capped_backfill_resumes_from_the_oldest_stored_point_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capped job leaves its rows; the next request resumes below them, never from the top."""
    monkeypatch.setattr("candleviewer.orderflow.open_interest.MAX_PAGES_PER_JOB", 2)
    venue, store = _Venue(rows=50, per_page=5), InMemoryOiStore()
    backfill = OiBackfill(store=store, fetcher=venue, sleep=_Sleep(), random_fn=lambda: 0.5)
    svc = OpenInterestService(
        store=store, listed=lambda s: True, backfill=backfill, clock_s=lambda: 60 * STEP / S
    )
    floors: list[int] = []
    for _ in range(5):  # 50 rows / (2 pages x 5 rows) = 5 capped jobs at most
        await svc.series(
            "BTCUSDT", interval="5min", start_us=0, end_us=55 * STEP, limit=1, cursor=None
        )
        await _drain(backfill)
        cov = await store.coverage("BTCUSDT", "5min", "rest")
        assert cov is not None
        floors.append(cov[0])
    assert floors == [41 * STEP, 31 * STEP, 21 * STEP, 11 * STEP, STEP]  # progress every cycle
    assert len(store) == 50
    await svc.series("BTCUSDT", interval="5min", start_us=0, end_us=55 * STEP, limit=1, cursor=None)
    await _drain(backfill)  # one more short job reaches the venue's end and completes
    calls = venue.calls
    await svc.series("BTCUSDT", interval="5min", start_us=0, end_us=55 * STEP, limit=1, cursor=None)
    assert backfill._queue.qsize() == 0 and venue.calls == calls  # the floor holds: no re-fetch


class _Hang(_Fetcher):
    async def __call__(
        self, symbol: str, interval: str, start_us: int, end_us: int, cursor: str | None
    ) -> OiPage:
        self.calls.append(cursor)
        await asyncio.Event().wait()  # never answers; the per-await timeout ends it
        raise AssertionError("unreachable")


async def test_oi_backfill_fetch_timeout_is_a_retryable_failure_that_completes_nothing() -> None:
    fetcher, sleep, store = _Hang(), _Sleep(), InMemoryOiStore()
    backfill = OiBackfill(
        store=store, fetcher=fetcher, sleep=sleep, random_fn=lambda: 0.5, fetch_timeout_s=0
    )
    with capture_logs() as logs:
        assert await backfill.run_once("BTCUSDT", "5min", WINDOW) is False
    assert len(fetcher.calls) == MAX_ATTEMPTS and len(sleep.delays) == MAX_ATTEMPTS - 1
    assert [e["event"] for e in logs] == ["oi_backfill_timeout"] * MAX_ATTEMPTS
    assert backfill._floor == {} and len(store) == 0


async def test_oi_backfill_store_timeout_fails_the_job_and_raises_no_floor() -> None:
    class _Stuck(InMemoryOiStore):
        async def write_points(self, rows: Sequence[OiPoint]) -> None:
            await asyncio.Event().wait()

    backfill = OiBackfill(
        store=_Stuck(), fetcher=_Fetcher(), sleep=_Sleep(), random_fn=lambda: 0.5,
        store_timeout_s=0,
    )  # fmt: skip
    with pytest.raises(TimeoutError):
        await backfill.run_once("BTCUSDT", "5min", WINDOW)
    assert backfill._floor == {}
