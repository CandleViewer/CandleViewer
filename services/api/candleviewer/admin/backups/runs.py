"""Backup runs (E42-T05 #966 BK-8): `createBackup`'s start. The engine executes and this records
(#966 Q1); `rows.RunRows` writes a run's row, its `finished` record and its end.

`BackupRuns.start` keeps the plan's order (BK-8): no engine or catalogue, `OpsNotWired` (501); the
caller's `RUNS_PER_HOUR` spent, `RunsLimited` (429), checked again first under the admission lock
(a start counted while this one waited is seen, SR-BK8A-03, and 429 still comes ahead of 409);
another run or a restore, `BackupConflict` (409); the engine's `plan`, within `PLAN_BUDGET_S`,
failing or at a location that is not an absolute path free of `://` and `@` (SR-BK3-03),
`OpsUnavailable` (503). Nothing is written up to here. A plan not encrypted under a named key
alias, whatever else it breaks (SR-091, SR-BK8A-01), writes its `backup.run` `stage: refused`
record, which counts towards the limit as the contract says, then `BackupEngineInvalid` (503);
with that record unwritten, `OpsAuditUnavailable` (503). Nothing starts either way.

Then the caller's `write_ahead(id, kind)`, awaited within its bound ahead of the row (C-2.9),
writes `backup.run` `stage: requested` through `audit_requested`, the `note` its `reason` and
nowhere else, so a route's handler shows its audit write (SR-112, the incident acknowledgement's
mechanism); unwritten, `OpsAuditUnavailable` (503) and no row. The run counts once it is written.
Then the `running` row (`triggered_by: manual`, the caller) and the `backup` job, its id the row's
and its `result` `backup_id`; a job the job store refuses ends its request `internal_error`, then
`OpsUnavailable` (503). A report breaking the port's rules (`ports.BackupRunner.run`) fails the
run `internal_error`. The limit is in-process: a restart resets it (AD-D09)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Final, NoReturn, Protocol, cast
from uuid import UUID, uuid4

import structlog

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.ports import (
    BackupJobError,
    BackupRunner,
    JobEnd,
    JobRunner,
    RunPlan,
)
from candleviewer.admin.backups.rows import Actor, RunAudit, RunRows, recorded, run_record
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories import backups as port

WriteAhead = Callable[[UUID, port.BackupKind], Awaitable[None]]  # writes the `requested` record
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")  # the `sha256_hex` domain of `checksum_sha256`
_INVALID: Final = "backup_engine_invalid"


def _log() -> structlog.stdlib.BoundLogger:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class RunsLimited(AdminError):
    """429 `rate_limited`: the caller started `RUNS_PER_HOUR` runs in the rolling hour."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__("backups: the hourly run limit is spent")
        self.retry_after_s = retry_after_s


class BackupEngineInvalid(AdminError):
    """503 `backup_engine_invalid`: the engine plans runs not encrypted under a key alias."""

    def __init__(self) -> None:
        super().__init__("backups: the backup engine plans runs that are not encrypted")


class StartLimit(Protocol):
    """Starts per user in a rolling hour, each counted once it is recorded."""

    def retry_after(self, user: str) -> int | None: ...

    def record_start(self, user: str) -> None: ...


def _actor(who: AuditPrincipal) -> Actor:
    return {
        "actor_label": who.username, "actor_user_id": who.user_id, "actor_ip": who.ip,
        "session_id": who.session_id, "request_id": who.request_id,
    }  # fmt: skip


def _absolute(path: str) -> bool:
    """A filesystem path, never a URL or userinfo (21 Sec.3.10.3)."""
    return path.startswith("/") and "://" not in path and "@" not in path


def _unplanned(failure: str) -> NoReturn:
    _log().error("backups.plan_failed", error=failure)  # never the location or the alias
    raise OpsUnavailable("backups: the backup engine could not plan the run")


def _code(error: str | None) -> port.BackupErrorCode:
    known = error in port.BACKUP_ERROR_CODES
    return cast(port.BackupErrorCode, error) if known else "internal_error"


class BackupRuns:
    def __init__(
        self,
        rows: RunRows | None,
        runner: BackupRunner | None,
        *,
        gate: BackupJobGate,
        jobs: JobRunner,
        audit: RunAudit,
        limit: StartLimit,
        now: Callable[[], datetime] = utc_now,
        new_id: Callable[[], UUID] = uuid4,
    ) -> None:
        self._rows, self._runner, self._gate, self._jobs = rows, runner, gate, jobs
        self._audit, self._limit, self._now, self._new_id = audit, limit, now, new_id

    async def start(
        self, who: AuditPrincipal, *, kind: port.BackupKind, write_ahead: WriteAhead
    ) -> port.BackupRow:
        """Start a run for `who`: its row, `running`, and its job, submitted."""
        rows, runner = self._rows, self._runner
        if rows is None or runner is None:
            raise OpsNotWired("backups: no backup engine wired")
        user, backup_id, actor = str(who.user_id), self._new_id(), _actor(who)
        self._limited(user)  # a spent limit never waits for the lock
        async with self._gate.admit("backup", backup_id) as admission:
            self._limited(user)  # again, still before 409: only a holder of the lock counts a start
            admission.check()
            plan = await self._plan(runner, kind)
            if not (plan.encrypted and plan.encryption_ref):
                await self._refuse(actor, backup_id, kind, user)
            if not _absolute(plan.location):
                _unplanned("unstorable_plan")
            new = port.NewBackup(backup_id, kind, plan.location, plan.encrypted, "manual",
                                 who.user_id, self._now(), plan.encryption_ref)  # fmt: skip
            if not await recorded(write_ahead(backup_id, kind), "requested", backup_id):
                raise OpsAuditUnavailable("backups: the record could not be written; nothing ran")
            self._limit.record_start(user)
            row = await rows.insert(actor, new)
            result: dict[str, object] = {"backup_id": str(backup_id)}  # the job's, as polled
            report: list[tuple[int, str | None]] = []

            async def work(progress: Callable[[float], None]) -> dict[str, object]:
                size, digest = await runner.run(backup_id, plan, progress)
                if size <= 0 or (digest is not None and not _DIGEST.fullmatch(digest)):
                    raise BackupJobError("internal_error")  # a report no artefact should give
                report.append((size, digest))
                return result

            async def done(end: JobEnd) -> None:
                ok = end.status == "succeeded"
                size, digest = report[0] if ok else (None, None)
                ran = port.RunFinished(self._now(), None if ok else _code(end.error),
                                       size_bytes=size, checksum_sha256=digest)  # fmt: skip
                await rows.end(actor, backup_id, ran, result=result)

            try:
                admission.submit(self._jobs, backup_id, work, done)
            except Exception as exc:  # the job store refused it: the request ends, nothing runs
                failure = type(exc).__name__
                _log().error("backups.run_not_submitted", backup_id=str(backup_id), error=failure)
                await rows.end(actor, backup_id, port.RunFinished(self._now(), "internal_error"))
                raise OpsUnavailable("backups: the run could not start") from None
        return row

    def _limited(self, user: str) -> None:
        wait = self._limit.retry_after(user)
        if wait is not None:
            raise RunsLimited(wait)

    async def _plan(self, runner: BackupRunner, kind: port.BackupKind) -> RunPlan:
        try:
            async with asyncio.timeout(limits.PLAN_BUDGET_S):
                return await runner.plan(kind)
        except Exception as exc:  # the engine's own failure, or its budget spent
            failure = type(exc).__name__
        _unplanned(failure)

    async def _refuse(
        self, actor: Actor, backup_id: UUID, kind: port.BackupKind, user: str
    ) -> NoReturn:
        """SR-BK8A-01: an unencrypted plan's failure record, then 503 `backup_engine_invalid`."""
        state: dict[str, object] = {"stage": "refused", "kind": kind, "error": _INVALID}
        record = self._audit.emit("backup.run", **run_record(actor, backup_id, state, _INVALID))
        if not await recorded(record, "refused", backup_id):
            raise OpsAuditUnavailable("backups: the record could not be written; nothing ran")
        self._limit.record_start(user)  # counted like a start: refusals never flood the trail
        _log().error("backups.plan_refused", error=_INVALID)
        raise BackupEngineInvalid

    async def audit_requested(
        self,
        who: AuditPrincipal,
        backup_id: UUID,
        *,
        kind: port.BackupKind,
        verify: bool,
        note: str | None,
    ) -> None:
        """Run `backup_id`'s `requested` record, for a `write_ahead`: the `note` is its `reason`
        and is kept nowhere else."""
        state: dict[str, object] = {"stage": "requested", "kind": kind, "verify": verify}
        await self._audit.emit("backup.run", **run_record(_actor(who), backup_id, state, note))
