"""Composition of the backups surface (E42-T05, #966 BK-7): backups jobs run in the admin job store
(`GET /admin/jobs/{jobId}`); positions are unknown until E29-T05/T07 write them. Nothing is
mounted yet: no backups route exists, and the engine ports stay unwired."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Final, Literal
from uuid import UUID

import structlog

from candleviewer.admin.backups import ports
from candleviewer.admin.backups.ports import JOB_ERROR_CODES, BackupJobError, JobEnd
from candleviewer.api.recorder_admin import AdminJobStore, Job
from candleviewer.auth.step_up import POSITION_SOURCE_NOT_DEPLOYED


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
