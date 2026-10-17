# Ingestion runbook (E08-T06)

Operator runbook for the Ingestion alert set in `infra/prometheus/alerts/ingestion.yml` and the
Grafana board **CV / Ingestion** (`infra/grafana/dashboards/ingestion.json`, uid `cv-ingestion`).
Every alert below has exactly one entry here, and every entry names a real alert:
`infra/alertmanager/tests/test_ingestion_alerts.py` fails the build otherwise. Clock-drift alerts
(`BybitClockDriftWarning`, `BybitClockDriftCritical`, `BybitClockOffsetStale`) are owned by E08-S07
and documented in `docs/plan/07-release-and-prr.md`; they are summarised in the last section so this
page covers every ingestion signal.

Each entry: what it means, then the first three actions, in order. Alert text is written as complete
sentences that can be read aloud; dashboard states are always a number or word as well as a colour.

Metric names and labels are owned by `services/api/candleviewer/ingestion/metrics.py` (declaration-first
registry). Every series carries `env` and `exchange` labels; symbols are bounded to the configured set
(anything else is reported as `symbol="other"`).

<a id="alert-ingestiontopicstale"></a>

## IngestionTopicStale

**Meaning.** `ws_topic_staleness_seconds` for a topic exceeded 10 s for 1 minute: no message arrived on
that upstream topic, so the UI shows the "stale data" badge for the symbol. Severity: Ticket.

1. Open **CV / Ingestion** and check _Public socket up_. If it reads 0, follow
   [IngestionStoppedReporting](#alert-ingestionstoppedreporting) instead — every topic is stale.
2. If only one topic is stale, check the exchange status page for that symbol (halt / delisting) and
   the instrument catalogue (`GET /v1/instruments`) for a non-`trading` status.
3. If the symbol is trading, force a resubscribe by removing and re-adding it from a chart; if it stays
   stale, capture a support bundle and open a defect with the topic name and time window.

<a id="alert-ingestionbookresyncratehigh"></a>

## IngestionBookResyncRateHigh

**Meaning.** More than five book resyncs in five minutes for one symbol
(`ingest_book_resyncs_total`). The book is unavailable to consumers during each resync, and the B14
breaker marks it degraded at more than 5 per 60 s. Severity: Ticket.

1. Read the `reason` label on _Book resyncs/min_. `sequence_gap` or `frame_loss` point upstream or at
   local backpressure; `bad_snapshot` / `bad_replay` point at payload corruption.
2. For `frame_loss`, check _Never-drop queue full events/s_ and host CPU: the frame buffer is
   overflowing. Reduce subscribed symbols or depth tier until it clears.
3. For `sequence_gap` with a healthy host, check exchange status; if it persists for 30 minutes,
   drop the symbol to depth 50 and file a defect with the reason counts.

<a id="alert-bookresyncstorm"></a>

## BookResyncStorm

**Meaning.** More than five `rejected_frame` / `backoff` book resyncs in five minutes for one symbol,
sustained for 5 minutes (`ingest_book_resyncs_total{reason}`). Each rejected book frame invalidates the
book; the per-symbol backoff (250 ms doubling to 30 s, with jitter, reset after 5 s of stable LIVE) bounds
snapshot requests, and `reason="backoff"` counts requests held back while the symbol stays stale (no
book served). Deferred/back-off requests also count, so a storm inflates its own signal; that is
acceptable for paging. Severity: Page.

1. Check `ingest_rejected_total{stream="book"}` for the `reason`: `off_tick` after an instrument refresh
   means a tick-size change; `non_finite` / `out_of_bounds` / `crossed` point at a corrupt feed.
2. If the venue is healthy and one symbol is affected, release its demand until the cause is
   understood; the backoff keeps other symbols unaffected.
3. File a defect with the reason counts and a redacted frame sample from the recorder.

<a id="alert-ingestionframesrejectedsustained"></a>

## IngestionFramesRejectedSustained

**Meaning.** One stream has rejected more than one frame every 10 seconds, sustained for 10 minutes
(`ingest_rejected_total{stream, reason}`). Rejected frames are never published: book frames trigger a
resync (`ingest_book_resyncs_total{reason="rejected_frame"}`) and trade frames open a tape gap that
backfill heals. Reasons: `off_tick` (price not on the tick grid), `crossed` (bid above ask),
`ts_future` / `ts_past` (event time outside the clock or listing window), `out_of_bounds`,
`non_positive`, `non_finite`, `depth_limit` (frame nested deeper than 32), `malformed`, and
`internal_error` (an unexpected exception the frame pump caught). Severity: Ticket.

1. Read the `stream` and `reason` labels. `off_tick` right after an instrument refresh usually means
   the venue changed the tick size: check `GET /v1/instruments` for a new `tick_size` on the symbol.
2. `ts_future` on every stream at once points at the local clock: check the clock-drift alerts and
   host NTP before you suspect the feed.
3. `internal_error` or `depth_limit` from `stream="pump"` means hostile or corrupt frames are arriving.
   Capture a support bundle (logs carry the reason and error class, never the payload) and open a
   security defect with the time window. If `pump_breaker` resyncs repeat, recycle the socket.

<a id="alert-ingestiontradegapunrecovered"></a>

## IngestionTradeGapUnrecovered

**Meaning.** A trade tape gap (after a reconnect or frame loss) could not be filled by the REST
recent-trades backfill (`trade_gaps_total{recovered="false"}`). Trades in that window are missing from
the tape and the recording. Severity: Page. No `[RESOLVED]` message follows: the alert clears 15
minutes after the last unrecovered gap because the window moved on, not because the trades were
filled in, so a resolved page would read as recovered (`resolves: window`, the `page_event`
receiver). Work through the steps below whether or not the alert has cleared.

1. Note the symbol and the alert start time; the gap window is published on `{env}.md.{symbol}.gap`
   and appears in the tape as a gap marker.
2. Check `trade_backfill_rows_total{result="error"|"unavailable"}` and
   [IngestionRateLimitHeadroomExhausted](#alert-ingestionratelimitheadroomexhausted): a rate-limited
   backfill is the usual cause.
3. Mark the window as incomplete in the journal for any analysis that relies on footprint or CVD for
   that period, and open a defect if gaps recur within the hour.

<a id="alert-ingestionratelimitheadroomexhausted"></a>

## IngestionRateLimitHeadroomExhausted

**Meaning.** The last observed remaining request budget (`bybit_rate_limit_remaining`, labelled by
`scope` public|account and `endpoint_class`, never a UID) is at or below one for a minute. Further
requests in that class will be rate limited; the reserve for stop/cancel/SL paths is separate (C-12.7).
Severity: Ticket.

1. Identify the endpoint class on _Rate-limit headroom_ and the busiest endpoint on _REST p95 by
   endpoint_.
2. Stop any manual backfill or kline range load in progress; they share the public budget.
3. If the class is `account`, check for a runaway rule or client retry loop before resuming;
   persistent exhaustion needs a defect with the endpoint counts.

<a id="alert-ingestionneverdropqueuefull"></a>

## IngestionNeverDropQueueFull

**Meaning.** A NEVER_DROP bus queue (trades, executions) was observed full repeatedly over five minutes
(`ingest_queue_full_total{class}`). Nothing is lost — the publisher awaits — but the socket reader is
back-pressured, so ingest lag rises and Bybit may disconnect a slow reader. Severity: Ticket.

1. Check _Subscriber queue depth_ to find the slow subscriber, and _Ingest lag by stream_.
2. Check host CPU and event-loop lag (`event_loop_lag_seconds` on CV / System health).
3. If one subscriber is stuck, restart the API in a quiet period; if load is the cause, reduce
   recorded symbols (supported operation, RSK-011 contingency).

<a id="alert-ingestionstoppedreporting"></a>

## IngestionStoppedReporting

**Meaning.** Silent-death detector (R6 Feed rot): `ingest_enabled` is 1 but no market events were
counted for five minutes. Every chart is frozen. Severity: Page.

1. Check _Public socket up_ and the API logs for `ws_conn` transitions; a socket stuck in `degraded`
   or `connecting` points at network or exchange availability.
2. Confirm the host clock and DNS work (`BybitClockOffsetStale` usually fires alongside a network
   outage).
3. Restart the API process; if events do not resume within two minutes, escalate per
   `docs/plan/07-release-and-prr.md` incident flow with the last 15 minutes of logs.

<a id="alert-ingestionmetricsabsent"></a>

## IngestionMetricsAbsent

**Meaning.** Prometheus has had no `ingest_enabled` series for 15 minutes: the API is down, not
scraped, or running without the ingestion registry exported. Severity: Ticket.

1. Check the `candleviewer-api` target on the Prometheus _Targets_ page.
2. If the target is up, confirm `CV_INGESTION_WS_ENABLED` is set for this environment (the flag is off
   by default; the alert is expected to fire where ingestion is intentionally disabled — silence it
   there).
3. If the target is down, follow the API-down section of `docs/plan/07-release-and-prr.md`.

## Clock drift (owned by E08-S07)

`BybitClockDriftWarning` (|drift| > 500 ms), `BybitClockDriftCritical` (> 2000 ms, blocks order entry)
and `BybitClockOffsetStale` (no measurement for 15 min) are defined in
`infra/prometheus/alerts/clock_sync.yml` with runbooks in `docs/plan/07-release-and-prr.md`; the
_Clock drift (ms)_ stat on CV / Ingestion shows the live value.
