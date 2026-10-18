"""Domain errors for the storage module (M10).

Each exception carries a stable `code` string attribute (frozen mapping
tested by `services/api/tests/unit/storage/test_errors.py`) so log consumers
and `system_events` rows never break silently on a refactor that renames a
class (ticket "Scope / Deliverables": "each with a stable string code used in
logs and `system_events`").
"""

from __future__ import annotations

from typing import Literal

#: Why a `DROP PARTITION` could not be confirmed (closed set: safe as a metric label).
DropNotAppliedReason = Literal["suspended", "timeout", "unexpected_shape"]

#: Why a WAL table's apply could not be confirmed caught up (closed set: safe as a metric label).
WalNotAppliedReason = Literal["suspended", "timeout", "unexpected_shape"]


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


class StoragePartitionDropNotApplied(StorageError):
    """A `DROP PARTITION` was issued but could not be confirmed applied: the day may still be hot.

    QuestDB applies DDL on WAL tables asynchronously. `reason`: `suspended` (the table's WAL apply
    is suspended: an operator must resume it), `timeout` (still listed after the wall-clock
    bound) or `unexpected_shape` (the partition inventory lacks the `name` column: fail closed).
    The reason is part of the message and a field; `table`, `partition` and `waited_s` say where
    and how long. Never a success: callers keep the day, and the DROP is not re-issued here.
    """

    code = "STORAGE_PARTITION_DROP_NOT_APPLIED"

    def __init__(
        self,
        message: str,
        *,
        reason: DropNotAppliedReason,
        table: str = "",
        partition: str = "",
        waited_s: float = 0.0,
    ) -> None:
        super().__init__(f"{message} (reason={reason})")
        self.reason: DropNotAppliedReason = reason
        self.table = table
        self.partition = partition
        self.waited_s = waited_s


class StorageSchemaDrift(StorageError):
    """A tier's on-disk/on-wire schema no longer matches this package's models."""

    code = "STORAGE_SCHEMA_DRIFT"


class StorageWalNotApplied(StorageError):
    """A WAL table's apply job did not catch up with its sequencer, so a read cannot be trusted.

    QuestDB acknowledges a write once it is committed to the sequencer; a `SELECT` sees it only
    after the apply job ran (#3064). `reason`: `suspended` (an operator must resume the apply),
    `timeout` (still behind after the wall-clock bound) or `unexpected_shape` (the status row
    lacks the txn columns: fail closed). `table` and `waited_s` say where and how long. Never a
    success: the caller does not read the table.
    """

    code = "STORAGE_WAL_NOT_APPLIED"

    def __init__(
        self,
        message: str,
        *,
        reason: WalNotAppliedReason,
        table: str = "",
        waited_s: float = 0.0,
    ) -> None:
        super().__init__(f"{message} (reason={reason})")
        self.reason: WalNotAppliedReason = reason
        self.table = table
        self.waited_s = waited_s


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


class StorageQueryFailed(StorageError):
    """A database statement failed and the repository has no domain error for it.

    Carries only the SQLSTATE (None for a driver-side failure that has none). It never carries the
    statement, its bound parameters or the driver's message: those can embed P1 column values (a
    bound `bookmarks` note, the server's `DETAIL: Failing row contains (...)`), and no exception
    chain may render them (C-12.6). Raise it `from None` so the driver error is not chained.
    """

    code = "STORAGE_QUERY_FAILED"

    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(f"database statement failed (sqlstate {sqlstate or 'unknown'})")
        self.sqlstate = sqlstate


class WriteAheadTimeout(StorageError, TimeoutError):
    """A write-ahead audit hook awaited inside a unit of work outlived its bound (#2510).

    The unit of work rolled back before its commit: nothing persisted and its row locks are
    free, so a route may answer "nothing was changed". A driver or commit `TimeoutError` is a
    different case (the outcome may be unknown) and must not be mapped like this one.
    """

    code = "STORAGE_WRITE_AHEAD_TIMEOUT"


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


class StorageRecordInvalid(StorageError, ValueError):
    """A stored market-data row cannot become a `RecordedEvent` (E26-T02): a column is missing,
    mistyped, non-finite or outside its closed set, or the stream is not replayable. Raised,
    never skipped, so a replay cannot silently lose a recorded event. The message names the
    column, and no exception chain carries the value."""

    code = "STORAGE_RECORD_INVALID"


class AuditEntryTooLarge(StorageError):
    """An audit entry's renderings are over the verify per-entry cap (E42-T02), so a verify
    run cannot check it within its memory bound and stops fail-closed: never a pass. Its
    renderings are never fetched; `entry_id` names it."""

    code = "STORAGE_AUDIT_ENTRY_TOO_LARGE"

    def __init__(self, entry_id: int) -> None:
        super().__init__(f"audit entry {entry_id} is over the verify entry size cap")
        self.entry_id = entry_id


class HotReplayReadError(StorageTierUnavailable):
    """QuestDB could not serve a replay read (connection lost, backoff, server error): typed, so
    a replay surfaces a datastore outage as one error (chaos scenario 10)."""

    code = "HOT_REPLAY_READ_ERROR"


class HotReplayReadTimeout(StorageTierUnavailable):
    """A QuestDB replay read exceeded the reader's deadline, which sits below the replay merge's:
    typed, so a slow query fails in its tier first."""

    code = "HOT_REPLAY_READ_TIMEOUT"


class RewrapAuditNotWired(StorageError):
    """The credential store has no audit row builder, so it refuses every re-wrap (#2266)."""

    code = "STORAGE_REWRAP_AUDIT_NOT_WIRED"


class RewrapAuditNotWritten(StorageError):
    """A re-wrap's record was not written (its `record_id` is stored), so both rolled back."""

    code = "STORAGE_REWRAP_AUDIT_NOT_WRITTEN"


#: Frozen mapping from exception class to its stable code, asserted by a
#: unit test so a future rename cannot silently change a log/system_events
#: value (ticket "Scope / Deliverables").
ERROR_CODES: dict[type[StorageError], str] = {
    StorageError: StorageError.code,
    StorageTierUnavailable: StorageTierUnavailable.code,
    StorageExportVerifyFailed: StorageExportVerifyFailed.code,
    StoragePartitionDropNotApplied: StoragePartitionDropNotApplied.code,
    StorageSchemaDrift: StorageSchemaDrift.code,
    StorageWalNotApplied: StorageWalNotApplied.code,
    StorageRetentionBlockedByPin: StorageRetentionBlockedByPin.code,
    StorageRetentionBlockedUnverified: StorageRetentionBlockedUnverified.code,
    StorageRetentionBlockedByReplay: StorageRetentionBlockedByReplay.code,
    StorageDiskCritical: StorageDiskCritical.code,
    StorageQueryFailed: StorageQueryFailed.code,
    WriteAheadTimeout: WriteAheadTimeout.code,
    IlpRowError: IlpRowError.code,
    MissingDesignatedTimestamp: MissingDesignatedTimestamp.code,
    InvalidSymbol: InvalidSymbol.code,
    UnknownIlpTable: UnknownIlpTable.code,
    StorageRecordInvalid: StorageRecordInvalid.code,
    AuditEntryTooLarge: AuditEntryTooLarge.code,
    HotReplayReadError: HotReplayReadError.code,
    HotReplayReadTimeout: HotReplayReadTimeout.code,
    RewrapAuditNotWired: RewrapAuditNotWired.code,
    RewrapAuditNotWritten: RewrapAuditNotWritten.code,
}
