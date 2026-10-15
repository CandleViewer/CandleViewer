"""`AdminCapacityService` (E42-T01): the `GET /admin/capacity` read model.

Four sections through the shared `SliceFanOut`: the disk projection, ingestion, the per-UID
rate budget and the sub-account capacity. Only the backend's own accounting is read, never the
exchange. The projection follows the ticket: growth per recorded symbol is measured (DiskBudget)
or, with no measurement yet, the upper bound of the documented band (0.75 GB/day/symbol at
200-depth, so the warning comes early) with `estimated` set (C10); a symbol not being recorded
does not grow; with nothing recorded growth is 0 by fact (`nothing_recorded`), not unknown.
`projected = sum(growth x retention)` over retention-bounded symbols: the disk is projected to
fill only when a pinned (unbounded) symbol grows or that steady state exceeds used + free.
The sub-account tier is a recorded fact read through `TierPort`, never inferred.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from candleviewer.admin.overview.fanout import Degraded, SliceFanOut, SliceResult, SourceUnavailable
from candleviewer.admin.overview.metrics import capacity_projection_bytes
from candleviewer.admin.overview.ports import (
    CountsPort,
    IngestionPort,
    IngestionStats,
    RateLimitPort,
    RecorderPort,
    StorageSnapshot,
    TierPort,
)

#: 0.75 GB/day/symbol (GB = 1e9 bytes, as the recorder's DiskBudget measures).
ESTIMATED_DAILY_GROWTH_BYTES: Final = 750_000_000
#: The exchange's sub-account cap per recorded tier (US-ADMIN-014).
TIER_CAPS: Final[dict[str, int]] = {"regular": 5, "business_kyc": 20}
Basis = Literal["measured", "estimated", "nothing_recorded"]
Tier = Literal["regular", "business_kyc"]


@dataclass(frozen=True, slots=True)
class SymbolProjection:
    symbol: str
    used_bytes: int
    daily_growth_bytes: int
    pinned: bool
    retention_days: int | None


@dataclass(frozen=True, slots=True)
class DiskProjection:
    used_bytes: int
    free_bytes: int
    daily_growth_bytes: int
    days_until_full: float | None
    projected_bytes: int
    basis: Basis
    estimated: bool
    per_symbol: tuple[SymbolProjection, ...]


@dataclass(frozen=True, slots=True)
class RateBudgetRow:
    exchange_account_id: UUID
    label: str
    limit_per_minute: int
    peak_used_per_minute: int
    utilisation_pct: float


@dataclass(frozen=True, slots=True)
class SubaccountCapacity:
    tier: Tier | None
    cap: int | None
    used: int
    tier_source: Literal["recorded", "unrecorded"]
    recorded_at: datetime | None


@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    generated_at: datetime
    storage: SliceResult[DiskProjection]
    ingestion: SliceResult[IngestionStats]
    rate_budget: SliceResult[tuple[RateBudgetRow, ...]]
    subaccounts: SliceResult[SubaccountCapacity]


def project(snap: StorageSnapshot) -> DiskProjection:
    """The disk projection for one storage snapshot (pure)."""
    rows: list[SymbolProjection] = []
    estimated, projected, unbounded = False, 0, False
    recording = any(s.recording for s in snap.symbols)
    for s in snap.symbols:
        if not s.recording:
            growth = 0
        elif s.daily_growth_bytes is None:
            growth, estimated = ESTIMATED_DAILY_GROWTH_BYTES, True
        else:
            growth = s.daily_growth_bytes
        if s.retention_days is None:
            unbounded = unbounded or growth > 0
        else:
            projected += growth * s.retention_days
        rows.append(SymbolProjection(s.symbol, s.used_bytes, growth, s.pinned, s.retention_days))
    growth_total = sum(r.daily_growth_bytes for r in rows)
    fills = growth_total > 0 and (unbounded or projected > snap.used_bytes + snap.free_bytes)
    days = round(snap.free_bytes / growth_total, 2) if fills else None
    basis: Basis = "nothing_recorded" if not recording else "estimated" if estimated else "measured"
    return DiskProjection(
        snap.used_bytes,
        snap.free_bytes,
        growth_total,
        days,
        projected,
        basis,
        estimated,
        tuple(rows),
    )


def _unwired(source: str) -> SourceUnavailable:
    return SourceUnavailable(f"{source}: no provider wired")


class AdminCapacityService:
    def __init__(
        self,
        fan: SliceFanOut,
        *,
        recorder: RecorderPort | None = None,
        ingestion: IngestionPort | None = None,
        rate_limit: RateLimitPort | None = None,
        counts: CountsPort | None = None,
        tier: TierPort | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._fan, self._now = fan, now
        self._recorder, self._ingestion, self._rate_limit = recorder, ingestion, rate_limit
        self._counts, self._tier = counts, tier

    async def capacity(self) -> CapacitySnapshot:
        read = self._fan.read
        storage, ingestion, rate_budget, subaccounts = await asyncio.gather(
            read("capacity_storage", self._storage),
            read("ingestion", self._ingestion_stats),
            read("rate_budget", self._rate_budget),
            read("subaccounts", self._subaccounts),
        )
        return CapacitySnapshot(self._now(), storage, ingestion, rate_budget, subaccounts)

    async def _storage(self) -> DiskProjection:
        if self._recorder is None:
            raise _unwired("storage")
        snap = await self._recorder.storage_snapshot()
        if snap is None:
            raise SourceUnavailable("storage: no disk sample yet")
        projection = project(snap)
        capacity_projection_bytes.set(projection.projected_bytes)
        return projection

    async def _ingestion_stats(self) -> IngestionStats:
        if self._ingestion is None:
            raise _unwired("ingestion")
        return await self._ingestion.ingestion_stats()

    async def _rate_budget(self) -> tuple[RateBudgetRow, ...]:
        if self._rate_limit is None:
            raise _unwired("rate-limit peak")
        return tuple(
            RateBudgetRow(
                u.exchange_account_id,
                u.label,
                u.limit_per_minute,
                u.peak_used_per_minute,
                (
                    round(100 * u.peak_used_per_minute / u.limit_per_minute, 1)
                    if u.limit_per_minute > 0
                    else 0.0
                ),
            )
            for u in await self._rate_limit.rate_budget()
        )

    async def _subaccounts(self) -> SubaccountCapacity | Degraded[SubaccountCapacity]:
        if self._counts is None:
            raise _unwired("subaccounts")
        used = await self._counts.subaccounts_in_use()
        unrecorded = SubaccountCapacity(None, None, used, "unrecorded", None)
        if self._tier is None:  # no settings store yet: say so, keep the count, never infer
            return Degraded(unrecorded, "unavailable", "tier: no provider wired")
        recorded = await self._tier.recorded_tier()
        if recorded is None:
            return unrecorded
        if recorded.tier not in TIER_CAPS:  # a corrupt value is an error, never a guess
            raise ValueError("unknown sub-account tier")
        tier: Tier = "regular" if recorded.tier == "regular" else "business_kyc"
        return SubaccountCapacity(tier, TIER_CAPS[tier], used, "recorded", recorded.recorded_at)
