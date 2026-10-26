# Runbook — recorder roll-off (E16-T05)

Owner: recorder-replay. Code: `services/api/candleviewer/recorder/rolloff.py` (`RollOffJob`),
`storage/cold/rolloff_ops.py` (export + read-back verify + drop), `storage/cold/watermarks.py`.

## How it works

Nightly, per stream, closed QuestDB days older than every present symbol's hot window
(`retention_policies.retain_days`; pinned = never) are exported via the existing cold exporter, then
re-read: row count **and** a canonical content SHA-256 must equal the hot source, and the manifest
SHA-256 must re-verify. Only when **every** symbol in that day verifies is the day audited
(`retention.purge`) and dropped. Days are processed oldest-first; each day's watermark advances
before its drop, and a failing day stops the stream (#2347). Watermarks live at
`<CV_PARQUET_ROOT>/_manifests/_watermarks/<stream>/symbol=<SYM>.json` and only move forward.

A day is its `yyyy-MM-dd` partition, or, for a `PARTITION BY HOUR` table (`orderbook_deltas`), its
`yyyy-MM-ddTHH` partitions: they are listed together and dropped in one statement (#3794). A table
holding partitions older than two days while roll-off lists no day for it fires
`RollOffStreamUnlisted` (ticket, `docs/plan/07-release-and-prr.md`). If that check's own query
fails, the run goes on with the next stream and counts
`recorder_rolloff_failures_total{reason="unlisted_check_failed"}`.

## Stuck watermark (`recorder_watermark_lag_days` > hot window + 2)

1. Check `recorder_rolloff_failures_total{reason}` and logs for `rolloff_archive_failed` /
   `system_event code=archive.verification_failed` or `archive.write_failed`.
2. `archive_write_failed`: usually disk full on the cold root (chaos 3b) or QuestDB unreachable
   (chaos 10). Free space / restore the datastore; the next nightly run retries. Nothing was dropped.
3. `archive_verification_failed`: a quarantined file exists (below). The hot partition is intact.
4. A day that keeps failing pins the watermark below it for the whole stream by design; it never
   skips ahead over data that is still hot.
5. `rolloff_skipped_locked`: another instance holds the advisory lock; check for a hung run.
6. `system_event code=rolloff.drop_unconfirmed` (WARNING for `timeout` and `missing`, CRITICAL
   otherwise) with `recorder_rolloff_failures_total{reason="drop_not_applied_<reason>"}`: the DROP
   was issued but QuestDB never confirmed it within `apply_timeout_s`, or, when the day's partition
   listing came back without names or without a live partition, it was never issued. Nothing was
   lost — the cold copy verified before the DROP and the watermark already covers the day, so it is
   in both tiers (read from Parquet) until the next run re-drops it. `reason=suspended`:
   the WAL is suspended; inspect `wal_tables()` and run `ALTER TABLE <table> RESUME WAL;` after
   fixing the cause — the next nightly run re-issues the drop. `reason=timeout`: QuestDB is slow or
   unreachable; the next run retries. `reason=unexpected_shape`: `table_partitions()` returned rows
   without a `name` — a QuestDB version/driver change; stop and file an issue. `reason=missing`
   (WARNING): the day had no live partition left when the drop came, so no DROP was issued; it
   left QuestDB another way after this run verified its archive (a concurrent drop or retention).
   Check `table_partitions()` and the retention log.
7. `rolloff_run_failed` with `error=StorageSchemaDrift` (`STORAGE_SCHEMA_DRIFT`,
   `recorder_rolloff_failures_total{reason="run_failed"}`): a hot table's columns differ from its
   dataset's registered set (`<CV_PARQUET_ROOT>/_manifests/schema-registry.json`) in a way the
   exporter does not accept. The run stops at the first export that drifts: that day is not
   dropped, and the streams after it wait for the next run, which fails the same way until the
   cause is fixed.
   A new nullable column listed in the exporter's `ALLOWED_ADDITIONS` is registered on its own
   (log `cold_export_schema_widened`, `21-database-schema.md` §5.2) and never stops a run; an
   unlisted, removed or retyped column fails closed. Do not edit the registry by hand: ship the
   column's migration with its `ALLOWED_ADDITIONS` entry (C-5.8), or revert the column change.

## Quarantined file

Location: `<CV_PARQUET_ROOT>/_quarantine/<stream>/symbol=<SYM>/dt=<DATE>/part-NNNN.parquet` with a
`part-NNNN.reason.json` sidecar (`row_count` | `checksum` | `sha256` | `missing_manifest`).
Quarantined files are removed from the manifest, so no DuckDB view or cold read can serve them.
Verify-on-read and the weekly scrub (`STORAGE_COLD_FILE_QUARANTINED`) quarantine the same way, with
no sidecar; a part they found missing leaves an empty directory.

While the partition's quarantine directory exists, the cold readers refuse that partition rather
than serve the parts that remain as all of it (#3477): `/market/klines` answers 503 for that month,
a replay over it fails typed (also when `auto` routing reads its coverage), and the cold repository
raises. The DuckDB analytics views (`storage/cold/duckdb_views.py`, not used by the app) glob the
partition's files and read neither the manifest nor the mark. The directory cannot tell a partition that is still missing a part from one a later run
re-exported in full, nor whether QuestDB still holds the day, so the reads refuse until an operator
deletes it (step 4). Retention deletes a partition with its manifest but never touches
`_quarantine/`: once the manifest is gone the partition no longer refuses, since nothing is left to
serve partly. Its quarantine directory stays until it is deleted, and refuses the partition again if
it is ever re-imported.

1. Do **not** move it back. After a roll-off quarantine the hot partition still holds the data.
2. Inspect: `duckdb -c "SELECT count(*) FROM read_parquet('<file>')"` vs the hot `count()`.
3. Fix the cause (disk, schema drift — see `STORAGE_SCHEMA_DRIFT`), then let the next run re-export.
4. After a later run has re-exported and verified the partition, delete the partition's whole
   quarantine directory (the part and its sidecar) and audit the deletion. That deletion is what
   restores the partition's reads.
5. If the hot tier no longer holds the day (a scrub or a read found the bad part after the day was
   dropped), no run can re-export it, and there is no restore procedure for a cold part yet: a part
   copied back without its manifest entry is deleted as an orphan by the next export. Leave the
   directory in place, so the partition stays refused rather than served partly. Deleting it
   without a restore serves the partition without that part, as if it were complete.

## Manual compaction

`POST /api/v1/admin/recorder/compact` (`recording:write`, `Idempotency-Key` required) returns a
`job_id`; poll `GET /api/v1/admin/jobs/{jobId}` (`admin:read`). Partitions in use by a replay are
deferred (`compaction_deferred` in `result.deferred`) and the rest complete.
