"""Composition-root wiring of the admin read models (E42-T01): `GET /admin/overview` and
`GET /admin/capacity`; `build_statechart_inspector` adds E42-T07's `GET /admin/statecharts`; and
(E42-T05) `GET /admin/incidents` (`build_admin_incidents` at the end, which stays `501` until the
incident materialiser ships).

Real sources on the real storage backend:
- the Postgres counts repository (users, accounts and keys, open incidents, sub-accounts in use),
  bound to the serving environment (`settings.environment`, `CV_ENVIRONMENT`; C-2.11);
- the recorded sub-account tier, read from the `settings` row `accounts.subaccount_tier`
  (migration `0025`): no row is "unrecorded";
- the storage snapshot, whenever `app.state.disk_budget` exists (the real backend, #2370):
  `DiskBudgetAdapter` maps the recorder's `DiskBudget` to the `StorageSnapshot` behind the overview
  `storage` tile and the capacity `storage` section. It serves the last sample and never measures,
  fails closed once that sample or its byte breakdown is older than three sample intervals (or
  the breakdown never succeeded), takes growth from
  `measured_growth()` (so "not measured yet" is `None`, never the `0` of `report()`), and takes the
  cap from the budget's `BudgetConfig`.

Every other port stays unwired (`None`), so its slice is honestly `unavailable` ("no provider wired
yet" in the contract), never a made-up figure:
- the recorder status: its service is still a scaffold whose `recorded_symbols()` is always empty,
  so `0` symbols recording would be a guess (E16-T08, #492, adds the recording status surface);
- ingestion stats: `messages_per_sec` and `dropped_last_hour` are rates over a window, but
  ingestion exports only cumulative counters and instantaneous gauges and keeps no rolling sample,
  so both would be invented (a counter since process start is not "the last hour"; the delta
  between two admin reads is not a per-second rate), and "queue depth" has three candidates (the
  WS frame queue, the dispatch lanes, the write-behind buffers). The in-process sampler is #2950;
  E16-T08's `recorder` topic (`ingest_rate_msgs_per_sec`) is the nearest source today;
- the per-UID rate-budget peak: the governor keeps no per-minute peak (E34-T02, #859);
- the OMS kill switch, live flag and positions (E39-S03 #956, E44-T04 #1247, E29-T05 #848 and
  E29-T07 #915).
On the fake backend there is no budget and the tier is unwired too.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Final

from candleviewer.admin.inspector import StatechartInspector
from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.admin.overview.capacity import AdminCapacityService, project
from candleviewer.admin.overview.fanout import SliceFanOut, SourceUnavailable, utc_now
from candleviewer.admin.overview.ports import (
    SUBACCOUNT_TIER_KEY,
    AccountCounts,
    RecordedTier,
    RecorderStatus,
    StorageSnapshot,
    SymbolStorage,
    UserCounts,
)
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.api.admin_statecharts import machine_key
from candleviewer.recorder.budget import RECORDED_TIERS, DiskBudget
from candleviewer.settings import Settings
from candleviewer.statechart.lock import DEFAULT_LOCK_PATH, load_lock
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import SqlAlchemyAdminCounts
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
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


#: A disk sample is shown for this many sample intervals, then the slice fails closed. The budget
#: itself tolerates three intervals of lateness in its own series before it calls a sampling hole
#: (`BudgetConfig.hole_us`: one series step plus three intervals), so a sample that old means at
#: least two passes were missed. A live sampler replaces its report every interval plus a pass,
#: and a pass is bounded by its own timeouts (about a minute at worst): two slow passes in a row
#: still keep the age under three default intervals, so a healthy budget is shown. That holds
#: while a healthy pass takes no longer than one interval; a slower one can outlast the bound,
#: and the slice then fails closed (`unavailable`), the safe side. The same bound applies to the
#: breakdown's age, since `report()` keeps the last sizes while the breakdown fails.
MAX_SAMPLE_AGE_INTERVALS: Final = 3


class DiskBudgetAdapter:
    """The admin `RecorderPort` over the recorder's `DiskBudget`: the storage snapshot only.

    A request reads the last sample and never measures (SCR-142). Fail closed (SR-096): no sample
    yet is `None`; a breakdown that never succeeded (no recorded tier: not measured is never `0`
    used), or a sample or breakdown older than `MAX_SAMPLE_AGE_INTERVALS` of the budget's own
    sample interval, or stamped in the future of the admin clock, raises `SourceUnavailable`, so
    a stuck sampler or a failing breakdown never shows a stale headroom. Growth is the fit's
    (`measured_growth()`): `None` until measured, never the `0` `report()` folds it into. The
    cap, the interval and the retention come from the budget's own `BudgetConfig`.

    Two fields are not known to the budget, so they are stated as what is safe, not measured:
    `recording` is `True` for every symbol with bytes on disk (the recorder service knows no set
    yet), so an unmeasured symbol gets the flagged estimate of `/admin/capacity` and growth is
    never under-stated; and a symbol's `retention_days` is the budget's configured retention
    (`None` when pinned), since per-symbol retention overrides are not visible to it.

    `days_until_full` is the capacity projection's own (`project`): 0 at zero headroom, with or
    without growth; `None` when growth is not fully measured, because the estimate belongs to
    `/admin/capacity`, and when the steady state fits on disk. The overview tile and the capacity
    section therefore tell one story.

    The recorder status is not served: its slice stays `unavailable`, as when nothing is wired."""

    def __init__(self, budget: DiskBudget, *, now: Callable[[], datetime]) -> None:
        self._budget, self._now = budget, now

    async def recorder_status(self) -> RecorderStatus:
        raise SourceUnavailable("recorder: no provider wired")

    async def storage_snapshot(self) -> StorageSnapshot | None:
        budget = self._budget
        report = budget.report()
        if report is None:
            return None  # before the first sample; the services say "no disk sample yet"
        config, now = budget.config, self._now()
        if not any(t.tier in RECORDED_TIERS for t in report.tiers):
            raise SourceUnavailable("storage: no disk breakdown yet")  # never `0` used
        bound_s = MAX_SAMPLE_AGE_INTERVALS * config.sample_interval_s
        if not 0 <= (now - report.generated_at).total_seconds() <= bound_s:
            raise SourceUnavailable("storage: disk sample is stale")
        if not 0 <= (now - budget.breakdown_fresh_at).total_seconds() <= bound_s:
            raise SourceUnavailable("storage: disk breakdown is stale")  # QuestDB or Parquet walk
        total, rates = budget.measured_growth()  # one synchronous step with `report()` above
        snapshot = StorageSnapshot(
            used_bytes=sum(t.used_bytes for t in report.tiers if t.tier in RECORDED_TIERS),
            free_bytes=report.disk_free_bytes,
            daily_growth_bytes=total,
            days_until_full=None,
            symbols=tuple(
                SymbolStorage(
                    symbol=s.symbol,
                    used_bytes=s.used_bytes,
                    daily_growth_bytes=rates.get(s.symbol),  # no fit for it yet: `None`, not 0
                    pinned=s.pinned,
                    retention_days=None if s.pinned else config.retention_days,
                    recording=True,  # the budget knows no recorded set: see the class docstring
                )
                for s in report.symbols
            ),
            cap_bytes=config.cap_bytes,
        )
        return replace(snapshot, days_until_full=_days_until_full(snapshot))


def _days_until_full(snapshot: StorageSnapshot) -> float | None:
    """The overview tile's days: the capacity projection's, but never an estimate."""
    if snapshot.headroom_bytes == 0:
        return 0.0  # at the cap or on a full volume: exhausted now, growth or not
    projection = project(snapshot)
    return None if projection.estimated else projection.days_until_full


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
    disk_budget: DiskBudget | None = None,
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
    recorder = None if disk_budget is None else DiskBudgetAdapter(disk_budget, now=now)
    overview = AdminOverviewService(fan, counts=counts, recorder=recorder, now=now)
    tier = None if system_settings is None else SettingsTierReader(system_settings)
    capacity = AdminCapacityService(fan, recorder=recorder, subaccounts=counts, tier=tier, now=now)
    return overview, capacity


def build_statechart_inspector(*, now: Callable[[], datetime] = utc_now) -> StatechartInspector:
    """The E42-T07 inspector over the sources that exist: the chart registry and the committed lock.
    No snapshot store or KMS-backed HMAC keys (E50-T61, #2744) and no metrics source exist yet, so
    `snapshots` and `metrics` stay `unavailable` and the list stays empty."""
    lock = {kind: str(entry.get("hash")) for kind, entry in load_lock(DEFAULT_LOCK_PATH).items()}
    return StatechartInspector(SliceFanOut(now=now), machine_key, lock)


#: The incident list reads the `incidents` table only once something writes it. Nothing does
#: until the incident materialiser (a later E42-T05 slice), so a wired reader would answer 200 with
#: an empty list while `system_events` holds errors: the "no incidents" that the 501 exists to
#: prevent. The materialiser's PR sets this to True.
INCIDENTS_MATERIALISED = False


def build_admin_incidents(
    settings: Settings,
    *,
    system_settings: SystemSettings | None = None,
    now: Callable[[], datetime] = utc_now,
) -> AdminIncidentsService:
    """The incident list: `501 not_implemented`, never a made-up page, until the incident
    materialiser fills the `incidents` table. `SqlAlchemyIncidents` is built and tested but
    unwired: once `INCIDENTS_MATERIALISED` is set the real backend reads the table over the admin
    area's one engine, and the fake backend never has a store. Until then `/admin/overview` still
    counts open incidents from raw `system_events`."""
    store = None
    if INCIDENTS_MATERIALISED and settings.storage_backend == "real":
        # The admin area's one engine, shared with the counts and the tier, as above.
        relational = (
            system_settings.relational
            if isinstance(system_settings, SqlAlchemySystemSettings)
            else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
        )
        store = SqlAlchemyIncidents(relational)
    return AdminIncidentsService(store, now=now)
