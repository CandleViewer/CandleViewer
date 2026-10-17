# E04-Q01 — Black-box test plan: observability baseline

Owner: QA (agent-delivered; reviewer = epic owner). Scope: US-OBS-001..005, US-OBS-007
(`docs/plan/11-user-stories.md` §28). Out of scope: US-OBS-006 chaos (E45), exploratory (E04-Q02).
Principle: observability defects are invisible by construction, so every case proves a signal
**fires**, never that the system merely "looks healthy". Canary secrets are prefixed
`CANARY-SECRET-` so a leaked fixture is harmless and greppable.

Execution status key: **Auto** = runs in CI today; **Staging** = needs the compose stack
(docker/Prometheus/Alertmanager); not executable on the authoring workstation (no docker) and
recorded as *pending staging run* in `qa/plans/e04-alert-drill-matrix.md`.

## Cases

| Case | Preconditions | Steps | Expected (stated in advance) | Verifies | Execution |
|---|---|---|---|---|---|
| E04-TC-M01 | stack up, `ingest` fixture `bybit/recorded-10min` | scrape `/metrics` | ingest rate/lag, WS state, book resyncs, order latency, rule eval, rate-limit budget, recorder write rate, DB size, error counts present | US-OBS-001 / E04-T01 | Staging |
| E04-TC-M02 | as M01 | inspect all label sets | only symbol/account/env/stage labels; no secret/PII; series count <= declared cardinality | US-OBS-001 / E04-T01 | Staging |
| E04-TC-M03 | Prometheus stopped 10 min | restart; read logs | fallback snapshot log entries cover the window | US-OBS-001 / E04-T01, E04-S01 | Staging |
| E04-TC-M04 | k6 | `tests/perf/obs/metrics_scrape.k6.js` at full cardinality | scrape p95 < 50 ms | US-OBS-001 / E04-T01 | Staging |
| E04-TC-L01 | stage telemetry | send ticks with end-to-end timestamps | per-stage percentiles exported | US-OBS-002 / E04-T02 | Staging |
| E04-TC-L02 | synthetic p95 > 250 ms for 60 s | inject series | `LatencyBudgetBreach` fires naming stage | US-OBS-002 / E04-T05 | Auto (promtool) + Staging |
| E04-TC-L03 | UI session | open latency indicator | compact current figure shown | US-OBS-002 / E04-T06 | Staging |
| E04-TC-G01 | canary fixture, DEBUG | push canaries through app, stdlib, third-party, traceback paths | zero canaries in captured output (hit = p0 bug) | US-OBS-003 / E04-T03 | CI (automated: test_g01 in services/api/tests/qa/test_e04_q01_blackbox.py) + Staging |
| E04-TC-G02 | one order request | follow correlation id | same id on API, OMS, adapter, WS lines | US-OBS-003 / E04-T03 | Staging |
| E04-TC-G03 | runtime override | raise one subsystem, wait timeout | only that subsystem verbose; reverts automatically | US-OBS-003 / E04-T03 | Staging |
| E04-TC-A01 | Page and Ticket rules | fire each per drill matrix | notification received <= 60 s, runbook walked | US-OBS-004 / E04-T05 | Staging |
| E04-TC-A02 | near-miss series | inject threshold-epsilon and duration-epsilon | rule does not fire | US-OBS-004 / E04-T05 | Auto (promtool) |
| E04-TC-A03 | grouped repeats | fire same alert repeatedly | grouped with occurrence count | US-OBS-004 / E04-T05 | Auto (alertmanager tests) |
| E04-TC-A04 | page severity at quiet hours | fire Page | delivered via all channels, bypassing mute | US-OBS-004 / E04-T05 | Auto (alertmanager tests) |
| E04-TC-R01 | rate-limit fixture | read budget panel | remaining budget per class/account shown | US-OBS-005 / E04-S01 | Staging |
| E04-TC-R02 | induced 10006 | observe logs/metric | exact error logged, backoff, `OmsRateRejects` fires | US-OBS-005 / E04-T05 | Staging |
| E04-TC-D01 | six dashboards, synthetic load | open every panel | data shown or annotated "awaits module X"; no silent-empty | US-OBS-001 / E04-S01 | Staging (lint: Auto) |
| E04-TC-H01..H06 | health fixtures | see `test_e04_q01_blackbox.py` (H05, admin RBAC, is now `tests/contract/test_admin_ops_routes_contract.py::test_rbac_cell`, E42-T05) | live/ready/admin behave per E04-T04; slow probe isolated | US-OBS-001 / E04-T04 | Auto |
| E04-TC-T01..T05 | telemetry fixtures | see `test_e04_q01_blackbox.py` | 401/400/429 rejections, counted, no cardinality mint | US-OBS-002 / E04-T06 | Auto |
| E04-TC-T06 | k6 | `tests/perf/obs/telemetry.k6.js` | 204s at expected session load, 429 above limit | US-OBS-002 / E04-T06 | Staging |
| E04-TC-B01 | window | generate bundle | logs, metric snapshot, config sans secrets, health, errors | US-OBS-007 / E04-S02 | Staging |
| E04-TC-B02 | canary in log | generate bundle | fails loudly; `SupportBundleSecretDetected` ticket | US-OBS-007 / E04-S02 | Staging |
| E04-TC-B03 | huge window | generate bundle | capped, truncation stated, latest preserved | US-OBS-007 / E04-S02 | Staging |
| E04-TC-B04 | non-admin | request bundle | RBAC denial | US-OBS-007 / E04-S02 | Staging |
| E04-TC-B05 | two concurrent requests | request twice | second rejected | US-OBS-007 / E04-S02 | Staging |
| E04-TC-N01 | alert text, panels | review without colour | state conveyed by text/icon; defects filed with `a11y` label | US-OBS-004 / E04-D02 | Staging |

## Traceability

| Story | Cases | Automated | Staging |
|---|---|---|---|
| US-OBS-001 | M01-M04, D01, H01-H06 | H01-H06 | M01-M04, D01 |
| US-OBS-002 | L01-L03, T01-T06 | L02, T01-T05 | L01-L03, T06 |
| US-OBS-003 | G01-G03 | — | G01-G03 |
| US-OBS-004 | A01-A04, N01 | A02-A04 | A01, N01 |
| US-OBS-005 | R01-R02 | — | R01-R02 |
| US-OBS-007 | B01-B05 | — | B01-B05 |

## Performance targets recorded (06-performance-and-load-standard.md §2)

`/metrics` scrape < 50 ms at full cardinality; Page alert delivery <= 60 s (condition injected -> alert
received, timestamps recorded in the drill matrix).
