# E04-C2 Charter: silence detector (alerting path)

- Ticket: E04-Q02 (#257) · Format: session-based test management · Date: 2026-10-31
- Plan: `docs/qa/test-plans/e04-observability-charters.md` (base, rulings, regression pack, blind-spot report, sign-off draft).
- Tester: AI agent. **Deviation (honest scope):** an agent ran the static and in-process work. It is not a human session. No Prometheus or Alertmanager server ran, and no notification was sent or received. Every live technique is **not attempted — blocked on the PRR staging re-run** (BQ-01, pending ruling). The two new checks run in CI as pytest; promtool and amtool run only in CI's docker.
- No credentials used. No webhook URL or secret file was read. No network (C-13.5).

## Charter

Explore the alerting path with the goal of producing a real failure that generates no notification.

Time box: 4 h (the ticket's). Actual: see "Session metrics" (BQ-15, pending ruling).

## Oracles (defined before probing)

- O1 A threshold rule whose series can go absent with no `absent()` companion (the ticket's systematic property).
- O2 A rule whose series nothing emits, records or scrapes, so it can never fire.
- O3 A route, mute or inhibition that drops a notification for a real failure.
- O4 A broken outbound path that nothing reports.

## Techniques

| Technique (ticket)                                           | Attempted                                            | Outcome                                                                                                                                                                                                                                  | Evidence                                                                                                                       |
| ------------------------------------------------------------ | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Metric emitted by a module that is down (the `absent()` gap) | static, now a CI check                               | **O1 holds for 58 of the 145 rules (69 rule and series pairs).** Each pair is in a committed baseline with a reason class. A new unguarded series fails CI.                                                                              | `services/api/tests/qa/test_e04_q02_alert_guards.py` and `e04_q02_alert_guard_baseline.json` (this PR)                         |
| (same, the series-existence leg)                             | static, now a CI check                               | **F2: 17 pairs on 9 series that nothing produces** (shipped: 7 pairs on 4 series; planned in the catalogue with no emitter: 10 pairs on 5 series). `PostgresDown` and `ClockDriftBlockingTrading` can never fire.                        | `services/api/tests/qa/test_e04_q02_alert_series.py` and `e04_q02_alert_series_baseline.json` (this PR)                        |
| Fire two alerts whose inhibition rules suppress each other   | static                                               | Mutual suppression is impossible: both rules take pages as sources and tickets as targets. **O-5:** a drill page inhibits an unrelated ticket. The `PostgresDown` inhibition is inert (F2).                                              | `infra/alertmanager/alertmanager.yml`:58–68                                                                                    |
| Fire during a quiet-hours window                             | static; the live fire is blocked on a running stack  | Tickets are muted 22:00–07:00. A ticket that fires and resolves inside the window is never sent. Pages bypass it. All 42 guards are tickets. This window is already accepted (`docs/plan/32-risk-register.md`:386).                      | `alertmanager.yml`:35–56                                                                                                       |
| Break Alertmanager's outbound path                           | static; the live break is blocked on a running stack | **O-6.** A broken page or ticket webhook produces no alert. `AlertmanagerNotificationsFailed` reads a series nothing scrapes (F2). Even when scraped, its notice would use the broken path. The dead-man route covers only the Watchdog. | `alertmanager.yml`:22–27, :70–94; `infra/prometheus/alerts/system_ticket.yml`:334–335; `infra/prometheus/prometheus.yml`:13–21 |

### The `absent()` property (O1)

- Population: 145 alert rules in 14 files. 42 are `absent()` guards: 41 in `infra/prometheus/alerts/metric_guards.yml`, plus `IngestionMetricsAbsent` (`infra/prometheus/alerts/ingestion.yml`:125–126). `Watchdog` (`infra/prometheus/alerts/meta.yml`:7) and the drill rule `SyntheticAlert` (`infra/prometheus/alerts/system_page.yml`:250) are not judged.
- The check counts a rule once per unguarded series. 58 rules have at least one series with no guard. The before-writing list counted 56 rules, because it counted a rule only when **none** of its series had a guard. Both counts match by metric name only; label scope is not checked.
- Reason classes in the baseline: `lazy-series` 24 rules, `module-guard` 4, `flag-gated` 2 (29 rules in all, one rule in two classes), and `routed` 30 rules (33 pairs; `AuditLaneRefusing` is also in `lazy-series`). The four audit-lane gauge pairs are `lazy-series`: the series are served only once the lane is wired (`audit/metrics.py`:58–59 returns early when it is not). A guard on a lazy or flag-gated series would fire for good on a healthy system. Three rule comments decline a guard for that reason (`system_ticket.yml`:437, :475, :492).
- Nine of the 58 are pages: `BybitClockDriftCritical` (`infra/prometheus/alerts/clock_sync.yml`:18), `BookResyncStorm` (`ingestion.yml`:38), `IngestionTradeGapUnrecovered` (:70), `IngestionStoppedReporting` (:110), `RecorderSilentStop` (`infra/prometheus/alerts/recorder.yml`:13), `RecorderMessagesDropped` (:26), `RecorderDiskPressureAutostop` (:71) and `RecorderWriteGateClosed` (:79) and `AuditVerifyNotPassing` (`infra/prometheus/alerts/system_page.yml`:82).
- Before this PR no gate checked the property. `infra/alertmanager/check_alert_rules.py`:1–5 checks severity, component and runbook only.

### Series that nothing produces (O2)

| Series                                    | Rules that read it                                                                             | Why nothing produces it                                                                                                   |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `pg_up`                                   | `PostgresDown` (page, `system_page.yml`:41–42) and its guard (`metric_guards.yml`:189)         | no emitter, no catalogue entry, and no Postgres exporter among the scrape jobs (`prometheus.yml`:13–21)                   |
| `credential_expiry_days`                  | `CredentialExpiryApproaching` (`system_ticket.yml`:72) and its guard (`metric_guards.yml`:280) | no emitter and no catalogue entry                                                                                         |
| `env_mismatch_attempts_total`             | `EnvMismatchAttempt` (`system_ticket.yml`:63) and its guard (`metric_guards.yml`:271)          | no emitter and no catalogue entry; the code only logs the event                                                           |
| `alertmanager_notifications_failed_total` | `AlertmanagerNotificationsFailed` (`system_ticket.yml`:334)                                    | on the dashboard lint's external list (`infra/grafana/lint_dashboards.py`:21–27), but Alertmanager is not a scrape target |

The promtool cases feed these series synthetically, so they pass (`infra/prometheus/tests/system_alerts.test.yml`:84, :331, :353). On a running stack the three guards would fire for good, as tickets. The E04-Q01 drill plans "PostgresDown by stopping Postgres" (`qa/plans/e04-alert-drill-matrix.md`:5). The `PostgresDown` inhibition depends on the same rule (`alertmanager.yml`:62–64). All of this is static and not yet confirmed live.

## Session metrics

- Time: about 12 minutes of agent tool time, 05:28–05:40 UTC, shared with charters 1 and 3. Times are from the agent's tool log. Not a 4 h human session.
- The two new checks ran at 05:30: 26 passed in 0.65 s, self-tests included. `python infra/alertmanager/check_alert_rules.py` and `python infra/grafana/lint_dashboards.py --strict` both passed at the base.
- Inhibition and route analysis: a parse of `alertmanager.yml` and the 14 rule files' `severity` and `component` labels. Not committed.

## Findings

**F2 — nine series that nothing emits or scrapes; two pages, `PostgresDown` and `ClockDriftBlockingTrading`, can never fire (static; proposed P1, "to file on go", BQ-11).** See the table above. The series check counts a catalogue name as emitted only if its status is `live` or it is `exported` (`register_r0` registers live entries only, `metrics_catalogue.py`:5168). Shipped, 4 series: `pg_up`, `credential_expiry_days`, `env_mismatch_attempts_total`, `alertmanager_notifications_failed_total`. Planned, no emitter, 5 series: `bybit_clock_drift_ms` (E08; read by the page `ClockDriftBlockingTrading`, `system_page.yml`:50–51, and a guard, `metric_guards.yml`:198–199; the emitted series is `exchange_clock_drift_ms`, and the planned name appears only in a comment in `observability/latency.py`), and four for unshipped modules, `credential_verification_failures_total` (E27), `egress_ip_changes_total` (E43), `naked_position_alerts_total` (E32, which feeds the page `NakedPositionDetected`) and `rule_autodisarm_total` (E35), RSK-047. Four catalogue entries marked `planned` are already emitted by their modules (`cv_outbox_*`, `oms_unknown_orders`, `oms_position_reading_owed_age_seconds`); the check lists them with a cite, and a test re-checks each. One issue would cover the class. It is labelled a static finding pending live confirmation. The new series-existence check now stops new cases.

## Observations (routed rows; no issue filed under the freeze)

- **O-5 — a drill page inhibits an unrelated ticket.** `SyntheticAlert` is a page with `component: alerting` (`system_page.yml`:250–255). The drill pushes it with an `env` grouping label (`infra/alertmanager/alert_drill.py`:59–60). The second inhibit rule suppresses every ticket with the same `component` and `env` (`alertmanager.yml`:66–68). So, during a drill, `AuthBreakGlassStateReadFailing` (`system_ticket.yml`:343, `component: alerting`, summed by `env`) is suppressed in the drilled environment. That ticket says the break-glass pages cannot read their state. The 41 guards carry no `env` label, so they are not suppressed. Routed to E04 (BS-19).
- **O-6 — a broken outbound path is silent.** The page and ticket receivers use their own webhook secrets (`alertmanager.yml`:70–90). The dead-man receiver hears only the Watchdog (:22–27, :91–94). A page channel that fails while the dead-man channel works sends nothing and raises nothing. Proposed for owner acceptance (BS-09).
- **O-7 — no rule reads `up`.** If the API stops or cannot be scraped, its series go absent. Every threshold rule then stops, and only the guard tickets fire, after 15 minutes, muted overnight. There is no page. Routed to E04 (BS-02, NQ-2).
- **O-8 — no rule reads `health_component_state`.** A storage dependency that is down shows in the health matrix and on the "System health" dashboard (`infra/grafana/dashboards/system-health.json`:494) but sends nothing. No rule mentions QuestDB or Parquet. A QuestDB outage notifies only once write-behind evicts rows (`RecorderMessagesDropped`). Routed to E04 (BS-05).

## Not attempted (blocked on a running stack)

- Break a real webhook and watch for a notice. Fire a real ticket at 23:00. Stop a real module and watch the guard fire after 15 minutes. Fire `PostgresDown` and a storage ticket together. Owner: the PRR staging re-run (BQ-01).
- Confirm F2 live: scrape a running stack and list the series that are absent.

## Follow-ups

1. F2: file the one P1 on the coordinator's go (BQ-11).
2. Route the 30 `routed` rules to their owning epics as rows (blind-spot report, BS-12 to BS-18).
3. Promtool cases for the seven rule files no test loads, and a fire case per guard (BQ-05). Proposed, not in this PR.
