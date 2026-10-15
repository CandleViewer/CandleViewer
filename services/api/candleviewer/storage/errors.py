"""Domain errors for the storage module (M10).

Each exception carries a stable `code` string attribute (frozen mapping
tested by `services/api/tests/unit/storage/test_errors.py`) so log consumers
and `system_events` rows never break silently on a refactor that renames a
class (ticket "Scope / Deliverables": "each with a stable string code used in
logs and `system_events`").
"""

from __future__ import annotations


class StorageError(Exception):
    """Base exception for the M10 `storage` module."""

    code: str = "STORAGE_ERROR"


class StorageTierUnavailable(StorageError):
    """A tier client failed to connect or answer at boot or at call time.

    Raised by `health()` implementations' internal probes and by repository
    methods when their tier is down; the supervisor treats this as
    readiness-blocking for `postgres`, degraded-but-serving for `questdb`
    reads-from-cold, and export-blocking only for `cold` (ticket "Technical
    notes / design").
    """

    code = "STORAGE_TIER_UNAVAILABLE"


class StorageExportVerifyFailed(StorageError):
    """`ColdTierRepository.verify_checksums` found a mismatch after export."""

    code = "STORAGE_EXPORT_VERIFY_FAILED"


class StorageSchemaDrift(StorageError):
    """A tier's on-disk/on-wire schema no longer matches this package's models."""

    code = "STORAGE_SCHEMA_DRIFT"


class StorageRetentionBlockedByPin(StorageError):
    """`RetentionRepository.apply` refused to roll off or delete a pinned range."""

    code = "STORAGE_RETENTION_BLOCKED_BY_PIN"


class StorageRetentionBlockedUnverified(StorageError):
    """A hot partition may not be dropped: its cold export is missing or unverified (Sec.5.3)."""

    code = "STORAGE_RETENTION_BLOCKED_UNVERIFIED"


class StorageRetentionBlockedByReplay(StorageError):
    """A partition is referenced by an active `replay_sessions` row."""

    code = "STORAGE_RETENTION_BLOCKED_REPLAY"


class StorageDiskCritical(StorageError):
    """Free disk fell below the configured critical threshold for a tier."""

    code = "STORAGE_DISK_CRITICAL"


class IlpRowError(StorageError, ValueError):
    """A row handed to `IlpWriter.write_rows` is malformed (E49-K01-F2, #1636).

    Raised *before* any row of the batch is enqueued, so a bad row never
    poisons a batch or tears down the writer; the caller (ingestion
    supervisor) can quarantine the row and alarm. Subclasses `ValueError`
    for callers that already catch it.
    """

    code = "STORAGE_ILP_ROW_INVALID"


class MissingDesignatedTimestamp(IlpRowError):
    """The row lacks the designated-timestamp key, or it is not a non-negative int (µs)."""

    code = "STORAGE_ILP_MISSING_DESIGNATED_TS"


class InvalidSymbol(IlpRowError):
    """The row's `symbol` tag is missing, empty or not a string."""

    code = "STORAGE_ILP_INVALID_SYMBOL"


class UnknownIlpTable(IlpRowError, KeyError):
    """`write_rows` was called for a table with no registered `TableSchema`.

    Also a `KeyError` (the pre-contract behaviour) for caller compatibility.
    """

    code = "STORAGE_ILP_UNKNOWN_TABLE"


class AuditEntryTooLarge(StorageError):
    """An audit entry's renderings are over the verify per-entry cap (E42-T02), so a verify
    run cannot check it within its memory bound and stops fail-closed: never a pass. Its
    renderings are never fetched; `entry_id` names it."""

    code = "STORAGE_AUDIT_ENTRY_TOO_LARGE"

    def __init__(self, entry_id: int) -> None:
        super().__init__(f"audit entry {entry_id} is over the verify entry size cap")
        self.entry_id = entry_id


#: Frozen mapping from exception class to its stable code, asserted by a
#: unit test so a future rename cannot silently change a log/system_events
#: value (ticket "Scope / Deliverables").
ERROR_CODES: dict[type[StorageError], str] = {
    StorageError: StorageError.code,
    StorageTierUnavailable: StorageTierUnavailable.code,
    StorageExportVerifyFailed: StorageExportVerifyFailed.code,
    StorageSchemaDrift: StorageSchemaDrift.code,
    StorageRetentionBlockedByPin: StorageRetentionBlockedByPin.code,
    StorageRetentionBlockedUnverified: StorageRetentionBlockedUnverified.code,
    StorageRetentionBlockedByReplay: StorageRetentionBlockedByReplay.code,
    StorageDiskCritical: StorageDiskCritical.code,
    IlpRowError: IlpRowError.code,
    MissingDesignatedTimestamp: MissingDesignatedTimestamp.code,
    InvalidSymbol: InvalidSymbol.code,
    UnknownIlpTable: UnknownIlpTable.code,
    AuditEntryTooLarge: AuditEntryTooLarge.code,
}
