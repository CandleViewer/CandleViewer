"""E42-T03: the flag service's read path: kill-switch freshness, the 30 s cache, the read budget,
fail closed on an outage (D1a) or one unreadable row (D1b), overrides ignored on every safety flag
(D2a), and resolution filtered by each flag's visibility, which matches 21-database-schema 10.7."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import LIVE_ENABLED, MAINTENANCE_MODE, Resolution, default_registry
from candleviewer.admin.flags.metrics import (
    export_flag_metrics,
    flag_evaluations_total,
    unreadable_overrides_total,
)
from candleviewer.admin.flags.service import (
    DEFAULT_READ_BUDGET_MS,
    READ_BUDGET_SETTING,
    FlagService,
)
from candleviewer.observability.metrics import CollectorRegistry
from tests.unit.admin.flag_fakes import T0, Clock, FakeFlagStore

_OWNER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_STORED = {"key", "kind", "description", "value"}


async def _service(budget_ms: int = 500) -> tuple[FlagService, FakeFlagStore, Clock]:
    store, clock = FakeFlagStore(), Clock()
    service = FlagService(default_registry(), store, clock=clock, read_budget_ms=budget_ms)
    with capture_logs() as logs:
        await service.start()
    assert logs[0]["event"] == "feature_flag_registry"
    assert set(store.rows) == set(service.registry)
    return service, store, clock


def _overtake_once(service: FlagService, store: FakeFlagStore) -> None:
    def once() -> None:  # a write (`invalidate()`) lands right after the next load's snapshot
        store.on_load = None
        service.invalidate()

    store.on_load = once


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


async def test_a_failed_load_is_retried_1_s_after_it_failed_whatever_the_budget() -> None:
    service, store, clock = await _service(2000)

    def spend_the_budget() -> None:
        clock.now += 2.0

    store.on_load, store.down, loads = spend_the_budget, True, store.loads
    clock.now += 30
    assert await service.value(MAINTENANCE_MODE) is True
    clock.now += 0.9
    assert await service.value(MAINTENANCE_MODE) is True
    assert store.loads == loads + 1


async def test_an_outage_a_list_detects_at_5_s_fails_the_cached_live_gate_closed() -> None:
    service, store, clock = await _service()
    store.rows[LIVE_ENABLED] = replace(store.rows[LIVE_ENABLED], value=True)
    assert await service.value(LIVE_ENABLED) is True
    store.down, clock.now = True, clock.now + 5
    listed = await service.visible(_OWNER, frozenset({"owner"}))
    assert listed.resolution is Resolution.FAIL_CLOSED  # the list reloads at the 5 s bound
    assert await service.value(LIVE_ENABLED) is False  # not the 5 s old snapshot's True


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
    service = FlagService(default_registry(), store, clock=clock, read_budget_ms=50)
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
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    store.hold, loads = asyncio.Event(), store.loads
    reader = asyncio.create_task(service.value(MAINTENANCE_MODE))
    await asyncio.sleep(0)  # the reader spawns the load,
    await asyncio.sleep(0)  # which takes its snapshot (True) and waits
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=False)
    service.invalidate()  # a write committed while the first load was in flight
    store.hold.set()
    assert await reader is False  # the retried load's value: the stale True was never installed
    assert store.loads == loads + 2


async def test_a_read_overtaken_once_answers_from_its_retried_load() -> None:
    service, store, _ = await _service()
    key = "rules.graph_editor"  # its fail-closed value is True
    store.rows[key] = replace(store.rows[key], value=False)
    _overtake_once(service, store)
    assert await service.value(key) is False
    service.invalidate()
    _overtake_once(service, store)
    assert (await service.visible(_OWNER, frozenset({"owner"}))).resolution is Resolution.STORED


async def test_a_read_overtaken_twice_fails_closed_instead_of_looping() -> None:
    service, store, _ = await _service()
    service.invalidate()
    store.on_load = service.invalidate  # every load is overtaken by a write
    loads = store.loads
    assert await service.value(MAINTENANCE_MODE) is True
    assert store.loads == loads + 2


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
    flags = {f.spec.key: f for f in (await service.visible(_OWNER, roles)).items}
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


def test_the_read_budget_is_the_contract_setting() -> None:
    assert (READ_BUDGET_SETTING, DEFAULT_READ_BUDGET_MS) == ("flags.read_budget_ms", 500)


@pytest.mark.parametrize(
    ("budget_ms", "ok"), [(49, False), (50, True), (2000, True), (2001, False)]
)
def test_a_read_budget_outside_50_to_2000_ms_refuses_to_start(budget_ms: int, ok: bool) -> None:
    if ok:
        assert FlagService(default_registry(), FakeFlagStore(), read_budget_ms=budget_ms)
        return
    with pytest.raises(ValueError, match=r"flags\.read_budget_ms must be 50-2000 ms"):
        FlagService(default_registry(), FakeFlagStore(), read_budget_ms=budget_ms)


async def test_live_enabled_is_cached_for_30_s_unlike_the_kill_switches() -> None:
    service, store, clock = await _service()
    assert await service.value(LIVE_ENABLED) is False
    store.rows[LIVE_ENABLED] = replace(store.rows[LIVE_ENABLED], value=True)
    clock.now += 29.9
    assert await service.value(LIVE_ENABLED) is False
    clock.now += 0.1
    assert await service.value(LIVE_ENABLED) is True


async def test_a_store_outage_fails_the_whole_list_closed_without_stored_members() -> None:
    service, store, clock = await _service()
    store.down, clock.now = True, clock.now + 30
    listed = await service.visible(_OWNER, frozenset({"owner"}))
    assert listed.resolution is Resolution.FAIL_CLOSED
    assert all(set(f.members()) == _STORED for f in listed.items)
    values = {f.spec.key: f.value for f in listed.items}
    assert (values[MAINTENANCE_MODE], values["killswitch.order_entry"]) == (True, True)
    assert (values[LIVE_ENABLED], values["killswitch.ingestion"]) == (False, False)


async def test_one_unreadable_row_fails_that_flag_alone_and_stays_writable() -> None:
    service, store, _ = await _service()
    key = "killswitch.order_entry"
    store.rows[key] = replace(store.rows[key], value="engaged?")
    listed = await service.visible(_OWNER, frozenset({"owner"}))
    assert listed.resolution is Resolution.STORED
    flags = {f.spec.key: f for f in listed.items}
    assert flags[key].value is True and flags[key].members() == {
        "key": key,
        "kind": "boolean",
        "description": "Refuses order acceptance.",
        "value": True,
        "overrides": [],
        "updated_at": T0,
        "unreadable": True,
    }
    other = flags[MAINTENANCE_MODE].members()
    assert {"default_value", "updated_by", "updated_at"} <= set(other) and "unreadable" not in other


async def test_an_unreadable_override_on_a_non_safety_flag_is_ignored_and_counted() -> None:
    service, store, _ = await _service()
    key, roles = "rules.graph_editor", frozenset({"owner"})
    store.rows[key] = replace(
        store.rows[key], value=False, user_overrides={_OWNER: "yes"}, role_overrides={"owner": 1}
    )
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], user_overrides={_OWNER: 2})
    service.invalidate()
    before = {k: unreadable_overrides_total.labels(k)._value.get() for k in (key, MAINTENANCE_MODE)}
    assert await service.value(key, user_id=_OWNER, roles=roles) is False
    assert await service.value(MAINTENANCE_MODE, user_id=_OWNER, roles=roles) is False
    assert unreadable_overrides_total.labels(key)._value.get() == before[key] + 2
    assert (
        unreadable_overrides_total.labels(MAINTENANCE_MODE)._value.get() == before[MAINTENANCE_MODE]
    )


_SAFETY = {MAINTENANCE_MODE, "killswitch.order_entry", "killswitch.ingestion", LIVE_ENABLED}


@pytest.mark.parametrize("key", sorted(_SAFETY))
async def test_every_safety_flag_ignores_override_rows_at_resolution(key: str) -> None:
    assert {k for k, s in default_registry().items() if not s.overridable} == _SAFETY
    service, store, _ = await _service()
    store.rows[key] = replace(
        store.rows[key], value=False, user_overrides={_OWNER: True}, role_overrides={"owner": True}
    )
    service.invalidate()
    assert await service.value(key, user_id=_OWNER, roles=frozenset({"owner"})) is False
