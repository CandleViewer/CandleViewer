# Runbook — recorder roll-off (E16-T05)

Owner: recorder-replay. Code: `services/api/candleviewer/recorder/rolloff.py` (`RollOffJob`),
`storage/cold/rolloff_ops.py` (export + read-back verify + drop), `storage/cold/watermarks.py`.

## How it works

Nightly, per stream, closed QuestDB DAY partitions older than every present symbol's hot window
(`retention_policies.retain_days`; pinned = never) are exported via the existing cold exporter, then
re-read: row count **and** a canonical content SHA-256 must equal the hot source, and the manifest
SHA-256 must re-verify. Only when **every** symbol in that day verifies is the partition audited
(`retention.purge`) and dropped. Days are processed newest-first. Watermarks live at
`<CV_PARQUET_ROOT>/_manifests/_watermarks/<stream>/symbol=<SYM>.json` and only move forward.

## Stuck watermark (`recorder_watermark_lag_days` > hot window + 2)

1. Check `recorder_rolloff_failures_total{reason}` and logs for `rolloff_archive_failed` /
   `system_event code=archive.verification_failed` or `archive.write_failed`.
2. `archive_write_failed`: usually disk full on the cold root (chaos 3b) or QuestDB unreachable
   (chaos 10). Free space / restore the datastore; the next nightly run retries. Nothing was dropped.
3. `archive_verification_failed`: a quarantined file exists (below). The hot partition is intact.
4. A day that keeps failing pins the watermark below it for the whole stream by design; it never
   skips ahead over data that is still hot.
5. `rolloff_skipped_locked`: another instance holds the advisory lock; check for a hung run.
6. `system_event code=rolloff.drop_unconfirmed` (CRITICAL) with
   `recorder_rolloff_failures_total{reason="drop_not_applied_<reason>"}`: the DROP was issued but
   QuestDB never confirmed it within `apply_timeout_s`. Nothing was lost — the cold copy verified
   before the DROP, the day stays `retained` and the watermark did not move. `reason=suspended`:
   the WAL is suspended; inspect `wal_tables()` and run `ALTER TABLE <table> RESUME WAL;` after
   fixing the cause — the next nightly run re-issues the drop. `reason=timeout`: QuestDB is slow or
   unreachable; the next run retries. `reason=unexpected_shape`: `table_partitions()` returned rows
   without a `name` — a QuestDB version/driver change; stop and file an issue.

## Quarantined file

Location: `<CV_PARQUET_ROOT>/_quarantine/<stream>/symbol=<SYM>/dt=<DATE>/part-NNNN.parquet` with a
`part-NNNN.reason.json` sidecar (`row_count` | `checksum` | `sha256` | `missing_manifest`).
Quarantined files are removed from the manifest, so no DuckDB view or cold read can serve them.

1. Do **not** move it back. The hot partition still holds the data.
2. Inspect: `duckdb -c "SELECT count(*) FROM read_parquet('<file>')"` vs the hot `count()`.
3. Fix the cause (disk, schema drift — see `STORAGE_SCHEMA_DRIFT`), then let the next run re-export.
4. After a successful later run, the quarantined file may be deleted manually (audit the deletion).

## Manual compaction

`POST /api/v1/admin/recorder/compact` (`recording:write`, `Idempotency-Key` required) returns a
`job_id`; poll `GET /api/v1/admin/jobs/{jobId}` (`admin:read`). Partitions in use by a replay are
deferred (`compaction_deferred` in `result.deferred`) and the rest complete.
