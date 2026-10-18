"""Unit tests for `candleviewer.storage.errors` (E07-T01).

Error-code stability: a frozen mapping of exception class -> string code, so
log/`system_events` consumers do not break silently on a rename (ticket
"Test plan").
"""

from __future__ import annotations

from candleviewer.storage.errors import (
    ERROR_CODES,
    AuditEntryTooLarge,
    BackupCheckViolation,
    BackupWriteOnceViolation,
    HotReplayReadError,
    HotReplayReadTimeout,
    IlpRowError,
    InvalidSymbol,
    KcvEnrolmentNotAudited,
    MissingDesignatedTimestamp,
    RewrapAuditNotWired,
    RewrapAuditNotWritten,
    StorageDiskCritical,
    StorageError,
    StorageExportVerifyFailed,
    StoragePartitionDropNotApplied,
    StorageQueryFailed,
    StorageRecordInvalid,
    StorageRetentionBlockedByPin,
    StorageRetentionBlockedByReplay,
    StorageRetentionBlockedUnverified,
    StorageSchemaDrift,
    StorageTierUnavailable,
    StorageWalNotApplied,
    UnknownIlpTable,
    WriteAheadTimeout,
)


def test_error_codes_are_stable_and_unique() -> None:
    assert ERROR_CODES == {
        StorageError: "STORAGE_ERROR",
        StorageTierUnavailable: "STORAGE_TIER_UNAVAILABLE",
        StorageExportVerifyFailed: "STORAGE_EXPORT_VERIFY_FAILED",
        StoragePartitionDropNotApplied: "STORAGE_PARTITION_DROP_NOT_APPLIED",
        StorageSchemaDrift: "STORAGE_SCHEMA_DRIFT",
        StorageWalNotApplied: "STORAGE_WAL_NOT_APPLIED",
        StorageRetentionBlockedByPin: "STORAGE_RETENTION_BLOCKED_BY_PIN",
        StorageRetentionBlockedUnverified: "STORAGE_RETENTION_BLOCKED_UNVERIFIED",
        StorageRetentionBlockedByReplay: "STORAGE_RETENTION_BLOCKED_REPLAY",
        StorageDiskCritical: "STORAGE_DISK_CRITICAL",
        StorageQueryFailed: "STORAGE_QUERY_FAILED",
        WriteAheadTimeout: "STORAGE_WRITE_AHEAD_TIMEOUT",
        IlpRowError: "STORAGE_ILP_ROW_INVALID",
        MissingDesignatedTimestamp: "STORAGE_ILP_MISSING_DESIGNATED_TS",
        InvalidSymbol: "STORAGE_ILP_INVALID_SYMBOL",
        UnknownIlpTable: "STORAGE_ILP_UNKNOWN_TABLE",
        StorageRecordInvalid: "STORAGE_RECORD_INVALID",
        AuditEntryTooLarge: "STORAGE_AUDIT_ENTRY_TOO_LARGE",
        HotReplayReadError: "HOT_REPLAY_READ_ERROR",
        HotReplayReadTimeout: "HOT_REPLAY_READ_TIMEOUT",
        RewrapAuditNotWired: "STORAGE_REWRAP_AUDIT_NOT_WIRED",
        RewrapAuditNotWritten: "STORAGE_REWRAP_AUDIT_NOT_WRITTEN",
        BackupWriteOnceViolation: "STORAGE_BACKUP_WRITE_ONCE",
        BackupCheckViolation: "STORAGE_BACKUP_CHECK_VIOLATION",
        KcvEnrolmentNotAudited: "STORAGE_KCV_ENROLMENT_NOT_AUDITED",
    }
    assert len(set(ERROR_CODES.values())) == len(ERROR_CODES)


def test_every_storage_error_is_an_exception_subclass() -> None:
    for cls in ERROR_CODES:
        assert issubclass(cls, Exception)


def test_storage_tier_unavailable_carries_its_class_code() -> None:
    err = StorageTierUnavailable("questdb down")
    assert err.code == "STORAGE_TIER_UNAVAILABLE"
    assert str(err) == "questdb down"


def test_partition_drop_not_applied_carries_structured_reason_and_names_it_in_the_message() -> None:
    err = StoragePartitionDropNotApplied(
        "partition 2026-10-17 of trades not applied",
        reason="suspended",
        table="trades",
        partition="2026-10-17",
        waited_s=1.5,
    )
    assert isinstance(err, StorageError) and err.code == "STORAGE_PARTITION_DROP_NOT_APPLIED"
    assert (err.reason, err.table, err.partition, err.waited_s) == (
        "suspended",
        "trades",
        "2026-10-17",
        1.5,
    )
    assert str(err) == "partition 2026-10-17 of trades not applied (reason=suspended)"


def test_storage_query_failed_names_only_the_sqlstate() -> None:
    err = StorageQueryFailed("40001")
    assert (err.code, err.sqlstate) == ("STORAGE_QUERY_FAILED", "40001")
    assert str(err) == "database statement failed (sqlstate 40001)"
    assert (StorageQueryFailed(None).sqlstate, str(StorageQueryFailed(None))) == (
        None,
        "database statement failed (sqlstate unknown)",
    )
