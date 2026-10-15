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
   hot window / total horizon → **active replay lease** → (hot only) **roll-off watermark** →
   (hot only) **archive rows**: each symbol's rows on the day, counted now, must equal its
   verified cold-manifest rows. A mismatch (late or backfilled rows, a new symbol, no manifest,
   nothing read back) keeps the day and raises CRITICAL `archive.verification_failed`.
   Planning applies the same guards. A day held while planning is listed in the pass report
   and raises the same alert (`retention.not_archived` or `archive.verification_failed`).
4. Writes `data.deleted` (write-ahead; `actor=system:retention`, exact range, rows, bytes,
   `deletion_id`), marks the item `pending` in the checkpoint, deletes, marks it `done`.
5. Writes `retention.run` at start and end (`phase=end` or `partial`).

Hot (QuestDB) DAY partitions are dropped only when every symbol in the day is past its hot window,
the watermark proves the day archived, and every symbol's rows still equal its verified archive.
Cold (Parquet) partition directories are deleted when they are past the total horizon
(`21-database-schema.md` §7). `bars` partitions use their family's §7 row (the key carries
`family=`): `family=time` (`bars_time`) is kept forever, `tick/volume/range/renko/delta` go at
24 months, and any other or missing family is kept forever. Pinned symbols are never touched by
a policy run, including a policy with `applies_to_pinned`.

Provisional defaults (E16-K01, `docs/plan/notes/e16-storage-measurement.md` §5):
`CV_RECORDER_HOT_DAYS=7`, `CV_RECORDER_RETENTION_DAYS=30`. With no policy row a stream uses its
§7 default (`recorder/retention_defaults.py`). These hard defaults apply only to a known stream
that §7 does not list (none today); an unknown stream is kept forever. Re-validate both after
the live 7-day re-measure.

## Stuck reaper (`retention_last_success_timestamp` older than 48 h)

1. Logs: `retention_skipped_locked` → another holder has `pg_try_advisory_lock` for
   `retention:recorder`. Find it with `SELECT pid, application_name FROM pg_locks JOIN
pg_stat_activity USING (pid) WHERE locktype = 'advisory'`. A crashed holder releases the lock when
   its connection dies; a hung one must be terminated (`pg_terminate_backend`) only after confirming
   no purge job is `running` (`GET /admin/jobs/{id}`).
2. `retention_delete_failed` (with `error=`): the item stays `pending` in the checkpoint; the next pass
   finishes it **without a second `data.deleted`**. `TimeoutError` usually means a long compaction or
   import held the partition lock — wait, it retries. `OSError` on the cold root: chaos 3b (disk
   full / read-only volume) — fix the volume first. A hot DROP whose QuestDB apply outlived the
   bounded wait (`TimeoutError`, or a typed storage error) also stays `pending`. If QuestDB applies
   it later, the next pass finds the day gone and closes the trail with `phase=done`,
   `applied=earlier`.
3. QuestDB unreachable (chaos 10): hot drops fail and stay `pending`; cold deletes continue.
4. `retention_yield_ingest_lag`: ingest lag stayed above 1 s for 5 min; the pass stopped early and
   resumes from the checkpoint next night. Not a fault.
5. `retention_checkpoint_corrupt`: the pass refuses to delete anything. Inspect the file. To start
   over, move it aside (do not edit it); the next pass re-plans from current facts. Items already
   deleted simply do not reappear in the new plan.
6. `retention.not_archived` (WARNING event): a hot day is past its window but the roll-off watermark
   has not reached it. Fix the roll-off first (`recorder-rolloff.md`); retention will never drop an
   unarchived day.
7. `archive.verification_failed` (CRITICAL event, `retention_skipped reason=archive_mismatch`): a hot
   day's rows no longer match its verified archive. Typical causes are late or backfilled rows that
   landed after the roll-off exported the day, a new symbol in the day, or a missing manifest. The
   day is kept and the alert repeats on every pass until the counts match. Nothing has been lost:
   the extra rows are still hot. Compare the hot `count()` per symbol for the day with the
   manifest row counts (`_manifests/<stream>/symbol=<SYM>/dt=<DATE>.json`) and find where the rows
   came from. Never drop the partition by hand.

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

**Owner-only** (capability 9a, `04-security-program.md` §13): a manager is refused 403
(`purge_owner_only`, audited) even though managers hold `recording:write`, and the refusal
comes before any step-up prompt. The owner also needs a `recorder` step-up, `reason` (3–280
chars), `confirm_symbol == symbol`, and `include_pinned: true` for a pinned symbol.
`retention.purge` (exact window, partition count, rows, bytes, `plan_id`) is audited before the
job exists; an audit outage answers 503 and starts nothing. QuestDB days shared with other
symbols are skipped (`shared_partition`); the nightly roll-off/retention handles them. Right
before each hot drop the job re-reads which symbols are in the day. If another symbol's rows
arrived after the plan, the day is skipped: `shared_partition`, or `pinned` when that symbol is
pinned, because `include_pinned` covers only the purged symbol. The job result and the closing
`retention.purge` record list every skipped partition with its reason. Poll
`GET /admin/jobs/{job_id}`.
