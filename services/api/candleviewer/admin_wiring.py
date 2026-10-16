"""Composition-root wiring of the admin read models (E42-T01): `GET /admin/overview` and
`GET /admin/capacity`.

Real source on `main`: the Postgres counts repository (users, accounts and keys, open
incidents, sub-accounts in use), bound to the serving environment (`settings.environment`,
`CV_ENVIRONMENT`; C-2.11), when the real storage backend is configured.

Every other port stays unwired (`None`), so its slice is honestly `unavailable` ("no provider
wired yet" in the contract), never a made-up figure: the recorder (its service is still a
scaffold whose `recorded_symbols()` is always empty, so `0` would be a guess), the storage
snapshot (`app.state.disk_budget` exists on the real backend, #2370, but no adapter maps it to a
`StorageSnapshot` yet: growth from `measured_growth()`, `cap_bytes` from `BudgetConfig`),
ingestion stats, the per-UID rate-budget peak (the governor keeps no per-minute peak), the OMS
kill switch / live flag / positions, and the sub-account tier store (the `settings` table exists,
migration `0025`, #2680, but nothing reads `accounts.subaccount_tier` yet).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from candleviewer.admin.overview.capacity import AdminCapacityService
from candleviewer.admin.overview.fanout import SliceFanOut, utc_now
from candleviewer.admin.overview.ports import AccountCounts, UserCounts
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.settings import Settings
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import SqlAlchemyAdminCounts
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)


class AdminCountsAdapter:
    """Storage totals to the admin `CountsPort` / `SubaccountPort` (env bound in the repo)."""

    def __init__(self, repo: SqlAlchemyAdminCounts) -> None:
        self._repo = repo

    async def user_counts(self) -> UserCounts:
        t = await self._repo.user_totals()
        return UserCounts(t.total, t.active, t.without_mfa)

    async def account_counts(self, expiring_before: datetime) -> AccountCounts:
        t = await self._repo.account_totals(expiring_before)
        return AccountCounts(t.total, t.enabled, t.keys_expiring, t.keys_invalid)

    async def open_incidents(self) -> int:
        return await self._repo.open_incidents()

    async def subaccounts_in_use(self) -> int:
        return await self._repo.subaccounts_in_use()


def build_admin_read_models(
    settings: Settings, *, now: Callable[[], datetime] = utc_now
) -> tuple[AdminOverviewService, AdminCapacityService]:
    counts = None
    if settings.storage_backend == "real":
        relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
        counts = AdminCountsAdapter(
            SqlAlchemyAdminCounts(relational, env=settings.environment.value)
        )
    fan = SliceFanOut(now=now)
    overview = AdminOverviewService(fan, counts=counts, now=now)
    capacity = AdminCapacityService(fan, subaccounts=counts, now=now)
    return overview, capacity
