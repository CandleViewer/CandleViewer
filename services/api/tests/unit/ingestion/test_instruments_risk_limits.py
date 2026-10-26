"""S-RL (#913): risk-limit tiers held beside the instrument catalogue, in memory.

Fetched on first demand (`ensure_risk_limits`), then re-fetched by each catalogue refresh and
swapped with it; a fetch that fails or is late leaves the symbol's tiers unknown (`None`), and
the restart window, before any fetch, is unknown too (fail closed). Recorded rows only (C-13.5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.base.models import RiskLimitTier
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.bybit.risk_limits import order_tiers, parse_risk_limit_page
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from tests._corpus import rest

_NOW = 1_700_000_000_000_000


def _tiers(symbol: str) -> tuple[RiskLimitTier, ...]:
    page, _ = parse_risk_limit_page(rest(f"rest/risk_limit_{symbol}.json"), symbol=symbol)
    return order_tiers(page)


async def _catalogue(now_us: Callable[[], int]) -> InstrumentsFetchResult:
    return parse_instruments(rest("rest/instruments_before.json")["result"]["list"],
                             fetched_at_us=now_us())  # fmt: skip


class _Repo:
    def __init__(self) -> None:
        self.rows: Sequence[Mapping[str, Any]] = []

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.rows = rows

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        return self.rows


class _Fetch:
    """Answers from the recorded tiers; `fail` makes the next calls raise, `hang` never answer."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False
        self.hang = False

    async def __call__(self, symbol: str) -> Sequence[RiskLimitTier]:
        self.calls.append(symbol)
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("venue down")
        return _tiers(symbol)


class _Clock:
    def __init__(self) -> None:
        self.us = _NOW

    def __call__(self) -> int:
        return self.us


def _sched(
    fetch: _Fetch | None,
    repo: _Repo | None = None,
    *,
    clock: Callable[[], int] = lambda: _NOW,
    budget_s: float = 15.0,
) -> InstrumentsRefreshScheduler:
    return InstrumentsRefreshScheduler(
        fetch_instruments_info=_catalogue, repository=repo or _Repo(), now_us=clock,
        fetch_risk_limits=fetch, on_demand_timeout_s=0.05, on_demand_cooldown_s=60.0,
        risk_limits_budget_s=budget_s,
    )  # fmt: skip


async def test_ensure_risk_limits_fetches_once_then_serves_the_snapshot() -> None:
    fetch = _Fetch()
    sched = _sched(fetch)
    await sched.refresh_now()
    assert fetch.calls == []  # nothing asked for yet: the refresh fetches no tiers
    first = await sched.ensure_risk_limits("BTCUSDT")
    assert first == _tiers("BTCUSDT") and await sched.ensure_risk_limits("BTCUSDT") == first
    snap = sched.snapshot()
    assert snap is not None and snap.risk_limit_tiers("BTCUSDT") == first
    assert snap.risk_limit_tiers("ETHUSDT") is None and fetch.calls == ["BTCUSDT"]


async def test_catalogue_refresh_refetches_the_asked_symbols_and_keeps_the_stale_mark() -> None:
    fetch = _Fetch()
    sched = _sched(fetch)
    await sched.refresh_now()
    await sched.ensure_risk_limits("ETHUSDT")
    await sched.refresh_now()
    assert fetch.calls == ["ETHUSDT", "ETHUSDT"]
    sched.cache.mark_stale(stale_since_us=_NOW)
    snap = sched.snapshot()
    assert snap is not None and snap.stale_since_us == _NOW
    assert snap.risk_limit_tiers("ETHUSDT") == _tiers("ETHUSDT")


async def test_a_failed_tier_fetch_in_a_refresh_leaves_the_symbol_unknown_not_stale() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock=clock)
    await sched.refresh_now()
    await sched.ensure_risk_limits("BTCUSDT")
    fetch.fail = True
    await sched.refresh_now()  # the catalogue still loads
    snap = sched.snapshot()
    assert snap is not None and snap.get("BTCUSDT") is not None
    assert snap.risk_limit_tiers("BTCUSDT") is None  # the previous ladder is not kept
    clock.us += 61_000_000  # past the cooldown the failed refresh fetch started
    assert await sched.ensure_risk_limits("BTCUSDT") is None  # retried, still failing
    fetch.fail = False
    clock.us += 61_000_000
    assert await sched.ensure_risk_limits("BTCUSDT") == _tiers("BTCUSDT")


async def test_ensure_risk_limits_waits_out_a_cooldown_after_a_failed_fetch() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock=clock)
    await sched.refresh_now()
    fetch.fail = True
    assert await sched.ensure_risk_limits("BTCUSDT") is None
    fetch.fail = False
    clock.us += 59_000_000
    assert await sched.ensure_risk_limits("BTCUSDT") is None  # cooling: no upstream call
    assert fetch.calls == ["BTCUSDT"]
    clock.us += 2_000_000
    assert await sched.ensure_risk_limits("BTCUSDT") == _tiers("BTCUSDT")
    assert fetch.calls == ["BTCUSDT", "BTCUSDT"]


async def test_hanging_tier_fetches_never_hold_the_catalogue_swap_past_the_budget() -> None:
    fetch = _Fetch()
    sched = _sched(fetch, budget_s=0.05)
    await sched.refresh_now()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        await sched.ensure_risk_limits(symbol)
    before = sched.snapshot()
    fetch.calls.clear()
    fetch.hang = True
    async with asyncio.timeout(5):  # a guard only; the budget is 0.05 s
        await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None and snap is not before and snap.get("BTCUSDT") is not None
    assert snap.risk_limit_tiers("BTCUSDT") is None and snap.risk_limit_tiers("ETHUSDT") is None
    assert fetch.calls == ["BTCUSDT"]  # the budget ran out on the first; ETHUSDT stays unknown


async def test_a_symbol_joins_the_refresh_on_success_and_stays_after_repeated_failures() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock=clock)
    await sched.refresh_now()
    fetch.fail = True
    await sched.ensure_risk_limits("BTCUSDT")
    await sched.refresh_now()
    assert fetch.calls == ["BTCUSDT"]  # a failed first fetch never joins the refreshed set
    fetch.fail = False
    clock.us += 61_000_000  # past the cooldown
    assert await sched.ensure_risk_limits("BTCUSDT") == _tiers("BTCUSDT")
    fetch.fail = True
    for _ in range(4):
        await sched.refresh_now()
    assert fetch.calls == ["BTCUSDT"] * 6  # S4-S-c: retried on every refresh, never dropped


async def test_ensure_risk_limits_is_unknown_without_a_catalogue_symbol_or_fetcher() -> None:
    fetch = _Fetch()
    sched = _sched(fetch)
    assert await sched.ensure_risk_limits("BTCUSDT") is None  # nothing loaded yet
    await sched.refresh_now()
    assert await sched.ensure_risk_limits("NOPEUSDT") is None and fetch.calls == []
    unwired = _sched(None)
    await unwired.refresh_now()
    assert await unwired.ensure_risk_limits("BTCUSDT") is None


async def test_ensure_risk_limits_past_its_deadline_is_unknown() -> None:
    fetch = _Fetch()
    sched = _sched(fetch)
    await sched.refresh_now()
    fetch.hang = True
    assert await sched.ensure_risk_limits("BTCUSDT") is None


async def test_restart_window_has_no_tiers_until_the_first_fetch() -> None:
    """Tiers are never persisted: a restarted scheduler serves the warm catalogue without them."""
    repo, fetch = _Repo(), _Fetch()
    before = _sched(fetch, repo)
    await before.refresh_now()
    await before.ensure_risk_limits("BTCUSDT")
    assert all("risk_limits" not in row and "tiers" not in row for row in repo.rows)
    after = _sched(_Fetch(), repo)
    await after.start()  # warm load + startup refresh
    try:
        snap = after.snapshot()
        assert snap is not None and snap.get("BTCUSDT") is not None
        assert snap.risk_limit_tiers("BTCUSDT") is None
    finally:
        await after.stop()


async def test_concurrent_first_asks_cost_one_fetch() -> None:
    fetch = _Fetch()
    sched = _sched(fetch)
    await sched.refresh_now()
    first, second = await asyncio.gather(
        sched.ensure_risk_limits("BTCUSDT"), sched.ensure_risk_limits("BTCUSDT")
    )
    assert first == second == _tiers("BTCUSDT") and fetch.calls == ["BTCUSDT"]
