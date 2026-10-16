"""#2702: the on-demand catalogue refresh behind `GET /instruments/{symbol}` is bounded.

It is one shared, tracked task: a caller waits on it for at most `on_demand_timeout_s` (the route
then answers 503) and never cancels it; a concurrent caller joins it; a caller queued behind a
refresh that loaded the catalogue does not fetch again; `stop()` cancels and awaits it. An
abandoned startup fetch counts `result="timeout"` and serves a warm snapshot stale. Recorded
catalogue rows only (C-13.5); no real time passes (C-13.7)."""

from __future__ import annotations

import asyncio
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


def _warm(sched: instruments_refresh.InstrumentsRefreshScheduler, *symbols: str) -> None:
    loaded = {i.symbol: i for i in _parsed(*symbols).instruments}
    sched.cache.swap(CatalogueSnapshot(by_symbol=loaded, fetched_at_us=_NOW))


def _count(result: str) -> float:
    value: float = instruments_refresh_total.labels(result=result)._value.get()
    return value


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
