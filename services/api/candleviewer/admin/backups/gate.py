"""The backups admission lock (E42-T05, #966 BK-7, Q6): the one process-wide lock that admits a run,
a verification, a restore and a delete one at a time, and the registry of the admitted jobs still
running. The caller holds it from the check through the write-ahead record (C-2.9) to the submit,
so an await in between never lets a second admission through:

    async with gate.admit("backup_verify", backup_id) as admission:
        admission.check()  # BackupConflict(rule): 409, nothing written, no entry
        await audit.emit(...)
        admission.submit(runner, job_id, work, on_done)

`check()` may sit later in a caller's contract order (a restore reads maintenance mode first) and
`submit` checks again. A job's entry goes once, when the job settles: after `on_done`, or when it
is cancelled. A delete runs no job: under `admit_delete` BK-12 evaluates `backup_deleted`,
`check()` (`backup_in_use`: any job on that backup) and `last_usable_backup`, writes its record,
removes the artefact (`remover.remove` under the lock) and marks the row, one delete at a time
(SR-BK0-08). A download link runs no job either: under `admit_link` BK-10 decides whether the
backup is usable and writes its record, so neither interleaves with a delete; no job refuses it.

Bounds (`limits`): an admission waits `ADMIT_WAIT_S` for the lock, then `OpsUnavailable` (503
`store_unavailable`, retryable) with nothing registered; every await inside an admission needs
its own budget, since a stalled one holds the lock for every caller. An admitted job's `work`
ends at its kind's `JOB_DEADLINE_S` and fails `internal_error`. The lock is not re-entrant: an
`admit` or `admit_delete` inside an admission block waits on itself, then is refused."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Final, Literal
from uuid import UUID

from candleviewer.admin.backups.limits import ADMIT_WAIT_S, JOB_DEADLINE_S
from candleviewer.admin.backups.ports import JobDone, JobKind, JobRunner, JobWork, Progress
from candleviewer.admin.errors import AdminError, OpsUnavailable

ConflictRule = Literal["backup_or_restore_running", "verify_running", "backup_in_use"]
_NoJob = Literal["delete", "link"]  # admissions that run no job
_BUSY: Final = "backup_or_restore_running"
#: Per job kind: the running kinds that refuse it, in order, and the rule each answers.
_EXCLUSIONS: Final[Mapping[JobKind, tuple[tuple[frozenset[str], ConflictRule], ...]]] = {
    "backup": ((frozenset({"backup", "backup_restore"}), _BUSY),),
    "backup_verify": (
        (frozenset({"backup_restore"}), _BUSY),
        (frozenset({"backup_verify"}), "verify_running"),
    ),
    "backup_restore": ((frozenset({"backup", "backup_restore", "backup_verify"}), _BUSY),),
}


class BackupConflict(AdminError):
    """`409 conflict` with the contract's `rule`."""

    def __init__(self, rule: ConflictRule) -> None:
        super().__init__(rule)
        self.rule: ConflictRule = rule


class BackupJobGate:
    def __init__(
        self,
        *,
        admit_wait_s: float = ADMIT_WAIT_S,
        deadlines_s: Mapping[JobKind, float] = JOB_DEADLINE_S,
    ) -> None:
        self._lock = asyncio.Lock()
        self._admit_wait_s, self._deadlines_s = admit_wait_s, deadlines_s
        #: Keyed by a token per job, so a job's settle never takes a later job's entry.
        self._running: dict[object, tuple[JobKind, UUID]] = {}

    def active(self) -> list[tuple[JobKind, UUID]]:
        return list(self._running.values())

    def admit(self, kind: JobKind, backup_id: UUID) -> AbstractAsyncContextManager[JobAdmission]:
        return self._held(JobAdmission(self, kind, backup_id))

    def admit_delete(self, backup_id: UUID) -> AbstractAsyncContextManager[Admission]:
        return self._held(Admission(self, "delete", backup_id))

    def admit_link(self, backup_id: UUID) -> AbstractAsyncContextManager[Admission]:
        return self._held(Admission(self, "link", backup_id))

    @asynccontextmanager
    async def _held[A: Admission](self, admission: A) -> AsyncIterator[A]:
        try:
            async with asyncio.timeout(self._admit_wait_s):
                await self._lock.acquire()
        except TimeoutError:
            raise OpsUnavailable("backups: the admission lock is busy") from None
        try:
            yield admission
        finally:
            admission.open = False
            self._lock.release()

    def _refusal(self, kind: JobKind | _NoJob, backup_id: UUID) -> ConflictRule | None:
        if kind == "link":
            return None
        if kind == "delete":
            used = any(backup == backup_id for _, backup in self._running.values())
            return "backup_in_use" if used else None
        running = {running_kind for running_kind, _ in self._running.values()}
        return next((rule for kinds, rule in _EXCLUSIONS[kind] if kinds & running), None)


class Admission:
    """The lock, held until the admission's `async with` block ends."""

    def __init__(self, gate: BackupJobGate, kind: JobKind | _NoJob, on: UUID) -> None:
        self._gate, self._kind, self._on, self.open = gate, kind, on, True

    def check(self) -> None:
        if not self.open:
            raise RuntimeError("the admission lock was released")
        rule = self._gate._refusal(self._kind, self._on)
        if rule is not None:
            raise BackupConflict(rule)


class JobAdmission(Admission):
    _kind: JobKind

    def submit(self, runner: JobRunner, job_id: UUID, work: JobWork, on_done: JobDone) -> None:
        self.check()
        running, token = self._gate._running, object()
        running[token] = (self._kind, self._on)
        deadline = self._gate._deadlines_s[self._kind]

        async def bounded(progress: Progress) -> dict[str, object]:
            async with asyncio.timeout(deadline):  # a hung job fails and frees its lane
                return await work(progress)

        def settled() -> None:
            running.pop(token, None)

        try:
            runner.submit(self._kind, job_id, bounded, on_done, settled)
        except BaseException:
            settled()
            raise
