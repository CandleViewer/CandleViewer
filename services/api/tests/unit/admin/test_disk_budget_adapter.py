"""E42-T01: `DiskBudgetAdapter`, the admin `RecorderPort` over the recorder's `DiskBudget`.

The storage snapshot is the budget's last sample, mapped and never measured per request. The
adapter fails closed (no sample, a breakdown never measured, or a sample or breakdown older than
three sample intervals, never yields a headroom), takes growth from `measured_growth()` so
"not measured yet" stays `None` (never the `0` that `report()` folds it into), reads the cap from
the budget's `BudgetConfig`, and says zero headroom is 0 days. The recorder status stays
unwired. Budgets here are real `DiskBudget`s over a fake meter and clock (`_disk_fakes`), sampled
by `sample_once()`."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

import candleviewer.admin_wiring as wiring
from candleviewer.admin.overview.capacity import (
    ESTIMATED_DAILY_GROWTH_BYTES,
    CapacitySnapshot,
    project,
)
from candleviewer.admin.overview.fanout import SourceUnavailable
from candleviewer.admin.overview.metrics import export_overview_metrics
from candleviewer.admin.overview.ports import StorageSnapshot, SymbolStorage
from candleviewer.admin.overview.service import OverviewSnapshot
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.recorder.budget import US_PER_S, BudgetConfig, DiskBudget
from candleviewer.settings import Settings
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import AccountTotals, UserTotals
from tests.unit.admin._disk_fakes import BTC, ETH, SIZE, clock, sampled, unsampled
from tests.unit.recorder._budget_fakes import CAP, GB, NOW, TOTAL, FakeMeter, make_budget

_STALE = "storage: disk sample is stale"
_NO_BREAKDOWN = "storage: no disk breakdown yet"


async def _snapshot(budget: DiskBudget, age_s: float = 0.0) -> StorageSnapshot:
    snap = await wiring.DiskBudgetAdapter(budget, now=clock(age_s)).storage_snapshot()
    assert snap is not None
    return snap


# -- no sample, a fresh sample, a stale sample -----------------------------------------------


async def test_before_the_first_sample_there_is_no_snapshot() -> None:
    adapter = wiring.DiskBudgetAdapter(unsampled(), now=clock())
    assert await adapter.storage_snapshot() is None  # the services answer "no disk sample yet"


async def test_a_fresh_sample_maps_recorded_bytes_free_space_cap_and_symbols() -> None:
    snap = await _snapshot(await sampled())  # 50 GB recorded (+ 1 GB postgres), 500 GB free
    assert snap == StorageSnapshot(
        used_bytes=50 * GB,  # QuestDB + Parquet, what the cap is measured against; not Postgres
        free_bytes=TOTAL // 2,
        daily_growth_bytes=None,
        days_until_full=None,
        symbols=(
            SymbolStorage(BTC, 30 * GB, None, False, 30, True),
            SymbolStorage(ETH, 20 * GB, None, False, 30, True),
        ),
        cap_bytes=CAP,
    )


@pytest.mark.parametrize("interval", [30.0, 60.0], ids=["30s", "60s"])
@pytest.mark.parametrize(
    ("intervals", "shown"),
    [(0, True), (1, True), (3, True), (3.001, False), (4, False), (-0.001, False)],
    ids=["now", "one", "three-is-the-last", "just-over-three", "four", "clock-behind-the-sample"],
)
async def test_a_sample_is_shown_for_three_sample_intervals_and_then_fails_closed(
    interval: float, intervals: float, shown: bool
) -> None:
    budget = await sampled(config=BudgetConfig(cap_bytes=CAP, sample_interval_s=interval))
    adapter = wiring.DiskBudgetAdapter(budget, now=clock(intervals * interval))
    if shown:
        assert await adapter.storage_snapshot() is not None
        return
    with pytest.raises(SourceUnavailable) as refused:  # never a stale headroom
        await adapter.storage_snapshot()
    assert refused.value.detail == _STALE


async def test_a_sampler_that_keeps_failing_leaves_a_report_that_ages_out() -> None:
    meter = FakeMeter(used=50 * GB, symbols={BTC: 50 * GB})
    budget, _, _ = make_budget(meter)
    await budget.sample_once()
    meter.fail = True  # statvfs fails: every later pass raises and the last report stays
    with pytest.raises(OSError):
        await budget.sample_once()
    await _snapshot(budget, 180.0)  # three intervals on, it is still the last sample
    with pytest.raises(SourceUnavailable):
        await _snapshot(budget, 181.0)  # past them, its headroom is no longer shown


async def test_the_staleness_bound_is_the_budgets_own_interval_not_a_constant() -> None:
    budget = await sampled(config=BudgetConfig(cap_bytes=CAP, sample_interval_s=1.0))
    await _snapshot(budget, 3.0)  # three intervals of 1 s
    with pytest.raises(SourceUnavailable):
        await _snapshot(budget, 3.5)  # a fixed 180 s bound (three default intervals) would show it


async def test_a_breakdown_that_never_succeeded_fails_closed_never_zero_bytes_used() -> None:
    budget, _, _ = make_budget(FakeMeter(used=450 * GB, symbols={BTC: GB}, breakdown_fail=True))
    await budget.sample_once()  # free space is sampled, the sizes never were: tiers stay empty
    with pytest.raises(SourceUnavailable) as refused:
        await _snapshot(budget)
    assert refused.value.detail == _NO_BREAKDOWN


async def test_a_breakdown_failing_after_a_success_ages_out_like_the_sample() -> None:
    at, meter = [NOW], FakeMeter(used=450 * GB, symbols={BTC: 450 * GB})
    budget, _, _ = make_budget(meter, clock=lambda: at[0])
    await budget.sample_once()
    meter.breakdown_fail, at[0] = True, NOW + 180 * US_PER_S
    await budget.sample_once()  # a fresh pass over sizes three intervals old: still shown
    assert (await _snapshot(budget, 180.0)).used_bytes == 450 * GB
    with pytest.raises(SourceUnavailable) as refused:  # past them, the old bytes are not shown
        await _snapshot(budget, 180.5)
    assert refused.value.detail == _STALE


async def test_a_recovering_pass_publishes_its_breakdown_age_with_its_report() -> None:
    at, gate = [NOW], asyncio.Event()
    gate.set()

    async def pins() -> frozenset[str]:  # the pass awaits the pinned set before its report
        await gate.wait()
        return frozenset()

    meter = FakeMeter(used=450 * GB, symbols={BTC: 450 * GB})
    budget, _, _ = make_budget(meter, clock=lambda: at[0], pins=pins)
    await budget.sample_once()
    meter.breakdown_fail, at[0] = True, NOW + 180 * US_PER_S
    await budget.sample_once()  # a fresh report over the sizes from NOW
    meter.breakdown_fail, meter.used, at[0] = False, 900 * GB, NOW + 240 * US_PER_S
    gate.clear()
    recovering = asyncio.create_task(budget.sample_once())  # sized now, held before its report
    await asyncio.sleep(0)
    with pytest.raises(SourceUnavailable):  # the old report's 240 s old sizes are not shown
        await _snapshot(budget, 240.0)
    gate.set()
    await recovering
    assert (await _snapshot(budget, 240.0)).used_bytes == 900 * GB


# -- growth: measured, or None -----------------------------------------------------------------


async def test_growth_not_measured_yet_is_none_never_the_zero_the_report_folds_it_into() -> None:
    budget = await sampled()
    report = budget.report()
    assert report is not None and report.daily_growth_bytes == 0  # the trap `report()` sets
    assert {s.daily_growth_bytes for s in report.symbols} == {0}
    snap = await _snapshot(budget)
    assert snap.daily_growth_bytes is None
    assert [s.daily_growth_bytes for s in snap.symbols] == [None, None]


async def test_measured_growth_is_the_fits_total_and_per_symbol_rate() -> None:
    budget = await sampled(measured=True, symbols={BTC: SIZE, ETH: GB // 10})
    total, rates = budget.measured_growth()
    snap = await _snapshot(budget)
    assert total is not None and abs(total - 10 * GB) <= GB // 100
    assert snap.daily_growth_bytes == total  # the net total, not the report's `or 0` copy
    by_symbol = {s.symbol: s for s in snap.symbols}
    assert by_symbol[BTC].daily_growth_bytes == rates[BTC] > 0
    assert by_symbol[ETH].daily_growth_bytes is None  # no fit for it yet: unmeasured, not 0


# -- per-symbol rows, the cap, zero headroom -----------------------------------------------------


async def test_a_pinned_symbol_is_kept_forever_the_others_for_the_budgets_retention() -> None:
    config = BudgetConfig(cap_bytes=CAP, retention_days=45)
    snap = await _snapshot(await sampled(pinned=frozenset({BTC}), config=config))
    assert snap.symbols == (
        SymbolStorage(BTC, 30 * GB, None, True, None, True),  # pinned: retention_days is None
        SymbolStorage(ETH, 20 * GB, None, False, 45, True),
    )


async def test_the_cap_is_the_budgets_config_never_the_volume() -> None:
    snap = await _snapshot(await sampled(config=BudgetConfig(cap_bytes=123 * GB)))
    assert snap.cap_bytes == 123 * GB != TOTAL
    assert snap.headroom_bytes == 73 * GB  # min(cap - used, free) = min(123 - 50, 500)


@pytest.mark.parametrize(
    ("used", "free"),
    [(CAP, TOTAL // 2), (CAP + GB, TOTAL // 2), (50 * GB, 0)],
    ids=["at-the-cap", "over-the-cap", "volume-full"],
)
async def test_zero_headroom_is_zero_days_even_with_no_growth_measured(
    used: int, free: int
) -> None:
    snap = await _snapshot(await sampled(used=used, free=free))
    assert snap.daily_growth_bytes is None and snap.headroom_bytes == 0
    assert snap.days_until_full == 0.0  # exhausted now: never "no exhaustion ahead"


# -- days until full follows the capacity projection ----------------------------------------------


@pytest.mark.parametrize("free_gb", [500, 333], ids=["whole-days", "fractional-days"])
async def test_days_until_full_is_the_capacity_projections_when_growth_is_measured(
    free_gb: int,
) -> None:
    budget = await sampled(measured=True, pinned=frozenset({BTC}), free=free_gb * GB)
    snap = await _snapshot(budget)  # pinned: unbounded growth
    _, rates = budget.measured_growth()
    days = round(snap.headroom_bytes / rates[BTC], 2)
    assert snap.headroom_bytes == free_gb * GB and abs(days - free_gb / 10) < 0.1
    assert snap.days_until_full == days == project(snap).days_until_full


async def test_a_steady_state_that_fits_on_disk_has_no_exhaustion_ahead() -> None:
    snap = await _snapshot(await sampled(measured=True))  # 10 GB/day x 30 days = 300 GB < 500 GB
    assert snap.daily_growth_bytes is not None and project(snap).basis == "measured"
    assert snap.days_until_full is None


async def test_the_estimate_belongs_to_capacity_so_an_unmeasured_symbol_has_no_days() -> None:
    snap = await _snapshot(await sampled(pinned=frozenset({BTC, ETH})))  # growth never measured
    estimate = project(snap)
    assert estimate.estimated and estimate.daily_growth_bytes == 2 * ESTIMATED_DAILY_GROWTH_BYTES
    assert estimate.days_until_full is not None  # `/admin/capacity` shows the flagged estimate
    assert snap.days_until_full is None  # the overview tile only ever shows measured growth


async def test_nothing_on_disk_is_nothing_recorded_with_zero_growth_not_a_null() -> None:
    snap = await _snapshot(await sampled(used=GB, symbols={}))
    projection = project(snap)
    assert snap.symbols == () and snap.days_until_full is None  # growth 0 by fact: no exhaustion
    assert (projection.basis, projection.daily_growth_bytes) == ("nothing_recorded", 0)


async def test_the_recorder_status_is_not_served_it_stays_unwired() -> None:
    adapter = wiring.DiskBudgetAdapter(await sampled(), now=clock())
    with pytest.raises(SourceUnavailable) as unwired:  # `symbols_recording = 0` would be a guess
        await adapter.recorder_status()
    assert unwired.value.detail == "recorder: no provider wired"


# -- composition-root wiring --------------------------------------------------------------------


async def _read_models(
    budget: DiskBudget | None, age_s: float = 0.0
) -> tuple[OverviewSnapshot, CapacitySnapshot]:
    overview, capacity = wiring.build_admin_read_models(
        Settings(storage_backend="fake"), now=clock(age_s), disk_budget=budget
    )
    return await overview.overview(), await capacity.capacity()


async def test_a_sampled_disk_budget_serves_both_storage_slices_and_nothing_else() -> None:
    overview, capacity = await _read_models(await sampled(measured=True, pinned=frozenset({BTC})))
    assert (overview.storage.status, capacity.storage.status) == ("ok", "ok")
    assert (overview.storage.value.used_bytes, overview.storage.value.free_bytes) == (
        SIZE,
        TOTAL // 2,
    )
    assert overview.storage.value.days_until_full == capacity.storage.value.days_until_full
    assert capacity.storage.value.basis == "measured" and not capacity.storage.value.estimated
    unwired = {
        "recorder": overview.recorder,  # the scaffold knows no symbols: `0` would be a guess
        "trading": overview.trading,
        "ingestion": capacity.ingestion,
        "rate_budget": capacity.rate_budget,
    }
    assert {k: v.status for k, v in unwired.items()} == dict.fromkeys(unwired, "unavailable")
    assert overview.recorder.detail == "recorder: no provider wired"


async def test_a_breakdown_never_measured_leaves_both_storage_slices_unavailable() -> None:
    budget, _, _ = make_budget(FakeMeter(used=450 * GB, breakdown_fail=True))
    await budget.sample_once()
    overview, capacity = await _read_models(budget)
    for part in (overview.storage, capacity.storage):
        assert (part.status, part.detail, part.value) == ("unavailable", _NO_BREAKDOWN, None)


class _Counts:
    """Stands in for `SqlAlchemyAdminCounts`, the real backend's relational repository."""

    async def user_totals(self) -> UserTotals:
        return UserTotals(5, 4, 1)

    async def account_totals(self, expiring_before: datetime) -> AccountTotals:
        return AccountTotals(6, 5, 2, 1)

    async def open_incidents(self) -> int:
        return 7

    async def subaccounts_in_use(self) -> int:
        return 3


async def test_the_real_backend_serves_the_budget_next_to_its_relational_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", lambda dsn, suffix: suffix)
    monkeypatch.setattr(wiring, "SqlAlchemyAdminCounts", lambda relational, *, env: _Counts())
    real = Settings(storage_backend="real")
    overview, capacity = wiring.build_admin_read_models(
        real, now=clock(), disk_budget=await sampled()
    )
    snap, cap = await overview.overview(), await capacity.capacity()
    assert (snap.users.status, snap.storage.status, cap.storage.status) == ("ok", "ok", "ok")
    assert (snap.recorder.status, cap.ingestion.status) == ("unavailable", "unavailable")


async def test_without_a_disk_budget_both_storage_slices_stay_unavailable() -> None:
    overview, capacity = await _read_models(None)
    for got in (overview.storage, capacity.storage):
        assert (got.status, got.detail, got.value) == (
            "unavailable",
            "storage: no provider wired",
            None,
        )


async def test_a_budget_that_has_not_sampled_yet_is_unavailable_with_its_own_reason() -> None:
    overview, capacity = await _read_models(unsampled())
    for got in (overview.storage, capacity.storage):
        assert (got.status, got.detail, got.value) == (
            "unavailable",
            "storage: no disk sample yet",
            None,
        )


async def test_a_stale_sample_shows_no_headroom_in_either_slice() -> None:
    overview, capacity = await _read_models(await sampled(), age_s=181.0)
    for got in (overview.storage, capacity.storage):
        assert (got.status, got.detail, got.value) == ("unavailable", _STALE, None)


async def test_the_projection_gauge_is_fed_by_the_wired_budget() -> None:
    registry = CollectorRegistry()
    collector = export_overview_metrics(registry, env="demo")
    _, capacity = await _read_models(await sampled(measured=True))  # BTC kept for 30 days
    gauge = registry.get_sample_value("cv_admin_capacity_projection_bytes", {"env": "demo"})
    collector.close()
    assert capacity.storage.value is not None
    assert gauge == capacity.storage.value.projected_bytes > 250 * GB  # 10 GB/day x 30 days
