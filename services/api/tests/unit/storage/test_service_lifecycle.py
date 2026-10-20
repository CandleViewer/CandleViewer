"""Unit tests for `StorageService` lifecycle (E07-T01 "Test plan": lifecycle
test — start/stop idempotency, stop during in-flight write) and acceptance
criteria 1 ("storage starts first, health() reports all three tiers as
'fake/healthy'") and 5 (a tier client failing to connect reports degraded
with `StorageTierUnavailable`, and the supervisor refuses readiness)."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.observability.health import HealthStatus
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.health import TierState
from candleviewer.storage.service import StorageService


async def test_start_with_fake_backend_reports_all_three_tiers_healthy() -> None:
    service = StorageService(backend="fake")
    await service.start(ctx=None)  # type: ignore[arg-type]
    report = service.tier_health()
    assert {t.tier for t in report.tiers} == {"postgres", "questdb", "cold"}
    assert all(t.state is TierState.OK and t.detail == "fake/healthy" for t in report.tiers)
    assert service.health().status is HealthStatus.OK


async def test_health_is_stopped_before_start() -> None:
    service = StorageService(backend="fake")
    assert service.health().status is HealthStatus.STOPPED
    assert service.tier_health().tiers == ()


async def test_stop_is_idempotent_and_resets_health_to_stopped() -> None:
    service = StorageService(backend="fake")
    await service.start(ctx=None)  # type: ignore[arg-type]
    await service.stop(grace_s=1.0)
    await service.stop(grace_s=1.0)  # second call must not raise
    assert service.health().status is HealthStatus.STOPPED


async def test_accessing_market_data_before_start_raises_tier_unavailable() -> None:
    service = StorageService(backend="fake")
    with pytest.raises(StorageTierUnavailable):
        _ = service.market_data


async def test_accessing_relational_before_start_raises_tier_unavailable() -> None:
    service = StorageService(backend="fake")
    with pytest.raises(StorageTierUnavailable):
        _ = service.relational


async def test_accessing_cold_before_start_raises_tier_unavailable() -> None:
    service = StorageService(backend="fake")
    with pytest.raises(StorageTierUnavailable):
        _ = service.cold


async def test_accessing_retention_before_start_raises_tier_unavailable() -> None:
    service = StorageService(backend="fake")
    with pytest.raises(StorageTierUnavailable):
        _ = service.retention


async def test_started_tiers_are_accessible_and_typed() -> None:
    service = StorageService(backend="fake")
    await service.start(ctx=None)  # type: ignore[arg-type]
    assert service.market_data is not None
    assert service.relational is not None
    assert service.cold is not None
    assert service.retention is not None
    await service.stop(grace_s=1.0)


async def test_health_is_degraded_when_started_but_postgres_tier_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer.storage.health import StorageHealthReport

    service = StorageService(backend="fake")
    await service.start(ctx=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "tier_health", lambda: StorageHealthReport(tiers=()))
    assert service.health().status is HealthStatus.DEGRADED


async def test_stop_awaits_in_flight_write_within_grace_window() -> None:
    service = StorageService(backend="fake")
    await service.start(ctx=None)  # type: ignore[arg-type]
    completed = False

    async def _write() -> None:
        nonlocal completed
        await asyncio.sleep(0.01)
        completed = True

    task = asyncio.ensure_future(_write())
    service.track_write(task)
    await service.stop(grace_s=1.0)
    assert completed is True


async def test_stop_cancels_write_that_exceeds_grace_window() -> None:
    service = StorageService(backend="fake")
    await service.start(ctx=None)  # type: ignore[arg-type]
    cancelled = False

    async def _hangs_forever() -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = asyncio.ensure_future(_hangs_forever())
    service.track_write(task)
    await service.stop(grace_s=0.01)
    assert cancelled is True
