"""Composition of the backups surface (E42-T05, #966).

- BK-7: backups jobs run in the admin job store (`GET /admin/jobs/{jobId}`); positions are unknown
  until E29-T05/T07 write them; the engine ports stay unwired.
- BK-4: the catalogue reads (`GET /admin/backups`, `GET /admin/backups/{backupId}`) answer
  `501 not_implemented` on every backend until `BACKUPS_CATALOGUED` is set; then the real backend
  reads the `backups` table over the admin area's one engine, and the fake backend still has no
  catalogue.
- BK-5: the backup series are served, and the freshness loaded at boot, only once
  `BACKUPS_CATALOGUED` is set.
- BK-8: a run on demand answers `501 not_implemented` until a backup engine is wired (#3319): no
  `BackupRunner` here. Its runs go through the app's one admission gate, which the composition
  root builds once for every backups service (BK-9, BK-10, BK-12 and BK-13 take the same one),
  and count towards `RUNS_PER_HOUR` per user in the rolling-hour limiter the audit verify runs
  use (in-process: a restart resets it). Once the catalogue is set, the boot pass ends the runs a
  restart lost and counts them with the jobs it lost (SR-BK7-05).
- BK-12: a delete needs the catalogue and the engine's artefact remover (#3319); until both are
  wired `DELETE /admin/backups/{backupId}` answers `501` before any challenge. It runs under the
  app's one admission gate, which the composition root builds once for every backups service.
- BK-13: the restore guard reads maintenance mode fresh from the flag repository
  (`FlagStoreMaintenance`) and positions stay unknown. Nothing builds it until BK-14 mounts the
  restore after D7 (#3084).
- BK-10: a download link is issued once the catalogue is read and `CV_BACKUP_ROOT` is set; until
  then `POST /admin/backups/{backupId}/download` answers `501` before any challenge."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from typing import Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.admin.backups import ports
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.deletion import BackupDeletion, DeleteAudit
from candleviewer.admin.backups.downloads import BackupDownloads
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.limits import RUNS_PER_HOUR
from candleviewer.admin.backups.links import DownloadLinks
from candleviewer.admin.backups.metrics import BackupFreshness, export_backup_metrics
from candleviewer.admin.backups.ports import JOB_ERROR_CODES, BackupJobError, JobEnd
from candleviewer.admin.backups.rows import LostCount, LostRuns, RunAudit, RunRows
from candleviewer.admin.backups.runs import BackupRuns
from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.service import DEFAULT_READ_BUDGET_MS
from candleviewer.admin.http import AuditEmitter
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.api.recorder_admin import AdminJobStore, Job
from candleviewer.auth.step_up import POSITION_SOURCE_NOT_DEPLOYED
from candleviewer.observability.metrics import CollectorRegistry, ReexportCollector
from candleviewer.settings import Settings
from candleviewer.storage.backup_artefacts import LocalArtefactStore
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
from candleviewer.storage.repositories.flags_sqlalchemy import FlagRow
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.system_settings import SystemSettings
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings

#: The catalogue is read only once something records runs in it. Nothing does until the E45 backup
#: engine (#3319) plugs in, and manual backups exist outside the catalogue, so a wired reader would
#: answer an empty page that reads as "no backups" (Q3 on #966). #3319 sets this to True and
#: deletes `test_backups_answer_501_on_every_backend_until_catalogued` (C-4.13).
BACKUPS_CATALOGUED: Final = False


class AdminJobRunner:
    """A failed job reports a `JOB_ERROR_CODES` code only (C-12.6): a `BackupJobError` its own,
    anything else `internal_error`, its class name logged for the operator, never its text."""

    def __init__(self, store: AdminJobStore) -> None:
        self._store = store

    def submit(
        self,
        kind: ports.JobKind,
        job_id: UUID,
        work: ports.JobWork,
        on_done: ports.JobDone,
        on_settled: Callable[[], None],
    ) -> None:
        async def run(progress: ports.Progress) -> dict[str, object]:
            try:
                return await work(progress)
            except BackupJobError as exc:
                if exc.code in JOB_ERROR_CODES:
                    raise
                failure = type(exc).__name__
            except Exception as exc:
                failure = type(exc).__name__
            with contextlib.suppress(Exception):  # the closed code never depends on the logger
                log = structlog.get_logger(__name__)  # per call, never module-level (#2008)
                log.error("backups.job_failed", kind=kind, job_id=str(job_id), error=failure)
            raise BackupJobError("internal_error") from None

        async def done(job: Job) -> None:
            ok = job.status == "succeeded"
            status: Literal["succeeded", "failed"] = "succeeded" if ok else "failed"
            await on_done(JobEnd(status, job.result, job.error))

        # The actor half never equals a recorder caller's (a user id): no idempotency key meets.
        key = ("backups", str(job_id), "")
        self._store.submit(kind, key, run, done, job_id=str(job_id), on_settled=on_settled)


class UnknownOpenPositions:
    """Unknown, never 0, so a restore must carry `acknowledge_unknown_positions`."""

    source: Final = POSITION_SOURCE_NOT_DEPLOYED

    async def count_open(self) -> int | None:
        return None


class FlagRows(Protocol):
    async def load(self) -> Mapping[str, FlagRow]: ...  # `SqlAlchemyFlagRepository.load`


class FlagStoreMaintenance:
    """The restore guard's `MaintenanceState`: `maintenance.mode` read fresh from the flag
    repository within the flag read budget (`flags.read_budget_ms`), never `FlagService.value()`,
    whose outage value is "on" (`restrictive`) and would admit a restore. A failure, a read past
    the budget, no row or a value that is not a bool reads `None`; overrides never count for a
    kill switch."""

    def __init__(self, flags: FlagRows, *, read_budget_ms: int = DEFAULT_READ_BUDGET_MS) -> None:
        self._flags, self._budget_s = flags, read_budget_ms / 1000

    async def read(self) -> bool | None:
        try:
            async with asyncio.timeout(self._budget_s):
                rows = await self._flags.load()
        except Exception as exc:  # an outage, a refused statement, the budget spent
            log = structlog.get_logger(__name__)  # per call, never module-level (#2008)
            log.warning("backups.maintenance_unread", error=type(exc).__name__)
            return None
        row = rows.get(MAINTENANCE_MODE)
        value = None if row is None else row.value
        return value if isinstance(value, bool) else None


def _catalogue(
    settings: Settings, system_settings: SystemSettings | None
) -> SqlAlchemyBackups | None:
    """The `backups` table on the real backend once catalogued, on the admin area's one engine:
    shared with the counts, the tier and the incident list (`admin_wiring`), never a second one."""
    if not (BACKUPS_CATALOGUED and settings.storage_backend == "real"):
        return None
    relational = (
        system_settings.relational
        if isinstance(system_settings, SqlAlchemySystemSettings)
        else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
    )
    return SqlAlchemyBackups(relational)


def build_admin_backups(
    settings: Settings, *, system_settings: SystemSettings | None
) -> BackupCatalogue:
    """The catalogue reads."""
    return BackupCatalogue(_catalogue(settings, system_settings))


def serve_backup_metrics(
    settings: Settings, registry: CollectorRegistry
) -> ReexportCollector | None:
    """The backup series on `registry` (the scraped one), once `BACKUPS_CATALOGUED` is set. Until
    then nothing is served: no kind has a sample and no counter moves before an engine records
    runs, which would read as "nothing to watch"."""
    if not BACKUPS_CATALOGUED:
        return None
    return export_backup_metrics(registry, env=settings.environment.value)


def build_backup_freshness(
    settings: Settings, *, system_settings: SystemSettings | None
) -> BackupFreshness | None:
    """The freshness the lifespan loads, over the catalogue the reads use, once catalogued."""
    if not BACKUPS_CATALOGUED:
        return None
    return BackupFreshness(_catalogue(settings, system_settings))


def build_backup_runs(
    settings: Settings,
    jobs: AdminJobStore,
    audit: RunAudit,
    *,
    gate: BackupJobGate,
    lost: LostCount,
    system_settings: SystemSettings | None,
    freshness: BackupFreshness | None,
) -> tuple[BackupRuns, LostRuns | None]:
    """`createBackup`'s service on the catalogue, with no backup engine yet (#3319), through the
    app's one `gate`; and the boot pass over its lost runs, none until the catalogue is set."""
    store = _catalogue(settings, system_settings)
    rows = None if store is None else RunRows(store, audit, lost=lost, freshness=freshness)
    limit = AuditVerifyLimiter(rate_per_hour=RUNS_PER_HOUR)
    runs = BackupRuns(rows, None, gate=gate, jobs=AdminJobRunner(jobs), audit=audit, limit=limit)
    return runs, None if rows is None else LostRuns(rows)


def build_backup_downloads(
    settings: Settings, catalogue: BackupCatalogue, *, gate: BackupJobGate, audit: AuditEmitter
) -> BackupDownloads | None:
    """The link issue on the catalogue the reads serve, under the one admission lock; None until
    `BACKUPS_CATALOGUED` and `CV_BACKUP_ROOT` are both set."""
    if not (BACKUPS_CATALOGUED and settings.backup_root):
        return None
    reader = LocalArtefactStore(settings.backup_root)
    return BackupDownloads(catalogue, reader, DownloadLinks(), gate=gate, audit=audit)


def build_backup_deletion(
    settings: Settings,
    *,
    gate: BackupJobGate,
    audit: DeleteAudit,
    system_settings: SystemSettings | None,
    freshness: BackupFreshness | None,
    remover: ports.ArtefactRemover | None = None,
) -> BackupDeletion | None:
    """`deleteBackup`'s service on the catalogue, through the app's one `gate`, recomputing
    BK-5's `freshness`; None until the engine (#3319) passes its `remover` and the catalogue is
    set, so the route answers `501` before any challenge."""
    store = None if remover is None else _catalogue(settings, system_settings)
    if store is None or remover is None:
        return None
    return BackupDeletion(store, remover, gate=gate, audit=audit, freshness=freshness)
