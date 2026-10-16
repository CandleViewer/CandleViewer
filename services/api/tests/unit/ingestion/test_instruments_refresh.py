"""Unit tests for `InstrumentsRefreshScheduler` (E08-S01-2 Gherkin AC):
startup load, refresh without restart, tick-size change -> version row +
bus publish, refresh failure -> stale_since + error metric + previous
snapshot kept, on-demand throttle. No network, no DB, fake clock/sleep."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments_refresh import (
    RETRY_BACKOFF_MAX_S,
    RETRY_BACKOFF_MIN_S,
    InstrumentRefreshError,
    InstrumentsRefreshScheduler,
    retry_backoff_s,
)
from candleviewer.ingestion.metrics import instruments_refresh_total

_BASE: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "baseCoin": "BTC",
    "quoteCoin": "USDT",
    "settleCoin": "USDT",
    "status": "Trading",
    "launchTime": "1585699200000",
    "priceScale": "2",
    "priceFilter": {"tickSize": "0.10", "minPrice": "0.10", "maxPrice": "999999.00"},
    "lotSizeFilter": {
        "qtyStep": "0.001",
        "minOrderQty": "0.001",
        "maxOrderQty": "100.000",
        "maxMktOrderQty": "50.000",
        "minNotionalValue": "5",
    },
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "100.00", "leverageStep": "0.01"},
    "fundingInterval": 480,
    "upperFundingRate": "0.00375",
    "lowerFundingRate": "-0.00375",
    "copyTrading": "both",
}


def raw(symbol: str = "BTCUSDT", **overrides: Any) -> dict[str, Any]:
    r = copy.deepcopy(_BASE)
    r["symbol"] = symbol
    r["baseCoin"] = symbol.removesuffix("USDT")
    r.update(overrides)
    return r


class FakeRepo:
    def __init__(self, persisted: Sequence[Mapping[str, Any]] = ()) -> None:
        self.persisted = list(persisted)
        self.snapshots: list[list[Mapping[str, Any]]] = []
        self.versions: list[tuple[Mapping[str, Any], tuple[str, ...]]] = []
        self.stale: list[int] = []

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.snapshots.append(list(rows))
        self.persisted = list(rows)

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        self.versions.append((row, tuple(changed_fields)))

    async def mark_stale(self, *, stale_since_us: int) -> None:
        self.stale.append(stale_since_us)

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        return self.persisted


class Clock:
    def __init__(self) -> None:
        self.us = 1_700_000_000_000_000

    def __call__(self) -> int:
        return self.us


#: The shortest wait the refresh schedule can choose (#2599: the first retry backoff with no
#: jitter); the TTL wait is far longer. In-refresh retry backoffs are shorter: 0 s under
#: `make()`, which pins `random_fn` to 0.
_SHORTEST_SCHEDULE_WAIT_S = retry_backoff_s(1, 0.0)


async def _no_sleep(delay: float) -> None:
    """In-refresh retry backoffs return at once; every schedule wait (the TTL, or the #2599
    retry backoff) parks until `stop()` cancels the task, so a failing schedule never spins
    without yielding to the event loop (never a real sleep, C-13.7)."""
    if delay >= _SHORTEST_SCHEDULE_WAIT_S:
        await asyncio.Event().wait()


class ParkingSleep:
    """Fake schedule `sleep`: records each delay and parks the caller until `release()`, so a
    test steps the refresh schedule one wait at a time (no real time passes, C-13.7)."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self._parked: list[asyncio.Future[None]] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        wake: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._parked.append(wake)
        await wake

    def release(self) -> None:
        while self._parked[0].done():  # a wait cut short (#2715: a TTL wait) is skipped
            self._parked.pop(0)
        self._parked.pop(0).set_result(None)


async def _settle() -> None:
    """Let the scheduler's task run until it parks again (event-loop turns, no time passes)."""
    for _ in range(50):
        await asyncio.sleep(0)


def make(
    pages: list[Any],
    repo: FakeRepo | None = None,
    clock: Clock | None = None,
    *,
    sleep: Callable[[float], Awaitable[None]] = _no_sleep,
    max_retries: int = 3,
) -> tuple[InstrumentsRefreshScheduler, FakeRepo, list[InstrumentUpdatedEvent], Clock]:
    """`pages`: each fetch pops the next entry; an Exception entry is raised."""
    repo = repo or FakeRepo()
    clock = clock or Clock()
    published: list[InstrumentUpdatedEvent] = []

    async def fetch(now_us: Callable[[], int]) -> InstrumentsFetchResult:
        item = pages.pop(0) if len(pages) > 1 else pages[0]
        if isinstance(item, Exception):
            raise item
        return parse_instruments(list(item), fetched_at_us=now_us())

    async def publish(event: Any) -> None:
        published.append(event)

    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch,
        repository=repo,
        publish=publish,
        now_us=clock,
        sleep=sleep,
        random_fn=lambda: 0.0,
        max_retries=max_retries,
    )
    return sched, repo, published, clock


def _count(result: str) -> float:
    value: float = instruments_refresh_total.labels(result=result)._value.get()
    return value


async def test_refresh_now_populates_snapshot_and_persists() -> None:
    sched, repo, published, _ = make([[raw("BTCUSDT"), raw("ETHUSDT")]])
    await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None and set(snap.by_symbol) == {"BTCUSDT", "ETHUSDT"}
    assert len(repo.snapshots) == 1 and len(repo.snapshots[0]) == 2
    assert published == []  # new symbols are not "updates"


async def test_new_listing_appears_on_refresh_without_restart() -> None:
    sched, _, _, _ = make([[raw("BTCUSDT")], [raw("BTCUSDT"), raw("SOLUSDT")]])
    await sched.refresh_now()
    assert sched.snapshot().get("SOLUSDT") is None  # type: ignore[union-attr]  # set above
    await sched.refresh_now()
    assert sched.snapshot().get("SOLUSDT") is not None  # type: ignore[union-attr]  # set above


async def test_tick_size_change_records_version_and_publishes_event() -> None:
    changed = raw(priceFilter={"tickSize": "0.50", "minPrice": "0.10", "maxPrice": "999999.00"})
    sched, repo, published, _ = make([[raw()], [changed]])
    await sched.refresh_now()
    await sched.refresh_now()
    inst = sched.snapshot().get("BTCUSDT")  # type: ignore[union-attr]  # set above
    assert inst is not None and inst.metadata_version == 2
    assert len(repo.versions) == 1 and "tick_size" in repo.versions[0][1]
    assert len(published) == 1
    assert published[0].symbol == "BTCUSDT" and published[0].metadata_version == 2


async def test_unchanged_refresh_is_noop_for_versions() -> None:
    sched, repo, published, _ = make([[raw()], [raw()]])
    await sched.refresh_now()
    await sched.refresh_now()
    assert repo.versions == [] and published == []


async def test_refresh_failure_keeps_previous_snapshot_and_marks_stale() -> None:
    sched, repo, _, clock = make([[raw()], RuntimeError("boom")])
    await sched.refresh_now()
    before = _count("error")
    clock.us += 5_000_000
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None and snap.get("BTCUSDT") is not None  # never empty
    assert snap.stale_since_us == clock.us
    assert repo.stale == [clock.us]
    assert _count("error") == before + 1
    first = clock.us
    clock.us += 5_000_000
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    assert sched.snapshot().stale_since_us == first  # type: ignore[union-attr]  # set above


async def test_successful_refresh_clears_stale() -> None:
    sched, _, _, _ = make(
        [[raw()], RuntimeError("x"), RuntimeError("x"), RuntimeError("x"), [raw()]]
    )
    await sched.refresh_now()
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    await sched.refresh_now()
    assert sched.snapshot().stale_since_us is None  # type: ignore[union-attr]  # set above


async def test_start_loads_persisted_when_fetch_fails() -> None:
    seed, _, _, _ = make([[raw()]])
    await seed.refresh_now()
    persisted = seed.snapshot().get("BTCUSDT").model_dump(mode="json")  # type: ignore[union-attr]  # set above
    sched, _, _, _ = make([RuntimeError("down")], repo=FakeRepo([persisted]))
    await sched.start()
    try:
        snap = sched.snapshot()
        assert snap is not None and snap.get("BTCUSDT") is not None
    finally:
        await sched.stop(grace_s=1.0)


async def test_no_sleep_parks_the_retry_schedule_after_a_failed_start() -> None:
    """#2599 review (C-13.7): `make()`'s default sleep parks every schedule wait, the short
    retry backoff included; returning at once would spin a failing schedule without ever
    yielding. This fetch yields, so a regression fails on the count instead of hanging."""
    calls = 0

    async def fetch(_now_us: Callable[[], int]) -> InstrumentsFetchResult:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        raise RuntimeError("exchange down")

    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch, repository=FakeRepo(), sleep=_no_sleep, random_fn=lambda: 0.0
    )
    await sched.start()
    try:
        await _settle()
        assert calls == 3  # the startup refresh's attempts only: the schedule is parked
    finally:
        await sched.stop(grace_s=1.0)


async def test_ensure_symbol_triggers_one_refresh_then_throttles() -> None:
    sched, _, _, clock = make([[raw()], [raw(), raw("NEWUSDT")]])
    await sched.refresh_now()
    found = await sched.ensure_symbol("NEWUSDT")
    assert found is not None and found.symbol == "NEWUSDT"
    before = _count("throttled")
    assert await sched.ensure_symbol("NOPEUSDT") is None
    assert _count("throttled") == before + 1
    clock.us += 61_000_000
    assert await sched.ensure_symbol("BTCUSDT") is not None  # cached path, no fetch


async def test_zero_parseable_rows_is_an_error_not_an_empty_catalogue() -> None:
    sched, _, _, _ = make([[raw()], [{"symbol": "BAD"}]])
    await sched.refresh_now()
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    assert sched.snapshot().get("BTCUSDT") is not None  # type: ignore[union-attr]  # set above


async def test_stop_propagates_cancellation_of_its_caller() -> None:
    sched, _, _, _ = make([[raw()]])
    await sched.start()

    # Make the periodic task ignore cancel for a while so stop() is waiting.
    blocker = asyncio.Event()

    async def _stubborn() -> None:
        try:
            await blocker.wait()
        except asyncio.CancelledError:
            await blocker.wait()

    sched._task.cancel()  # type: ignore[union-attr]  # replace the real loop
    stubborn = asyncio.create_task(_stubborn())
    sched._task = stubborn
    await asyncio.sleep(0)
    caller = asyncio.create_task(sched.stop(grace_s=1_000.0))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    blocker.set()
    await stubborn


async def test_listener_awaited_after_swap_and_fault_isolated() -> None:
    """#1913: delist teardown hooks the swap; a listener fault never fails refresh."""
    sched, _, _, _ = make([[raw("BTCUSDT"), raw("LUNAUSDT")], [raw("LUNAUSDT", status="Closed")]])
    seen: list[str | None] = []

    async def listener() -> None:
        snap = sched.snapshot()
        luna = snap.get("LUNAUSDT") if snap is not None else None
        seen.append(None if luna is None else luna.status)

    async def broken() -> None:
        raise RuntimeError("consumer bug")

    sched.add_listener(listener)
    sched.add_listener(listener)  # idempotent
    sched.add_listener(broken)
    await sched.refresh_now()
    await sched.refresh_now()
    assert len(seen) == 2 and seen[0] == "trading" and seen[1] != "trading"


async def test_failed_cold_start_retries_within_minutes_not_after_the_ttl() -> None:
    """#2599: nothing persisted and the startup fetch fails -> the schedule retries on a short
    backoff (seconds to minutes), never the 12 h TTL; once a retry loads the catalogue, the
    schedule goes back to the TTL."""
    sleep = ParkingSleep()
    sched, _, _, _ = make([RuntimeError("exchange down"), [raw()]], sleep=sleep, max_retries=1)
    await sched.start()
    try:
        assert sched.snapshot() is None  # cold: nothing persisted, the startup fetch failed
        await _settle()
        assert len(sleep.delays) == 1 and sleep.delays[0] <= 300.0  # minutes at most, not 12 h
        sleep.release()
        await _settle()
        snap = sched.snapshot()
        assert snap is not None and snap.get("BTCUSDT") is not None
        assert len(sleep.delays) == 2 and sleep.delays[1] >= 43_200.0  # back on the TTL
    finally:
        await sched.stop(grace_s=1.0)


async def test_failed_refreshes_back_off_doubling_up_to_the_cap() -> None:
    """#2599: consecutive failures double the wait (equal jitter; `random_fn` is 0 here, so
    each wait is half its step) up to the five-minute cap, and never reach the TTL."""
    sleep = ParkingSleep()
    sched, _, _, _ = make([RuntimeError("exchange down")], sleep=sleep, max_retries=1)
    await sched.start()
    try:
        for _ in range(9):
            await _settle()
            sleep.release()
        await _settle()
        steps = [min(RETRY_BACKOFF_MAX_S, RETRY_BACKOFF_MIN_S * 2**n) for n in range(10)]
        assert sleep.delays == [step / 2 for step in steps]
        assert sched.snapshot() is None
    finally:
        await sched.stop(grace_s=1.0)


async def test_failed_scheduled_refresh_of_a_loaded_catalogue_retries_soon() -> None:
    """#2599: the same backoff follows any failed refresh, so a stale catalogue (and the
    `catalogue_stale` readiness reason) recovers within minutes, not after another TTL."""
    sleep = ParkingSleep()
    sched, _, _, _ = make([[raw()], RuntimeError("blip"), [raw()]], sleep=sleep, max_retries=1)
    await sched.start()
    try:
        await _settle()
        sleep.release()  # the TTL elapses; the scheduled refresh fails
        await _settle()
        assert sched.snapshot().stale_since_us is not None  # type: ignore[union-attr]  # loaded
        sleep.release()  # the short retry succeeds
        await _settle()
        assert sleep.delays[0] >= 43_200.0 and sleep.delays[1] <= RETRY_BACKOFF_MIN_S
        assert sleep.delays[2] >= 43_200.0  # back on the TTL
        assert sched.snapshot().stale_since_us is None  # type: ignore[union-attr]  # loaded
    finally:
        await sched.stop(grace_s=1.0)


async def test_failed_on_demand_refresh_ends_the_ttl_wait_and_retries_soon() -> None:
    """#2715 review: a failed on-demand refresh marks the catalogue stale (`catalogue_stale`)
    while the schedule waits out the 12 h TTL; the wait ends and the schedule retries on the
    #2599 backoff, so the degraded window is seconds to minutes, not up to the TTL."""
    sleep = ParkingSleep()
    sched, _, _, _ = make([[raw()], RuntimeError("blip"), [raw()]], sleep=sleep, max_retries=1)
    await sched.start()
    try:
        await _settle()
        assert len(sleep.delays) == 1 and sleep.delays[0] >= 43_200.0  # waiting out the TTL
        assert await sched.ensure_symbol("NEWUSDT") is None  # the on-demand refresh fails
        assert sched.snapshot().stale_since_us is not None  # type: ignore[union-attr]  # loaded
        await _settle()
        assert sleep.delays[1:] == [RETRY_BACKOFF_MIN_S / 2]  # the backoff, not the TTL
        sleep.release()  # the retry succeeds
        await _settle()
        assert sched.snapshot().stale_since_us is None  # type: ignore[union-attr]  # loaded
        assert len(sleep.delays) == 3 and sleep.delays[2] >= 43_200.0  # back on the TTL
    finally:
        await sched.stop(grace_s=1.0)


async def test_start_abandons_a_hanging_startup_fetch_and_retries_soon() -> None:
    """#2599: boot (the supervisor awaits `start()`) never waits on the exchange for longer than
    `start_timeout_s`: the hanging fetch is abandoned and the schedule retries it shortly."""
    exchange_up = asyncio.Event()

    async def fetch(now_us: Callable[[], int]) -> InstrumentsFetchResult:
        await exchange_up.wait()  # no answer until the test says so
        return parse_instruments([raw()], fetched_at_us=now_us())

    sleep = ParkingSleep()
    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch,
        repository=FakeRepo(),
        now_us=Clock(),
        sleep=sleep,
        random_fn=lambda: 0.0,
        start_timeout_s=0.0,
    )
    await sched.start()  # returns although the exchange never answered
    try:
        assert sched.snapshot() is None
        await _settle()
        assert sleep.delays == [RETRY_BACKOFF_MIN_S / 2]  # a short retry, not the TTL
        exchange_up.set()
        sleep.release()
        await _settle()
        assert sched.snapshot() is not None
    finally:
        await sched.stop(grace_s=1.0)


async def test_start_cancelled_during_the_startup_fetch_leaves_no_task() -> None:
    """Cancelling `start()` (boot aborted) propagates and schedules nothing."""
    hang = asyncio.Event()

    async def fetch(now_us: Callable[[], int]) -> InstrumentsFetchResult:
        await hang.wait()
        raise AssertionError("unreachable")

    sched = InstrumentsRefreshScheduler(fetch_instruments_info=fetch, repository=FakeRepo())
    starting = asyncio.create_task(sched.start())
    await _settle()
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert sched._task is None


@settings(max_examples=200, deadline=None)
@given(failures=st.integers(min_value=1, max_value=100_000), rand=st.floats(0.0, 1.0))
def test_retry_backoff_is_bounded_for_any_outage(failures: int, rand: float) -> None:
    """Never sooner than half the first step, never past the cap, never an overflow."""
    delay = retry_backoff_s(failures, rand)
    assert RETRY_BACKOFF_MIN_S / 2 <= delay <= RETRY_BACKOFF_MAX_S
