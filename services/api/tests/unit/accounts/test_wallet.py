"""E27-T04 wallet snapshot cache and its REST reconciliation (US-ACCT-008): AC Wallet reconciliation
after silence and AC Stale balances disable risk-based sizing, at the exact 10 s and 60 s
boundaries; snapshots ordered by the exchange's `updated_at`; a failed read or a credential
rejection is never health evidence; the poll cadence while the private WS is down; Decimal only.
Risk-based sizing follows the last reconciliation, not the 10 s stale flag (the ruling on #837,
Option B), with its two guards: a reconciliation that cannot run counts as failed, and so does a
period that passes with no refresh; every decision on a snapshot older than the period is logged
and counted. Fake clock, fake ports, no network, no sleeps."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from structlog.testing import capture_logs

from candleviewer.accounts.health import AccountHealthMonitor, HealthState, HealthTransition
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import (
    SizingDecision,
    WalletCache,
    WalletPoll,
    WalletReconciler,
    WalletSnapshot,
    WalletThresholds,
    WalletUnavailable,
    WalletView,
)
from candleviewer.observability.context import get_context
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.settings import Settings
from tests.unit.accounts._fakes import ACC, ACC_B, T0, Dms, FakeClock, Standings

_AMOUNTS = ("equity", "wallet_balance", "available_balance", "unrealised_pnl")
_RATES = ("account_im_rate", "account_mm_rate")
#: Text a failed read's message may echo from the exchange; it must reach no log line (C-12.6).
_ECHO = "echoed exchange text: key abc123"
_T10 = T0 + timedelta(seconds=10)
#: The counter of decisions taken on a snapshot older than the reconciliation period (catalogue).
_OLD_SNAPSHOT = "cv_wallet_sizing_old_snapshot_total"


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


class Rest:
    """The REST port: answers `answer` (raised if an exception, else a snapshot as of the fake wall
    clock), records each call's monotonic time and the correlation context it ran under, and waits
    for `hold` once `entered` counts it (only for the account `hold_only`, if set). `cancelled`:
    the accounts whose wait was cancelled."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.answer: WalletSnapshot | Exception | None = None
        self.calls: list[tuple[UUID, float]] = []
        self.contexts: dict[UUID, dict[str, Any]] = {}
        self.hold: asyncio.Event | None = None
        self.hold_only: UUID | None = None
        self.cancelled: list[UUID] = []
        self.entered = asyncio.Semaphore(0)

    async def wallet(self, account_id: UUID) -> WalletSnapshot:
        self.calls.append((account_id, self.clock.monotonic()))
        self.contexts[account_id] = get_context()
        self.entered.release()
        if self.hold is not None and self.hold_only in (None, account_id):
            try:
                await self.hold.wait()
            except asyncio.CancelledError:
                self.cancelled.append(account_id)
                raise
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer or snapshot(self.clock.now())


class Evidence:
    """The monitor as the reconciler sees it: a settable state, and a `rest_ok` answer or error."""

    def __init__(self, state: HealthState | None = HealthState.HEALTHY) -> None:
        self.state = state
        self.successes: list[UUID] = []
        self.moved: HealthTransition | None = None
        self.error: Exception | None = None

    def current(self, account_id: UUID) -> HealthState | None:
        return self.state

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        if self.error is not None:
            raise self.error
        self.successes.append(account_id)
        return self.moved


class Rejections(list[tuple[UUID, Refusal]]):
    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
        self.append((account_id, refusal))


class Rig:
    """`ACC` tracked with a snapshot as of `T0`, and a reconciler over fake ports. `monitored`: the
    health port is a real monitor whose WS connected at the start and then dropped. `counted`: the
    cache counts its decisions on old snapshots on the catalogue's counter, of `self.metrics`."""

    def __init__(
        self,
        health: Evidence | None = None,
        *,
        monitored: bool = False,
        thresholds: WalletThresholds | None = None,
        timeout_s: float = 5.0,
        counted: bool = False,
    ) -> None:
        self.clock = FakeClock()
        self.metrics = Metrics("demo")
        counter = register_r0(self.metrics)[_OLD_SNAPSHOT] if counted else None
        self.cache = WalletCache(self.clock, thresholds, old_snapshot_decisions=counter)
        self.cache.track(ACC)
        self.cache.apply(ACC, snapshot(T0))
        self.rest, self.rejections, self.dms = Rest(self.clock), Rejections(), Dms()
        self.health: Any = health or Evidence()
        if monitored:
            self.health = AccountHealthMonitor(self.clock, self.dms)
            self.health.track(ACC)
            self.health.ws_heartbeat(ACC)
            self.health.ws_dropped(ACC)
        self.reconciler = WalletReconciler(
            self.cache, self.rest, self.health, self.rejections, timeout_s=timeout_s
        )

    @property
    def view(self) -> WalletView:
        view = self.cache.view(ACC)
        assert view is not None
        return view

    def decisions(self) -> float:
        """Decisions on an old snapshot counted so far (needs `counted`)."""
        return self.metrics.registry.get_sample_value(_OLD_SNAPSHOT, {"env": "demo"}) or 0.0

    def read_times(self) -> list[float]:
        """Seconds after the start at which the REST port was called."""
        return [t - 1000.0 for _, t in self.rest.calls]

    async def steps(self, seconds: int) -> None:
        """One second at a time: advance the clock, then run what is due."""
        for _ in range(seconds):
            self.clock.advance(1)
            await self.reconciler.run_due()


def pending_polls() -> list[str]:
    """Names of the wallet reads still running on the loop."""
    names = (task.get_name() for task in asyncio.all_tasks())
    return sorted(name for name in names if name.startswith("wallet-poll:"))


async def run_noting_the_reads_left(reconciler: WalletReconciler, left: list[str]) -> None:
    """`run_due()`, noting in `left` the reads still running at the moment it exits."""
    try:
        await reconciler.run_due()
    finally:
        left.extend(pending_polls())


# --- thresholds and the snapshot model


def test_thresholds_default_to_the_us_acct_008_windows() -> None:
    assert WalletThresholds() == WalletThresholds(10.0, 60.0, 10.0)
    settings_ = Settings(wallet_stale_s=5, wallet_reconcile_s=30, account_heartbeat_s=4)
    assert WalletThresholds.from_settings(settings_) == WalletThresholds(5.0, 30.0, 4.0)


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


@pytest.mark.parametrize("timeout_s", [0, -1.0, math.inf, math.nan])
def test_the_read_timeout_must_be_finite_and_positive(timeout_s: float) -> None:
    """An infinite one would let a hung read stall every account's reconciliation."""
    rig = Rig()
    with pytest.raises(ValueError, match="timeout_s"):
        WalletReconciler(rig.cache, rig.rest, rig.health, rig.rejections, timeout_s=timeout_s)


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
    ("age_s", "stale", "stale_since"),
    [(10, False, None), (10.001, True, _T10)],
    ids=["exactly-the-window", "just-past-it"],
)
def test_a_snapshot_is_stale_only_once_older_than_the_stale_window(
    age_s: float, stale: bool, stale_since: datetime | None
) -> None:
    """AC Stale: exactly 10 s old is not yet older than 10 s; just past it `stale_since` is the
    last refresh plus the window. The flag is for display: sizing follows the last reconciliation
    (the tests of the sizing rule below)."""
    rig = Rig()
    rig.clock.advance(age_s)
    shown = (rig.view.snapshot, rig.view.stale, rig.view.stale_since)
    assert shown == (snapshot(), stale, stale_since)


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


@pytest.mark.parametrize(
    "step", [timedelta(minutes=5), -timedelta(minutes=5)], ids=["forwards", "backwards"]
)
@pytest.mark.parametrize(
    ("age_s", "attempts", "decision"),
    [
        (10.001, (False,), SizingDecision(False, 10.001)),
        (60.001, (), SizingDecision(False, 60.001)),
        (5.0, (), SizingDecision(True, 5.0)),
        (5.0, (False,), SizingDecision(True, 5.0)),
    ],
    ids=["stale-after-a-failed-attempt", "lapsed", "fresh", "failed-attempt-inside-the-window"],
)
def test_a_wall_clock_step_does_not_move_a_sizing_decision(
    step: timedelta, age_s: float, attempts: tuple[bool, ...], decision: SizingDecision
) -> None:
    """The sizing flag runs on the monotonic clock, as the stale flag does: its verdict and the age
    it reports are the same after a 5 min step of the wall clock, either way. On the wall clock a
    step back reads a negative age, which keeps sizing on for a dead feed, and a step forward
    turns a fresh snapshot away. `attempts`: what the reconciler reported, `True` for a success."""
    rig = Rig()
    rig.clock.advance(age_s)
    for ok in attempts:
        rig.cache.record_attempt(ACC, ok=ok)
    with capture_logs():  # a decision on a snapshot past the period logs a warning
        assert rig.cache.sizing_decision(ACC) == decision
        rig.clock.wall += step
        assert rig.cache.sizing_decision(ACC) == decision


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
    assert check.risk_sizing_available(ACC) is True  # stale, but no reconciliation has failed
    cache.record_attempt(ACC, ok=False)
    assert check.risk_sizing_available(ACC) is False


def test_a_stale_wallet_after_a_failed_read_disables_sizing_and_refuses_no_order() -> None:
    rig = Rig()
    rig.clock.advance(10.001)
    rig.cache.record_attempt(ACC, ok=False)
    check = gate_over(rig.cache)
    assert (check.risk_sizing_available(ACC), check.refusal(ACC)) == (False, None)


# --- the reconciler: when it reads


@pytest.mark.parametrize(("silent_s", "reads"), [(59.999, 0), (60.0, 1)])
async def test_a_read_runs_once_the_wallet_was_silent_for_the_reconcile_window(
    silent_s: float, reads: int
) -> None:
    rig = Rig()
    rig.clock.advance(silent_s)
    await rig.reconciler.run_due()
    assert len(rig.rest.calls) == reads


@pytest.mark.parametrize(("silent_s", "reads"), [(59.999, 0), (60.0, 1)])
async def test_a_wallet_push_restarts_the_silence_window(silent_s: float, reads: int) -> None:
    """The window runs from the push at 30 s, not from the start: 89.999 s in, the wallet has been
    silent for 59.999 s."""
    rig = Rig()
    rig.clock.advance(30)
    rig.cache.apply(ACC, snapshot(rig.clock.now()))
    rig.clock.advance(silent_s)
    await rig.reconciler.run_due()
    assert len(rig.rest.calls) == reads


@pytest.mark.parametrize(("silent_s", "reads"), [(59.999, 0), (60.0, 1)])
async def test_an_account_tracked_without_a_snapshot_is_read_a_window_after_it_was_tracked(
    silent_s: float, reads: int
) -> None:
    """It waits one window from when it was tracked, not from the start: tracked 100 s in, it is
    not due at 159.999 s."""
    rig = Rig()
    rig.cache.untrack(ACC)
    rig.clock.advance(100)
    rig.cache.track(ACC_B)
    rig.clock.advance(silent_s)
    assert len(await rig.reconciler.run_due()) == reads


async def test_the_read_refreshes_the_snapshot_and_counts_as_rest_evidence() -> None:
    """AC Wallet reconciliation: after 60 s of silence the read runs, the freshness timestamp
    updates (the stale flag clears) and the success is `rest_ok` evidence for the monitor."""
    rig = Rig()
    moved = HealthTransition(ACC, HealthState.DOWN, HealthState.DEGRADED, "rest_only", T0)
    rig.health.moved = moved
    rig.clock.advance(60)
    assert rig.view.stale is True
    assert await rig.reconciler.run_due() == [WalletPoll(ACC, "ok", True, moved)]
    assert rig.health.successes == [ACC]
    assert (rig.view.stale, rig.view.stale_since) == (False, None)
    assert rig.view.snapshot == snapshot(T0 + timedelta(seconds=60))


async def test_a_failed_read_is_retried_one_window_after_the_attempt_not_every_tick() -> None:
    rig = Rig()
    rig.rest.answer = WalletUnavailable()
    await rig.steps(125)
    assert rig.read_times() == [60.0, 120.0]


@pytest.mark.parametrize(
    ("state", "windows", "reads"),
    [
        (HealthState.DEGRADED, WalletThresholds(), [10.0, 20.0, 30.0]),
        (HealthState.DOWN, WalletThresholds(), [10.0, 20.0, 30.0]),
        (None, WalletThresholds(), [10.0, 20.0, 30.0]),
        (HealthState.DEGRADED, WalletThresholds(1, 5, 10), [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]),
    ],
    ids=["degraded", "down", "unmonitored", "never-slower-than-the-reconcile-window"],
)
async def test_while_the_ws_is_down_the_wallet_is_read_every_heartbeat_window(
    state: HealthState | None, windows: WalletThresholds, reads: list[float]
) -> None:
    """A 60 s poll alone would let a `degraded` account fall to `down` between polls."""
    rig = Rig(Evidence(state), thresholds=windows)
    await rig.steps(35)
    assert rig.read_times()[: len(reads)] == reads


async def test_the_cadence_follows_the_health_state_at_the_time_of_the_check() -> None:
    rig = Rig()
    rig.clock.advance(15)
    assert await rig.reconciler.run_due() == []  # healthy: nothing for 60 s
    rig.health.state = HealthState.DEGRADED  # the socket dropped: 15 s of silence is overdue
    assert len(await rig.reconciler.run_due()) == 1


async def test_a_quiet_but_healthy_account_is_stale_but_still_sized_until_its_truth_check() -> None:
    """Sizing follows the last reconciliation, not the 10 s stale flag (the ruling on #837, Option
    B): an idle account whose stream pushes only on change shows `stale` from 10 s on, keeps
    risk-based sizing, and nothing reads its wallet before 60 s."""
    rig = Rig()
    rig.clock.advance(30)
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, True)
    assert await rig.reconciler.run_due() == []


@pytest.mark.parametrize(
    ("poll_s", "flaps"),
    [(10.0, True), (8.0, False)],
    ids=["as-long-as-the-stale-window", "shorter-than-it"],
)
async def test_a_rest_polled_account_flaps_stale_for_display_but_never_loses_risk_sizing(
    poll_s: float, flaps: bool
) -> None:
    """A read is due once the snapshot is as old as the stale window, and the tick that finds it
    due comes a moment later, so a reader just before it sees `stale` (ticks of 0.7 s never land
    on the 10 s cycle, as real ones never do). The reads succeed, so sizing never turns off."""
    rig = Rig(Evidence(HealthState.DEGRADED), thresholds=WalletThresholds(10, 60, poll_s))
    seen_stale: list[bool] = []
    seen_sizing: list[bool | None] = []
    for _ in range(300):
        rig.clock.advance(0.7)
        seen_stale.append(rig.view.stale)  # what a reader sees just before this tick's reads
        seen_sizing.append(rig.cache.risk_sizing_available(ACC))
        await rig.reconciler.run_due()
    assert any(seen_stale) is flaps
    assert set(seen_sizing) == {True}


# --- the reconciler: what a read means


#: A read that gave no figures, as its exception may look: the port's own, a transport error, a bug.
_A_FAILED_READ = pytest.mark.parametrize(
    "failure",
    [WalletUnavailable(_ECHO), ConnectionResetError(_ECHO), RuntimeError(_ECHO)],
    ids=["unavailable", "transport", "other"],
)


@_A_FAILED_READ
async def test_a_failed_read_leaves_the_wallet_stale_and_is_never_evidence(
    failure: Exception,
) -> None:
    """AC Stale balances: the stream and the reconciliation both failed (a 5xx, a dropped
    connection): stale, `stale_since` populated, sizing unavailable, no `rest_ok`."""
    rig = Rig()
    rig.rest.answer = failure
    rig.clock.advance(60)
    polls = await rig.reconciler.run_due()
    assert polls == [WalletPoll(ACC, "failed", False, None)]
    assert rig.health.successes == [] and rig.rejections == []
    assert (rig.view.snapshot, rig.view.stale, rig.view.stale_since) == (snapshot(), True, _T10)
    assert rig.cache.risk_sizing_available(ACC) is False


@_A_FAILED_READ
async def test_a_failed_read_logs_only_the_type_of_its_error(failure: Exception) -> None:
    """The message may echo exchange text, which must reach no log line (C-12.6)."""
    rig = Rig()
    rig.rest.answer = failure
    rig.clock.advance(60)
    with capture_logs() as logs:
        await rig.reconciler.run_due()
    (line,) = logs
    assert line["event"] == "wallet.reconcile_failed" and line["error"] == type(failure).__name__
    assert _ECHO not in repr(logs)


async def test_a_read_that_outlives_the_timeout_is_a_failure() -> None:
    rig = Rig(timeout_s=0.01)
    rig.rest.hold = asyncio.Event()  # never set
    rig.clock.advance(60)
    with capture_logs() as logs:
        async with asyncio.timeout(1):  # a reconciler with no timeout of its own waits forever
            polls = await rig.reconciler.run_due()
    assert polls == [WalletPoll(ACC, "failed", False, None)]
    assert rig.health.successes == [] and logs[0]["error"] == "TimeoutError"


@pytest.mark.parametrize("refusal", list(Refusal))
async def test_a_credential_rejection_is_reported_and_never_health_evidence(
    refusal: Refusal,
) -> None:
    rig = Rig()
    rig.rest.answer = KeyRefused(refusal, 12345)
    rig.clock.advance(60)
    polls = await rig.reconciler.run_due()
    assert polls == [WalletPoll(ACC, "rejected", False, None)]
    assert rig.rejections == [(ACC, refusal)] and rig.health.successes == []
    assert (rig.view.snapshot, rig.view.stale) == (snapshot(), True)


@pytest.mark.parametrize("refusal", list(Refusal))
async def test_a_credential_rejection_logs_its_reason_and_never_the_exchange_code(
    refusal: Refusal,
) -> None:
    rig = Rig()
    rig.rest.answer = KeyRefused(refusal, 12345)
    rig.clock.advance(60)
    with capture_logs() as logs:
        await rig.reconciler.run_due()
    assert logs[0]["event"] == "wallet.reconcile_refused" and logs[0]["reason"] == refusal.value
    assert "12345" not in repr(logs)


async def test_each_read_runs_under_its_own_accounts_correlation_context() -> None:
    """Its log lines carry `account_id` (AGENTS.md section 5.2). `capture_logs` shows no
    contextvars, so the port notes the context it is called under."""
    rig = Rig()
    rig.cache.track(ACC_B)
    rig.clock.advance(60)
    await rig.reconciler.run_due()
    assert rig.rest.contexts == {
        ACC: {"account_id": str(ACC)},
        ACC_B: {"account_id": str(ACC_B)},
    }


async def test_an_answer_older_than_the_cached_snapshot_is_still_a_rest_success() -> None:
    """The call succeeded, so the account's REST path works; its snapshot lost to a newer push."""
    rig = Rig()
    newer = snapshot(T0 + timedelta(minutes=5), equity="5000")
    rig.cache.apply(ACC, newer)
    rig.clock.advance(60)
    assert await rig.reconciler.run_due() == [WalletPoll(ACC, "ok", False, None)]
    assert rig.health.successes == [ACC] and rig.view.snapshot == newer


# --- the reconciler: concurrency and cancellation


async def test_every_due_account_is_read_at_once_and_a_read_in_flight_is_not_repeated() -> None:
    rig = Rig()
    rig.cache.track(ACC_B)
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(60)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):  # a sequential reconciler never gets the second read started
        await rig.rest.entered.acquire()
        await rig.rest.entered.acquire()
    assert await rig.reconciler.run_due() == []  # both are in flight: nothing to repeat
    rig.rest.hold.set()
    assert [(p.account_id, p.result) for p in await run] == [(ACC, "ok"), (ACC_B, "ok")]
    assert sorted(a for a, _ in rig.rest.calls) == sorted([ACC, ACC_B])


async def test_a_run_skips_an_account_whose_last_read_is_still_hanging() -> None:
    """The poll interval (2 s) is shorter than the read timeout (5 s), so the account is due again
    while its last read hangs on an unresponsive exchange. One read in flight per account, or a
    hung exchange would multiply the calls against the UID's rate budget (C-12.7)."""
    rig = Rig(Evidence(HealthState.DEGRADED), thresholds=WalletThresholds(10, 60, 2))
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(2)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
    rig.clock.advance(2)  # due again, and the first read hangs on
    assert await rig.reconciler.run_due() == []
    assert len(rig.rest.calls) == 1
    rig.rest.hold.set()
    await run


@pytest.mark.parametrize(
    "answer",
    [None, WalletUnavailable(), KeyRefused(Refusal.KEY_EXPIRED)],
    ids=["answered", "failed", "refused"],
)
async def test_an_account_is_read_again_once_its_read_has_answered_or_failed(
    answer: Exception | None,
) -> None:
    rig = Rig(Evidence(HealthState.DEGRADED), thresholds=WalletThresholds(10, 60, 2))
    rig.rest.hold, rig.rest.answer = asyncio.Event(), answer
    rig.clock.advance(2)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
    rig.rest.hold.set()
    await run
    rig.clock.advance(2)
    assert len(await rig.reconciler.run_due()) == 1
    assert len(rig.rest.calls) == 2


async def test_an_account_is_read_again_once_its_hanging_read_was_cancelled() -> None:
    rig = Rig(Evidence(HealthState.DEGRADED), thresholds=WalletThresholds(10, 60, 2))
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(2)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    rig.rest.hold.set()
    rig.clock.advance(2)
    assert len(await rig.reconciler.run_due()) == 1
    assert len(rig.rest.calls) == 2


async def test_an_account_is_read_again_after_a_run_cancelled_before_its_read_began() -> None:
    """A read cancelled before it takes its first step never runs its own cleanup."""
    rig = Rig(Evidence(HealthState.DEGRADED), thresholds=WalletThresholds(10, 60, 2))
    rig.clock.advance(2)
    run = asyncio.create_task(rig.reconciler.run_due())
    await asyncio.sleep(0)  # the run has started its reads, and none has taken a step yet
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert rig.rest.calls == []
    rig.clock.advance(2)
    assert len(await rig.reconciler.run_due()) == 1


async def test_cancelling_a_run_counts_no_evidence_and_logs_nothing() -> None:
    rig = Rig()
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(60)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
    run.cancel()
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await run
    assert rig.health.successes == [] and logs == []


async def test_cancelling_a_run_cancels_every_read_in_flight_and_leaves_no_task() -> None:
    """Two reads are in flight: both see the cancellation, and neither is still running by the
    time the cancelled run has left (an awaiter of the run would see it a loop turn later)."""
    rig = Rig()
    rig.cache.track(ACC_B)
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(60)
    left: list[str] = []
    run = asyncio.create_task(run_noting_the_reads_left(rig.reconciler, left))
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
        await rig.rest.entered.acquire()
    assert len(pending_polls()) == 2  # the helper sees the reads, so `left == []` below means it
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert sorted(rig.rest.cancelled) == sorted([ACC, ACC_B]) and left == []


async def test_a_collaborator_that_raises_escapes_as_itself_and_cancels_the_other_reads() -> None:
    """What a collaborator raises is a bug: it reaches the caller as itself, not wrapped in an
    `ExceptionGroup`, and a read still in flight is cancelled rather than left running."""
    rig = Rig()
    rig.cache.track(ACC_B)
    rig.health.error = RuntimeError("rest_ok bug")
    rig.rest.hold, rig.rest.hold_only = asyncio.Event(), ACC_B  # ACC answers at once, ACC_B hangs
    rig.clock.advance(60)
    async with asyncio.timeout(1):  # only the run's own cancel ends it in time: the read's is 5 s
        with pytest.raises(RuntimeError, match="rest_ok bug"):
            await rig.reconciler.run_due()
    assert rig.rest.cancelled == [ACC_B] and pending_polls() == []


# --- the reconciler against the real health monitor


async def test_polling_every_heartbeat_window_keeps_a_wsless_account_degraded() -> None:
    rig = Rig(monitored=True)
    for _ in range(120):
        await rig.steps(1)
        rig.health.tick()
    await rig.health.drain()
    view = rig.health.view(ACC)
    assert (view.state, view.reason) == (HealthState.DEGRADED, "rest_only")
    assert rig.dms.calls == []


async def test_failed_reads_are_no_evidence_so_the_account_goes_down_in_30_s() -> None:
    rig = Rig(monitored=True)
    rig.rest.answer = WalletUnavailable()
    await rig.steps(30)
    assert rig.health.current(ACC) is HealthState.DOWN  # the WS success at the start was the last


# --- risk-based sizing follows the last reconciliation (the ruling on #837, Option B)


#: What a read that cannot run raises: the credentials are not loaded (the port has no key to sign
#: with), the exchange connection is down, or the exchange rejected the credential.
_CANNOT_RUN = pytest.mark.parametrize(
    "failure",
    [
        WalletUnavailable("no credentials loaded"),
        ConnectionResetError("exchange connection down"),
        KeyRefused(Refusal.UNKNOWN_KEY),
    ],
    ids=["no-credentials", "connection-down", "credential-rejected"],
)


def test_an_attempt_for_an_untracked_account_is_ignored() -> None:
    _, cache = tracked_without_a_snapshot()
    cache.record_attempt(ACC_B, ok=False)
    assert cache.view(ACC_B) is None and cache.risk_sizing_available(ACC_B) is None


@pytest.mark.parametrize(
    ("age_s", "sizing"),
    [(10.0, True), (10.001, False)],
    ids=["exactly-the-stale-window", "just-past-it"],
)
def test_a_failed_attempt_turns_sizing_off_only_once_the_snapshot_is_older_than_the_stale_window(
    age_s: float, sizing: bool
) -> None:
    """AC Stale balances: the stream and the reconciliation both failed. Exactly 10 s old is not
    yet stale, so a failed read alone takes nothing away."""
    rig = Rig()
    rig.cache.record_attempt(ACC, ok=False)
    rig.clock.advance(age_s)
    assert rig.cache.risk_sizing_available(ACC) is sizing


@pytest.mark.parametrize(
    ("silent_s", "sizing"),
    [(60.0, True), (60.001, False)],
    ids=["exactly-the-period", "just-past-it"],
)
def test_a_period_with_no_attempt_counts_as_a_failed_attempt(silent_s: float, sizing: bool) -> None:
    """Guard 1: "no attempt" never reads as "the last attempt succeeded". Nothing reports an attempt
    (the reconciler's task died, or never ran): once a period has passed with no refresh the
    account is as unsized as after a failed read, and not a moment before."""
    rig = Rig()
    rig.clock.advance(silent_s)
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, sizing)


def test_the_period_without_an_attempt_runs_from_the_last_refresh() -> None:
    """A wallet push restarts the period, whatever it was before."""
    rig = Rig()
    rig.clock.advance(50)
    rig.cache.apply(ACC, snapshot(rig.clock.now()))
    rig.clock.advance(60)  # 110 s in, 60 s since the push
    assert rig.cache.risk_sizing_available(ACC) is True
    rig.clock.advance(0.001)
    assert rig.cache.risk_sizing_available(ACC) is False


@_CANNOT_RUN
async def test_a_read_that_cannot_run_counts_as_a_failed_attempt(failure: Exception) -> None:
    """Guard 1: no credentials loaded, the exchange connection down, a credential the exchange
    rejects. The attempt itself is the failure, reported at once: a stale snapshot is unsized
    right after it, not a period later."""
    rig = Rig()
    rig.rest.answer = failure
    rig.clock.advance(60)
    await rig.reconciler.run_due()
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, False)


async def test_a_read_that_hangs_counts_as_a_failed_attempt() -> None:
    rig = Rig(timeout_s=0.01)
    rig.rest.hold = asyncio.Event()  # never set
    rig.clock.advance(60)
    with capture_logs() as logs:
        async with asyncio.timeout(1):  # a reconciler with no timeout of its own waits forever
            await rig.reconciler.run_due()
    assert [(line["event"], line["error"]) for line in logs] == [
        ("wallet.reconcile_failed", "TimeoutError")
    ]
    assert rig.cache.risk_sizing_available(ACC) is False


async def test_a_read_still_in_flight_at_the_end_of_the_period_does_not_cover_it() -> None:
    """Fail closed: only a snapshot the cache took is an outcome. A read that starts on the
    period's last tick has not answered yet, so for as long as it runs the account reads as
    unsized."""
    rig = Rig()
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(60)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
    assert rig.cache.risk_sizing_available(ACC) is True  # exactly one period: not yet past it
    rig.clock.advance(0.001)
    assert rig.cache.risk_sizing_available(ACC) is False  # the read has not answered
    rig.rest.hold.set()
    await run
    assert rig.cache.risk_sizing_available(ACC) is True  # answered: refreshed


async def test_a_cancelled_read_reports_no_outcome_so_the_period_keeps_running() -> None:
    rig = Rig()
    rig.rest.hold = asyncio.Event()
    rig.clock.advance(60)
    run = asyncio.create_task(rig.reconciler.run_due())
    async with asyncio.timeout(1):
        await rig.rest.entered.acquire()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert rig.cache.risk_sizing_available(ACC) is True  # no failure, and the period has not lapsed
    rig.clock.advance(0.001)
    assert rig.cache.risk_sizing_available(ACC) is False  # but nothing refreshed it


async def test_a_successful_read_that_refreshed_nothing_does_not_extend_the_period() -> None:
    """A snapshot dated ahead of the exchange's own answers blocks every later refresh (ordering by
    the exchange's `updated_at`). Reads that succeed but lose to it must not keep sizing on a
    balance that old: sizing stops one period after the last refresh, however many reads succeed
    after it (the display flag is stale all along)."""
    rig = Rig()
    rig.cache.apply(ACC, snapshot(T0 + timedelta(hours=5)))  # ahead of every answer to come
    await rig.steps(60)  # the read at 60 s succeeds, and the cache keeps its own
    assert rig.health.successes == [ACC] and rig.cache.risk_sizing_available(ACC) is True
    await rig.steps(1)
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, False)
    await rig.steps(60)  # the read at 120 s succeeds as well
    assert rig.health.successes == [ACC, ACC] and rig.cache.risk_sizing_available(ACC) is False


def test_a_successful_attempt_clears_a_failed_one_without_a_refresh() -> None:
    rig = Rig()
    rig.clock.advance(20)
    rig.cache.record_attempt(ACC, ok=False)
    assert rig.cache.risk_sizing_available(ACC) is False
    rig.clock.advance(5)
    rig.cache.record_attempt(ACC, ok=True)
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, True)


async def test_a_successful_read_that_refreshed_nothing_still_clears_a_failed_attempt() -> None:
    """The read answered, so the failed one before it is no longer the last. A newer snapshot is in
    the cache and inside the period, so sizing returns (polls every 10 s while the WS is down)."""
    rig = Rig(Evidence(HealthState.DEGRADED), thresholds=WalletThresholds(10, 60, 10))
    rig.cache.apply(ACC, snapshot(T0 + timedelta(minutes=5)))  # newer than any read answers
    rig.rest.answer = WalletUnavailable()
    await rig.steps(11)  # the read at 10 s fails, and the snapshot is stale from 10 s
    assert rig.cache.risk_sizing_available(ACC) is False
    rig.rest.answer = None
    await rig.steps(9)  # the read at 20 s succeeds, and loses to the cached snapshot
    assert rig.health.successes == [ACC] and rig.view.snapshot is not None
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, True)


async def test_a_successful_read_clears_a_failed_attempt() -> None:
    """AC Wallet reconciliation: the read after the failed one answers, so the figures are live
    again and sizing returns with them."""
    rig = Rig()
    rig.rest.answer = WalletUnavailable()
    await rig.steps(60)  # the read at 60 s fails
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, False)
    rig.rest.answer = None
    await rig.steps(60)  # the retry at 120 s succeeds
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (False, True)


async def test_a_wallet_push_clears_a_failed_attempt() -> None:
    """Any refresh clears it: the stream is alive again, so a failed read of a minute ago no
    longer says anything about the figures."""
    rig = Rig()
    rig.rest.answer = WalletUnavailable()
    await rig.steps(60)
    assert rig.cache.risk_sizing_available(ACC) is False
    rig.cache.apply(ACC, snapshot(rig.clock.now()))
    rig.clock.advance(30)  # quiet again: stale for display, and not failed
    assert (rig.view.stale, rig.cache.risk_sizing_available(ACC)) == (True, True)


def test_an_older_snapshot_that_refreshes_nothing_clears_nothing() -> None:
    rig = Rig()
    rig.cache.apply(ACC, snapshot(T0 + timedelta(minutes=5)))
    rig.clock.advance(30)
    rig.cache.record_attempt(ACC, ok=False)
    assert rig.cache.apply(ACC, snapshot(T0)) is False  # a late frame: not a refresh
    assert rig.cache.risk_sizing_available(ACC) is False


_STEP = st.one_of(
    st.tuples(st.just("advance"), st.integers(0, 90)),
    st.tuples(st.just("push"), st.just(0)),
    st.tuples(st.just("read_ok"), st.just(0)),
    st.tuples(st.just("read_failed"), st.just(0)),
)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(st.lists(_STEP, max_size=30))
def test_sizing_is_off_exactly_when_stale_after_a_failed_attempt_or_past_one_period(
    steps: list[tuple[str, int]],
) -> None:
    """Whole seconds, so the 10 s and 60 s boundaries are met exactly. Whatever the order of
    pushes, reads and silences: sizing is on while the snapshot is no older than 10 s, and
    after that only while the last attempt has not failed and the snapshot is no older than 60 s.
    So it never uses a balance more than one period old."""
    rig = Rig()
    now = refreshed = 0
    failed = False
    for step, seconds in steps:
        if step == "advance":
            rig.clock.advance(seconds)
            now += seconds
        elif step == "push":
            assert rig.cache.apply(ACC, snapshot(rig.clock.now()))
            refreshed, failed = now, False
        else:
            rig.cache.record_attempt(ACC, ok=step == "read_ok")
            failed = step == "read_failed"
        age = now - refreshed
        expected = age <= 10 or (age <= 60 and not failed)
        assert rig.cache.risk_sizing_available(ACC) is expected
        if expected:
            assert age <= 60


# --- every decision on a snapshot older than the period is logged and counted (Guard 2)


def test_a_decision_exposes_the_snapshot_age_at_decision_time() -> None:
    rig = Rig()
    rig.clock.advance(12.5)
    assert rig.cache.sizing_decision(ACC) == SizingDecision(True, 12.5)


@pytest.mark.parametrize("tracked", [True, False], ids=["tracked", "untracked"])
def test_a_decision_without_a_snapshot_is_unknown_and_has_no_age(tracked: bool) -> None:
    clock = FakeClock()
    cache = WalletCache(clock)
    if tracked:
        cache.track(ACC)
    clock.advance(100)
    assert cache.sizing_decision(ACC) == SizingDecision(None, None)


def test_a_decision_on_a_snapshot_older_than_the_period_is_logged_and_counted() -> None:
    """The line carries the age and the verdict and nothing else: no figure of the snapshot, no
    exchange text (C-12.6)."""
    rig = Rig(counted=True)
    rig.clock.advance(60.001)
    with capture_logs() as logs:
        decision = rig.cache.sizing_decision(ACC)
    assert decision == SizingDecision(False, 60.001)
    assert logs == [
        {
            "event": "wallet.sizing_on_old_snapshot",
            "log_level": "warning",
            "account_id": str(ACC),
            "available": False,
            "wallet_snapshot_age_seconds": 60.001,
        }
    ]
    assert rig.decisions() == 1.0


@pytest.mark.parametrize(
    ("age_s", "decisions"),
    [(60.0, 0.0), (60.001, 1.0)],
    ids=["exactly-the-period", "just-past-it"],
)
def test_only_a_decision_on_a_snapshot_older_than_the_period_is_logged_and_counted(
    age_s: float, decisions: float
) -> None:
    rig = Rig(counted=True)
    rig.cache.record_attempt(ACC, ok=False)
    rig.clock.advance(age_s)
    with capture_logs() as logs:
        rig.cache.risk_sizing_available(ACC)
    assert (len(logs), rig.decisions()) == (int(decisions), decisions)


def test_every_decision_on_an_old_snapshot_is_counted() -> None:
    rig = Rig(counted=True)
    rig.clock.advance(300)
    for _ in range(3):
        rig.cache.risk_sizing_available(ACC)
    assert rig.decisions() == 3.0


def test_a_decision_on_a_snapshot_within_the_period_is_neither_logged_nor_counted() -> None:
    """Whatever it decides: a stale one after a failed read is refused, a fresh one is not."""
    rig = Rig(counted=True)
    rig.cache.record_attempt(ACC, ok=False)
    rig.clock.advance(30)
    with capture_logs() as logs:
        assert rig.cache.risk_sizing_available(ACC) is False
        rig.cache.apply(ACC, snapshot(rig.clock.now()))
        assert rig.cache.risk_sizing_available(ACC) is True
    assert logs == [] and rig.decisions() == 0.0


def test_a_decision_with_no_snapshot_is_neither_logged_nor_counted() -> None:
    rig = Rig(counted=True)
    rig.cache.track(ACC_B)
    rig.clock.advance(300)
    with capture_logs() as logs:
        assert rig.cache.risk_sizing_available(ACC_B) is None
    assert logs == [] and rig.decisions() == 0.0


def test_a_display_read_is_not_a_decision() -> None:
    rig = Rig(counted=True)
    rig.clock.advance(300)
    with capture_logs() as logs:
        rig.cache.view(ACC)
        rig.cache.silence_s()
    assert logs == [] and rig.decisions() == 0.0


def test_the_gates_sizing_flag_is_the_counted_decision() -> None:
    """The sizing path reads the flag through the account check, so that is what is counted."""
    rig = Rig(counted=True)
    rig.clock.advance(300)
    assert gate_over(rig.cache).risk_sizing_available(ACC) is False
    assert rig.decisions() == 1.0


def test_a_cache_without_a_counter_still_logs_its_decisions_on_old_snapshots() -> None:
    rig = Rig()
    rig.clock.advance(300)
    with capture_logs() as logs:
        assert rig.cache.risk_sizing_available(ACC) is False
    assert [line["event"] for line in logs] == ["wallet.sizing_on_old_snapshot"]


def test_the_log_line_of_a_decision_shows_no_balance() -> None:
    figures = {
        "equity": "123456.78",
        "wallet_balance": "98765.43",
        "available_balance": "87654.32",
        "unrealised_pnl": "76543.21",
        "account_im_rate": "0.0987",
        "account_mm_rate": "0.0765",
    }
    rig = Rig()
    rig.cache.apply(
        ACC,
        WalletSnapshot(coin="USDT", updated_at=T0, **{k: Decimal(v) for k, v in figures.items()}),
    )
    rig.clock.advance(300)
    with capture_logs() as logs:
        rig.cache.risk_sizing_available(ACC)
    shown = repr(logs)
    assert logs and [v for v in figures.values() if v in shown] == []
