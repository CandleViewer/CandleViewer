# E04-C1 Charter: lie detector (health reporting)

- Ticket: E04-Q02 (#257) · Format: session-based test management · Date: 2026-10-31
- Plan: `docs/qa/test-plans/e04-observability-charters.md` (base, rulings, regression pack, blind-spot report, sign-off draft).
- Tester: AI agent. **Deviation (honest scope):** an agent ran the static and in-process work. It is not a human session. There was no running stack, no docker, no browser and no Grafana. Every live technique is **not attempted — blocked on the PRR staging re-run** (BQ-01, pending ruling). Nothing here was observed on a running system.
- No credentials used. No network: the suites and probes ran in-process against fakes and a fake clock (C-13.5).

## Charter

Explore the system's health reporting with the goal of making it report healthy while something is genuinely broken.

Time box: 4 h (the ticket's). Actual: see "Session metrics". The time box is recorded as the ticket's, not claimed (BQ-15, pending ruling).

## Oracles (defined before probing)

- O1 A component that is broken but reads `healthy` in the health matrix, `/admin/health` or `/readyz`.
- O2 A cached state that is stale with no visible sign (`last_good_at`, `server_time` or a detail).
- O3 A failure mode with no metric or alert that names it.

## What the code does (the cache under test)

- The probe ticker defaults to 1.0 s (`services/api/candleviewer/observability/health_probes.py`:278). The lifespan starts it (`services/api/candleviewer/main.py`:225).
- Each probe runs under `min(probe.timeout, deadline)` (`health_probes.py`:220). The registry deadline defaults to 1.5 s (:194). `CallableProbe`'s own default is 2.0 s (:102), but the real probes register 1.5 s or 1.0 s (`services/api/candleviewer/health_wiring.py`:346, :379, :395).
- So the ticket's "2 s probe cache" is a 1.0 s ticker plus a probe limit of at most 1.5 s. The worst-case stale window is about 2.5 s (BQ-04, pending ruling).
- `last_good_at` advances on `healthy` and on `not_deployed` (`health_probes.py`:228–229) and is kept after a failure (:238).
- `/admin/health` serves the cached snapshot and never runs a probe (`services/api/candleviewer/admin/ops/health.py`:51–58). Its `server_time` is the snapshot's `taken_at` (`services/api/candleviewer/api/health_report.py`:56).
- `not_deployed` ranks as `healthy` for `overall` (`health_probes.py`:28–29, :43–44).

## Techniques

| Technique (ticket)                                        | Attempted                                                   | Outcome                                                                                                                                                                                                                                           | Evidence                                                                                                                                                                                         |
| --------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Stop a component after its probe has cached a good result | in-process                                                  | The cache reads `healthy` until the next tick, then `down` with `last_good_at` kept. Bounded by one tick plus the probe limit. O1 and O2 ok within the window.                                                                                    | probe `p1`; `services/api/tests/unit/observability/test_health_probes.py`:80 `test_last_good_at_kept_after_failure`; `services/api/tests/qa/test_e04_q01_blackbox.py`:43 `h01`                   |
| (same, a hung dependency)                                 | in-process                                                  | A hanging probe reads `degraded` "probe timeout" at the deadline, never `healthy`.                                                                                                                                                                | probe `p4`; `test_e04_q01_blackbox.py`:62 `h03`                                                                                                                                                  |
| (same, the ticker itself dies)                            | in-process                                                  | **F1.** The ticker loop has no guard. One exception ends it, and the last snapshot is served as `healthy` from then on.                                                                                                                           | probe `p2`; `health_probes.py`:288–291                                                                                                                                                           |
| (same, a module stopped at run time)                      | in-process                                                  | **O-1.** A stopped module reads `not_deployed`, ranks as `healthy` and its `last_good_at` keeps advancing.                                                                                                                                        | probe `p3`; `health_wiring.py`:384–385                                                                                                                                                           |
| Saturate a queue without crossing a threshold             | static                                                      | **O-2.** Eleven queue and lag gauges are read by no alert, so there is no threshold to cross. Only "queue full" events alert.                                                                                                                     | see "Queue gauges" below                                                                                                                                                                         |
| Desync a topic while its connection stays up              | not attempted — blocked on a running stack (BQ-01)          | Static: the REST book `stale` flag was fixed by #3834; the WS half stays open in #2487.                                                                                                                                                           | `docs/qa/charters/E08-charter-4-staleness-honesty.md` (finding F4)                                                                                                                               |
| Fill disk to 79 %                                         | static; the live fill is blocked on a running stack (BQ-01) | At 79 % the disk probe reads `healthy` with detail "used 79%". Honest, since no threshold is crossed. **O-3:** `DiskHigh` and `DiskCritical` read the recorder's budget ratio, not the filesystem.                                                | `health_wiring.py`:82–83, :327–337; `infra/prometheus/alerts/system_ticket.yml`:45–53; `infra/prometheus/alerts/system_page.yml`:59–67; `services/api/candleviewer/recorder/budget.py`:490, :590 |
| Stall a writer without erroring                           | static                                                      | **O-4.** The hot-tier write-behind is `degraded` only after a failure (`ingestion/write_behind.py`:86–87). A writer that hangs without raising reads `healthy` until rows are evicted. The eviction then pages through `RecorderMessagesDropped`. | `health_wiring.py`:359–370; `infra/prometheus/alerts/recorder.yml`:26–30                                                                                                                         |

The 1 Hz UI poll the ticket names does not exist for health. No UI renders `last_good_at` today (no match in `apps/web/src` or `packages/ui/src`). The `/admin/health` route is R-350, owned by E18 (`apps/web/src/routes/manifest.ts`:112). So staleness is visible only in the API body (BS-17 in the plan).

### Queue gauges with no alert

`ingest_queue_depth`, `bars_write_queue_depth`, `cv_machine_deferred_depth`, `cv_alert_eval_queue_depth`, `cv_ws_client_topics_depth`, `cv_ws_queue_bytes`, `cv_ws_queue_frames`, `oms_stream_event_lag_seconds`, `recorder_write_backlog_rows`, `replay_readahead_depth` and `cv_audit_lane_depth` are in the metric catalogue. No alert expression reads any of them (a scan with `services/api/tests/_alert_rules.py`). Five appear on a dashboard. Queues are bounded (C-2.18), and the never-drop ingestion queue alerts when full (`infra/prometheus/alerts/ingestion.yml`:98).

## Session metrics

- Time: about 12 minutes of agent tool time, 05:28–05:40 UTC, shared with charters 2 and 3. Times are from the agent's tool log. Not a 4 h human session.
- Suites re-run at 05:34 (one run for all three charters): `test_e04_q01_blackbox.py`, `test_health_probes.py` and eight other observability and abuse-case files. 738 passed, 5 deselected, 18.4 s.
- Probes: `p1` to `p4`, one scratch script outside the repo, run at 05:35. Not committed. Promoting `p2` and `p3` to tests is a follow-up.
- Environment: a laptop with no measured profile. No E04-K01 or E04-T06 measurement was running (BQ-14, pending ruling).

## Findings

**F1 — a dead probe ticker freezes the health matrix at its last state (AC1 case; proposed P1; filing waits for the coordinator's go).**
`HealthRegistry._loop` calls `refresh()` with no exception guard (`health_probes.py`:288–291). Inside `refresh()`, the state observer runs unguarded (:259–260). Probe `p2` made the observer raise once: the task ended with `RuntimeError`, the snapshot stopped changing, and `overall` stayed `healthy` an hour later on the fake clock. `/admin/health` keeps serving it (`admin/ops/health.py`:51–58). The only tell is an old `server_time`. No alert reads `health_component_state` or `health_probe_duration_seconds`, so the stop is silent. Likelihood is low: the observers set gauges. The impact is the AC1 case, "reported healthy while broken". Routed to E04 (E04-T04 code). Raised as NQ-1 in the plan.

## Observations (routed rows; no issue filed under the freeze)

- **O-1:** a module stopped at run time reads as never built (probe `p3`). Whether any path stops a module without a process exit is not traced. Routed to E04 with a trace first.
- **O-2:** queue depth below "full" has no alert. Proposed for owner acceptance (BS-07).
- **O-3:** the disk alerts measure recorded bytes against `CV_DISK_CAP_GB` (catalogue help text, `services/api/candleviewer/observability/metrics_catalogue.py`:3963–3972). Their summary says "Disk usage above 80 percent". No metric names the Postgres or QuestDB data volume. The health disk probe watches only the Parquet root (`services/api/candleviewer/app.py`:1715). Routed to E07 (BS-08).
- **O-4:** a stalled writer that raises nothing reads healthy until eviction. The storage client's own timeout is not traced. Routed to E08 (BS-06).

## Not attempted (blocked on a running stack or a human)

- Every live leg: stop a real Postgres or QuestDB after a good probe, desync a real topic, fill a real volume to 79 %, stall a real writer. Owner: the PRR staging re-run (BQ-01).
- The Grafana "System health" panels under those faults. The dashboard JSON was read statically only.

## Follow-ups

1. F1: one regression test that kills the ticker and asserts the stop is visible. It belongs with the fix, in E04.
2. O-1: trace whether a module can stop at run time without a process exit. Then decide on a `stopped` state distinct from `not_deployed`.
3. Run the blocked live legs at the PRR staging re-run, with this table as the script.
