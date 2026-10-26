"""S4-S-c (#913): each catalogue refresh seeds its tier set from `order_path_symbols`, so the order
path's symbols get tiers with no detail-route visit; a failed fetch stays for the next refresh, a
`closed` symbol leaves, a failed seed read seeds nothing, and the set stays capped. Recorded rows
only (C-13.5); a fixed clock."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from typing import Any

import pytest

from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.ingestion import instruments_refresh as refresh_mod
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from tests.unit.ingestion.test_instruments_risk_limits import _NOW, _catalogue, _Fetch, _Repo

_HOUR_US = 3_600 * 1_000_000


class _Seed:
    """The order path's rows: `held` (open positions or orders) and `created` (symbol, time)."""

    def __init__(self, *held: str, created: Collection[tuple[str, int]] = ()) -> None:
        self.held, self.created, self.asks = set(held), created, list[tuple[int, int]]()
        self.fail = self.hang = False
        self.ranked: list[str] | None = None  # the port's rank order, when a test sets one

    async def __call__(self, *, since_us: int, limit: int) -> Collection[str]:
        self.asks.append((since_us, limit))
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            raise ConnectionError("postgres down")
        if self.ranked is not None:
            return self.ranked[:limit]
        return sorted(self.held | {s for s, at in self.created if at >= since_us})[:limit]


def _sched(fetch: _Fetch, seed: _Seed, **kw: Any) -> InstrumentsRefreshScheduler:
    args: dict[str, Any] = {"fetch_instruments_info": _catalogue, "repository": _Repo(),
                               "now_us": lambda: _NOW, "fetch_risk_limits": fetch,
                               "on_demand_timeout_s": 0.05, "order_path_symbols": seed}  # fmt: skip
    return InstrumentsRefreshScheduler(**(args | kw))


async def test_refresh_open_position_symbol_gets_tiers_without_the_detail_route() -> None:
    fetch = _Fetch()
    sched = _sched(fetch, _Seed("ETHUSDT"))
    await sched.refresh_now()
    snap = sched.snapshot()
    assert fetch.calls == ["ETHUSDT"] and snap is not None
    assert snap.risk_limit_tiers("ETHUSDT") is not None


async def test_refresh_submit_23h_ago_is_fetched_and_25h_ago_is_not() -> None:
    fetch = _Fetch()
    seed = _Seed(created=[("BTCUSDT", _NOW - 23 * _HOUR_US), ("ETHUSDT", _NOW - 25 * _HOUR_US)])
    await _sched(fetch, seed).refresh_now()
    assert seed.asks == [(_NOW - 24 * _HOUR_US, refresh_mod.TIER_SYMBOLS_MAX)]
    assert fetch.calls == ["BTCUSDT"]


async def test_refresh_failed_fetch_is_retried_next_tick_not_dropped() -> None:
    fetch = _Fetch()
    sched = _sched(fetch, _Seed("BTCUSDT"))
    fetch.fail = True
    for _ in range(5):  # more than the three misses that used to drop a symbol
        await sched.refresh_now()
    fetch.fail = False
    await sched.refresh_now()
    snap = sched.snapshot()
    assert fetch.calls == ["BTCUSDT"] * 6 and snap is not None
    assert snap.risk_limit_tiers("BTCUSDT") is not None


async def test_refresh_closed_symbol_leaves_the_set() -> None:
    fetch, closed = _Fetch(), set[str]()

    async def catalogue(now_us: object) -> InstrumentsFetchResult:
        page = await _catalogue(lambda: _NOW)
        items = tuple(i.model_copy(update={"status": "closed"}) if i.symbol in closed else i
                      for i in page.instruments)  # fmt: skip
        return InstrumentsFetchResult(instruments=items, rejected=page.rejected)

    sched = _sched(fetch, _Seed(), fetch_instruments_info=catalogue)
    await sched.refresh_now()
    await sched.ensure_risk_limits("ETHUSDT")
    closed.add("ETHUSDT")
    for _ in range(2):
        await sched.refresh_now()
    assert fetch.calls == ["ETHUSDT"]  # closed: no fetch, and out of the set


@pytest.mark.parametrize("mode", ["fail", "hang"])
async def test_refresh_seed_read_failure_seeds_nothing_and_the_refresh_continues(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(refresh_mod, "ORDER_PATH_SEED_TIMEOUT_S", 0.05)
    fetch, seed = _Fetch(), _Seed("ETHUSDT")
    sched = _sched(fetch, seed)
    await sched.refresh_now()
    setattr(seed, mode, True)
    async with asyncio.timeout(5):  # a guard only
        await sched.refresh_now()
    snap = sched.snapshot()
    assert fetch.calls == ["ETHUSDT"] * 2  # the symbols already held are still refreshed
    assert snap is not None and snap.risk_limit_tiers("ETHUSDT") is not None


async def test_refresh_set_cap_holds_seed_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_mod, "TIER_SYMBOLS_MAX", 1)
    fetch, seed = _Fetch(), _Seed("BTCUSDT", "ETHUSDT")
    sched = _sched(fetch, seed)
    await sched.refresh_now()
    assert seed.asks[0][1] == 1 and fetch.calls == ["BTCUSDT"]
    seed.held = {"ETHUSDT"}
    await sched.refresh_now()  # the seed displaces the symbol held before
    assert fetch.calls == ["BTCUSDT", "ETHUSDT"]


async def test_start_seeded_tiers_never_hold_the_startup_refresh_past_its_timeout() -> None:
    fetch = _Fetch()
    fetch.hang = True
    sched = _sched(fetch, _Seed("BTCUSDT"), start_timeout_s=0.4)
    await sched.start()  # the tiers get a quarter of the timeout, so the catalogue still loads
    try:
        snap = sched.snapshot()
        assert snap is not None and snap.stale_since_us is None and fetch.calls == ["BTCUSDT"]
    finally:
        await sched.stop()


async def test_refresh_fetches_the_seed_in_its_rank_order_before_the_symbols_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_mod, "TIER_FETCH_CONCURRENCY", 1)
    fetch, seed = _Fetch(), _Seed()
    sched = _sched(fetch, seed)
    await sched.refresh_now()
    await sched.ensure_risk_limits("ETHUSDT")  # held from a detail-route visit
    seed.ranked = ["SOLUSDT", "BTCUSDT"]  # positions and open orders first, not by name
    await sched.refresh_now()
    assert fetch.calls == ["ETHUSDT", "SOLUSDT", "BTCUSDT", "ETHUSDT"]


async def test_refresh_set_cap_keeps_the_rank_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_mod, "TIER_SYMBOLS_MAX", 2)
    fetch, seed = _Fetch(), _Seed()
    seed.ranked = ["SOLUSDT", "ETHUSDT", "BTCUSDT"]  # the port honours `limit`; the cap holds too
    await _sched(fetch, seed).refresh_now()
    assert sorted(fetch.calls) == ["ETHUSDT", "SOLUSDT"]


async def test_refresh_allowed_symbol_with_no_orders_is_fetched() -> None:
    fetch, seed = _Fetch(), _Seed()
    seed.ranked = ["ETHUSDT"]  # the port's rank 2 arm: a profile allows it, no order or position
    await _sched(fetch, seed).refresh_now()
    assert fetch.calls == ["ETHUSDT"]


async def test_refresh_cap_drops_allowed_symbols_before_positions_and_open_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_mod, "TIER_SYMBOLS_MAX", 2)
    fetch, seed = _Fetch(), _Seed()
    # held, then a recent submit, then an allowed symbol: rank 0, 1, 2 (not by name)
    seed.ranked = ["SOLUSDT", "ETHUSDT", "BTCUSDT"]
    await _sched(fetch, seed).refresh_now()
    assert sorted(fetch.calls) == ["ETHUSDT", "SOLUSDT"]  # the allowed symbol is the one dropped


async def test_refresh_fetches_tiers_concurrently_within_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_mod, "TIER_FETCH_CONCURRENCY", 2)
    running = peak = 0
    plain = _Fetch()

    async def fetch(symbol: str) -> Any:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        running -= 1
        return await plain(symbol)

    sched = _sched(fetch, _Seed("BTCUSDT", "ETHUSDT", "SOLUSDT"))  # type: ignore[arg-type]
    await sched.refresh_now()
    assert peak == 2 and sorted(plain.calls) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


class _Parking:
    """Fake schedule `sleep`: records each delay and parks until `stop()` cancels the task."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.Event().wait()


async def _first_schedule_wait(
    fetch: _Fetch, start_timeout_s: float, seed: _Seed | None = None
) -> float:
    park = _Parking()
    sched = _sched(fetch, seed or _Seed("BTCUSDT"), sleep=park, random_fn=lambda: 0.0,
                   start_timeout_s=start_timeout_s)  # fmt: skip
    await sched.start()
    try:
        for _ in range(20):
            await asyncio.sleep(0)
        return park.delays[0]
    finally:
        await sched.stop()


async def test_start_that_leaves_seeded_tiers_unknown_is_followed_by_a_short_retry() -> None:
    fetch = _Fetch()
    fetch.hang = True  # the quarter-budget is spent before the symbol answers
    assert await _first_schedule_wait(fetch, 0.4) == refresh_mod.TIERS_RETRY_S


async def test_start_that_reaches_every_seeded_tier_waits_the_ttl() -> None:
    assert await _first_schedule_wait(_Fetch(), 10.0) == 43_200.0


async def test_start_with_a_failed_seed_read_is_followed_by_a_short_retry() -> None:
    seed = _Seed("BTCUSDT")
    seed.fail = True  # nothing is seeded, so no tier is pending: the read itself is the gap
    assert await _first_schedule_wait(_Fetch(), 10.0, seed) == refresh_mod.TIERS_RETRY_S


async def test_incomplete_refreshes_double_the_retry_and_a_complete_one_resets_it() -> None:
    fetch, delays = _Fetch(), list[float]()
    fetch.fail = True

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 3:
            fetch.fail = False  # the next scheduled refresh reaches every tier
        if len(delays) >= 4:
            await asyncio.Event().wait()

    sched = _sched(fetch, _Seed("BTCUSDT"), sleep=sleep, random_fn=lambda: 0.0)
    await sched.start()
    try:
        for _ in range(100):
            await asyncio.sleep(0)
        assert delays[:4] == [
            refresh_mod.TIERS_RETRY_S,  # streak 1
            refresh_mod.TIERS_RETRY_S * 2,  # streak 2: 120 s
            refresh_mod.TIERS_RETRY_S * 4,  # streak 3
            43_200.0,  # a complete refresh reset the streak: the TTL
        ]
    finally:
        await sched.stop()
