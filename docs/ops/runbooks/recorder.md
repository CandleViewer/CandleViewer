# Runbook — recorder alerts (E16-T09)

Alerts: `infra/prometheus/alerts/recorder.yml`; board **CV / Recorder**. Roll-off and retention
details stay in [recorder-rolloff.md](recorder-rolloff.md) and [recorder-retention.md](recorder-retention.md).
Always: **never delete `recording_gaps` rows**, and **never clear or move the recorder WAL without
recording a gap**.

<a id="alert-recordersilentstop"></a>

## RecorderSilentStop

**Symptom.** A symbol that wrote in the last 6 hours has written nothing for 60 s while ingest
events still arrive in the environment (any symbol, last 30 s). Severity: Page. A venue-wide outage
fires `IngestionStoppedReporting` once instead (`docs/ops/ingestion.md`).

**Limitation.** No per-symbol recording-state or last-write gauge is exported, so "recording" means
"wrote in the last 6 hours". The page keeps firing for a dead writer, but a deliberate stop or unpin
also pages for up to 6 hours: silence it by `symbol` when you stop recording on purpose.

1. On _Recorder write rate by symbol_, confirm the named symbol is flat and others write. If all are
   flat, treat it as a writer stall.
2. On **CV / Ingestion** _Events/s per stream and symbol_: no events for the symbol means it is
   quiet or halted upstream, not a recorder fault.
3. Check `GET /api/v1/recording/status` for the symbol and the logs for writer errors. A deliberate stop or unpin in the last 6 hours explains the page; silence it.

**Remediation.** Stop and start recording for the symbol; if every lane stalled, restart the API
(the WAL replays on startup). Record when the page fired and when writes resumed.

**Do not** delete the gap the stall leaves or backfill it into QuestDB by hand.

<a id="alert-recordermessagesdropped"></a>

## RecorderMessagesDropped

**Symptom.** Rows were evicted from a market-data write-behind queue in the last 5 minutes and never
reach the hot store. Severity: Page. It resolves 5 minutes after the last drop, fixed or not.

1. Read `reason` on _Dropped rows/s_: `outage` = QuestDB refused writes, `queue_full` = the writer
   fell behind.
2. Check _Write backlog_ and, on **CV / Storage**, _QuestDB write p95_: slow writes point at QuestDB
   (chaos 10), a flat backlog at a burst larger than the queue.
3. Check _Disk used_: at 95 % the write gate drops symbols without an open position by design.

**Remediation.** Restore QuestDB or free disk. Confirm a `recording_gaps` row covers the window.

**Do not** raise the queue bound to silence the page without a capacity review.

<a id="alert-recorderspilling"></a>

## RecorderSpilling

**Symptom.** `recorder_spill_bytes` above 0 for 5 minutes: the recorder writes to its on-disk WAL
because its queue is full or QuestDB failed. Past the WAL bound (1 GiB) rows become
`backpressure_drop` gaps. Severity: Ticket.

1. On _Spill bytes (WAL)_: rising = the sink still fails, falling = the WAL is replaying.
2. Check QuestDB health and _Write backlog_.
3. Check _Disk used_: the WAL shares the recording volume.

**Remediation.** Restore QuestDB; the writer replays the WAL and the alert clears at 0.

**Do not** delete WAL files to reclaim space; stop recording first so the writer records the gap.

<a id="alert-recordergapburst"></a>

## RecorderGapBurst

**Symptom.** More than five tape gaps opened for one symbol in an hour (`trade_gaps_total`).
Severity: Ticket. Unrecovered gaps also page via `IngestionTradeGapUnrecovered`.

1. On _Gaps per interval by symbol_: one symbol points at its feed, many at the connection.
2. Check **CV / Ingestion** for book resyncs and rejected frames on the symbol.
3. Check _Disk used_ and _Spill bytes (WAL)_: gate and WAL drops also open gaps.

**Remediation.** Fix the upstream cause; backfill recovers what it can. Note the window in the incident.

**Do not** delete gap rows to make coverage look whole.

<a id="alert-rolloffwatermarklag"></a>

## RollOffWatermarkLag

**Symptom.** A stream's `recorder_watermark_lag_days` exceeds its hot window + 2 days
(`orderbook_delta` 9, `trades` and `tickers` 32, `liquidations` 92). Hot data is not archived, so
retention cannot free space. Severity: Ticket.

1. Check `recorder_rolloff_failures_total` by `reason` and the last nightly run's logs.
2. Check for a quarantined file or a held advisory lock.
3. Check _Disk used_ and _Projected full date (UTC)_.

**Remediation.** Follow
[Stuck watermark](recorder-rolloff.md#stuck-watermark-recorder_watermark_lag_days--hot-window--2)
and [Quarantined file](recorder-rolloff.md#quarantined-file).

**Do not** drop hot partitions by hand; a day is dropped only after its archive verifies.

<a id="alert-recorderdiskbudgetsamplestale"></a>

## RecorderDiskBudgetSampleStale

**Symptom.** `recorder_disk_budget_last_sample_timestamp_seconds` is more than 300 seconds old: disk-budget
sampling is stale or failing. Severity: Ticket. Tracker: #4581.
The write gate also fails closed on its own three sample intervals (180 s by default) after the
last completed pass, so a healthy disk can read level 3 and page until sampling resumes.

1. Read `recorder_disk_budget_last_sample_timestamp_seconds` and confirm it has stopped advancing.
2. Read `recorder_disk_pressure_level`: while sampling is stale it may not reflect the volume.
3. Check _Disk used_ and the API logs for disk-budget errors. `disk_budget_sample_failed_total`
   counts each failed pass: it rises while passes fail and stays flat while none ends.

**Remediation.** Restore disk-budget sampling (restart the API if it does not resume) and confirm
the timestamp advances again. Follow #4581.
The gate re-opens after two completed passes in a row.

**Do not** silence this alert while sampling is stale; the disk alerts depend on it.

<a id="alert-recorderdiskpressureautostop"></a>

## RecorderDiskPressureAutostop

**Symptom.** `recorder_disk_pressure_level` is 2 or higher (autostop or halt). Severity: Page.
Tracker: #4581.

1. Read `recorder_disk_pressure_level`: 2 = autostop, 3 = halt (`RecorderWriteGateClosed` also fires).
2. Check _Disk used_ and _Projected full date (UTC)_.
3. Check `RecorderDiskBudgetSampleStale`: a stale sample means the level may be out of date.

**Remediation.** Free space on the recording volume through the retention and roll-off paths, then
confirm the level falls. Follow #4581.

**Do not** delete recorded files, gap rows or the WAL by hand to clear the page.

<a id="alert-recorderwritegateclosed"></a>

## RecorderWriteGateClosed

**Symptom.** `recorder_disk_pressure_level` is 3: the write gate is closed (a recording volume
refused at boot, a halt, or a stale disk-budget sample). Severity: Page. Tracker: #567.
A stale sample closes the gate even on a healthy disk: see `RecorderDiskBudgetSampleStale`.

1. Read `recorder_disk_pressure_level` and confirm it is 3.
2. Check the API startup logs for a refused recording volume.
3. Check _Disk used_ and _Projected full date (UTC)_.

**Remediation.** Fix the recording volume or free space on it, then confirm the level falls below 3. Follow #567.

**Do not** bypass the write gate or delete recorded data by hand to reopen it.

## Related signals

Disk: `DiskHigh` (80 %, `CV_DISK_WARN_PCT`) and `DiskCritical` (95 %, `CV_DISK_HALT_PCT`) in
`docs/plan/07-release-and-prr.md`. Retention: no alert yet. The reaper sets
`retention_last_success_timestamp`, but the series is not in the metrics catalogue, so no rule or
panel may read it; until then follow [Stuck reaper](recorder-retention.md#stuck-reaper-retention_last_success_timestamp-older-than-48-h).
