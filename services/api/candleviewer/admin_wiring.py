"""Composition-root wiring of the admin read models (E42-T01): `GET /admin/overview` and
`GET /admin/capacity`.

Real sources on the real storage backend: the Postgres counts repository (users, accounts and
keys, open incidents, sub-accounts in use), bound to the serving environment
(`settings.environment`, `CV_ENVIRONMENT`; C-2.11), and the recorded sub-account tier, read from
the `settings` row `accounts.subaccount_tier` (migration `0025`): no row is "unrecorded".

Every other port stays unwired (`None`), so its slice is honestly `unavailable` ("no provider
wired yet" in the contract), never a made-up figure: the recorder (its service is still a
scaffold whose `recorded_symbols()` is always empty, so `0` would be a guess), the storage
snapshot (`app.state.disk_budget` exists on the real backend, #2370, but no adapter maps it to a
`StorageSnapshot` yet: growth from `measured_growth()`, `cap_bytes` from `BudgetConfig`),
ingestion stats, the per-UID rate-budget peak (the governor keeps no per-minute peak), and the OMS
kill switch / live flag / positions. On the fake backend the tier is unwired too.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from candleviewer.admin.overview.capacity import AdminCapacityService
from candleviewer.admin.overview.fanout import SliceFanOut, utc_now
from candleviewer.admin.overview.ports import (
    SUBACCOUNT_TIER_KEY,
    AccountCounts,
    RecordedTier,
    UserCounts,
)
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.settings import Settings
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import SqlAlchemyAdminCounts
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.system_settings import SystemSettings
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings


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


class SettingsTierReader:
    """The capacity `TierPort` over the `settings` store: the recorded tier word and when it was
    recorded, `None` only when there is no row. A read that fails raises, so the slice reports an
    error instead of "unrecorded"; the word is validated by the capacity service, not here."""

    def __init__(self, settings: SystemSettings) -> None:
        self._settings = settings

    async def recorded_tier(self) -> RecordedTier | None:
        row = await self._settings.get_string(SUBACCOUNT_TIER_KEY)
        return None if row is None else RecordedTier(row.value, row.updated_at)


def build_system_settings(settings: Settings) -> SystemSettings | None:
    """The `settings` store on the real backend; `None` on the fake one (nothing to read). Its
    repository is the admin area's one engine: the counts share it (`build_admin_read_models`)."""
    if settings.storage_backend != "real":
        return None
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
    return SqlAlchemySystemSettings(relational)


def build_admin_read_models(
    settings: Settings,
    *,
    now: Callable[[], datetime] = utc_now,
    system_settings: SystemSettings | None = None,
) -> tuple[AdminOverviewService, AdminCapacityService]:
    counts = None
    if settings.storage_backend == "real":
        # The counts ride the settings store's repository: one lazy engine for the admin area, not
        # two. Like most repositories `create_app` builds, it is never disposed at shutdown (#2526).
        relational = (
            system_settings.relational
            if isinstance(system_settings, SqlAlchemySystemSettings)
            else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
        )
        counts = AdminCountsAdapter(
            SqlAlchemyAdminCounts(relational, env=settings.environment.value)
        )
    fan = SliceFanOut(now=now)
    overview = AdminOverviewService(fan, counts=counts, now=now)
    tier = None if system_settings is None else SettingsTierReader(system_settings)
    capacity = AdminCapacityService(fan, subaccounts=counts, tier=tier, now=now)
    return overview, capacity
