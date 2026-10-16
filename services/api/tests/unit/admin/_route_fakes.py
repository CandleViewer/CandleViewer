"""Fakes for the admin route tests (E42-T01): one fake implementing every read-model port, and
the app under test (the actors, resolver and audit spy are the guard's, `_admin_fakes`)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.overview import ports as p
from candleviewer.admin.overview.capacity import AdminCapacityService
from candleviewer.admin.overview.fanout import SliceFanOut, utc_now
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.api.admin_overview import make_admin_overview_router
from tests.unit.admin._admin_fakes import AuditSpy, Resolver

GB = 10**9
NOW = datetime(2026, 10, 16, 0, 30, tzinfo=UTC)


class Ports:
    """Every port, healthy; with `hang` the disk sample (read by both routes) never answers."""

    def __init__(self, *, hang: bool = False) -> None:
        self.hang = hang

    async def user_counts(self) -> p.UserCounts:
        return p.UserCounts(4, 4, 0)

    async def account_counts(self, expiring_before: datetime) -> p.AccountCounts:
        return p.AccountCounts(4, 3, 1, 0)

    async def open_incidents(self) -> int:
        return 0

    async def subaccounts_in_use(self) -> int:
        return 3

    async def recorder_status(self) -> p.RecorderStatus:
        return p.RecorderStatus(3, 0, 0.042)

    async def storage_snapshot(self) -> p.StorageSnapshot | None:
        if self.hang:
            await asyncio.Event().wait()
        btc = p.SymbolStorage("BTCUSDT", 30 * GB, GB, True, None, True)
        return p.StorageSnapshot(41 * GB, 400 * GB, None, 187.5, (btc,), 1000 * GB)

    async def ingestion_stats(self) -> p.IngestionStats:
        return p.IngestionStats(1840.5, 12, 0)

    async def rate_budget(self) -> tuple[p.RateBudgetUse, ...]:
        return (p.RateBudgetUse(UUID(int=1), "main", 600, 450),)

    async def recorded_tier(self) -> p.RecordedTier | None:
        return p.RecordedTier("regular", NOW)

    async def kill_switch_engaged(self) -> bool:
        return False

    async def live_enabled(self) -> bool:
        return False

    async def open_positions(self) -> int:
        return 0


def make_app(
    ports: Ports | None = None, *, ttl_s: float = 5.0, now: Callable[[], datetime] = utc_now
) -> tuple[FastAPI, AuditSpy]:
    f, spy, fan = ports or Ports(), AuditSpy(), SliceFanOut(ttl_s=ttl_s, now=now)
    overview = AdminOverviewService(fan, counts=f, recorder=f, oms=f, now=now)
    capacity = AdminCapacityService(
        fan, recorder=f, ingestion=f, rate_limit=f, subaccounts=f, tier=f, now=now
    )
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(
        make_admin_overview_router(overview, capacity, resolver=Resolver(), audit=spy)
    )
    return app, spy
