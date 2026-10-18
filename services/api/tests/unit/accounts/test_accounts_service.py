"""AccountsService lifecycle (E27-T01 QA gap) and its row gauges (#2314)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.errors import AccountsError
from candleviewer.accounts.service import (
    REFRESH_INTERVAL_S,
    STALE_AFTER_INTERVALS,
    AccountHealthFeed,
    AccountsService,
)
from candleviewer.app import AppContext
from candleviewer.observability.health import HealthStatus
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0

_CTX = cast(AppContext, object())
_KINDS = ("main", "sub")
_STATES = ("pending", "active", "rotating", "revoked", "expired", "invalid")
_TASK = "accounts-row-gauges"


class _Counts:
    """Fake `AccountsRowCounts`: the configured counts, or `fail`, or a read that never ends."""

    def __init__(self, accounts: dict[str, int], keys: dict[str, int]) -> None:
        self.accounts, self.keys = accounts, keys
        self.fail: Exception | None = None
        self.hang = False
        self.envs: list[str] = []
        self.calls = 0

    async def count_accounts_by_kind(self, env: str) -> dict[str, int]:
        self.envs.append(env)
        self.calls += 1
        if self.hang:
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        return dict(self.accounts)

    async def count_api_keys_by_status(self, env: str) -> dict[str, int]:
        self.envs.append(env)
        return dict(self.keys)


class _Sleep:
    """Fake sleep: records the delay, sets `parked`, then waits for `release()` (no wall clock)."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.parked = asyncio.Event()
        self._go = asyncio.Event()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        self.parked.set()
        await self._go.wait()
        self._go.clear()

    async def next_pass(self) -> None:
        self.parked.clear()
        self._go.set()
        await self.parked.wait()


def _wired(counts: _Counts, **kw: Any) -> tuple[AccountsService, Metrics]:
    metrics = Metrics("demo")
    gauges = register_r0(metrics)
    svc = AccountsService(**kw)
    svc.attach_row_gauges(
        counts, gauges["cv_accounts_rows"], gauges["cv_api_keys_rows"], env="demo"
    )
    return svc, metrics


def _rows(m: Metrics) -> dict[str, float | None]:
    get = m.registry.get_sample_value
    return {k: get("cv_accounts_rows", {"env": "demo", "kind": k}) for k in _KINDS}


def _keys(m: Metrics) -> dict[str, float | None]:
    get = m.registry.get_sample_value
    return {s: get("cv_api_keys_rows", {"env": "demo", "state": s}) for s in _STATES}


def _loops() -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t.get_name() == _TASK]


def test_health_before_start_is_stopped() -> None:
    report = AccountsService().health()
    assert report.status is HealthStatus.STOPPED


async def test_start_then_health_is_ok() -> None:
    svc = AccountsService()
    await svc.start(_CTX)
    assert svc.health().status is HealthStatus.OK


async def test_stop_returns_health_to_stopped() -> None:
    svc = AccountsService()
    await svc.start(_CTX)
    await svc.stop(1.0)
    assert svc.health().status is HealthStatus.STOPPED


async def test_stop_without_start_is_safe_and_idempotent() -> None:
    svc = AccountsService()
    await svc.stop(0.0)
    await svc.stop(0.0)
    assert svc.health().status is HealthStatus.STOPPED


async def test_without_a_store_start_spawns_nothing_and_the_gauges_stay_unset() -> None:
    svc = AccountsService()  # the fake backend: create_app attaches no store
    await svc.start(_CTX)
    assert _loops() == []
    assert await svc.refresh_once() is False
    report = svc.health()
    assert report.status is HealthStatus.OK and "unset" in report.detail


async def test_refresh_sets_every_label_value_and_zero_for_absent_ones() -> None:
    counts = _Counts({"main": 2}, {"active": 2, "revoked": 1})
    svc, m = _wired(counts)
    assert await svc.refresh_once() is True
    assert _rows(m) == {"main": 2.0, "sub": 0.0}
    assert _keys(m) == {
        "pending": 0.0, "active": 2.0, "rotating": 0.0,
        "revoked": 1.0, "expired": 0.0, "invalid": 0.0,
    }  # fmt: skip
    assert counts.envs == ["demo", "demo"]  # both reads scoped to the process environment


async def test_a_vanished_category_reads_zero_not_its_stale_value() -> None:
    counts = _Counts({"main": 1, "sub": 3}, {"invalid": 1})
    svc, m = _wired(counts)
    await svc.refresh_once()
    counts.accounts, counts.keys = {"main": 1}, {}
    await svc.refresh_once()
    assert _rows(m) == {"main": 1.0, "sub": 0.0}
    assert set(_keys(m).values()) == {0.0}


async def test_start_spawns_one_loop_and_stop_cancels_it() -> None:
    counts, sleep = _Counts({}, {}), _Sleep()
    svc, _ = _wired(counts, sleep=sleep)
    await svc.start(_CTX)
    await svc.start(_CTX)  # idempotent: still one loop
    first = svc.health()
    assert first.status is HealthStatus.OK and "pending" in first.detail
    await sleep.parked.wait()
    loops = _loops()
    assert len(loops) == 1 and counts.calls == 1
    await svc.stop(1.0)
    assert loops[0].cancelled() and _loops() == []
    assert svc.health().status is HealthStatus.STOPPED


async def test_store_error_keeps_last_values_counts_it_and_degrades_until_recovery() -> None:
    counts, sleep = _Counts({"sub": 4}, {"pending": 2}), _Sleep()
    svc, m = _wired(counts, sleep=sleep)
    await svc.start(_CTX)
    await sleep.parked.wait()
    assert _rows(m)["sub"] == 4.0 and svc.health().status is HealthStatus.OK
    counts.fail = OSError("connection refused to 10.1.2.3")
    with capture_logs() as logs:
        await sleep.next_pass()
    assert _rows(m)["sub"] == 4.0 and _keys(m)["pending"] == 2.0  # last values kept
    report = svc.health()
    assert report.status is HealthStatus.DEGRADED and "1 consecutive" in report.detail
    failed = [e for e in logs if e["event"] == "accounts_row_gauges_refresh_failed"]
    assert failed and failed[0]["error"] == "OSError"
    assert "10.1.2.3" not in repr(logs)  # the type only: driver text can name hosts
    await sleep.next_pass()  # still failing: the loop survives and keeps counting
    assert "2 consecutive" in svc.health().detail
    counts.fail, counts.accounts = None, {"sub": 5}
    await sleep.next_pass()
    assert _rows(m)["sub"] == 5.0 and svc.health().status is HealthStatus.OK
    assert sleep.delays == [REFRESH_INTERVAL_S] * 4
    await svc.stop(1.0)


async def test_a_hung_read_times_out_and_counts_as_a_failure() -> None:
    counts, sleep = _Counts({"main": 1}, {}), _Sleep()
    counts.hang = True
    svc, m = _wired(counts, timeout_s=0.0, sleep=sleep)
    await svc.start(_CTX)
    await sleep.parked.wait()
    assert svc.health().status is HealthStatus.DEGRADED
    assert _rows(m) == {"main": None, "sub": None}  # nothing published, nothing invented
    await svc.stop(1.0)


async def test_a_refresh_older_than_the_stale_bound_degrades_health() -> None:
    now = [0.0]
    counts, sleep = _Counts({}, {}), _Sleep()
    svc, _ = _wired(counts, clock=lambda: now[0], sleep=sleep)
    await svc.start(_CTX)
    await sleep.parked.wait()
    now[0] = STALE_AFTER_INTERVALS * REFRESH_INTERVAL_S
    assert svc.health().status is HealthStatus.OK
    now[0] += 1.0
    report = svc.health()
    assert report.status is HealthStatus.DEGRADED and "stale" in report.detail
    await svc.stop(1.0)


async def test_a_publish_error_is_counted_like_a_read_error_and_never_raised() -> None:
    counts = _Counts({"main": cast(int, "n/a")}, {})  # a count the gauge cannot take
    svc, m = _wired(counts)
    with capture_logs() as logs:
        assert await svc.refresh_once() is False
    assert [(e["error"], e["consecutive_failures"]) for e in logs] == [("ValueError", 1)]
    counts.accounts = {"main": 3}
    assert await svc.refresh_once() is True
    assert _rows(m)["main"] == 3.0


async def test_a_loop_that_dies_degrades_health_at_once_and_logs_the_error() -> None:
    async def broken_sleep(delay: float) -> None:
        raise RuntimeError("timer gone")

    svc, m = _wired(_Counts({"main": 1}, {}), sleep=broken_sleep)
    with capture_logs() as logs:
        await svc.start(_CTX)
        await asyncio.wait(_loops())  # the done-callback runs before this returns
    assert _rows(m)["main"] == 1.0  # the pass before the crash still published
    report = svc.health()
    assert report.status is HealthStatus.DEGRADED and "exited" in report.detail
    died = [e for e in logs if e["event"] == "accounts_row_gauges_loop_died"]
    assert [e["error"] for e in died] == ["RuntimeError"]
    await svc.stop(1.0)
    assert svc.health().status is HealthStatus.STOPPED


def _feed(fault: str | None = None) -> Any:
    return SimpleNamespace(fault=fault)


def test_the_account_health_feed_is_not_served_until_it_is_attached() -> None:
    with pytest.raises(AccountsError, match="account health is not wired"):
        _ = AccountsService().account_health


def test_the_attached_feed_is_what_the_private_ws_consumer_gets() -> None:
    svc, feed = AccountsService(), _feed()
    svc.attach_account_health(cast(AccountHealthFeed, feed))
    assert svc.account_health is feed


async def test_a_fault_of_the_account_health_runtime_degrades_the_check_until_it_clears() -> None:
    svc, feed = AccountsService(), _feed()
    svc.attach_account_health(cast(AccountHealthFeed, feed))
    await svc.start(_CTX)
    assert svc.health().status is HealthStatus.OK
    feed.fault = "the account-health-tick loop ended"
    report = svc.health()
    assert report.status is HealthStatus.DEGRADED
    assert report.detail == "the account-health-tick loop ended"
    feed.fault = None
    assert svc.health().status is HealthStatus.OK
