"""The `backups` catalogue port (E42-T05 #966 BK-3; 21 Sec.3.10.3 with `0032`), no driver imported:
`backups_sqlalchemy` is the Postgres side. Nothing reads `encryption_ref` (class S). `error_message`
holds only a code of `BACKUP_ERROR_CODES` (3.10.3's redaction rule). The reads are BK-3a's; BK-3b
adds the writes to `BackupStore`, with their implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def counts_as_usable(row: BackupRow) -> bool:
    """The delete rule's usable (`last_usable_backup`, Q4 on #966), as `usable_count` counts it."""
    return (
        row.status in VERIFIED_STATUSES and row.verified_at is not None and row.deleted_at is None
    )


class BackupStore(Protocol):
    """Raises `StorageTierUnavailable` when the table is not reached in time and otherwise a typed
    `StorageError` (`StorageQueryFailed`, or the 23514 refusals), never with the driver's text."""

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
