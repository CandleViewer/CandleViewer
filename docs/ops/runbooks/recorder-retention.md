# Runbook — recorder retention (E16-T06)

Owner: recorder-replay. Code: `services/api/candleviewer/recorder/retention.py` (`RetentionManager`),
`storage/cold/retention_ops.py` (cold delete under the partition lock, QuestDB hot store, checkpoint),
`retention_wiring.py` (composition), `api/recorder_purge.py` (`POST /admin/recorder/purge`).

## How it works

Nightly pass (`run_nightly`). The manager is composed in `app.state.retention_manager` (real
backend only); like the roll-off, the nightly loop is not scheduled yet and will run behind
`retention_enabled` (default off, cron `CV_RETENTION_CRON`) once the scheduler wiring lands:

1. Takes the Postgres advisory lock `retention:recorder` (a second instance skips the pass).
2. If `<CV_PARQUET_ROOT>/_manifests/_retention/checkpoint-reaper.json` exists, **resumes that plan**;
   otherwise builds a fresh plan (`preview()`) and checkpoints it.
3. For each plan item, re-checks every guard against current facts, in this order: **pin** →
   hot window / total horizon → **active replay lease** → (hot only) **roll-off watermark**.
4. Writes `data.deleted` (write-ahead; `actor=system:retention`, exact range, rows, bytes,
   `deletion_id`), marks the item `pending` in the checkpoint, deletes, marks it `done`.
5. Writes `retention.run` at start and end (`phase=end` or `partial`).

Hot (QuestDB) DAY partitions are dropped only when every symbol in the day is past its hot window
and the watermark proves the day archived. Cold (Parquet) partition directories are deleted when
they are past the total horizon (`21-database-schema.md` §7 `cold_days`). Pinned symbols are never
touched by a policy run, including a policy with `applies_to_pinned`.

Provisional defaults (E16-K01, `docs/plan/notes/e16-storage-measurement.md` §5):
`CV_RECORDER_HOT_DAYS=7`, `CV_RECORDER_RETENTION_DAYS=30` (hard default when no policy row
exists). Re-validate both after the live 7-day re-measure.

## Stuck reaper (`retention_last_success_timestamp` older than 48 h)

1. Logs: `retention_skipped_locked` → another holder has `pg_try_advisory_lock` for
   `retention:recorder`. Find it with `SELECT pid, application_name FROM pg_locks JOIN
pg_stat_activity USING (pid) WHERE locktype = 'advisory'`. A crashed holder releases the lock when
   its connection dies; a hung one must be terminated (`pg_terminate_backend`) only after confirming
   no purge job is `running` (`GET /admin/jobs/{id}`).
2. `retention_delete_failed` (with `error=`): the item stays `pending` in the checkpoint; the next pass
   finishes it **without a second `data.deleted`**. `TimeoutError` usually means a long compaction or
   import held the partition lock — wait, it retries. `OSError` on the cold root: chaos 3b (disk
   full / read-only volume) — fix the volume first.
3. QuestDB unreachable (chaos 10): hot drops fail and stay `pending`; cold deletes continue.
4. `retention_yield_ingest_lag`: ingest lag stayed above 1 s for 5 min; the pass stopped early and
   resumes from the checkpoint next night. Not a fault.
5. `retention_checkpoint_corrupt`: the pass refuses to delete anything. Inspect the file. To start
   over, move it aside (do not edit it); the next pass re-plans from current facts. Items already
   deleted simply do not reappear in the new plan.
6. `retention.not_archived` (WARNING event): a hot day is past its window but the roll-off watermark
   has not reached it. Fix the roll-off first (`recorder-rolloff.md`); retention will never drop an
   unarchived day.

## Accidental over-broad policy

Retention is irreversible once a pass runs. Act before the next pass:

1. Set `CV_RETENTION_ENABLED=false` and restart, or let the running pass finish and stop the next
   one. A pass already running only deletes what its checkpointed plan listed.
2. Pin anything at risk (pinning wins over every policy and is re-checked right before each delete).
3. Fix the policy row in `retention_policies` (the REST policy API is E16-T08).
4. Preview the effect before re-enabling: `RetentionManager.preview(PruneScope(policies=...))`
   lists every partition that would go, with the GB and date range, plus what is protected and why.
5. To see what was already lost, query the audit log for `data.deleted` since the change (the
   records outlive the data). Any range listed there is gone from both tiers. Recovery is from
   backup only, or for `trades` by re-import (`POST /admin/recorder/import`, E16-T10).

## Owner purge (`POST /admin/recorder/purge`)

Needs `recording:write`, a `recorder` step-up, `reason` (3–280 chars), `confirm_symbol == symbol`,
and `include_pinned: true` for a pinned symbol. `retention.purge` (exact window, partition count,
rows, bytes, `plan_id`) is audited before the job exists; an audit outage answers 503 and starts
nothing. QuestDB days shared with other symbols are skipped (`shared_partition`); the nightly
roll-off/retention handles them. Poll `GET /admin/jobs/{job_id}`.
