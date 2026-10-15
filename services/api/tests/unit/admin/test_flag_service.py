"""E42-T03: the flag service's read path: kill-switch freshness, the 30 s cache, fail closed on
an unreachable store, and role-filtered resolution."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import MAINTENANCE_MODE, default_registry
from candleviewer.admin.flags.metrics import export_flag_metrics, flag_evaluations_total
from candleviewer.admin.flags.service import FlagService
from candleviewer.observability.metrics import CollectorRegistry
from tests.unit.admin.flag_fakes import Clock, FakeFlagStore

_OWNER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")


async def _service() -> tuple[FlagService, FakeFlagStore, Clock]:
    store, clock = FakeFlagStore(), Clock()
    service = FlagService(default_registry(), store, clock=clock)
    with capture_logs() as logs:
        await service.start()
    assert logs[0]["event"] == "feature_flag_registry"
    assert set(store.rows) == set(service.registry)
    return service, store, clock


async def test_killswitch_flag_changed_in_the_database_is_reflected_within_5_s() -> None:
    service, store, clock = await _service()
    assert await service.value(MAINTENANCE_MODE) is False
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    clock.now += 4.9
    assert await service.value(MAINTENANCE_MODE) is False
    clock.now += 0.1
    assert await service.value(MAINTENANCE_MODE) is True


async def test_ordinary_flags_are_cached_for_30_s() -> None:
    service, store, clock = await _service()
    assert await service.value("rules.graph_editor") is True
    store.rows["rules.graph_editor"] = replace(store.rows["rules.graph_editor"], value=False)
    clock.now += 29.9
    assert await service.value("rules.graph_editor") is True
    loads = store.loads
    clock.now += 0.1
    assert await service.value("rules.graph_editor") is False
    assert store.loads == loads + 1


async def test_unreachable_store_fails_closed_and_is_retried_after_1_s() -> None:
    service, store, clock = await _service()
    store.down = True
    clock.now += 30
    with capture_logs() as logs:
        assert await service.value(MAINTENANCE_MODE) is True
        assert await service.value("trading.live_enabled") is False
    assert logs[0]["event"] == "feature_flag_store_unavailable"
    loads = store.loads
    clock.now += 0.5
    assert await service.value(MAINTENANCE_MODE) is True
    assert store.loads == loads
    store.down = False
    clock.now += 0.5
    assert await service.value(MAINTENANCE_MODE) is False


async def test_invalidate_forces_a_reload() -> None:
    service, store, _ = await _service()
    await service.value("rules.form_editor")
    loads = store.loads
    service.invalidate()
    await service.value("rules.form_editor")
    assert store.loads == loads + 1


async def test_a_flag_without_a_row_resolves_to_its_default_not_its_fail_closed_value() -> None:
    service, store, _ = await _service()
    del store.rows[MAINTENANCE_MODE]
    service.invalidate()
    assert await service.value(MAINTENANCE_MODE) is False


async def test_a_hung_store_times_out_and_fails_closed() -> None:
    store, clock = FakeFlagStore(), Clock()
    service = FlagService(default_registry(), store, clock=clock, store_timeout_s=0.001)
    await store.ensure(service.registry.values())
    store.hold = asyncio.Event()
    with capture_logs() as logs:
        assert await service.value(MAINTENANCE_MODE) is True
    assert logs[-1] == {
        "event": "feature_flag_store_unavailable",
        "error": "TimeoutError",
        "log_level": "warning",
    }


async def test_a_raising_store_fails_closed_and_waits_for_the_retry() -> None:
    service, store, clock = await _service()
    store.crash = RuntimeError("socket closed")
    clock.now += 30
    assert await service.value(MAINTENANCE_MODE) is True
    loads = store.loads
    assert await service.value(MAINTENANCE_MODE) is True
    assert store.loads == loads


async def test_concurrent_reads_share_one_load() -> None:
    service, store, _ = await _service()
    service.invalidate()
    store.hold = asyncio.Event()
    loads = store.loads
    readers = [asyncio.create_task(service.value("rules.graph_editor")) for _ in range(3)]
    await asyncio.sleep(0)
    store.hold.set()
    assert await asyncio.gather(*readers) == [True, True, True]
    assert store.loads == loads + 1


async def test_a_load_started_before_invalidate_is_dropped() -> None:
    service, store, _ = await _service()
    service.invalidate()
    store.hold = asyncio.Event()
    loads = store.loads
    reader = asyncio.create_task(service.value(MAINTENANCE_MODE))
    await asyncio.sleep(0)
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    service.invalidate()  # a write committed while the first load was in flight
    store.hold.set()
    assert await reader is True  # the stale snapshot (value False) was never installed
    assert store.loads == loads + 2


async def test_a_read_overtaken_twice_fails_closed_instead_of_looping() -> None:
    service, store, _ = await _service()
    service.invalidate()
    store.on_load = service.invalidate  # every load is overtaken by a write
    loads = store.loads
    assert await service.value(MAINTENANCE_MODE) is True
    assert store.loads == loads + 2


async def test_a_fresh_read_bypasses_a_valid_cache() -> None:
    service, store, _ = await _service()
    assert await service.value(MAINTENANCE_MODE) is False
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    assert await service.value(MAINTENANCE_MODE) is False
    assert await service.value(MAINTENANCE_MODE, fresh=True) is True


@pytest.mark.parametrize(
    ("roles", "owner_only_seen"), [(frozenset({"owner"}), True), (frozenset({"manager"}), False)]
)
async def test_visible_flags_are_filtered_by_role(
    roles: frozenset[str], owner_only_seen: bool
) -> None:
    service, store, _ = await _service()
    store.rows["rules.graph_editor"] = replace(
        store.rows["rules.graph_editor"], user_overrides={_OWNER: False}
    )
    service.invalidate()
    flags = {f.spec.key: f for f in await service.visible(_OWNER, roles)}
    assert ("maintenance.keep_recorder" in flags) is owner_only_seen
    assert ("storage.cold_tier" in flags) is owner_only_seen
    assert MAINTENANCE_MODE in flags
    assert flags["rules.graph_editor"].value is False
    assert flags["rules.graph_editor"].stored is not None


async def test_every_evaluation_is_counted_per_flag() -> None:
    assert flag_evaluations_total._labelnames == ("flag",)
    service, _, _ = await _service()
    before = flag_evaluations_total.labels(MAINTENANCE_MODE)._value.get()
    await service.value(MAINTENANCE_MODE)
    assert flag_evaluations_total.labels(MAINTENANCE_MODE)._value.get() == before + 1


def test_flag_series_are_exported_with_the_env_label() -> None:
    registry = CollectorRegistry()
    flag_evaluations_total.labels("rules.form_editor").inc()
    collector = export_flag_metrics(registry, env="demo")
    try:
        samples = [s for family in registry.collect() for s in family.samples]
        names = {s.name for s in samples}
        assert "cv_feature_flag_evaluations_total" in names
        assert {s.labels["env"] for s in samples} == {"demo"}
    finally:
        collector.close()


@pytest.mark.perf
async def test_cached_resolution_is_under_1_ms_p99() -> None:
    import time

    service, _, _ = await _service()
    samples = []
    for _ in range(2000):
        start = time.perf_counter()
        await service.value("rules.graph_editor", user_id=_OWNER, roles=frozenset({"owner"}))
        samples.append(time.perf_counter() - start)
    samples.sort()
    assert samples[int(len(samples) * 0.99)] < 0.001
