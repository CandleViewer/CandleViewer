"""E08-T08 (#4707): the shared venue-wide ticker snapshot behind `GET /market/tickers`, and the
read-only `UniverseTickerSource` the scanner (#4708) shares with the route.

Fake clocks and a fake venue read (no network, no sleeps): one read per `REFRESH_S` however many
consumers ask, failures included; fresh within `FRESH_S`, served `stale` up to `SERVE_MAX_S`,
refused past it; one read in flight, a bounded wait on it, a bounded number of waiters.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.ticker_delta import TickerDelta
from candleviewer.exchange.base.universe import TickerPage, UniverseSnapshot, UniverseTickerSource
from candleviewer.ingestion.ticker_bulk import (
    FRESH_S,
    OUTCOMES,
    REFRESH_S,
    SERVE_MAX_S,
    AgeGauge,
    TickerBulkCache,
    TickersUnavailable,
    normalise,
)
from candleviewer.observability.metrics import NOOP_CHILD, Metrics
from candleviewer.observability.metrics_catalogue import register_r0

VENUE_TS_US = 1_792_391_746_229_000
ROW = TickerDelta("BTCUSDT", True, VENUE_TS_US, {"last_price": Decimal("82751.20")})
PAGE = TickerPage(VENUE_TS_US, {"BTCUSDT": ROW})


class Clock:
    """Monotonic seconds, and the wall clock in µs moving with it."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def wall_us(self) -> int:
        return 1_800_000_000_000_000 + int(self.t * 1e6)


class Venue:
    """The venue-wide read: counts calls; `gate` holds one open, `fail` makes it raise."""

    def __init__(self) -> None:
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.fail: Exception | None = None

    async def __call__(self) -> TickerPage:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return PAGE


class _Child:
    def __init__(self) -> None:
        self.count = 0
        self.function: Callable[[], float] | None = None

    def inc(self, amount: float = 1) -> None:
        self.count += int(amount)

    def set_function(self, function: Callable[[], float]) -> None:
        self.function = function


class _Counter:
    def __init__(self) -> None:
        self.children: dict[str, _Child] = {}

    def labels(self, *values: str) -> _Child:
        return self.children.setdefault(values[0], _Child())


async def _inline(page: TickerPage, received_at_us: int) -> tuple[UniverseSnapshot, int]:
    return normalise(page, received_at_us)  # on the loop: no thread for a test to wait on


def _cache(venue: Venue, clock: Clock, **kw: Any) -> TickerBulkCache:
    return TickerBulkCache(venue, clock=clock, now_us=clock.wall_us, normalised=_inline, **kw)


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until `predicate` holds (bounded: a regression fails, never hangs)."""
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0)
    pytest.fail("condition never held")


def test_a_row_normalises_into_a_ticker_event_at_the_venues_time() -> None:
    universe, refused = normalise(PAGE, 7)
    event = universe.tickers["BTCUSDT"]
    assert (universe.received_at_us, universe.exchange_ts_us, refused) == (7, VENUE_TS_US, 0)
    assert (event.ts_event, event.ts_ingest, event.is_delta) == (VENUE_TS_US, 7, False)
    assert event.last_price == Decimal("82751.20") and event.high_24h is None


def test_a_row_the_model_refuses_is_left_out_and_counted() -> None:
    bad = TickerDelta("ETHUSDT", True, VENUE_TS_US, {"next_funding_time": Decimal("0.5")})
    universe, refused = normalise(TickerPage(VENUE_TS_US, {"BTCUSDT": ROW, "ETHUSDT": bad}), 7)
    assert (list(universe.tickers), refused) == (["BTCUSDT"], 1)


async def test_a_snapshot_at_most_fresh_s_old_answers_without_a_read() -> None:
    venue, clock = Venue(), Clock()
    cache = _cache(venue, clock)
    first = await cache.serve()
    assert (first.stale, first.universe.received_at_us) == (False, clock.wall_us())
    clock.t += FRESH_S  # exactly the bound: still fresh
    assert (await cache.serve()).stale is False and venue.calls == 1
    clock.t += 0.01
    assert (await cache.serve()).stale is False and venue.calls == 2  # expired: read again


async def test_twenty_concurrent_requests_share_one_read() -> None:
    venue, clock = Venue(), Clock()
    venue.gate = asyncio.Event()
    cache = _cache(venue, clock)
    tasks = [asyncio.create_task(cache.serve()) for _ in range(20)]
    await _until(lambda: cache.waiters == 20)
    venue.gate.set()
    answers = await asyncio.gather(*tasks)
    assert venue.calls == 1 and cache.waiters == 0
    assert len({id(a.universe) for a in answers}) == 1 and not any(a.stale for a in answers)


async def test_a_failed_read_counts_toward_the_spacing_and_the_bound_holds() -> None:
    venue, clock = Venue(), Clock()
    cache = _cache(venue, clock)
    await cache.serve()  # the snapshot, received at t0
    venue.fail = RuntimeError("venue down")
    clock.t += 6.0
    assert (await cache.serve()).stale is True and venue.calls == 2  # failed: the snapshot answers
    clock.t += 1.0
    assert (await cache.serve()).stale is True and venue.calls == 2  # spacing: no read may start
    clock.t += REFRESH_S - 1.0
    assert (await cache.serve()).stale is True and venue.calls == 3
    clock.t = 100.0 + SERVE_MAX_S + 0.5  # past the bound, next read not due for 0.5 s
    with pytest.raises(TickersUnavailable) as refused:
        await cache.serve()
    assert venue.calls == 3 and refused.value.retry_after_s == 1


async def test_no_snapshot_and_a_failed_read_is_refused_with_the_seconds_to_the_next() -> None:
    venue, clock = Venue(), Clock()
    venue.fail = RuntimeError("venue down")
    cache = _cache(venue, clock)
    with pytest.raises(TickersUnavailable) as first:
        await cache.serve()
    clock.t += 2.2
    with pytest.raises(TickersUnavailable) as later:
        await cache.serve()
    assert venue.calls == 1 and (first.value.retry_after_s, later.value.retry_after_s) == (5, 3)


@pytest.mark.parametrize("snapshot", [True, False])
async def test_one_request_past_the_waiting_bound_does_not_wait(snapshot: bool) -> None:
    venue, clock = Venue(), Clock()
    cache = _cache(venue, clock, max_waiters=2)
    if snapshot:
        await cache.serve()
        clock.t += FRESH_S + 1.0
    venue.gate = asyncio.Event()
    waiting = [asyncio.create_task(cache.serve()) for _ in range(2)]
    await _until(lambda: cache.waiters == 2)
    if snapshot:  # answered at once from the snapshot within its bound, never queued
        assert (await cache.serve()).stale is True
    else:
        with pytest.raises(TickersUnavailable):
            await cache.serve()
    assert cache.waiters == 2
    venue.gate.set()
    await asyncio.gather(*waiting)
    assert venue.calls == 1 + snapshot


async def test_the_wait_has_a_deadline_and_the_read_goes_on_for_the_next_request() -> None:
    venue, clock = Venue(), Clock()
    venue.gate = asyncio.Event()
    cache = _cache(venue, clock, wait_s=0.001)
    with pytest.raises(TickersUnavailable):
        await cache.serve()  # nothing to fall back on while the read is still out
    venue.gate.set()
    await _until(lambda: cache.age_s() == 0.0)
    assert (await cache.serve()).stale is False and venue.calls == 1


async def test_latest_reads_nothing_and_refresh_honours_the_bounds() -> None:
    """`UniverseTickerSource`: `latest()` is no read; `refresh()` reads past 5 s, single flight;
    after a failed read the last snapshot until 15 s old, then `None`, from both."""
    venue, clock = Venue(), Clock()
    cache = _cache(venue, clock)
    source: UniverseTickerSource = cache
    assert source.latest() is None and venue.calls == 0
    fresh = await source.refresh()
    assert isinstance(fresh, UniverseSnapshot) and venue.calls == 1
    assert source.latest() is fresh and await source.refresh() is fresh and venue.calls == 1
    venue.fail = RuntimeError("venue down")
    clock.t += FRESH_S + 1.0
    assert await source.refresh() is fresh and venue.calls == 2
    clock.t += SERVE_MAX_S - FRESH_S - 1.0  # 15 s: still served
    assert source.latest() is fresh and venue.calls == 2
    clock.t += 0.5
    assert source.latest() is None and await source.refresh() is None and venue.calls == 3


async def test_outcomes_are_counted_and_the_age_is_read_at_scrape_time() -> None:
    venue, clock = Venue(), Clock()
    refreshes, age = _Counter(), _Child()
    cache = _cache(venue, clock, refreshes=refreshes, age=age, read_timeout_s=0.05)
    assert age.function is not None and age.function() == math.inf  # before the first read
    await cache.serve()
    clock.t += 7.0
    assert age.function() == 7.0
    venue.fail = RuntimeError("venue down")
    await cache.serve()
    clock.t += REFRESH_S
    venue.fail, venue.gate = None, asyncio.Event()  # a read that never answers in time
    await cache.serve()
    assert set(refreshes.children) == set(OUTCOMES)
    assert {k: c.count for k, c in refreshes.children.items()} == {
        "ok": 1,
        "error": 1,
        "timeout": 1,
    }


def test_the_facades_age_gauge_is_an_age_gauge_and_a_scrape_reads_it() -> None:
    """The composition root hands the cache the facade's child of the catalogued gauge only when it
    is an `AgeGauge`, which the facade's no-op child is not."""
    metrics = Metrics("dev")
    child = register_r0(metrics)["ticker_bulk_cache_age_seconds"].child()
    assert isinstance(child, AgeGauge) and not isinstance(NOOP_CHILD, AgeGauge)
    _cache(Venue(), Clock(), age=child)
    sample = metrics.registry.get_sample_value("ticker_bulk_cache_age_seconds", {"env": "dev"})
    assert sample == math.inf  # read at scrape time: no snapshot yet


async def test_aclose_cancels_a_read_in_flight_and_starts_none_after() -> None:
    venue, clock = Venue(), Clock()
    venue.gate = asyncio.Event()
    cache = _cache(venue, clock, wait_s=0.001)
    with pytest.raises(TickersUnavailable):
        await cache.serve()
    await cache.aclose()
    clock.t += REFRESH_S
    venue.gate.set()
    with pytest.raises(TickersUnavailable):
        await cache.serve()  # the cancelled read installed nothing, and no read starts now
    assert venue.calls == 1


async def test_closed_before_any_read_it_refuses_with_a_retry_of_one_never_an_overflow() -> None:
    """No read ever started, so none is due: the retry is the bound's floor, 1 s."""
    venue, clock = Venue(), Clock()
    cache = _cache(venue, clock)
    await cache.aclose()
    with pytest.raises(TickersUnavailable) as refused:
        await cache.serve()
    assert (refused.value.retry_after_s, venue.calls) == (1, 0)
