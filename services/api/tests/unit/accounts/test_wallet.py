"""E27-T04 wallet snapshot cache (US-ACCT-008): AC Stale balances disable risk-based sizing, at the
exact 10 s boundary; snapshots ordered by the exchange's `updated_at`; Decimal only. Fake clock,
no network, no sleeps."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from candleviewer.accounts.health import HealthState
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
from candleviewer.accounts.wallet import (
    WalletCache,
    WalletSnapshot,
    WalletThresholds,
    WalletView,
)
from candleviewer.settings import Settings
from tests.unit.accounts._fakes import ACC, ACC_B, T0, FakeClock, Standings

_AMOUNTS = ("equity", "wallet_balance", "available_balance", "unrealised_pnl")
_RATES = ("account_im_rate", "account_mm_rate")
_T10 = T0 + timedelta(seconds=10)


def snapshot(updated_at: datetime = T0, equity: str = "1000.50") -> WalletSnapshot:
    return WalletSnapshot(
        coin="USDT",
        equity=Decimal(equity),
        wallet_balance=Decimal("1000"),
        available_balance=Decimal("800.25"),
        unrealised_pnl=Decimal("0.50"),
        account_im_rate=Decimal("0.0125"),
        account_mm_rate=Decimal("0.005"),
        updated_at=updated_at,
    )


class Evidence:
    """The monitor as a collaborator sees it: a settable state."""

    def __init__(self, state: HealthState | None = HealthState.HEALTHY) -> None:
        self.state = state

    def current(self, account_id: UUID) -> HealthState | None:
        return self.state


class Rig:
    """`ACC` tracked with a snapshot as of `T0`, over a fake clock."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.cache = WalletCache(self.clock)
        self.cache.track(ACC)
        self.cache.apply(ACC, snapshot(T0))

    @property
    def view(self) -> WalletView:
        view = self.cache.view(ACC)
        assert view is not None
        return view


# --- thresholds and the snapshot model


def test_thresholds_default_to_the_us_acct_008_windows() -> None:
    assert WalletThresholds() == WalletThresholds(10.0, 60.0, 10.0)
    settings = Settings(wallet_stale_s=5, wallet_reconcile_s=30, account_heartbeat_s=4)
    assert WalletThresholds.from_settings(settings) == WalletThresholds(5.0, 30.0, 4.0)


@pytest.mark.parametrize(
    "args",
    [(0, 60, 10), (10, math.inf, 10), (10, 60, math.inf), (10, 60, math.nan), (10, 10, 10)],
)
def test_thresholds_refuse_a_window_not_positive_finite_and_ordered(
    args: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError, match="wallet thresholds"):
        WalletThresholds(*args)


@pytest.mark.parametrize(
    "args",
    [(10.001, 60, 10), (10, 60.001, 10), (10_000, 60_000, 10)],
    ids=["stale-past-10-s", "reconcile-past-60-s", "milliseconds-for-seconds"],
)
def test_thresholds_refuse_a_window_past_its_us_acct_008_default(
    args: tuple[float, float, float],
) -> None:
    """No caller can build a cache that holds an old snapshot fresh, or reads the wallet less
    often than the contract's windows (C-4.14)."""
    with pytest.raises(ValueError, match="capped"):
        WalletThresholds(*args)


@pytest.mark.parametrize("bad", [1.5, Decimal("NaN")], ids=["float", "nan"])
@pytest.mark.parametrize("name", _AMOUNTS + _RATES)
def test_a_snapshot_holds_finite_decimals_never_floats(name: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        WalletSnapshot(**(snapshot().model_dump() | {name: bad}))


@pytest.mark.parametrize("name", _AMOUNTS + _RATES)
def test_a_refused_snapshot_never_prints_the_figure_it_refused(name: str) -> None:
    """Balances are Confidential (C-12.6): a malformed exchange frame must not put its figures in a
    log line through `str()` or `repr()` of the refusal. (`errors()` and `json()` still carry the
    input, so a consumer logs only the type of the error.)"""
    with pytest.raises(ValidationError) as refused:
        WalletSnapshot(**(snapshot().model_dump() | {name: 987654.321}))
    assert "987654.321" not in str(refused.value) and "987654.321" not in repr(refused.value)


def test_a_snapshot_never_prints_its_balances() -> None:
    """Balances are Confidential: a snapshot that reaches a log line by mistake shows none."""
    shown = repr(snapshot(equity="123456.78"))
    assert "123456.78" not in shown and "800.25" not in shown and "USDT" in shown


# --- the cache


@pytest.mark.parametrize(
    ("age_s", "stale", "stale_since", "sizing"),
    [(10, False, None, True), (10.001, True, _T10, False)],
    ids=["exactly-the-window", "just-past-it"],
)
def test_a_snapshot_is_stale_only_once_older_than_the_stale_window(
    age_s: float, stale: bool, stale_since: datetime | None, sizing: bool
) -> None:
    """AC Stale: exactly 10 s old is not yet older than 10 s; just past it `stale_since` is the
    last refresh plus the window, and risk-based sizing is off."""
    rig = Rig()
    rig.clock.advance(age_s)
    shown = (rig.view.snapshot, rig.view.stale, rig.view.stale_since)
    assert shown == (snapshot(), stale, stale_since)
    assert rig.cache.risk_sizing_available(ACC) is sizing


def test_stale_since_stays_at_the_lapse_as_the_snapshot_ages_on() -> None:
    rig = Rig()
    rig.clock.advance(310)
    assert rig.cache.view(ACC) == WalletView(snapshot(), True, _T10)


def test_a_refresh_clears_a_stale_snapshot() -> None:
    rig = Rig()
    rig.clock.advance(310)
    rig.cache.apply(ACC, snapshot(rig.clock.now()))
    assert rig.cache.view(ACC) == WalletView(snapshot(rig.clock.now()), False, None)


def test_stale_since_follows_the_latest_refresh() -> None:
    """Dated from the last refresh, not from when the account was tracked: a refresh at +100 s that
    goes stale 10 s later is stale since +110 s, never since the first snapshot's +10 s."""
    rig = Rig()
    rig.clock.advance(100)
    rig.cache.apply(ACC, snapshot(rig.clock.now()))
    rig.clock.advance(10.001)
    assert (rig.view.stale, rig.view.stale_since) == (True, T0 + timedelta(seconds=110))


@pytest.mark.parametrize("step", [timedelta(minutes=5), -timedelta(minutes=5)])
def test_a_wall_clock_step_does_not_move_freshness(step: timedelta) -> None:
    rig = Rig()
    rig.clock.wall += step
    assert rig.view.stale is False
    rig.clock.mono += 10.001
    assert (rig.view.stale, rig.view.stale_since) == (True, _T10)  # dated at the refresh


@pytest.mark.parametrize(("offset", "taken"), [(-4, False), (0, True), (1, True)])
def test_a_snapshot_is_taken_unless_older_than_the_held_one(offset: int, taken: bool) -> None:
    """Ordered by the exchange's time: an older snapshot replaces nothing and refreshes nothing; the
    same time does both."""
    rig = Rig()
    held = snapshot(T0 + timedelta(seconds=5), equity="2000")
    rig.cache.apply(ACC, held)
    rig.clock.advance(9)
    newcomer = snapshot(T0 + timedelta(seconds=5 + offset), equity="1")
    assert rig.cache.apply(ACC, newcomer) is taken
    rig.clock.advance(1.5)  # 10.5 s since the held one, 1.5 s since the newcomer
    assert (rig.view.snapshot, rig.view.stale) == (newcomer if taken else held, not taken)


def tracked_without_a_snapshot() -> tuple[FakeClock, WalletCache]:
    clock = FakeClock()
    cache = WalletCache(clock)
    cache.track(ACC)
    return clock, cache


def test_an_account_tracked_without_a_snapshot_is_fresh_with_no_figures() -> None:
    _, cache = tracked_without_a_snapshot()
    assert cache.view(ACC) == WalletView(None, False, None)


def test_an_account_without_a_snapshot_has_unknown_sizing_even_once_its_window_lapsed() -> None:
    clock, cache = tracked_without_a_snapshot()
    clock.advance(10.001)
    assert cache.risk_sizing_available(ACC) is None


def test_an_account_without_a_snapshot_ages_from_when_it_was_tracked() -> None:
    clock, cache = tracked_without_a_snapshot()
    clock.advance(10.001)
    assert cache.view(ACC) == WalletView(None, True, _T10)


def test_tracking_an_account_again_restarts_nothing() -> None:
    clock, cache = tracked_without_a_snapshot()
    clock.advance(10.001)
    cache.track(ACC)
    assert cache.view(ACC) == WalletView(None, True, _T10)


def test_a_snapshot_for_an_untracked_account_is_ignored() -> None:
    _, cache = tracked_without_a_snapshot()
    assert cache.apply(ACC_B, snapshot()) is False and cache.view(ACC_B) is None


def test_an_untracked_account_has_unknown_sizing() -> None:
    _, cache = tracked_without_a_snapshot()
    assert cache.risk_sizing_available(ACC_B) is None


def test_untracking_an_account_forgets_it() -> None:
    _, cache = tracked_without_a_snapshot()
    cache.untrack(ACC)
    assert cache.view(ACC) is None and cache.silence_s() == {}


def gate_over(cache: WalletCache) -> AccountHealthCheck:
    """The account's order-entry check over `cache`: `ACC` is degraded (REST only, which still
    trades) and holds an active key, so only its wallet could make a difference."""
    return AccountHealthCheck(
        Evidence(HealthState.DEGRADED), Standings({ACC: KeyStanding(True)}), cache
    )


def test_the_gates_sizing_flag_follows_the_cache() -> None:
    clock = FakeClock()
    cache = WalletCache(clock)
    cache.track(ACC)
    check = gate_over(cache)
    assert check.risk_sizing_available(ACC) is False  # no snapshot yet
    cache.apply(ACC, snapshot())
    assert check.risk_sizing_available(ACC) is True
    clock.advance(10.001)
    assert check.risk_sizing_available(ACC) is False


def test_a_stale_wallet_disables_sizing_and_refuses_no_order() -> None:
    rig = Rig()
    rig.clock.advance(10.001)
    check = gate_over(rig.cache)
    assert (check.risk_sizing_available(ACC), check.refusal(ACC)) == (False, None)
