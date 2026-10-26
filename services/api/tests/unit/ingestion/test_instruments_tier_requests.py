"""S4-S-d (#913): `request_tiers`, the order path's ask for a symbol's missing tiers. It joins the
refreshed set, kicks one on-demand fetch per symbol a minute through `ensure_risk_limits`, caps the
symbols kicked in a window, drops a request once stopped, and never waits on the fetch. Recorded
rows only (C-13.5); a fixed clock, no sleeps."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.ingestion import instruments_refresh as refresh_mod
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from tests.unit.ingestion.test_instruments_risk_limits import (
    _NOW,
    _catalogue,
    _Clock,
    _Fetch,
    _Repo,
)

_MINUTE_US = 60 * 1_000_000


def _sched(fetch: _Fetch, clock: _Clock) -> InstrumentsRefreshScheduler:
    return InstrumentsRefreshScheduler(
        fetch_instruments_info=_catalogue, repository=_Repo(), now_us=clock,
        fetch_risk_limits=fetch, on_demand_timeout_s=0.05, on_demand_cooldown_s=60.0,
    )  # fmt: skip


async def _kicked(sched: InstrumentsRefreshScheduler) -> None:
    """The kicked fetches, ended: each within `on_demand_timeout_s`."""
    async with asyncio.timeout(5):  # a guard only
        await asyncio.gather(*sched._tier_kicks)


async def test_request_tiers_adds_the_symbol_and_kicks_one_fetch() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock)
    await sched.refresh_now()  # nothing seeded or held: no tier fetched
    assert sched.request_tiers("BTCUSDT") is None
    await _kicked(sched)
    snap = sched.snapshot()
    assert fetch.calls == ["BTCUSDT"] and snap is not None
    assert snap.risk_limit_tiers("BTCUSDT") is not None
    await sched.refresh_now()  # the symbol joined the refreshed set
    assert fetch.calls == ["BTCUSDT"] * 2


async def test_request_tiers_a_second_request_within_a_minute_kicks_nothing() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock)
    await sched.refresh_now()
    fetch.fail = True  # the tiers stay unknown, so each request would fetch again
    sched.request_tiers("BTCUSDT")
    await _kicked(sched)
    clock.us = _NOW + _MINUTE_US - 1
    assert sched.request_tiers("BTCUSDT") is None
    assert sched._tier_kicks == set() and fetch.calls == ["BTCUSDT"]
    clock.us = _NOW + _MINUTE_US  # the window and the failure's cooldown have passed
    sched.request_tiers("BTCUSDT")
    await _kicked(sched)
    assert fetch.calls == ["BTCUSDT"] * 2


async def test_request_tiers_past_the_cap_is_full_and_fetches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_mod, "TIER_REQUESTS_MAX", 1)
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock)
    await sched.refresh_now()
    fetch.fail = True
    assert sched.request_tiers("BTCUSDT") is None
    assert sched.request_tiers("ETHUSDT") == "full"
    await _kicked(sched)
    assert fetch.calls == ["BTCUSDT"]
    assert "ETHUSDT" not in sched._tier_symbols


async def test_request_tiers_known_or_unlisted_symbol_kicks_nothing() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock)
    assert sched.request_tiers("BTCUSDT") is None  # no catalogue yet
    await sched.refresh_now()
    await sched.ensure_risk_limits("BTCUSDT")
    assert sched.request_tiers("BTCUSDT") is None  # known tiers
    assert sched.request_tiers("NOPEUSDT") is None  # not listed
    assert sched._tier_kicks == set() and fetch.calls == ["BTCUSDT"]


async def test_request_tiers_returns_at_once_while_the_fetch_hangs_and_stop_ends_it() -> None:
    fetch, clock = _Fetch(), _Clock()
    sched = _sched(fetch, clock)
    await sched.refresh_now()
    fetch.hang = True
    assert sched.request_tiers("BTCUSDT") is None  # synchronous: nothing to await
    await asyncio.sleep(0)
    assert fetch.calls == ["BTCUSDT"] and len(sched._tier_kicks) == 1
    kick = next(iter(sched._tier_kicks))
    async with asyncio.timeout(5):  # a guard only
        await sched.stop()
    assert kick.done() and sched._tier_kicks == set()
    assert sched.request_tiers("ETHUSDT") == "stopped"
    assert fetch.calls == ["BTCUSDT"]
