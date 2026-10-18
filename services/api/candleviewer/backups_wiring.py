"""Composition of the backups surface (E42-T05, #966).

- BK-7: backups jobs run in the admin job store (`GET /admin/jobs/{jobId}`); positions are unknown
  until E29-T05/T07 write them; the engine ports stay unwired.
- BK-4: the catalogue reads (`GET /admin/backups`, `GET /admin/backups/{backupId}`) answer
  `501 not_implemented` on every backend until `BACKUPS_CATALOGUED` is set; then the real backend
  reads the `backups` table over the admin area's one engine, and the fake backend still has no
  catalogue."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Final, Literal
from uuid import UUID

import structlog

from candleviewer.admin.backups import ports
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.ports import JOB_ERROR_CODES, BackupJobError, JobEnd
from candleviewer.api.recorder_admin import AdminJobStore, Job
from candleviewer.auth.step_up import POSITION_SOURCE_NOT_DEPLOYED
from candleviewer.settings import Settings
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
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


def build_admin_backups(
    settings: Settings, *, system_settings: SystemSettings | None
) -> BackupCatalogue:
    """The catalogue reads, on the admin area's one engine: shared with the counts, the tier and
    the incident list (`admin_wiring`), never a second one."""
    store = None
    if BACKUPS_CATALOGUED and settings.storage_backend == "real":
        relational = (
            system_settings.relational
            if isinstance(system_settings, SqlAlchemySystemSettings)
            else SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "admin")
        )
        store = SqlAlchemyBackups(relational)
    return BackupCatalogue(store)
