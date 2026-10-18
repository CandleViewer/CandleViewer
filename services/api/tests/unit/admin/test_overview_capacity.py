"""Unit (E42-T01): the `GET /admin/capacity` read model. Projection maths (measured, estimated
fallback, idle and unmeasured symbols, nothing recorded, negative fits, pinned symbols, cap and
zero headroom) with a parity grid against `DiskBudget.project_full_at`, the sub-account tier and
usage read independently under their own sub-budgets (the tier is never inferred), the
rate-budget mapping, unwired ports, the exported metrics and the slice names each service reads."""

from __future__ import annotations

import asyncio
from asyncio import Barrier
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.inspector import StatechartInspector
from candleviewer.admin.overview import slices
from candleviewer.admin.overview.capacity import (
    PART_BUDGET_S,
    TIER_CAPS,
    AdminCapacityService,
    RateBudgetRow,
    SubaccountCapacity,
    project,
)
from candleviewer.admin.overview.fanout import DEFAULT_BUDGET_S, Degraded, SliceFanOut, SliceResult
from candleviewer.admin.overview.metrics import export_overview_metrics
from candleviewer.admin.overview.ports import (
    IngestionStats,
    RateBudgetUse,
    RecordedTier,
    RecorderStatus,
    StorageSnapshot,
    SymbolStorage,
)
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.admin.overview.slices import CAPACITY_SLICES, OVERVIEW_SLICES, AdminSlice
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.recorder.budget import project_full_at

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
GB = 10**9
EST = 750_000_000
# A DSN with a fake password, which must never be echoed. Its scheme is joined at run time, so
# trufflehog's Postgres detector finds nothing here (#3482). Real credentials never go in source.
_DSN = "postgresql" + "://u:hunter2@db/x"


def _sym(
    symbol: str, growth: int | None, *, recording: bool = True, retention: int | None = 30
) -> SymbolStorage:
    return SymbolStorage(symbol, 10 * GB, growth, retention is None, retention, recording)


def _snap(
    *symbols: SymbolStorage, used: int = 40, free: int = 400, cap: int = 1000
) -> StorageSnapshot:
    return StorageSnapshot(used * GB, free * GB, None, None, symbols, cap * GB)


@pytest.mark.parametrize(
    ("snap", "per_symbol", "basis", "days"),
    [
        (_snap(_sym("BTCUSDT", GB), _sym("ETHUSDT", 2 * GB)), [GB, 2 * GB], "measured", None),
        (_snap(_sym("BTCUSDT", 3 * GB, retention=365)), [3 * GB], "measured", 133.33),
        (_snap(_sym("BTCUSDT", None), _sym("ETHUSDT", GB)), [EST, GB], "estimated", None),
        (_snap(_sym("BTCUSDT", 5 * GB, recording=False)), [0], "nothing_recorded", None),
        (_snap(_sym("SOLUSDT", None, recording=False)), [0], "nothing_recorded", None),
        (_snap(), [], "nothing_recorded", None),
        (_snap(_sym("BTCUSDT", -2 * GB)), [0], "measured", None),
        (_snap(_sym("BTCUSDT", GB, retention=None)), [GB], "measured", 400.0),
        (_snap(_sym("BTCUSDT", GB, retention=None), cap=140), [GB], "measured", 100.0),
        (_snap(_sym("BTCUSDT", GB), used=100, cap=100), [GB], "measured", 0.0),
        (_snap(_sym("BTCUSDT", GB), free=0), [GB], "measured", 0.0),
        (_snap(_sym("BTCUSDT", GB), used=110, cap=100), [GB], "measured", 0.0),
        (_snap(used=100, cap=100), [], "nothing_recorded", 0.0),
        (_snap(_sym("BTCUSDT", 0), used=100, cap=100), [0], "measured", 0.0),
        (_snap(_sym("BTCUSDT", 0, retention=None), free=0), [0], "measured", 0.0),
        (_snap(_sym("BTCUSDT", GB, retention=-5)), [GB], "measured", None),
    ],
    ids=[
        "measured-steady-state-fits",
        "measured-steady-state-exceeds-disk",
        "estimated-upper-bound",
        "idle-symbol-does-not-grow",
        "idle-unmeasured-is-not-estimated",
        "nothing-recorded",
        "negative-fit-adds-no-growth",
        "pinned-is-unbounded",
        "cap-headroom-min-of-cap-and-free",
        "cap-reached-is-exhausted-now",
        "free-zero-is-exhausted-now",
        "cap-below-use-is-exhausted-now",
        "nothing-recorded-at-cap-is-exhausted-now",
        "measured-zero-growth-at-cap-is-exhausted-now",
        "pinned-zero-growth-on-full-volume-is-exhausted-now",
        "negative-retention-is-clamped",
    ],
)
def test_projection(
    snap: StorageSnapshot, per_symbol: list[int], basis: str, days: float | None
) -> None:
    p = project(snap)
    assert [r.daily_growth_bytes for r in p.per_symbol] == per_symbol
    assert (p.daily_growth_bytes, p.basis, p.days_until_full) == (sum(per_symbol), basis, days)
    assert p.estimated is (basis == "estimated")


@pytest.mark.parametrize(
    ("used", "cap", "free"),
    [(40, 1000, 400), (40, 140, 400), (100, 100, 400), (110, 100, 400), (40, 1000, 0)],
    ids=["free-bound", "cap-bound", "cap-reached", "cap-below-use", "free-zero"],
)
@pytest.mark.parametrize("pinned", [True, False], ids=["unbounded", "steady-state-below-use"])
def test_projection_matches_the_disk_budget_runway(
    used: int, cap: int, free: int, pinned: bool
) -> None:
    symbol = _sym("BTCUSDT", GB, retention=None if pinned else 1)  # bounded: 1 GB <= used
    days = project(_snap(symbol, used=used, free=free, cap=cap)).days_until_full
    _, runway = project_full_at(
        used=used * GB, cap=cap * GB, free=free * GB, daily_growth=GB, now_us=0
    )
    assert runway is not None
    if pinned or runway == 0:
        assert days == round(float(runway), 2)
    else:
        assert days is None  # the steady state fits on disk: no exhaustion ahead


class Recorder:
    def __init__(self, *, sampled: bool = True) -> None:
        self.sampled = sampled

    async def recorder_status(self) -> RecorderStatus:
        raise AssertionError("capacity never reads recorder status")

    async def storage_snapshot(self) -> StorageSnapshot | None:
        return _snap(_sym("BTCUSDT", 2 * GB, retention=10)) if self.sampled else None


class Ingestion:
    async def ingestion_stats(self) -> IngestionStats:
        return IngestionStats(messages_per_sec=1840.5, queue_depth=12, dropped_last_hour=0)


async def _hang() -> None:
    await asyncio.Event().wait()


class Subaccounts:
    def __init__(
        self, used: int | BaseException | None = 3, barrier: Barrier | None = None
    ) -> None:
        self.used, self.entered, self.barrier = used, asyncio.Event(), barrier  # None: hang

    async def subaccounts_in_use(self) -> int:
        self.entered.set()
        if self.barrier is not None:
            await self.barrier.wait()
        if self.used is None:
            await _hang()
        if isinstance(self.used, BaseException):
            raise self.used
        return int(self.used or 0)


class Tier:
    def __init__(
        self, tier: str | Exception | None, *, hang: bool = False, barrier: Barrier | None = None
    ) -> None:
        self.tier, self.hang, self.barrier = tier, hang, barrier

    async def recorded_tier(self) -> RecordedTier | None:
        if self.barrier is not None:
            await self.barrier.wait()
        if self.hang:
            await _hang()
        if isinstance(self.tier, Exception):
            raise self.tier
        return None if self.tier is None else RecordedTier(self.tier, NOW)


class RateLimit:
    def __init__(self, sub_limit: int = 0, sub_peak: int = 0) -> None:
        self.sub_limit, self.sub_peak = sub_limit, sub_peak

    async def rate_budget(self) -> tuple[RateBudgetUse, ...]:
        uid, sub = UUID(int=1), (self.sub_limit, self.sub_peak)
        return (RateBudgetUse(uid, "main", 600, 450), RateBudgetUse(uid, "sub", *sub))


def _service(
    tier: Tier | None,
    *,
    sampled: bool = True,
    used: int | BaseException | None = 3,
    fan: SliceFanOut | None = None,
    part_s: float = PART_BUDGET_S,
) -> AdminCapacityService:
    return AdminCapacityService(
        fan or SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW),
        recorder=Recorder(sampled=sampled),
        ingestion=Ingestion(),
        rate_limit=RateLimit(),
        subaccounts=Subaccounts(used),
        tier=tier,
        now=lambda: NOW,
        part_budget_s=part_s,
    )


@pytest.mark.parametrize(("tier", "cap"), list(TIER_CAPS.items()), ids=list(TIER_CAPS))
async def test_a_recorded_tier_states_its_own_cap_as_a_recorded_fact(tier: str, cap: int) -> None:
    sub = (await _service(Tier(tier)).capacity()).subaccounts
    assert sub.status == "ok" and sub.value is not None
    assert (sub.value.tier, sub.value.cap, sub.value.used) == (tier, cap, 3)
    assert (sub.value.tier_source, sub.value.recorded_at) == ("recorded", NOW)


async def test_a_never_recorded_tier_is_unrecorded_and_still_counts_usage() -> None:
    sub = (await _service(Tier(None)).capacity()).subaccounts
    assert (sub.status, sub.value) == ("ok", SubaccountCapacity(None, None, 3, "unrecorded", None))


@pytest.mark.parametrize(
    ("tier", "status", "detail"),
    [
        (None, "unavailable", "tier: no provider wired"),
        (Tier("vip"), "error", "tier: unrecognised value"),
        (Tier(OSError("db down")), "error", "tier: source failed"),
        (Tier(None, hang=True), "error", "tier: timed out"),
    ],
    ids=["no-tier-store", "unrecognised-tier-word", "tier-read-fails", "tier-read-hangs"],
)
async def test_a_failed_tier_read_keeps_the_usage_and_never_infers(
    tier: Tier | None, status: str, detail: str
) -> None:
    sub = (await _service(tier, part_s=0.01).capacity()).subaccounts
    assert (sub.status, sub.detail) == (status, detail)
    assert sub.value == SubaccountCapacity(None, None, 3, None, None)


@pytest.mark.parametrize(
    ("used", "detail"),
    [(OSError("db down"), "subaccounts: source failed"), (None, "subaccounts: timed out")],
    ids=["usage-read-fails", "usage-read-hangs"],
)
async def test_a_failed_usage_read_keeps_the_recorded_tier(
    used: Exception | None, detail: str
) -> None:
    sub = (await _service(Tier("regular"), used=used, part_s=0.01).capacity()).subaccounts
    assert (sub.status, sub.detail) == ("error", detail)
    assert sub.value == SubaccountCapacity("regular", 5, None, "recorded", NOW)


async def test_a_stray_cancel_from_a_part_fails_only_that_part() -> None:
    sub = (await _service(Tier("regular"), used=asyncio.CancelledError()).capacity()).subaccounts
    assert (sub.status, sub.detail) == ("error", "subaccounts: source failed")
    assert sub.value == SubaccountCapacity("regular", 5, None, "recorded", NOW)


async def test_cancelling_the_request_cancels_both_parts() -> None:
    usage, fan = Subaccounts(None), SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    service = AdminCapacityService(fan, subaccounts=usage, tier=Tier(None, hang=True))
    task = asyncio.create_task(service.capacity())
    await usage.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_error_status_carries_the_error_detail_and_logs_only_part_and_class() -> None:
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    service = AdminCapacityService(fan, tier=Tier("vip"), now=lambda: NOW)  # usage unwired
    with capture_logs() as logs:
        sub = (await service.capacity()).subaccounts
    assert (sub.status, sub.detail) == ("error", "tier: unrecognised value")
    reasons = {e["reason"] for e in logs if e.get("source") == AdminSlice.SUBACCOUNTS}
    assert reasons == {"subaccounts:unwired--tier:UnrecognisedTier"} and "vip" not in repr(logs)


def test_the_part_budget_stays_inside_the_slice_budget() -> None:
    assert PART_BUDGET_S < DEFAULT_BUDGET_S
    with pytest.raises(ValueError):
        AdminCapacityService(SliceFanOut(budget_s=0.1), part_budget_s=0.2)


async def test_rate_budget_utilisation_and_the_exported_metrics() -> None:
    registry = CollectorRegistry()
    collector = export_overview_metrics(registry, env="demo")
    snap = await _service(Tier("regular")).capacity()
    assert snap.rate_budget.value == (
        RateBudgetRow(UUID(int=1), "main", 600, 450, 75.0),
        RateBudgetRow(UUID(int=1), "sub", 0, 0, 0.0),
    )
    assert snap.rate_budget.status == "ok"
    assert snap.storage.value is not None and snap.storage.value.projected_bytes == 20 * GB
    gauge = registry.get_sample_value("cv_admin_capacity_projection_bytes", {"env": "demo"})
    timed = registry.get_sample_value(
        "cv_admin_overview_source_duration_seconds_count",
        {"source": AdminSlice.CAPACITY_STORAGE, "env": "demo"},
    )
    collector.close()
    assert gauge == 20 * GB and (timed or 0) >= 1


class SpyFan(SliceFanOut):
    """Records the slice name of every read, then reads as usual."""

    def __init__(self) -> None:
        super().__init__(monotonic=lambda: 0.0, now=lambda: NOW)
        self.names: set[AdminSlice] = set()

    async def read[T](
        self,
        name: AdminSlice,
        load: Callable[[], Awaitable[T | Degraded[T]]],
        *,
        cached: bool = True,
    ) -> SliceResult[T]:
        self.names.add(name)
        return await super().read(name, load, cached=cached)


async def test_each_service_reads_exactly_its_own_slice_names() -> None:
    overview_fan, capacity_fan = SpyFan(), SpyFan()
    inspector_fan = SpyFan()
    await AdminOverviewService(overview_fan).overview()
    await AdminCapacityService(capacity_fan).capacity()
    await StatechartInspector(inspector_fan, lambda *_: None, {}).listing(lambda *_: True)
    assert overview_fan.names == set(OVERVIEW_SLICES)
    assert capacity_fan.names == set(CAPACITY_SLICES)
    assert inspector_fan.names == set(slices.INSPECTOR_SLICES)


async def test_ingestion_is_reported_and_storage_waits_for_the_first_disk_sample() -> None:
    snap = await _service(Tier("regular"), sampled=False).capacity()
    assert snap.ingestion.value == IngestionStats(1840.5, 12, 0)
    assert (snap.storage.status, snap.storage.detail) == (
        "unavailable",
        "storage: no disk sample yet",
    )


async def test_unwired_ports_make_every_section_unavailable() -> None:
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    snap = await AdminCapacityService(fan, now=lambda: NOW).capacity()
    sections = (snap.storage, snap.ingestion, snap.rate_budget, snap.subaccounts)
    assert {s.status for s in sections} == {"unavailable"}
    assert {s.detail for s in sections} == {
        "storage: no provider wired",
        "ingestion: no provider wired",
        "rate-limit peak: no provider wired",
        "subaccounts: no provider wired",
    }


async def test_usage_and_tier_are_read_concurrently() -> None:
    both = Barrier(2)  # read one after the other, the first part would time out at the barrier
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    usage, tier = Subaccounts(3, barrier=both), Tier("regular", barrier=both)
    sub = (await AdminCapacityService(fan, subaccounts=usage, tier=tier).capacity()).subaccounts
    assert (sub.status, sub.value) == ("ok", SubaccountCapacity("regular", 5, 3, "recorded", NOW))


async def test_a_failed_usage_read_logs_only_part_and_class() -> None:
    leak = OSError(_DSN)
    with capture_logs() as logs:
        await _service(Tier("regular"), used=leak).capacity()
    reasons = [e["reason"] for e in logs if e.get("source") == AdminSlice.SUBACCOUNTS]
    assert reasons == ["subaccounts:OSError"] and "hunter2" not in repr(logs)


@pytest.mark.parametrize(
    ("limit", "peak", "detail"),
    [(0, 7, "invalid limit"), (600, -1, "invalid usage"), (-5, 0, "invalid limit")],
    ids=["usage-against-no-limit", "negative-usage", "negative-limit-without-usage"],
)
async def test_an_invalid_rate_budget_row_is_an_error_not_a_healthy_figure(
    limit: int, peak: int, detail: str
) -> None:
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    service = AdminCapacityService(fan, rate_limit=RateLimit(sub_limit=limit, sub_peak=peak))
    budget = (await service.capacity()).rate_budget
    assert (budget.status, budget.detail) == ("error", f"rate_budget: {detail}")


def test_a_negative_retention_is_clamped_to_zero_never_flipped() -> None:
    p = project(_snap(_sym("A", 3 * GB, retention=-30), _sym("B", 5 * GB, retention=100)))
    assert [r.retention_days for r in p.per_symbol] == [0, 100]
    assert (p.projected_bytes, p.days_until_full) == (500 * GB, 50.0)
