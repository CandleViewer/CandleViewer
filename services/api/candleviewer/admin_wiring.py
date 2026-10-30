"""Composition-root wiring of the admin read models (E42-T01): `GET /admin/overview` and
`GET /admin/capacity`; `build_statechart_inspector` adds E42-T07's `GET /admin/statecharts` (its
rows' scope bound by `RegistryScopedStore`, a non-Owner's grants read by `build_admin_grants`); and
(E42-T05) `GET /admin/incidents` (`build_admin_incidents`) and the `cv_incidents_open` gauge over
the overview's incident count (`build_open_incidents_gauge`, at the end).

Real sources on the real storage backend:
- the Postgres counts repository (users, accounts and keys, unresolved incidents from the
  `incidents` table, sub-accounts in use), bound to the serving environment
  (`settings.environment`, `CV_ENVIRONMENT`; C-2.11);
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

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Final
from uuid import UUID

from candleviewer.admin.inspector import (
    BoundScope,
    DroppedReceipts,
    EventStore,
    SnapshotRow,
    SnapshotStore,
    StatechartInspector,
)
from candleviewer.admin.ops.incident_metrics import OpenIncidentsGauge
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
from candleviewer.api.admin_statecharts import GrantsOf, machine_key
from candleviewer.auth.scopes import AccountGrant
from candleviewer.observability.health_probes import SystemEventWriter
from candleviewer.observability.metrics import ENV_LABEL, Metrics
from candleviewer.recorder.budget import RECORDED_TIERS, DiskBudget
from candleviewer.settings import Settings
from candleviewer.statechart.lock import DEFAULT_LOCK_PATH, load_lock
from candleviewer.statechart.persistence import HmacKeys
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import SqlAlchemyAdminCounts
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.storage.repositories.system_settings import SystemSettings
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from candleviewer.ws.topics import EntityScope


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


#: The `CvMetricsPlugin` family `dropped_receipts` reads (catalogue, E50-T60) and its sample.
DROPPED_RECEIPTS_FAMILY: Final = "cv_machine_dropped_receipts"
_DROPPED_RECEIPTS_SAMPLE: Final = f"{DROPPED_RECEIPTS_FAMILY}_total"


def dropped_receipts_reader(metrics: Metrics) -> DroppedReceipts:
    """`cv_machine_dropped_receipts_total` per `kind` on the app's one facade, its own `env`
    only: the same series `/metrics` exports, read, never registered or incremented here. Only
    that family's collector runs (a restricted registry), never every exporter in the process."""

    def read() -> dict[str, int]:
        counts: dict[str, int] = {}
        only = metrics.registry.restricted_registry([_DROPPED_RECEIPTS_SAMPLE])
        for family in only.collect():
            if family.name != DROPPED_RECEIPTS_FAMILY:
                continue
            for sample in family.samples:
                labels = sample.labels
                if sample.name == _DROPPED_RECEIPTS_SAMPLE and labels.get(ENV_LABEL) == metrics.env:
                    kind = labels.get("kind", "")
                    counts[kind] = counts.get(kind, 0) + int(sample.value)
        return counts

    return DroppedReceipts(metrics.env, read)


class RegistryScopedStore:
    """A `SnapshotStore` whose rows carry the scope the owning module bound to the machine in the
    `machines.{entity}.state` registry (`MachineStateRegistry.scope`, the entry E17-T08's topic
    check reads; 23 §6.4), never one from the row or the snapshot's context. The registry holds
    the serving process's own environment only, so a row of another environment, a machine with
    no live entry and a kind without a public id get the empty scope: a scoped kind's row is then
    shown to no role (fail closed). `scope_of` is synchronous and runs on the loop, as the WS
    check runs it (SR-189)."""

    def __init__(
        self, store: SnapshotStore, scope_of: Callable[[str], EntityScope | None], *, env: str
    ) -> None:
        self._store, self._scope_of, self._env = store, scope_of, env

    async def snapshots(self) -> Sequence[SnapshotRow]:
        return [self._bound(row) for row in await self._store.snapshots()]

    async def snapshot(
        self, machine_kind: str, entity_id: str | None, environment: str
    ) -> SnapshotRow | None:
        row = await self._store.snapshot(machine_kind, entity_id, environment)
        return None if row is None else self._bound(row)

    def _bound(self, row: SnapshotRow) -> SnapshotRow:
        key = machine_key(row.machine_kind, row.entity_id)
        same_env = key is not None and row.environment == self._env
        found = self._scope_of(f"machines.{key}.state") if same_env else None
        scope = BoundScope() if found is None else BoundScope(found.accounts, found.user)
        return replace(row, scope=scope)


#: The bound on reading a non-Owner's account grants for the inspector.
GRANTS_TIMEOUT_S: Final = 2.0


def build_admin_grants(
    settings: Settings, *, system_settings: SystemSettings | None = None
) -> GrantsOf | None:
    """A non-Owner's view grants from `user_account_access` (`can_trade` not loaded), on the
    admin area's one engine, for the inspector's per-entity check; `None` on the fake backend,
    where a non-Owner then sees no account-scoped machine."""
    if settings.storage_backend != "real":
        return None
    relational = (
        system_settings.relational
        if isinstance(system_settings, SqlAlchemySystemSettings)
        else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
    )
    source = SqlAlchemyScopeSource(relational)

    async def grants(user_id: UUID) -> Sequence[AccountGrant]:
        async with asyncio.timeout(GRANTS_TIMEOUT_S):
            rows = await source.load_grants(user_id)
        return tuple(AccountGrant(acc, view, False, frozen) for acc, view, frozen in rows)

    return grants


def build_statechart_inspector(
    *,
    now: Callable[[], datetime] = utc_now,
    store: SnapshotStore | None = None,
    keys: HmacKeys | None = None,
    metrics: Metrics | None = None,
    events: EventStore | None = None,
    system_events: SystemEventWriter | None = None,
) -> StatechartInspector:
    """The E42-T07 inspector over the chart registry, the committed lock and, when the statechart
    persistence bundle is wired (E50-T63: the real backend with HMAC keys), its snapshot store
    (scope-bound: `RegistryScopedStore`), the keys that verify it and its `machine_events` reader.
    Without both, as until a KMS-backed key provider exists (a plan gap, #2701), `snapshots` stays
    `unavailable` and the list empty. `metrics` is the facade the `CvMetricsPlugin`s count on;
    without it `metrics` stays `unavailable`. `system_events` gets one critical `statechart` row
    per snapshot version the inspector leaves out (22 `listStatecharts`, migration 0057)."""
    lock = {kind: str(entry.get("hash")) for kind, entry in load_lock(DEFAULT_LOCK_PATH).items()}
    dropped = None if metrics is None else dropped_receipts_reader(metrics)
    fan = SliceFanOut(now=now)
    return StatechartInspector(
        fan,
        machine_key,
        lock,
        store=store,
        keys=keys,
        dropped=dropped,
        events=events,
        system_events=system_events,
    )


def build_admin_incidents(
    settings: Settings,
    *,
    system_settings: SystemSettings | None = None,
    now: Callable[[], datetime] = utc_now,
) -> AdminIncidentsService:
    """The incident list. The real backend reads the `incidents` table, which every `error` and
    `critical` system event fills as it is written (`PgSystemEventWriter`, the break-glass reset),
    over the admin area's one engine. The fake backend never has a store, so its list is
    `501 not_implemented`, never a made-up page."""
    store = None
    if settings.storage_backend == "real":
        # The admin area's one engine, shared with the counts and the tier, as above.
        relational = (
            system_settings.relational
            if isinstance(system_settings, SqlAlchemySystemSettings)
            else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
        )
        store = SqlAlchemyIncidents(relational)
    return AdminIncidentsService(store, now=now)


def build_open_incidents_gauge(
    settings: Settings, *, system_settings: SystemSettings | None = None
) -> OpenIncidentsGauge:
    """`cv_incidents_open` (E42-T05, #966 BK-15) over the count the overview shows as
    `incidents_open` (`AdminCountsAdapter.open_incidents`), on the admin area's one engine as
    above; the lifespan refreshes it. The fake backend has no `incidents` table, so its series
    never has a sample, never a made-up 0."""
    if settings.storage_backend != "real":
        return OpenIncidentsGauge(None)
    relational = (
        system_settings.relational
        if isinstance(system_settings, SqlAlchemySystemSettings)
        else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
    )
    return OpenIncidentsGauge(
        AdminCountsAdapter(SqlAlchemyAdminCounts(relational, env=settings.environment.value))
    )
