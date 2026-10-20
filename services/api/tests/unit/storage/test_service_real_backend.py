"""Unit tests for `StorageService` on the real backend (#3874), with the tier clients replaced by
recording fakes (`real_tiers=`): no network. The acceptance criteria: the API boots on the real
tiers (every tier probed and reported ready), an unreachable tier fails closed with the typed
error naming it and no DSN, and `stop()` closes the tiers in reverse order within its grace."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.observability.health import HealthStatus
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.health import StorageHealthReport, TierState
from candleviewer.storage.models import StorageTier
from candleviewer.storage.real_tiers import RealTier, RealTiers
from candleviewer.storage.service import StorageService
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.settings import Settings

_SETTINGS = object()
_CTX = cast("AppContext", SimpleNamespace(settings=_SETTINGS))
#: What a driver error may carry (a host, a user): it must never reach the raised error.
_LEAKY = "leaky-detail-must-not-surface"


class _Tiers:
    """Builds three recording tiers; `fail` maps a tier to what its probe raises."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.budgets: dict[str, float] = {}
        self.fail: dict[str, BaseException] = {}
        self.hang_probe: set[str] = set()
        self.yield_in_probe = False
        self.stubborn_probe: set[str] = set()
        self.hang_close: set[str] = set()
        self.fail_close: set[str] = set()
        self.settings: object = None
        self.builds = 0
        self.probed = asyncio.Event()

    def _tier(self, name: StorageTier) -> RealTier:
        async def probe() -> None:
            self.calls.append(f"probe:{name}")
            self.probed.set()
            if self.yield_in_probe:
                await asyncio.sleep(0)  # a suspension point, as a real probe has
            if name in self.hang_probe:
                await asyncio.Event().wait()
            if name in self.stubborn_probe:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:  # ignores its first cancellation
                    await asyncio.Event().wait()
            if name in self.fail:
                raise self.fail[name]

        async def close(budget_s: float) -> None:
            self.calls.append(f"close:{name}")
            self.budgets[name] = budget_s
            if name in self.hang_close:
                await asyncio.Event().wait()
            if name in self.fail_close:
                raise RuntimeError(_LEAKY)

        return RealTier(name, probe, close)

    def build(self, settings: Settings) -> RealTiers:
        self.settings = settings
        self.builds += 1
        return RealTiers(
            market_data=FakeMarketDataRepository(),
            relational=FakeRelationalRepository(),
            cold=FakeColdTierRepository(),
            tiers=(self._tier("postgres"), self._tier("questdb"), self._tier("cold")),
        )

    def closes(self) -> list[str]:
        return [c for c in self.calls if c.startswith("close:")]


def _service(
    tiers: _Tiers, *, probe_timeout_s: float = 5.0, probe_interval_s: float = 15.0
) -> StorageService:
    return StorageService(
        backend="real",
        real_tiers=tiers.build,
        probe_timeout_s=probe_timeout_s,
        probe_interval_s=probe_interval_s,
    )


_REVERSE = ["close:cold", "close:questdb", "close:postgres"]


async def test_real_start_probes_each_tier_in_order_and_reports_every_tier_ready() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    try:
        assert tiers.settings is _SETTINGS and tiers.builds == 1
        assert tiers.calls == ["probe:postgres", "probe:questdb", "probe:cold"]
        report = service.tier_health()
        assert [t.tier for t in report.tiers] == ["postgres", "questdb", "cold"]
        assert all(t.state is TierState.OK and t.detail == "" for t in report.tiers)
        assert service.health().status is HealthStatus.OK
        assert isinstance(service.market_data, FakeMarketDataRepository)
        assert isinstance(service.relational, FakeRelationalRepository)
        assert isinstance(service.cold, FakeColdTierRepository)
    finally:
        await service.stop(grace_s=1.0)


async def test_real_start_twice_before_stop_builds_and_probes_once() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    try:
        await service.start(_CTX)
        assert tiers.builds == 1
        assert tiers.calls == ["probe:postgres", "probe:questdb", "probe:cold"]
    finally:
        await service.stop(grace_s=1.0)
    assert tiers.closes() == _REVERSE


async def test_real_start_called_concurrently_builds_and_probes_once() -> None:
    tiers = _Tiers()
    tiers.yield_in_probe = True  # so the two starts interleave
    service = _service(tiers)
    await asyncio.gather(service.start(_CTX), service.start(_CTX))
    try:
        assert tiers.builds == 1
        assert tiers.calls == ["probe:postgres", "probe:questdb", "probe:cold"]
    finally:
        await service.stop(grace_s=1.0)
    assert tiers.closes() == _REVERSE


async def test_real_start_with_an_unreachable_tier_fails_closed_naming_it() -> None:
    tiers = _Tiers()
    tiers.fail["questdb"] = ConnectionRefusedError(_LEAKY)
    service = _service(tiers)
    with pytest.raises(StorageTierUnavailable) as refused:
        await service.start(_CTX)
    message = str(refused.value)
    assert "'questdb'" in message and "ConnectionRefusedError" in message
    assert _LEAKY not in message
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    assert "probe:cold" not in tiers.calls  # no tier after the failing one is touched
    assert tiers.closes() == _REVERSE
    assert service.health().status is HealthStatus.STOPPED  # readiness is false
    assert service.tier_health().tiers == ()
    with pytest.raises(StorageTierUnavailable):
        _ = service.market_data


async def test_real_start_with_a_hung_probe_fails_on_the_probe_bound() -> None:
    tiers = _Tiers()
    tiers.hang_probe.add("postgres")
    service = _service(tiers, probe_timeout_s=0.01)
    with pytest.raises(StorageTierUnavailable, match=r"'postgres'.*TimeoutError"):
        await service.start(_CTX)
    assert tiers.closes() == _REVERSE


async def test_real_start_cancelled_in_a_probe_closes_the_tiers_and_propagates() -> None:
    tiers = _Tiers()
    tiers.hang_probe.add("cold")
    service = _service(tiers, probe_timeout_s=30.0)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):  # a real cancellation, inside the cold probe
            await service.start(_CTX)
    assert tiers.closes() == _REVERSE
    assert service.health().status is HealthStatus.STOPPED


async def test_real_start_failure_keeps_its_error_when_a_close_also_fails() -> None:
    tiers = _Tiers()
    tiers.fail["questdb"] = OSError(_LEAKY)
    tiers.fail_close.add("postgres")
    service = _service(tiers)
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable, match="'questdb'"):
        await service.start(_CTX)
    failed = [e for e in logs if e["event"] == "storage_tier_close_failed"]
    assert failed == [
        {"event": "storage_tier_close_failed", "tier": "postgres", "error": "RuntimeError"}
        | {"log_level": "warning"}
    ]
    assert not any(_LEAKY in str(e) for e in logs)


async def test_refresh_reports_postgres_down_and_the_other_tiers_degraded() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    try:
        tiers.fail.update(
            postgres=OSError(_LEAKY), questdb=ConnectionError(), cold=PermissionError()
        )
        with capture_logs() as logs:
            report = await service.refresh()
        states = {t.tier: (t.state, t.detail) for t in report.tiers}
        assert states == {
            "postgres": (TierState.DOWN, "OSError"),
            "questdb": (TierState.DEGRADED, "ConnectionError"),
            "cold": (TierState.DEGRADED, "PermissionError"),
        }
        assert service.health().status is HealthStatus.DEGRADED
        changed = [e for e in logs if e["event"] == "storage_tier_state_changed"]
        assert [(e["tier"], e["state"], e["previous"]) for e in changed] == [
            ("postgres", "down", "ok"),
            ("questdb", "degraded", "ok"),
            ("cold", "degraded", "ok"),
        ]
        tiers.fail.clear()
        report = await service.refresh()
        assert all(t.state is TierState.OK for t in report.tiers)
        assert service.health().status is HealthStatus.OK
    finally:
        await service.stop(grace_s=1.0)


async def test_refresh_with_questdb_alone_degraded_keeps_the_module_ok() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    try:
        tiers.fail["questdb"] = ConnectionError()
        with capture_logs():
            report = await service.refresh()
        assert [(t.tier, t.state) for t in report.tiers] == [
            ("postgres", TierState.OK),
            ("questdb", TierState.DEGRADED),
            ("cold", TierState.OK),
        ]
        assert service.health().status is HealthStatus.OK  # questdb serves degraded
    finally:
        await service.stop(grace_s=1.0)


async def test_refresh_with_an_unchanged_state_logs_nothing() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    try:
        with capture_logs() as logs:
            await service.refresh()
        assert logs == []
    finally:
        await service.stop(grace_s=1.0)


async def test_probe_task_reprobes_the_tiers_on_its_interval() -> None:
    tiers = _Tiers()
    service = _service(tiers, probe_interval_s=0.0)
    await service.start(_CTX)
    tiers.probed.clear()
    async with asyncio.timeout(5.0):  # an event, not a sleep: the next round's first probe
        await tiers.probed.wait()
    await service.stop(grace_s=1.0)
    assert tiers.calls[3] == "probe:postgres"


async def test_probe_round_that_fails_is_logged_and_the_next_round_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tiers = _Tiers()
    service = _service(tiers, probe_interval_s=0.0)
    await service.start(_CTX)
    real_refresh = service.refresh
    rounds: list[int] = []
    second = asyncio.Event()

    async def refresh() -> StorageHealthReport:
        rounds.append(len(rounds))
        if len(rounds) == 1:
            raise RuntimeError(_LEAKY)
        second.set()
        return await real_refresh()

    monkeypatch.setattr(service, "refresh", refresh)
    with capture_logs() as logs:
        async with asyncio.timeout(5.0):  # an event, not a sleep: the round after the failed one
            await second.wait()
    await service.stop(grace_s=1.0)
    failed = [e for e in logs if e["event"] == "storage_tier_probe_round_failed"]
    assert failed == [
        {"event": "storage_tier_probe_round_failed", "error": "RuntimeError", "log_level": "error"}
    ]


async def test_stop_closes_the_tiers_in_reverse_order_once() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    await service.stop(grace_s=1.0)
    await service.stop(grace_s=1.0)  # idempotent: nothing left to close
    assert tiers.closes() == _REVERSE
    assert service.health().status is HealthStatus.STOPPED
    assert service.tier_health().tiers == ()
    with pytest.raises(StorageTierUnavailable):
        _ = service.relational


async def test_stop_gives_each_tier_an_equal_share_of_what_is_left() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    await service.stop(grace_s=9.0)
    cold, questdb, postgres = (tiers.budgets[t] for t in ("cold", "questdb", "postgres"))
    assert cold <= 3.0 and questdb <= 4.5 and postgres <= 9.0  # a third, a half, all of it
    assert 0 < cold < questdb < postgres  # the quick closes roll their time over to the next


async def test_stop_with_a_hung_close_still_closes_the_later_tiers_within_grace() -> None:
    tiers = _Tiers()
    tiers.hang_close.add("questdb")
    service = _service(tiers)
    await service.start(_CTX)
    with capture_logs() as logs:
        async with asyncio.timeout(5.0):  # a guard: the share bounds the hung close
            await service.stop(grace_s=0.2)
    assert tiers.closes() == _REVERSE
    assert [(e["tier"], e["error"]) for e in logs if e["event"] == "storage_tier_close_failed"] == [
        ("questdb", "TimeoutError")
    ]


async def test_stop_gives_tracked_writes_half_the_grace_and_the_tiers_the_rest() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    loop = asyncio.get_running_loop()
    cancelled_at: list[float] = []

    async def forever() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled_at.append(loop.time())
            raise

    write = asyncio.ensure_future(forever())  # never finishes on its own
    service.track_write(write)
    began = loop.time()
    async with asyncio.timeout(5.0):  # a guard: half the grace bounds the hung write
        await service.stop(grace_s=2.0)
    assert write.cancelled() and tiers.closes() == _REVERSE
    # The write waits for 0.8 s (half the grace, less a fifth kept for it to unwind), and the
    # tiers share the 1.2 s left: a write given no time, or the whole grace, fails one of these.
    assert cancelled_at[0] - began >= 0.5
    assert 0.25 < tiers.budgets["cold"] <= 2.0 / 3


async def test_stop_gives_cancelled_writes_time_to_unwind() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    unwound = asyncio.Event()

    async def slow_to_unwind() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            for _ in range(3):  # an async cleanup: yields to the loop, never waits on time
                await asyncio.sleep(0)
            unwound.set()
            raise

    write = asyncio.ensure_future(slow_to_unwind())
    service.track_write(write)
    await service.stop(grace_s=0.4)
    assert unwound.is_set() and write.cancelled()


async def test_stop_does_not_wait_past_its_bound_for_a_prober_that_ignores_cancellation() -> None:
    tiers = _Tiers()
    service = _service(tiers, probe_timeout_s=30.0, probe_interval_s=0.0)
    await service.start(_CTX)
    tiers.stubborn_probe.add("postgres")
    tiers.probed.clear()
    async with asyncio.timeout(5.0):
        await tiers.probed.wait()  # the next round is inside the stubborn probe
    async with asyncio.timeout(5.0):  # a guard: the prober's wait is bounded too
        await service.stop(grace_s=0.2)
    assert tiers.closes() == _REVERSE
    for task in asyncio.all_tasks():  # the prober is still unwinding: end it for the next test
        if task.get_name() == "storage-tier-probes":
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_stop_cancelled_mid_close_still_closes_the_later_tiers_then_propagates() -> None:
    tiers = _Tiers()
    tiers.hang_close.add("questdb")
    service = _service(tiers)
    await service.start(_CTX)
    with capture_logs(), pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):  # cancels stop() inside the hung questdb close
            await service.stop(grace_s=30.0)
    assert tiers.closes() == _REVERSE
    assert service.health().status is HealthStatus.STOPPED
    assert service.tier_health().tiers == ()


async def test_stop_cancelled_while_draining_writes_cancels_them_and_closes_the_tiers() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    cancelled = asyncio.Event()

    async def hangs() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    write = asyncio.ensure_future(hangs())
    service.track_write(write)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):  # cancels stop() while it waits for the write
            await service.stop(grace_s=30.0)
    assert cancelled.is_set() and write.cancelled()
    assert tiers.closes() == _REVERSE
    assert service.health().status is HealthStatus.STOPPED


async def test_stop_cancels_the_probe_task() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    prober = service._prober
    assert prober is not None and not prober.done()
    await service.stop(grace_s=1.0)
    assert prober.cancelled()


async def test_real_retention_is_unavailable_with_its_reason() -> None:
    tiers = _Tiers()
    service = _service(tiers)
    await service.start(_CTX)
    try:
        with pytest.raises(StorageTierUnavailable, match="retention_wiring"):
            _ = service.retention
    finally:
        await service.stop(grace_s=1.0)


async def test_fake_backend_never_builds_the_real_tiers() -> None:
    tiers = _Tiers()
    service = StorageService(backend="fake", real_tiers=tiers.build)
    await service.start(_CTX)
    await service.stop(grace_s=1.0)
    assert tiers.builds == 0 and tiers.calls == []


async def test_unknown_backend_is_refused_without_building_tiers() -> None:
    tiers = _Tiers()
    service = StorageService(backend="other", real_tiers=tiers.build)
    with pytest.raises(StorageTierUnavailable, match="unknown storage_backend"):
        await service.start(_CTX)
    assert tiers.builds == 0
