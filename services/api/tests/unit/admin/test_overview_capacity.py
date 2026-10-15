"""Unit (E42-T01): the `GET /admin/capacity` read model. Projection maths (measured, estimated
fallback, idle and unmeasured symbols, nothing recorded, negative fits, pinned symbols, cap
headroom), the sub-account tier and usage read independently (the tier is never inferred), the
rate-budget mapping, unwired ports, the exported metrics and the disjoint slice-name sets."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from candleviewer.admin.overview.capacity import (
    AdminCapacityService,
    RateBudgetRow,
    SubaccountCapacity,
    project,
)
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin.overview.metrics import export_overview_metrics
from candleviewer.admin.overview.ports import (
    IngestionStats,
    RateBudgetUse,
    RecordedTier,
    RecorderStatus,
    StorageSnapshot,
    SymbolStorage,
)
from candleviewer.admin.overview.slices import CAPACITY_SLICES, OVERVIEW_SLICES, AdminSlice
from candleviewer.observability.metrics import CollectorRegistry

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
GB = 10**9
EST = 750_000_000


def _sym(
    symbol: str, growth: int | None, *, recording: bool = True, retention: int | None = 30
) -> SymbolStorage:
    return SymbolStorage(symbol, 10 * GB, growth, retention is None, retention, recording)


def _snap(*symbols: SymbolStorage, cap: int | None = None) -> StorageSnapshot:
    return StorageSnapshot(40 * GB, 400 * GB, None, None, symbols, cap)


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
        (_snap(_sym("BTCUSDT", GB, retention=None), cap=140 * GB), [GB], "measured", 100.0),
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
    ],
)
def test_projection(
    snap: StorageSnapshot, per_symbol: list[int], basis: str, days: float | None
) -> None:
    p = project(snap)
    assert [r.daily_growth_bytes for r in p.per_symbol] == per_symbol
    assert (p.daily_growth_bytes, p.basis, p.days_until_full) == (sum(per_symbol), basis, days)
    assert p.estimated is (basis == "estimated")


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


class Subaccounts:
    def __init__(self, used: int | Exception = 3) -> None:
        self.used = used

    async def subaccounts_in_use(self) -> int:
        if isinstance(self.used, Exception):
            raise self.used
        return self.used


class Tier:
    def __init__(self, tier: str | Exception | None) -> None:
        self.tier = tier

    async def recorded_tier(self) -> RecordedTier | None:
        if isinstance(self.tier, Exception):
            raise self.tier
        return None if self.tier is None else RecordedTier(self.tier, NOW)


class RateLimit:
    async def rate_budget(self) -> tuple[RateBudgetUse, ...]:
        uid = UUID(int=1)
        return (RateBudgetUse(uid, "main", 600, 450), RateBudgetUse(uid, "sub", 0, 7))


def _service(
    tier: Tier | None, *, sampled: bool = True, used: int | Exception = 3
) -> AdminCapacityService:
    return AdminCapacityService(
        SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW),
        recorder=Recorder(sampled=sampled),
        ingestion=Ingestion(),
        rate_limit=RateLimit(),
        subaccounts=Subaccounts(used),
        tier=tier,
        now=lambda: NOW,
    )


@pytest.mark.parametrize(
    "expected",
    [
        SubaccountCapacity("regular", 5, 3, "recorded", NOW),
        SubaccountCapacity("business_kyc", 20, 3, "recorded", NOW),
    ],
    ids=["regular-caps-5", "business-kyc-caps-20"],
)
async def test_recorded_tier_states_its_cap_as_a_recorded_fact(
    expected: SubaccountCapacity,
) -> None:
    sub = (await _service(Tier(expected.tier)).capacity()).subaccounts
    assert (sub.status, sub.value) == ("ok", expected)


async def test_a_never_recorded_tier_is_unrecorded_and_still_counts_usage() -> None:
    sub = (await _service(Tier(None)).capacity()).subaccounts
    assert (sub.status, sub.value) == ("ok", SubaccountCapacity(None, None, 3, "unrecorded", None))


@pytest.mark.parametrize(
    ("tier", "status", "detail"),
    [
        (None, "unavailable", "tier: no provider wired"),
        (Tier("vip"), "error", "tier: source failed"),
        (Tier(OSError("db down")), "error", "tier: source failed"),
    ],
    ids=["no-tier-store", "unknown-tier-word", "tier-read-fails"],
)
async def test_a_failed_tier_read_keeps_the_usage_and_never_infers(
    tier: Tier | None, status: str, detail: str
) -> None:
    sub = (await _service(tier).capacity()).subaccounts
    assert (sub.status, sub.detail) == (status, detail)
    assert sub.value == SubaccountCapacity(None, None, 3, None, None)


async def test_a_failed_usage_read_keeps_the_recorded_tier() -> None:
    sub = (await _service(Tier("regular"), used=OSError("db down")).capacity()).subaccounts
    assert (sub.status, sub.detail) == ("error", "subaccounts: source failed")
    assert sub.value == SubaccountCapacity("regular", 5, None, "recorded", NOW)


async def test_rate_budget_utilisation_and_the_exported_metrics() -> None:
    registry = CollectorRegistry()
    collector = export_overview_metrics(registry, env="demo")
    snap = await _service(Tier("regular")).capacity()
    assert snap.rate_budget.value == (
        RateBudgetRow(UUID(int=1), "main", 600, 450, 75.0),
        RateBudgetRow(UUID(int=1), "sub", 0, 7, 0.0),
    )
    assert snap.storage.value is not None and snap.storage.value.projected_bytes == 20 * GB
    gauge = registry.get_sample_value("cv_admin_capacity_projection_bytes", {"env": "demo"})
    timed = registry.get_sample_value(
        "cv_admin_overview_source_duration_seconds_count",
        {"source": AdminSlice.CAPACITY_STORAGE, "env": "demo"},
    )
    collector.close()
    assert gauge == 20 * GB and (timed or 0) >= 1


def test_overview_and_capacity_slice_names_are_disjoint_and_cover_the_enum() -> None:
    assert OVERVIEW_SLICES.isdisjoint(CAPACITY_SLICES)
    assert OVERVIEW_SLICES | CAPACITY_SLICES == set(AdminSlice)


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
