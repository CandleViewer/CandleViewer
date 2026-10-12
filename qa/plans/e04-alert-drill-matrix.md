# E04-Q01 — Alert drill matrix (R0 subset)

Status: **prepared, pending staging execution** (not run locally: no docker/Prometheus/Alertmanager on the authoring host).
Each row is filled in by QA during the staging drill: UTC timestamps, delivered Y/N, runbook executable Y/N.
Synthetic injection proves the rule; the **real** drills (PostgresDown by stopping Postgres, PublicWsDown by dropping the public WS) prove the metric reacts.
Near-miss = threshold minus epsilon and duration minus epsilon; both must NOT fire (promtool coverage in `infra/prometheus/tests/system_alerts.test.yml`).
Drill windows are recorded in `system_events`; coordinate security-rule drills (AuthLoginFailureSpike, AuditChainVerificationFailed) with Security.

| Rule | Severity | For | Runbook | Mode | Injected (UTC) | Received (UTC) | <=60 s | Runbook walked | Near-miss silent | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| BybitClockDriftWarning | ticket | 2m | `docs/plan/07-release-and-prr.md#alert-bybitclockdriftwarning` | synthetic | | | | | | pending |
| BybitClockDriftCritical | page | 1m | `docs/plan/07-release-and-prr.md#alert-bybitclockdriftcritical` | synthetic | | | | | | pending |
| BybitClockOffsetStale | ticket | 1m | `docs/plan/07-release-and-prr.md#alert-bybitclockoffsetstale` | synthetic | | | | | | pending |
| LatencyBudgetBreach | ticket | 60s | `docs/plan/07-release-and-prr.md#alert-latencybudgetbreach` | synthetic | | | | | | pending |
| TickToPaintSloFastBurn | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-ticktopaintslofastburn` | synthetic | | | | | | pending |
| SupportBundleSecretDetected | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-supportbundlesecretdetected` | synthetic | | | | | | pending |
| NakedPositionDetected | page | 0m | `docs/plan/07-release-and-prr.md#alert-nakedpositiondetected` | synthetic | | | | | | pending |
| OmsUnknownOrders | page | 1m | `docs/plan/07-release-and-prr.md#alert-omsunknownorders` | synthetic | | | | | | pending |
| PostgresDown | page | 1m | `docs/plan/07-release-and-prr.md#alert-postgresdown` | real+synthetic | | | | | | pending |
| ClockDriftBlockingTrading | page | 1m | `docs/plan/07-release-and-prr.md#alert-clockdriftblockingtrading` | synthetic | | | | | | pending |
| DiskCritical | page | 2m | `docs/plan/07-release-and-prr.md#alert-diskcritical` | synthetic | | | | | | pending |
| AuditChainVerificationFailed | page | 0m | `docs/plan/07-release-and-prr.md#alert-auditchainverificationfailed` | synthetic | | | | | | pending |
| SyntheticAlert | page | 1m | `docs/plan/07-release-and-prr.md#alert-syntheticalert` | synthetic | | | | | | pending |
| PublicWsDown | ticket | 1m | `docs/plan/07-release-and-prr.md#alert-publicwsdown` | real+synthetic | | | | | | pending |
| BookResyncHigh | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-bookresynchigh` | synthetic | | | | | | pending |
| EventLoopLagHigh | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-eventlooplaghigh` | synthetic | | | | | | pending |
| DiskHigh | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-diskhigh` | synthetic | | | | | | pending |
| RuleAutodisarm | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-ruleautodisarm` | synthetic | | | | | | pending |
| EnvMismatchAttempt | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-envmismatchattempt` | synthetic | | | | | | pending |
| CredentialExpiryApproaching | ticket | 10m | `docs/plan/07-release-and-prr.md#alert-credentialexpiryapproaching` | synthetic | | | | | | pending |
| AuthLoginFailureSpike | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-authloginfailurespike` | synthetic | | | | | | pending |
| AuthLockouts | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-authlockouts` | synthetic | | | | | | pending |
| AuthzDeniedSpike | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-authzdeniedspike` | synthetic | | | | | | pending |
| CredentialVerificationFailures | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-credentialverificationfailures` | synthetic | | | | | | pending |
| OmsRateRejects | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-omsraterejects` | synthetic | | | | | | pending |
| EgressIpChanged | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-egressipchanged` | synthetic | | | | | | pending |
| AlertmanagerNotificationsFailed | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-alertmanagernotificationsfailed` | synthetic | | | | | | pending |
| IngestionTopicStale | ticket | 1m | `docs/ops/ingestion.md#alert-ingestiontopicstale` | synthetic | | | | | | pending |
| IngestionBookResyncRateHigh | ticket | 5m | `docs/ops/ingestion.md#alert-ingestionbookresyncratehigh` | synthetic | | | | | | pending |
| BookResyncStorm | page | 5m | `docs/ops/ingestion.md#alert-bookresyncstorm` | synthetic | | | | | | pending |
| IngestionFramesRejectedSustained | ticket | 10m | `docs/ops/ingestion.md#alert-ingestionframesrejectedsustained` | synthetic | | | | | | pending |
 ticket | 10m | `docs/ops/ingestion.md#alert-ingestionframesrejectedsustained` | synthetic | | | | | | pending |
| IngestionTradeGapUnrecovered | page | 0m | `docs/ops/ingestion.md#alert-ingestiontradegapunrecovered` | synthetic | | | | | | pending |
| IngestionRateLimitHeadroomExhausted | ticket | 1m | `docs/ops/ingestion.md#alert-ingestionratelimitheadroomexhausted` | synthetic | | | | | | pending |
| IngestionNeverDropQueueFull | ticket | 5m | `docs/ops/ingestion.md#alert-ingestionneverdropqueuefull` | synthetic | | | | | | pending |
| IngestionStoppedReporting | page | 5m | `docs/ops/ingestion.md#alert-ingestionstoppedreporting` | synthetic | | | | | | pending |
| IngestionMetricsAbsent | ticket | 15m | `docs/ops/ingestion.md#alert-ingestionmetricsabsent` | synthetic | | | | | | pending |
| GADefectForecastSlipping | ticket | 3d | `docs/plan/07-release-and-prr.md#alert-gadefectforecastslipping` | synthetic | | | | | | pending (promtool unit/firing test: #1844 follow-up) |
| GADefectArrivalExceedsClosure | ticket | 1h | `docs/plan/07-release-and-prr.md#alert-gadefectarrivalexceedsclosure` | synthetic | | | | | | pending (promtool unit/firing test: #1844 follow-up) |
| GADefectSLABreached | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-gadefectslabreached` | synthetic | | | | | | pending (promtool unit/firing test: #1844 follow-up) |

## Execution status and exception request (2026-10-02)

- **Executed locally (evidence):** `services/api/tests/qa/test_e04_q01_blackbox.py` — 12 passed (uv, py3.12, 2026-10-02). Covers in-process metrics exposure, canary-secret redaction across logging paths (AC5), and Prometheus-unavailable fallback behaviour (AC6) at unit/ASGI level.
- **Not executable on the authoring host:** AC2 live drills (fired/received/runbook walked), AC3 near-miss via promtool, AC4 dashboards, and k6 runs (`metrics_scrape.k6.js` p95<50 ms, alert delivery <=60 s). They need docker, Prometheus, Alertmanager, Grafana and k6, none installed here.
- **Owner exception requested:** these staging-only items are deferred to the first staging drill; this PR delivers the plan, matrix, scripts and in-process tests only. QA fills the matrix above and attaches k6 output to E04-Q01 before the ticket moves to Done. Until then the 60 s delivery and <50 ms scrape budgets are **unverified**, not passed.
