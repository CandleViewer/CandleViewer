"""`AdminCapacityService` (E42-T01): the `GET /admin/capacity` read model.

Four sections through the shared `SliceFanOut`: the disk projection, ingestion, the per-UID
rate budget and the sub-account capacity. Only the backend's own accounting is read, never the
exchange. The projection follows the ticket: growth per recorded symbol is measured (DiskBudget)
or, with no measurement yet, the upper bound of the documented band (0.75 GB/day/symbol at
200-depth, so the warning comes early) with `estimated` set (C10); a symbol not being recorded
does not grow; with nothing recorded growth is 0 by fact (`nothing_recorded`), not unknown.
`projected = sum(growth x retention)` over retention-bounded symbols. With growth, the disk is
projected to fill when a pinned (unbounded) symbol grows, when the headroom `min(cap - used,
free)` is already zero (runway 0, as `DiskBudget.project_full_at`), or when that steady state
exceeds used + headroom; never "no exhaustion" at the moment of exhaustion (SR-096).
The sub-account tier is a recorded fact read through `TierPort`, never inferred.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

from candleviewer.admin.overview.fanout import (
    Degraded,
    SliceFanOut,
    SliceResult,
    SourceUnavailable,
    utc_now,
)
from candleviewer.admin.overview.metrics import capacity_projection_bytes
from candleviewer.admin.overview.ports import (
    IngestionPort,
    IngestionStats,
    RateLimitPort,
    RecordedTier,
    RecorderPort,
    StorageSnapshot,
    SubaccountPort,
    TierPort,
)
from candleviewer.admin.overview.slices import AdminSlice

#: 0.75 GB/day/symbol (GB = 1e9 bytes, as the recorder's DiskBudget measures).
ESTIMATED_DAILY_GROWTH_BYTES: Final = 750_000_000
#: The exchange's sub-account cap per recorded tier (US-ADMIN-014).
Tier = Literal["regular", "business_kyc"]
TIER_CAPS: Final[Mapping[Tier, int]] = MappingProxyType({"regular": 5, "business_kyc": 20})
Basis = Literal["measured", "estimated", "nothing_recorded"]
#: A sub-read must answer inside the 300 ms slice budget so the other part survives.
PART_BUDGET_S: Final = 0.2
#: (status, fixed wire detail, logged-only reason: part and exception class).
Problem = tuple[Literal["error", "unavailable"], str, str]


class UnrecognisedTier(Exception):
    """A stored tier word outside `TIER_CAPS`: an error, never a guess."""


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
    """`used` and the tier are read independently; a part that failed is `None` (omitted)."""

    tier: Tier | None
    cap: int | None
    used: int | None
    tier_source: Literal["recorded", "unrecorded"] | None
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
            growth = max(s.daily_growth_bytes, 0)  # a negative fit (shrinking data) adds no growth
        if s.retention_days is None:
            unbounded = unbounded or growth > 0
        else:
            projected += growth * s.retention_days
        rows.append(SymbolProjection(s.symbol, s.used_bytes, growth, s.pinned, s.retention_days))
    growth_total = sum(r.daily_growth_bytes for r in rows)
    headroom = max(min(snap.cap_bytes - snap.used_bytes, snap.free_bytes), 0)  # project_full_at
    fills = growth_total > 0 and (
        unbounded or headroom == 0 or projected > snap.used_bytes + headroom
    )
    days = round(headroom / growth_total, 2) if fills else None
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
        subaccounts: SubaccountPort | None = None,
        tier: TierPort | None = None,
        now: Callable[[], datetime] = utc_now,
        part_budget_s: float = PART_BUDGET_S,
    ) -> None:
        if not 0 < part_budget_s < fan.budget_s:  # a hung part must not lose the other
            raise ValueError("part budget must be inside the slice budget")
        self._fan, self._now, self._part_budget_s = fan, now, part_budget_s
        self._recorder, self._ingestion, self._rate_limit = recorder, ingestion, rate_limit
        self._subaccounts_port, self._tier = subaccounts, tier

    async def capacity(self) -> CapacitySnapshot:
        read = self._fan.read
        storage, ingestion, rate_budget, subaccounts = await asyncio.gather(
            read(AdminSlice.CAPACITY_STORAGE, self._storage),
            read(AdminSlice.INGESTION, self._ingestion_stats),
            read(AdminSlice.RATE_BUDGET, self._rate_budget),
            read(AdminSlice.SUBACCOUNTS, self._subaccounts),
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
        (used, used_problem), (recorded, tier_problem) = await asyncio.gather(
            _part("subaccounts", self._used, self._part_budget_s),
            _part("tier", self._recorded_tier, self._part_budget_s),
        )  # both parts are self-guarded, so neither can outlive the slice
        if recorded is not None:
            tier = next(t for t in TIER_CAPS if t == recorded.tier)  # validated in _recorded_tier
            at = recorded.recorded_at
            value = SubaccountCapacity(tier, TIER_CAPS[tier], used, "recorded", at)
        else:  # never recorded is a fact; a failed tier read leaves the tier fields unknown
            source: Literal["unrecorded"] | None = None if tier_problem else "unrecorded"
            value = SubaccountCapacity(None, None, used, source, None)
        problems = [p for p in (used_problem, tier_problem) if p is not None]
        if not problems:
            return value
        worst = next((p for p in problems if p[0] == "error"), problems[0])  # status with detail
        return Degraded(value, worst[0], worst[1], worst[2])

    async def _used(self) -> int:
        if self._subaccounts_port is None:
            raise _unwired("subaccounts")
        return await self._subaccounts_port.subaccounts_in_use()

    async def _recorded_tier(self) -> RecordedTier | None:
        if self._tier is None:  # no settings store yet: say so, never infer
            raise _unwired("tier")
        recorded = await self._tier.recorded_tier()
        if recorded is not None and recorded.tier not in TIER_CAPS:
            raise UnrecognisedTier
        return recorded


async def _part[T](
    what: str, load: Callable[[], Awaitable[T]], budget_s: float
) -> tuple[T | None, Problem | None]:
    """One independently degradable part of a slice, under its own sub-budget. Never raises
    but for a real cancellation; only fixed details go out, the exception class is logged."""
    try:
        async with asyncio.timeout(budget_s):
            return await load(), None
    except SourceUnavailable as exc:
        return None, ("unavailable", exc.detail, f"{what}:unwired")
    except UnrecognisedTier as exc:
        return None, ("error", f"{what}: unrecognised value", f"{what}:{type(exc).__name__}")
    except TimeoutError:
        return None, ("error", f"{what}: timed out", f"{what}:TimeoutError")
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
        return None, ("error", f"{what}: source failed", f"{what}:CancelledError")
    except Exception as exc:  # the message may carry internals: never forwarded
        return None, ("error", f"{what}: source failed", f"{what}:{type(exc).__name__}")
