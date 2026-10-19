"""Ports of the backups surface (E42-T05, #966 BK-7), filled by `candleviewer.backups_wiring`. No
backup engine exists yet (#966 Q1), so its ports stay unwired and their routes answer `501`. The
engine executes; the backups services record: no catalogue write or audit record goes through a
port. M21 may not import `api` (C-3.1), so the admin job store is a port too (`JobRunner`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.admin.backups.artefact_port import OpenArtefact
from candleviewer.admin.errors import AdminError
from candleviewer.storage.repositories.backups import BACKUP_ERROR_CODES, BackupErrorCode, BackupRow
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
    location: str  # inside the backup root: an absolute filesystem path
    encrypted: bool  # a run is refused unless it is, under an alias (SR-091)
    #: The keyring alias (class S) the artefact is encrypted under; only ever written into the
    #: row, once (`backups.encryption_ref`), never read back or logged.
    encryption_ref: str | None = field(default=None, repr=False)


class BackupRunner(Protocol):
    async def plan(self, kind: str) -> RunPlan:
        """Within `PLAN_BUDGET_S`; encrypted under a non-empty alias, at an absolute path."""

    async def run(
        self, backup_id: UUID, plan: RunPlan, progress: Progress
    ) -> tuple[int, str | None]:
        """`(size_bytes, checksum_sha256)`: the size of what the run stored, never the bytes it
        added, so positive (an unchanged lake's sync reports its repository's size); the SHA-256
        as 64 lowercase hex, none for a directory or a repository (Q8). Else `internal_error`."""


class ScratchVerifier(Protocol):
    async def verify(
        self, backup_id: UUID, location: str, artefact: OpenArtefact | None, progress: Progress
    ) -> VerifyMethod:
        """Restore into scratch and assert, once the digest matched. `artefact` is the file the
        job hashed, still open: read it through `stream()` only, never by reopening `location`,
        so no file swapped in after the hash is decrypted (Q7); `None` for a directory or a
        repository, which this checks at `location` itself (Q8), so it is that backup's only
        integrity gate: it first resolves `location`, without following a symbolic link, to a
        directory inside the backup root (`CV_BACKUP_ROOT`) before reading anything, else fails
        conclusively (SR-BK9-02). Returns the `verify_method`. Any content failure (a failed
        assertion, content corrupt or unexpected) raises `BackupJobError("verify_failed")`,
        conclusive (SR-CD2-02); only the environment's faults are inconclusive: an unreadable
        volume or store (`ArtefactUnreadable`, `StorageTierUnavailable`,
        `BackupJobError("store_unavailable")`) or a timeout. The job takes anything else it raises
        as `verify_failed` too. It bounds the wait and, cancelled, closes the artefact."""


class ArtefactRemover(Protocol):
    async def remove(self, backup_id: UUID, location: str) -> None:
        """Remove the artefact at the row's stored `location`, and nothing else. It resolves the
        location as BK-6a's reader does (`storage/backup_artefacts.py`): absolute, canonical and
        inside `CV_BACKUP_ROOT`, or refused by raising before any I/O; then walked `O_NOFOLLOW` at
        every component, a symbolic link or another device than the root's refused by raising
        before anything is removed. A directory artefact's contents are removed without following
        a symbolic link, and nothing on a device other than the root's. A delete cancels it past
        `REMOVE_BUDGET_S`, under the admission lock, so it is cancel-safe: none of its work runs on
        once it returns or is cancelled. One already gone counts as removed, so a delete retried
        after its mark failed completes."""


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


@dataclass(frozen=True, slots=True)
class RunRecord:
    """What a backup's newest successful `backup.run` record at `stage: finished` bound."""

    digest: str | None  # `checksum_sha256`: none for a directory or a repository (Q8)
    covers_to: datetime | None = None  # the threat model's §6 step 3 reads it from the record


class RunRecords(Protocol):
    async def run_record(self, backup_id: UUID) -> RunRecord | None:
        """Read from the append-only trail, never the row; `None` when no such record is found,
        or none whose chain checks out."""


#: A verification's conclusive failures: only these are recorded on the row (contract-D); any
#: other end of its job (`store_unavailable`, `audit_unavailable`, `internal_error`) is no evidence.
CONCLUSIVE: Final = frozenset(
    {"checksum_mismatch", "checksum_unbound", "artefact_missing", "verify_failed"}
)


class Outcomes(Protocol):
    async def record_verify_outcome(
        self, backup_id: UUID, *, method: VerifyMethod, at: datetime, error: BackupErrorCode | None
    ) -> BackupRow | None: ...  # BK-3's guarded write


class Freshness(Protocol):
    """BK-5's `BackupFreshness` with BK-12's `recompute` (bounded, never raising, locked). The job
    contains a failure of either and bounds `recompute`, so neither changes its end."""

    def record_success(self, row: BackupRow) -> None: ...

    async def recompute(self, row: BackupRow) -> None: ...
