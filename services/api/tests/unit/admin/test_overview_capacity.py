"""Unit (E42-T01): the `GET /admin/capacity` read model. Projection maths (measured, estimated
fallback, nothing recorded, steady state vs disk, pinned symbols), the recorded sub-account tier
(never inferred), the rate-budget mapping, unwired ports and the projection gauge."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from prometheus_client import REGISTRY

from candleviewer.admin.overview.capacity import (
    AdminCapacityService,
    RateBudgetRow,
    SubaccountCapacity,
    project,
)
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin.overview.ports import (
    IngestionStats,
    RateBudgetUse,
    RecordedTier,
    RecorderStatus,
    StorageSnapshot,
    SymbolStorage,
)

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
GB = 10**9
EST = 750_000_000


def _sym(
    growth: int | None, *, recording: bool = True, retention: int | None = 30
) -> SymbolStorage:
    return SymbolStorage("BTCUSDT", 10 * GB, growth, retention is None, retention, recording)


def _snap(*symbols: SymbolStorage) -> StorageSnapshot:
    return StorageSnapshot(40 * GB, 400 * GB, None, None, symbols)


@pytest.mark.parametrize(
    ("symbols", "growth", "basis", "days"),
    [
        ((_sym(1 * GB), _sym(2 * GB)), 3 * GB, "measured", None),  # 90 GB steady state fits
        ((_sym(3 * GB, retention=365),), 3 * GB, "measured", 133.33),  # 1095 GB > 440 GB
        ((_sym(None), _sym(1 * GB)), EST + GB, "estimated", None),  # fallback: upper bound
        ((_sym(5 * GB, recording=False),), 0, "nothing_recorded", None),  # not recording
        ((), 0, "nothing_recorded", None),  # AC5: zero growth by fact, explicit marker
        ((_sym(1 * GB, retention=None),), GB, "measured", 400.0),  # pinned: unbounded
    ],
)
def test_projection(
    symbols: tuple[SymbolStorage, ...], growth: int, basis: str, days: float | None
) -> None:
    p = project(_snap(*symbols))
    assert (p.daily_growth_bytes, p.basis, p.days_until_full) == (growth, basis, days)
    assert p.estimated is (basis == "estimated")
    assert [r.daily_growth_bytes for r in p.per_symbol] == [
        0 if not s.recording else EST if s.daily_growth_bytes is None else s.daily_growth_bytes
        for s in symbols
    ]


class Recorder:
    def __init__(self, *, sampled: bool = True) -> None:
        self.sampled = sampled

    async def recorder_status(self) -> RecorderStatus:
        raise AssertionError("capacity never reads recorder status")

    async def storage_snapshot(self) -> StorageSnapshot | None:
        return _snap(_sym(2 * GB, retention=10)) if self.sampled else None


class Ingestion:
    async def ingestion_stats(self) -> IngestionStats:
        return IngestionStats(messages_per_sec=1840.5, queue_depth=12, dropped_last_hour=0)


class Counts:
    async def subaccounts_in_use(self) -> int:
        return 3


class Tier:
    def __init__(self, tier: str | None) -> None:
        self.tier = tier

    async def recorded_tier(self) -> RecordedTier | None:
        return None if self.tier is None else RecordedTier(self.tier, NOW)


class RateLimit:
    async def rate_budget(self) -> tuple[RateBudgetUse, ...]:
        uid = UUID(int=1)
        return (RateBudgetUse(uid, "main", 600, 450), RateBudgetUse(uid, "sub", 0, 7))


def _service(tier: Tier | None, *, sampled: bool = True) -> AdminCapacityService:
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    return AdminCapacityService(
        fan,
        recorder=Recorder(sampled=sampled),
        ingestion=Ingestion(),
        rate_limit=RateLimit(),
        counts=Counts(),  # type: ignore[arg-type]  # structural fake, sub-accounts only
        tier=tier,
        now=lambda: NOW,
    )


@pytest.mark.parametrize(("tier", "cap"), [("regular", 5), ("business_kyc", 20)])
async def test_recorded_tier_states_its_cap_as_a_recorded_fact(tier: str, cap: int) -> None:
    sub = (await _service(Tier(tier)).capacity()).subaccounts
    assert sub.status == "ok"
    assert sub.value == SubaccountCapacity(tier, cap, 3, "recorded", NOW)  # type: ignore[arg-type]


async def test_a_never_recorded_tier_is_unrecorded_and_still_counts_usage() -> None:
    sub = (await _service(Tier(None)).capacity()).subaccounts
    assert (sub.status, sub.value) == ("ok", SubaccountCapacity(None, None, 3, "unrecorded", None))


async def test_without_a_tier_store_the_slice_is_unavailable_but_keeps_usage() -> None:
    sub = (await _service(None).capacity()).subaccounts
    assert (sub.status, sub.detail) == ("unavailable", "tier: no provider wired")
    assert sub.value == SubaccountCapacity(None, None, 3, "unrecorded", None)


async def test_an_unknown_tier_word_is_an_error_never_a_guess() -> None:
    sub = (await _service(Tier("vip")).capacity()).subaccounts
    assert (sub.status, sub.value, sub.detail) == ("error", None, "source failed")


async def test_rate_budget_utilisation_and_the_projection_gauge() -> None:
    snap = await _service(Tier("regular")).capacity()
    assert snap.rate_budget.value == (
        RateBudgetRow(UUID(int=1), "main", 600, 450, 75.0),
        RateBudgetRow(UUID(int=1), "sub", 0, 7, 0.0),
    )
    assert snap.storage.value is not None and snap.storage.value.projected_bytes == 20 * GB
    assert REGISTRY.get_sample_value("cv_admin_capacity_projection_bytes") == 20 * GB


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
