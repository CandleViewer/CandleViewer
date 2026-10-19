"""Ports of the backups surface (E42-T05, #966 BK-7), filled by `candleviewer.backups_wiring`. No
backup engine exists yet (#966 Q1), so its ports stay unwired and their routes answer `501`. The
engine executes; the backups services record: no catalogue write or audit record goes through a
port. M21 may not import `api` (C-3.1), so the admin job store is a port too (`JobRunner`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.admin.errors import AdminError
from candleviewer.storage.repositories.backups import BACKUP_ERROR_CODES, BackupErrorCode
from candleviewer.storage.repositories.backups import VerifyMethod as VerifyMethod  # BK-3a's

JobKind = Literal["backup", "backup_verify", "backup_restore"]  # `Job.kind` values
#: The closed set of a failed backups job's `Job.error` (C-12.6) is the catalogue's own (BK-3a,
#: `backups.error_message`), so a job and its row name a failure alike; anything else is
#: `internal_error`, so no class name, message, path or key material reaches a client.
JobErrorCode = BackupErrorCode
JOB_ERROR_CODES: Final = BACKUP_ERROR_CODES
Component = Literal["postgres", "questdb", "parquet", "config"]
Progress = Callable[[float], None]
JobWork = Callable[[Progress], Awaitable[dict[str, object]]]  # returns `Job.result`


@dataclass(frozen=True, slots=True)
class JobEnd:
    status: Literal["succeeded", "failed"]
    result: dict[str, object] | None
    error: str | None


JobDone = Callable[[JobEnd], Awaitable[None]]
Settled = Callable[[], None]


class BackupJobError(AdminError):
    """Fails a backups job with `code`, its only text."""

    def __init__(self, code: JobErrorCode) -> None:
        super().__init__(code)
        self.code: JobErrorCode = code


class JobRunner(Protocol):
    def submit(
        self, kind: JobKind, job_id: UUID, work: JobWork, on_done: JobDone, on_settled: Settled
    ) -> None:
        """Start job `job_id`, pollable at once. `on_done` is awaited when it ends `succeeded` or
        `failed`; `on_settled` is called once after that, or when the job is cancelled, started or
        not. If it cannot start the job it raises and calls neither."""


#: The engine ports get a catalogue row's id and stored `location`, never a path a client sent.
@dataclass(frozen=True, slots=True)
class RunPlan:
    location: str  # inside the backup root
    encrypted: bool


class BackupRunner(Protocol):
    async def plan(self, kind: str) -> RunPlan: ...

    async def run(
        self, backup_id: UUID, plan: RunPlan, progress: Progress
    ) -> tuple[int, str | None]:
        """`(size_bytes, checksum_sha256)`; no digest for a directory or a repository (Q8)."""


class ScratchVerifier(Protocol):
    async def verify(self, backup_id: UUID, location: str, progress: Progress) -> VerifyMethod:
        """Restore into scratch and assert, after the digest check; returns the `verify_method`,
        and a failed assertion raises `BackupJobError("verify_failed")`."""


class ArtefactRemover(Protocol):
    async def remove(self, backup_id: UUID, location: str) -> None: ...


class RestoreExecutor(Protocol):
    async def restore(
        self, backup_id: UUID, location: str, components: frozenset[Component], progress: Progress
    ) -> dict[str, object]:
        """Reached only through the restore guard; re-checks maintenance mode when it starts and
        holds the trading halt outside the database it replaces (e42-admin.md §6 step 7). Its
        deadline or a shutdown cancels it at any await, and trading must stay halted then."""


class MaintenanceState(Protocol):
    async def read(self) -> bool | None:
        """A fresh read of `maintenance.mode`; `None` when unreadable, never "on"."""


class OpenPositions(Protocol):
    @property
    def source(self) -> str: ...  # `not_deployed` while no position store exists

    async def count_open(self) -> int | None:
        """Across every account; `None` when unknown, never a made-up 0."""


class RunEvidence(Protocol):
    async def bound_digest(self, backup_id: UUID) -> str | None:
        """The digest the run's finished `backup.run` record bound; `None` when none did."""
