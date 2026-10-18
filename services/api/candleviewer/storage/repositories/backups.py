"""The `backups` catalogue port (E42-T05 #966 BK-3; 21 Sec.3.10.3 with `0032`), no driver imported:
`backups_sqlalchemy` is the Postgres side. Nothing reads `encryption_ref` (class S); a `NewBackup`
writes it once. `error_message` holds only a code of `BACKUP_ERROR_CODES` (3.10.3's redaction rule).
Every datetime is timezone-aware: asyncpg would read a naive one in the process's local zone.
"""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol, get_args
from uuid import UUID

#: The table's enum types and CHECK lists, mirrored so no driver is imported; a unit test pins them.
BackupKind = Literal[
    "pg_basebackup", "pg_dump", "questdb_snapshot", "parquet_sync", "config_bundle"
]
BackupStatus = Literal["running", "ok", "failed", "verified", "restored"]
TriggeredBy = Literal["schedule", "manual", "pre_migration", "pre_release", "pre_restore"]
VerifyMethod = Literal["restore_smoke", "checksum", "pg_verifybackup", "duckdb_scan"]
BackupCheck = Literal["bk_trigger", "bk_verify", "bk_deleted"]  # by the name a violation reports
BackupErrorCode = Literal[
    "checksum_mismatch", "checksum_unbound", "artefact_missing", "verify_failed",
    "audit_unavailable", "store_unavailable", "internal_error",
]  # fmt: skip
BACKUP_ERROR_CODES: Final[frozenset[str]] = frozenset(get_args(BackupErrorCode))  # `Backup.error`
BACKUP_CHECKS: Final[frozenset[str]] = frozenset(get_args(BackupCheck))
SUCCESS_STATUSES: Final = ("ok", "verified", "restored")  # a run that succeeded
VERIFIED_STATUSES: Final = ("verified", "restored")  # with `verified_at`: the delete rule's usable
Position = tuple[datetime, UUID]  # `(started_at, id)` of the previous page's last row


@dataclass(frozen=True, slots=True)
class BackupRow:
    """`Backup` by column name (`target_path`, `error_message`), `covers_to`, `triggered_by`."""

    id: UUID
    kind: BackupKind
    status: BackupStatus
    target_path: str
    size_bytes: int | None
    checksum_sha256: str | None
    encrypted: bool
    covers_to: datetime | None
    verified_at: datetime | None
    error_message: str | None
    triggered_by: TriggeredBy
    started_at: datetime
    finished_at: datetime | None
    retention_until: datetime | None
    deleted_at: datetime | None


def require_aware(*values: datetime | None) -> None:
    """Refuse a naive datetime with a fixed message, before any SQL."""
    if any(value is not None and value.utcoffset() is None for value in values):
        raise ValueError("backups: datetimes must be timezone-aware")


@dataclass(frozen=True, slots=True)
class NewBackup:
    """A run's row as it starts, `running`; the class S alias stays out of `repr`."""

    id: UUID
    kind: BackupKind
    target_path: str
    encrypted: bool
    triggered_by: TriggeredBy
    triggered_by_user: UUID | None
    started_at: datetime
    encryption_ref: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        require_aware(self.started_at)


@dataclass(frozen=True, slots=True)
class RunFinished:
    """`ok` when `error` is `None`, else `failed` with that code; the engine's report as given."""

    finished_at: datetime
    error: BackupErrorCode | None
    _: KW_ONLY  # the report by name: three of its fields are datetimes a swap would type-check
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    covers_from: datetime | None = None
    covers_to: datetime | None = None
    retention_until: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.finished_at, self.covers_from, self.covers_to, self.retention_until)


def counts_as_usable(row: BackupRow) -> bool:
    """The delete rule's usable (`last_usable_backup`, Q4 on #966), as `usable_count` counts it."""
    return (
        row.status in VERIFIED_STATUSES and row.verified_at is not None and row.deleted_at is None
    )


class BackupStore(Protocol):
    """Raises `StorageTierUnavailable` when the table is not reached in time and otherwise a typed
    `StorageError` (`StorageQueryFailed`, or the 23514 refusals), never with the driver's text. A
    write that raises before its COMMIT changed nothing; a connection lost at the COMMIT leaves the
    outcome unknown. Each update is guarded, so its retry is safe: `None` then means it applied, or
    another writer's did (`get` tells which); an update returning `None` matched no row."""

    async def page(
        self,
        kind: BackupKind | None,
        status: BackupStatus | None,
        after: Position | None,
        limit: int,
    ) -> list[BackupRow]:
        """Newest first (`started_at`, then `id`), strictly after `after`; deleted rows too."""

    async def get(self, backup_id: UUID) -> BackupRow | None: ...

    async def last_success_by_kind(self) -> dict[BackupKind, datetime]:
        """Per kind, the latest `finished_at` of a success whose artefact was not deleted."""

    async def usable_count(self, kind: BackupKind) -> int:
        """Rows of `kind` that `counts_as_usable`; a delete reads it under the admission lock."""

    async def insert_running(self, new: NewBackup) -> BackupRow:
        """A new `running` row, its `target_path` an absolute filesystem path, never a URL or
        userinfo (21 Sec.3.10.3); `encryption_ref` is written here, once, and never read back.
        Repeating an insert that applied raises `StorageQueryFailed` (23505); `get` tells."""

    async def record_run_finished(self, backup_id: UUID, run: RunFinished) -> BackupRow | None:
        """Only while `running`."""

    async def record_verify_outcome(
        self, backup_id: UUID, *, method: VerifyMethod, at: datetime, error: BackupErrorCode | None
    ) -> BackupRow | None:
        """The latest outcome wins. A pass makes the row `verified` at `at` by `method`, clearing
        `error_message` (a `restored` row too, `restored_at` kept); a failure makes it `failed`
        with `error`, `verified_at` and `verify_method` kept from the last pass. Never on a
        running or deleted backup."""

    async def mark_deleted(self, backup_id: UUID, *, by: UUID, at: datetime) -> BackupRow | None:
        """`deleted_at` and `deleted_by` together, once, never on a running backup; the row and its
        status stay."""
