"""#2702: the on-demand catalogue refresh behind `GET /instruments/{symbol}` is bounded.

It is one shared, tracked task: a caller waits on it for at most `on_demand_timeout_s` (the route
then answers 503) and never cancels it; a concurrent caller joins it; a caller queued behind a
refresh that loaded the catalogue does not fetch again; `stop()` cancels and awaits it. An
abandoned startup fetch counts `result="timeout"` and serves a warm snapshot stale. Recorded
catalogue rows only (C-13.5); no real time passes (C-13.7).

#906 (B8): `ensure_fresh(max_age_s, deadline_s)` is the same shared, tracked task behind a freshness
check: a catalogue young enough and not marked stale returns at once; otherwise callers join one
refresh, wait for it at most `deadline_s` and never cancel it."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from structlog.testing import capture_logs

from candleviewer.api.instruments import InstrumentsPrincipal, make_instruments_router
from candleviewer.exchange.base.instruments import InstrumentsFetcher, InstrumentsFetchResult
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion import instruments_refresh
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.ingestion.metrics import instruments_refresh_total
from tests._corpus import rest
from tests.unit.ingestion._fakes import settle

_NOW = 1_700_000_000_000_000
#: The recorded `instruments-info` page: BTCUSDT, ETHUSDT, SOLUSDT, LUNAUSDT.
_ROWS: list[dict[str, Any]] = rest("rest/instruments_before.json")["result"]["list"]


def _parsed(*symbols: str) -> InstrumentsFetchResult:
    return parse_instruments(
        [r for r in _ROWS if not symbols or r["symbol"] in symbols], fetched_at_us=_NOW
    )


class HangingFetch:
    """`instruments-info` double: counts calls; each one hangs until `up` is set (an exchange
    that stopped answering, then recovered) and returns the recorded page."""

    def __init__(self) -> None:
        self.calls = 0
        self.up = asyncio.Event()

    async def __call__(self, now_us: Callable[[], int]) -> InstrumentsFetchResult:
        self.calls += 1
        await self.up.wait()
        return _parsed()


class MemoryRepo:
    """Catalogue repository double (no database)."""

    def __init__(self, rows: Sequence[Mapping[str, Any]] = ()) -> None:
        self.rows = list(rows)

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.rows = list(rows)

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        return self.rows


async def _park(_delay: float) -> None:
    """Every schedule wait parks until `stop()` cancels it."""
    await asyncio.Event().wait()


#: `asyncio.timeout` runs on the loop's wall clock: callers that must not hit the on-demand
#: deadline get one a stalled runner never reaches, not the 3 s default (C-13.7). The deadline
#: test passes its own bound.
_NO_DEADLINE_S = 1e9
#: #906: the profile save's rule, a catalogue fetched within 15 minutes.
_MAX_AGE_S = 900.0
#: A deadline that passes within a few loop turns (the bound must be positive): the tests that
#: rely on it never release their fetch, so only the deadline can end the wait.
_PAST_S = 1e-6


def _scheduler(
    fetch: InstrumentsFetcher,
    repo: MemoryRepo | None = None,
    *,
    on_demand_timeout_s: float = _NO_DEADLINE_S,
    **bounds: Any,
) -> instruments_refresh.InstrumentsRefreshScheduler:
    return instruments_refresh.InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch,
        repository=repo or MemoryRepo(),
        now_us=lambda: _NOW,
        sleep=_park,
        random_fn=lambda: 0.0,
        on_demand_timeout_s=on_demand_timeout_s,
        **bounds,
    )


def _warm(
    sched: instruments_refresh.InstrumentsRefreshScheduler,
    *symbols: str,
    age_s: float = 0.0,
    stale: bool = False,
) -> CatalogueSnapshot:
    """Swap in the recorded catalogue, fetched `age_s` ago and marked stale if `stale`."""
    loaded = {i.symbol: i for i in _parsed(*symbols).instruments}
    snapshot = CatalogueSnapshot(
        by_symbol=loaded,
        fetched_at_us=_NOW - round(age_s * 1_000_000),
        stale_since_us=_NOW if stale else None,
    )
    sched.cache.swap(snapshot)
    return snapshot


def _count(result: str) -> float:
    value: float = instruments_refresh_total.labels(result=result)._value.get()
    return value


async def _ended(
    sched: instruments_refresh.InstrumentsRefreshScheduler,
    max_age_s: float = _MAX_AGE_S,
    deadline_s: float = _PAST_S,
) -> asyncio.Task[CatalogueSnapshot | None]:
    """`ensure_fresh` as a task that has ended after a few loop turns, whatever it ended in. For a
    call that must not wait: one that would (a fetch that hangs, a deadline that never comes)
    fails here, so a regression never hangs the run. The default deadline is a few microseconds,
    which only a hung fetch reaches."""
    call = asyncio.create_task(sched.ensure_fresh(max_age_s, deadline_s))
    await settle()
    if not call.done():
        call.cancel()
        pytest.fail("ensure_fresh was still waiting")
    return call


class _Viewer:
    def resolve(self, request: Request) -> InstrumentsPrincipal:
        return InstrumentsPrincipal(user_id="u", permissions=frozenset({"instruments:read"}))


async def test_detail_route_answers_503_at_the_deadline_and_the_refresh_runs_on() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch, on_demand_timeout_s=0.0)
    _warm(sched, "BTCUSDT")
    app = FastAPI()
    app.include_router(make_instruments_router(lambda: sched, principal_resolver=_Viewer()))
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get("/instruments/SOLUSDT")  # the exchange never answers
            assert r.status_code == 503
            assert r.json() == {  # the route's "not loaded" problem, unchanged
                "type": "about:blank",
                "title": "Service unavailable",
                "status": 503,
                "detail": "instrument catalogue not loaded yet",
            }
            refresh = sched._on_demand
            assert refresh is not None and not refresh.done()  # the caller did not cancel it
            fetch.up.set()
            await refresh
            r = await client.get("/instruments/SOLUSDT")
            assert r.status_code == 200 and r.json()["symbol"] == "SOLUSDT"
        assert fetch.calls == 1
    finally:
        await sched.stop(grace_s=1.0)


async def test_ensure_symbol_concurrent_caller_joins_the_in_flight_refresh() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT")
    first = asyncio.create_task(sched.ensure_symbol("SOLUSDT"))
    await settle()
    second = asyncio.create_task(sched.ensure_symbol("ETHUSDT"))  # not throttled: it joins
    await settle()
    fetch.up.set()
    assert await first is not None and await second is not None
    assert fetch.calls == 1


@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
async def test_ensure_symbol_queued_behind_a_loading_refresh_does_not_fetch_again(
    warm: bool,
) -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    if warm:
        _warm(sched, "BTCUSDT")
    scheduled = asyncio.create_task(sched.refresh_now())  # e.g. the schedule's retry
    await settle()
    caller = asyncio.create_task(sched.ensure_symbol("SOLUSDT"))  # queues for the lock
    await settle()
    fetch.up.set()
    await scheduled
    found = await caller
    assert found is not None and found.symbol == "SOLUSDT"
    assert fetch.calls == 1  # the re-check after the lock found the catalogue loaded


async def test_ensure_symbol_cancelled_caller_never_cancels_the_shared_refresh() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    caller = asyncio.create_task(sched.ensure_symbol("SOLUSDT"))
    await settle()
    caller.cancel()  # e.g. the HTTP client went away
    with pytest.raises(asyncio.CancelledError):
        await caller
    refresh = sched._on_demand
    assert refresh is not None and not refresh.done()
    fetch.up.set()
    await refresh
    assert await sched.ensure_symbol("SOLUSDT") is not None and fetch.calls == 1


async def test_stop_cancels_and_awaits_the_shared_refresh_and_answers_its_waiters() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    waiter = asyncio.create_task(sched.ensure_symbol("SOLUSDT"))
    await settle()
    refresh = sched._on_demand
    assert refresh is not None and not refresh.done()
    await sched.stop(grace_s=1.0)
    assert refresh.cancelled() and sched._on_demand is None
    with pytest.raises(instruments_refresh.InstrumentRefreshPendingError):
        await waiter  # a 503, not a request cancelled under it
    with pytest.raises(instruments_refresh.InstrumentRefreshPendingError):
        await sched.ensure_symbol("SOLUSDT")  # a stopped scheduler starts no refresh
    assert fetch.calls == 1 and sched._on_demand is None


async def test_ensure_symbol_failed_refresh_answers_from_the_loaded_catalogue() -> None:
    async def down(_now_us: Callable[[], int]) -> InstrumentsFetchResult:
        raise RuntimeError("exchange down")

    sched = _scheduler(down, max_retries=1)
    _warm(sched, "BTCUSDT")
    assert await sched.ensure_symbol("SOLUSDT") is None  # the route answers 404, not a 500
    snap = sched.snapshot()
    assert snap is not None and snap.stale_since_us == _NOW  # marked stale, still serving


async def test_ensure_symbol_unexpected_refresh_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sched = _scheduler(HangingFetch())

    async def bug() -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(sched, "_refresh_with_retry", bug)
    with capture_logs() as logs:
        assert await sched.ensure_symbol("SOLUSDT") is None
    events = [e["event"] for e in logs]
    assert "instruments_on_demand_refresh_unexpected_error" in events


async def test_start_abandoned_fetch_counts_a_timeout_and_serves_the_warm_snapshot_stale() -> None:
    """#2702 NIT: the persisted (warm) snapshot was never re-validated, so it serves stale
    (`catalogue_stale`, `stale_since`) until the schedule's retry loads."""
    persisted = [i.model_dump(mode="json") for i in _parsed().instruments]
    sched = _scheduler(HangingFetch(), MemoryRepo(persisted), start_timeout_s=0.0)
    before = _count("timeout")
    await sched.start()
    try:
        assert _count("timeout") == before + 1
        snap = sched.snapshot()
        assert snap is not None and snap.get("BTCUSDT") is not None  # still serving
        assert snap.stale_since_us == _NOW
        assert sched.cache.is_stale(now_us=_NOW)
    finally:
        await sched.stop(grace_s=1.0)


@pytest.mark.parametrize(
    "age_s", [0.0, 899.999999, _MAX_AGE_S], ids=["new", "just_under", "at_the_limit"]
)
async def test_ensure_fresh_young_enough_catalogue_returns_at_once_without_a_fetch(
    age_s: float,
) -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    loaded = _warm(sched, "BTCUSDT", age_s=age_s)
    assert (await _ended(sched)).result() is loaded
    assert fetch.calls == 0 and sched._on_demand is None  # nothing fetched, nothing spawned


@pytest.mark.parametrize(
    "age_s", [None, 900.000001], ids=["nothing_loaded", "a_microsecond_too_old"]
)
async def test_ensure_fresh_unfit_catalogue_is_fetched_once_and_the_new_one_returned(
    age_s: float | None,
) -> None:
    fetch = HangingFetch()
    fetch.up.set()
    sched = _scheduler(fetch)
    old = _warm(sched, "BTCUSDT", age_s=age_s) if age_s is not None else None
    ok = _count("ok")
    fresh = await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)
    assert fresh is not None and fresh is not old and fresh is sched.snapshot()
    assert fresh.get("SOLUSDT") is not None and fresh.stale_since_us is None
    assert fetch.calls == 1 and _count("ok") == ok + 1  # counted by the existing series


async def test_ensure_fresh_catalogue_marked_stale_is_refreshed_however_young_it_is() -> None:
    fetch = HangingFetch()
    fetch.up.set()
    sched = _scheduler(fetch)
    marked = _warm(sched, "BTCUSDT", stale=True)  # age 0, but the last refresh failed
    fresh = await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)
    assert fresh is not None and fresh is not marked and fresh.stale_since_us is None
    assert fetch.calls == 1


async def test_ensure_fresh_does_not_trust_a_persisted_copy_after_a_startup_timeout() -> None:
    """`start()` stamps a catalogue loaded from disk with the boot time: after a startup fetch that
    failed it is young by age alone, and only its stale mark says that no fetch confirmed it."""
    persisted = [i.model_dump(mode="json") for i in _parsed().instruments]
    fetch = HangingFetch()
    sched = _scheduler(fetch, MemoryRepo(persisted), start_timeout_s=0.0)
    await sched.start()
    try:
        copy = sched.snapshot()
        assert copy is not None and copy.age_seconds(now_us=_NOW) == 0.0
        assert copy.stale_since_us is not None
        with pytest.raises(instruments_refresh.InstrumentRefreshPendingError):
            (await _ended(sched)).result()  # it refreshes first, and the exchange hangs
        assert fetch.calls == 2  # the abandoned startup fetch, then this refresh
    finally:
        await sched.stop(grace_s=1.0)


@pytest.mark.parametrize("loaded", [False, True], ids=["empty", "fresh"])
@pytest.mark.parametrize(
    ("max_age_s", "deadline_s"),
    [
        (0.0, 1.0),
        (-1.0, 1.0),
        (math.nan, 1.0),
        (math.inf, 1.0),
        (1.0, 0.0),
        (1.0, -1.0),
        (1.0, math.nan),
        (1.0, math.inf),
    ],
)
async def test_ensure_fresh_refuses_a_bound_that_is_not_positive_and_finite(
    max_age_s: float, deadline_s: float, loaded: bool
) -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    if loaded:
        _warm(sched, "BTCUSDT")  # the fast path would answer: the bound is refused before it
    with pytest.raises(ValueError, match="positive and finite"):
        (await _ended(sched, max_age_s, deadline_s)).result()
    assert fetch.calls == 0 and sched._on_demand is None


async def test_ensure_fresh_concurrent_callers_join_one_refresh_task_and_cost_one_fetch() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    first = asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S))
    await settle()
    shared = sched._on_demand
    assert shared is not None and not shared.done()
    others = [asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)) for _ in range(4)]
    await settle()
    assert sched._on_demand is shared and fetch.calls == 1  # they joined: none started a task
    fetch.up.set()
    answers = await asyncio.gather(first, *others)
    assert answers[0] is not None and all(a is answers[0] for a in answers)
    assert fetch.calls == 1


async def test_ensure_fresh_callers_in_one_loop_turn_cost_one_refresh_even_when_it_fails() -> None:
    """Callers started in one loop turn share one task (no await between the slot's read and
    write). A failing fetch shows it: a second task would find no loaded copy to skip, and retry."""

    async def down(_now_us: Callable[[], int]) -> InstrumentsFetchResult:
        raise RuntimeError("exchange down")

    sched = _scheduler(down, max_retries=1)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    errors = _count("error")  # one per refresh, and each tries once
    outcomes = await asyncio.gather(
        *(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S) for _ in range(5)), return_exceptions=True
    )
    assert all(isinstance(o, instruments_refresh.InstrumentRefreshError) for o in outcomes)
    assert _count("error") == errors + 1


async def test_ensure_fresh_raises_pending_at_the_deadline_and_the_refresh_runs_on() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    try:
        with pytest.raises(instruments_refresh.InstrumentRefreshPendingError):
            (await _ended(sched)).result()  # the exchange never answers
        refresh = sched._on_demand
        assert refresh is not None and not refresh.done()  # the deadline did not cancel it
        fetch.up.set()
        await refresh
        fresh = await sched.ensure_fresh(_MAX_AGE_S, _PAST_S)  # fresh now: no deadline to miss
        assert fresh is not None and fresh is sched.snapshot() and fresh.fetched_at_us == _NOW
        assert fresh.stale_since_us is None and fetch.calls == 1
    finally:
        await sched.stop(grace_s=1.0)


@pytest.mark.parametrize(
    "warm",
    [None, {"age_s": 1000.0}, {"stale": True}],
    ids=["nothing_loaded", "too_old", "young_but_never_confirmed"],
)
async def test_ensure_fresh_failed_fetch_raises_the_refresh_error(
    warm: dict[str, Any] | None,
) -> None:
    async def down(_now_us: Callable[[], int]) -> InstrumentsFetchResult:
        raise RuntimeError("exchange down")

    sched = _scheduler(down, max_retries=1)
    if warm is not None:
        _warm(sched, "BTCUSDT", **warm)
    errors = _count("error")
    with pytest.raises(instruments_refresh.InstrumentRefreshError):
        await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)  # never the copy it kept serving
    assert _count("error") == errors + 1


async def test_ensure_fresh_refresh_that_breaks_unexpectedly_never_hands_out_the_old_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sched = _scheduler(HangingFetch())
    _warm(sched, "BTCUSDT", age_s=1000.0)

    async def bug() -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(sched, "_refresh_with_retry", bug)  # logged by the task: loads nothing
    with pytest.raises(instruments_refresh.InstrumentRefreshError):
        await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)


async def test_ensure_fresh_a_later_call_fetches_again_after_a_failed_refresh() -> None:
    calls = 0

    async def flaky(_now_us: Callable[[], int]) -> InstrumentsFetchResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("exchange down")  # and then it recovers
        return _parsed()

    sched = _scheduler(flaky, max_retries=1)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    with pytest.raises(instruments_refresh.InstrumentRefreshError):
        await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)
    fresh = await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S)  # no restart needed
    assert fresh is not None and fresh.stale_since_us is None and calls == 2


async def test_ensure_fresh_cancelled_waiter_never_cancels_the_shared_refresh() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    gone = asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S))
    stays = asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S))
    await settle()
    gone.cancel()  # e.g. the HTTP client went away
    with pytest.raises(asyncio.CancelledError):
        await gone
    refresh = sched._on_demand
    assert refresh is not None and not refresh.done()
    fetch.up.set()
    fresh = await stays  # the other waiter still gets its answer
    assert fresh is not None and fresh is sched.snapshot() and fetch.calls == 1


async def test_ensure_fresh_stop_cancels_the_shared_refresh_and_answers_its_waiters() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    waiter = asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S))
    await settle()
    refresh = sched._on_demand
    assert refresh is not None and not refresh.done()
    await sched.stop(grace_s=1.0)
    assert refresh.cancelled() and sched._on_demand is None
    with pytest.raises(instruments_refresh.InstrumentRefreshPendingError):
        await waiter  # a 503, not a request cancelled under it
    with pytest.raises(instruments_refresh.InstrumentRefreshPendingError):
        (await _ended(sched)).result()  # a stopped scheduler starts no refresh
    assert fetch.calls == 1 and sched._on_demand is None


async def test_ensure_fresh_joins_the_refresh_an_unknown_symbol_lookup_started() -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    lookup = asyncio.create_task(sched.ensure_symbol("SOLUSDT"))
    await settle()
    shared = sched._on_demand
    assert shared is not None
    save = asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S))
    await settle()
    assert sched._on_demand is shared and fetch.calls == 1  # one task, one fetch for both
    fetch.up.set()
    found, fresh = await lookup, await save
    assert found is not None and fresh is not None and fetch.calls == 1


@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
async def test_ensure_fresh_queued_behind_a_loading_refresh_does_not_fetch_again(
    warm: bool,
) -> None:
    fetch = HangingFetch()
    sched = _scheduler(fetch)
    if warm:
        _warm(sched, "BTCUSDT", age_s=1000.0)
    scheduled = asyncio.create_task(sched.refresh_now())  # e.g. the schedule's refresh
    await settle()
    caller = asyncio.create_task(sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S))  # queues
    await settle()
    fetch.up.set()
    await scheduled
    fresh = await caller
    assert fresh is not None and fresh.stale_since_us is None
    assert fetch.calls == 1  # the re-check after the lock found the catalogue loaded


async def test_ensure_fresh_neither_reads_nor_arms_the_lookup_cooldown() -> None:
    """A save is not throttled by a lookup, nor a lookup by a save. The clock is fixed, so a
    cooldown armed by either would never lapse."""
    fetch = HangingFetch()
    fetch.up.set()
    sched = _scheduler(fetch)
    _warm(sched, "BTCUSDT", age_s=1000.0)
    throttled = _count("throttled")
    assert await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S) is not None  # a save: fetch 1
    assert await sched.ensure_symbol("NOPEUSDT") is None  # a lookup it did not throttle: fetch 2
    _warm(sched, "BTCUSDT", age_s=1000.0)  # stale again, inside the cooldown the lookup armed
    assert await sched.ensure_fresh(_MAX_AGE_S, _NO_DEADLINE_S) is not None  # fetch 3
    assert fetch.calls == 3 and _count("throttled") == throttled
