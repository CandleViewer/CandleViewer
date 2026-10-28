# ADR-0014 — Observability stack: Prometheus, Grafana, structured logs, targeted tracing

- Status: **decided**
- Date: 2026-09-14
- Deciders: DevSecOps, Architect, Backend lead
- Consulted: planning brief "SDLC requirements" (observability), `docs/research/11-backend-tech.md` (event-loop lag threshold), `docs/research/22-architecture-options.md` §10
- Related: `docs/plan/20-architecture.md` §12, `docs/plan/06-performance-and-load-standard.md`, ADR-0004

## Context and problem statement

The system runs unattended while holding real positions. Failures are mostly silent-by-default: a stale topic still renders a chart, a slow event loop still serves requests, an order stuck in `Unknown` looks like nothing at all. We need to know — quickly and specifically — when the system is lying to its user. The deployment is a single box for one operator, so the observability stack must be genuinely self-hostable and cheap to run alongside the workload it observes.

## Decision drivers

- The critical signals are numeric and continuous (lag, staleness, queue depth, latency percentiles, rate budget) — a metrics problem, not a log-search problem.
- Two conditions warrant waking the operator: an unprotected position and an order in an unknown state. Everything else can wait.
- Tracing every market-data event would distort the very loop it measures.
- No SaaS: the project is self-hosted and network-isolated by design.
- One operator means alert fatigue is fatal — a noisy alert set will be muted, and then the real one will be missed.

## Considered options

1. **Prometheus + Grafana + Alertmanager, structured JSON logs to stdout, OpenTelemetry tracing on two specific paths.**
2. **A full OpenTelemetry stack** (collector + Tempo + Loki + Mimir).
3. **SaaS observability** (Datadog/Grafana Cloud).
4. **Logs only.**

## Decision outcome

**Chosen: option 1.**

1. **Metrics** — the backend exposes `/metrics`; Prometheus scrapes every 10 s with 15-day retention. The metric catalogue is specified in `20-architecture.md` §12.1 and is part of the definition of done for every module: a module without metrics is not finished. Every metric carries an `env` label so demo and live never blur together.
2. **Frontend telemetry** — the web app pushes frame time, dropped frames, WS decode time and estimated GPU memory to a backend endpoint at a low rate (once per 10 s, aggregated). Field performance regressions in the chart engine are otherwise invisible until a user complains.
3. **Dashboards** — six provisioned dashboards (system health, market data, trading, rules, storage, frontend), stored as JSON in `infra/grafana` and code-reviewed like any other artefact. No click-ops dashboards: if it is not in the repository, it does not exist.
4. **Logging** — `structlog` JSON to stdout with mandatory correlation fields (`request_id`/`conn_id`, `user_id`, `account_id`, `symbol`, `order_link_id`, `trade_group_id`). A redaction processor strips keys, signatures, cookies and TOTP codes at the formatter, and a unit test asserts a known secret never reaches the output. Collected by the compose logging driver with rotation; **Loki is deliberately deferred** until log volume or an incident shows grep-over-files is insufficient.
5. **Tracing** — OpenTelemetry spans on exactly two paths: the **order path** (`http.request → oms.validate → oms.fanout → exchange.place_order → private_ws.fill`) and **replay session start**. Market-data hot loops are covered by metrics only; sampling them would distort the loop and produce data we would not act on.
6. **Alerting** — Alertmanager with two severities and nothing else:
   - **Page** (immediate): `naked_position_alerts_total > 0`; `oms_unknown_orders > 0` for 60 s; Postgres down; clock drift blocking trading; disk > 95 %.
   - **Ticket** (next working session): public WS down > 60 s; high book-resync rate; event-loop lag > 100 ms for 5 min; disk > 80 %; rule auto-disarm; demo/live mismatch attempts; certificate/credential expiry approaching.
     Every alert links to a runbook section in `07-release-and-prr.md`. An alert without a runbook is not allowed to be created.
7. **Health** — `/healthz` (liveness) and `/readyz` (readiness, including migrations-at-head and storage reachability) plus an aggregated module health report surfaced in the Admin health console, which is the operator's first stop.
8. **SLOs** — the budgets in `06-performance-and-load-standard.md` are encoded as recording rules so dashboards show burn rate rather than raw numbers, making "is this getting worse?" answerable at a glance.

### Consequences

Positive:

- Prometheus + Grafana is boring, well understood, self-hosted, and cheap enough to run beside the workload on one box.
- Restricting tracing to two paths keeps overhead negligible while covering the only flows where causality across modules is genuinely hard to reconstruct.
- A two-severity alert policy with mandatory runbooks is the only shape that survives a single-operator reality.

Negative / risks:

- No centralised log search until Loki is added; correlating an incident means `docker compose logs` plus `jq`. Accepted at this scale, and the correlation fields make it workable. Loki is a documented, non-breaking addition.
- Prometheus is not a long-term store; 15 days is short for slow trends. Mitigated by nightly Grafana snapshot exports for load-test and release comparisons.
- Frontend telemetry is a (small) new endpoint with a new data flow. Mitigated by authentication, aggressive aggregation, strict schema validation, and no PII.

### Why not the alternatives

- **Full OTel stack (Tempo/Loki/Mimir)**: three more stateful services on a box that also runs QuestDB and Postgres; the operational cost dwarfs the benefit for one operator and a handful of users. Deferred, not rejected forever.
- **SaaS**: contradicts the self-hosted, network-isolated, no-third-party posture, and would ship trading telemetry off-box.
- **Logs only**: cannot express percentiles, burn rates or continuous gauges like staleness and queue depth, which are precisely the signals that matter here.

## Validation

- Every alert is fired deliberately at least once (in staging with the synthetic feed) and its runbook walked, before Live enablement (R4) — a PRR checklist item.
- Load tests assert that the metric endpoints themselves stay under 50 ms scrape time with the full label set.
- Dashboard JSON is reviewed in PRs like code; a dashboard change without a review is a merge blocker.

## Addendum (2026-09-28) — E04-K01 instrumentation overhead spike

**Status of this addendum: measured, not overturning the original decision.**

E04-K01 (`docs/plan/spikes/E04-K01.md`) measured four instrumentation configurations
(none / metrics-only / metrics+structlog / metrics+structlog+OTel) on a synthetic
20,000-msg/s-shaped ingestion pipeline, and two label-handling shapes for the
metrics path (inline vs pre-bound). Full method, raw numbers, and gaps are in the
spike doc; the two decisions this ADR's original text depended on are:

1. **"Tracing every market-data event would distort the very loop it measures"
   (Context, above) — confirmed, measured.** OpenTelemetry spans at 100% sampling on
   the hot loop measured at **~98% CPU** against a 5%-over-baseline threshold — over
   19x the budget. The original decision (metrics only on market-data hot loops,
   tracing restricted to the order path and replay-session-start) **stands
   unchanged.**
2. **New finding, not previously assumed: the metrics facade's label-binding
   pattern matters.** A naive `counter.labels(topic, symbol).inc()` call inside the
   hot loop measured **3.70% CPU** overhead vs. a 1% budget (US-OBS-002 NFR); the
   same counter with labels pre-bound once per (topic, symbol) pair outside the
   loop measured **2.50%** — both exceed 1%, but pre-binding is meaningfully
   cheaper and the gap is expected to widen with label cardinality (more symbols
   in production). **Decision: the pre-bound-label pattern is adopted as the
   mandatory shape for the metrics facade being designed in E04-T03**; E04-T03's
   public API must not expose a per-message `.labels(...)` call as the supported
   entry point.

**Caveat:** measurements were taken on the delivery workstation, not the
4 vCPU / 8 GB reference VPS profile named in `06-performance-and-load-standard.md`
§3.1 (no VPS/container access in the delivery environment) — the _comparison_
between configurations is expected to hold, but a re-run on the actual reference
profile is filed as a follow-up before these absolute percentages are used to size
the production capacity plan (§10). See the spike doc's "Follow-up tickets"
section for the tracked items.

No change to the alerting, dashboard, logging or health-check sections of this ADR.

## Addendum (2026-10-02) — E04-T07 reconciliation: shipped versus decided

**Status: reconciled; no decision overturned.** Compared with the original text, what actually shipped under E04:

| Topic           | Decided                                          | Shipped                                                                                                                                                                                                            | Deviation                                                                            |
| --------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Metrics         | Prometheus, `env` label on every series          | Facade with injected `env`, disallowed label names and per-metric `max_series` cap; 60-entry catalogue in `metrics_catalogue.py` (live and planned)                                                                | Cardinality guard and `planned` status added; not in the original text               |
| Hot-path labels | Metrics only on hot loops                        | Pre-bound children are mandatory (E04-K01: inline `.labels()` 3.70% CPU vs pre-bound 2.50%; 100% OTel tracing about 98% CPU against a 5% budget)                                                                   | Clarification, see the 2026-09-28 addendum                                           |
| Dashboards      | Six provisioned, reviewed JSON                   | Generated by `infra/grafana/generate_dashboards.py`, linted against the catalogue, nightly snapshot export; Grafana host port 3001                                                                                 | Generated rather than hand-written                                                   |
| Alerts          | Page and ticket severities; each links a runbook | Two severities enforced by `check_alert_rules.py`; `Watchdog` dead-man exempt; per-metric `absent()` guards (`ExpectedMetricMissing*`) share one runbook anchor; `SyntheticAlert` plus `alert_drill.py` for drills | Added guards, drill and a delivery-failure alert (`AlertmanagerNotificationsFailed`) |
| Runbooks        | One per alert in `07-release-and-prr.md`         | Section 9 with seven mandatory elements, plus the "Observability stack is down" and "Dev environment rebuild" runbooks                                                                                             | None                                                                                 |
| Logging         | structlog JSON with redaction                    | As decided                                                                                                                                                                                                         | None                                                                                 |

Residual items: the K01 absolute overhead numbers still need a re-run on the reference VPS profile; the three-runbook literal-execution review needs a non-author and a staging stack (not available to the delivery agent) and is tracked on the PR.

## Addendum (2026-10-05) — E08-T06 ingestion observability

- **Registry.** Ingestion and adapter series are declared once in
  `services/api/candleviewer/ingestion/metrics.py` (`SPECS`); layers that may not import ingestion
  (`exchange.base`, `exchange.bybit`, `bus`) instantiate their declared series and a registry test fails
  on any undeclared / duplicated / orphaned / drifted name. The E04 catalogue still owns the
  platform-wide names; the dashboard lint reads both.
- **Scrape gap closed.** These module-level series lived only on the library default registry, which
  `/metrics` does not serve. `export_ingestion_metrics` re-exports exactly the declared set onto the
  scraped registry with constant `env` + `exchange` labels (`ReexportCollector`).
- **Cardinality.** Symbol label values are bounded (`symbol_label`: configured set or a 32-symbol cap,
  overflow `other`, malformed input never a label); `bybit_rate_limit_remaining` lost its `uid` label.
- **Board + alerts.** Seventh dashboard **CV / Ingestion** (`cv-ingestion`); alert set
  `infra/prometheus/alerts/ingestion.yml` whose runbook is `docs/ops/ingestion.md` (cross-checked both
  ways), incl. the silent-death meta-alert `IngestionStoppedReporting`.
- **Overhead.** Trade-path instrumentation measured ≈ 0.7–3 µs/event in a clean interpreter (host
  load dominates the spread), ≤ 1.5 % of one core at 5 000 ev/s; asserted < 2 % in CI. Same caveat as
  K01: dev workstation, not the reference VPS profile.
- **ADR-0016 deliberately not amended.** The ticket asked to amend ADR-0016 with the soak numbers.
  The harness exercises only hot-path code that ADR-0016 excludes from statecharts (bus publish,
  `BookState.apply`), so its numbers say nothing about the interpreter. ADR-0016's standing item —
  `cv_machine_live_count{kind}` flat across a 24 h soak — stays **unmeasured** until the 24 h demo run
  with B13/B14 wired (owner exception #1778 A). Only consistent figure: book apply p95 0.011 ms at
  depth 200, in line with ADR-0016's "15–60 µs of real work" hot-path premise.

## Addendum (2026-10-28) — E29-T04 order-path spans

§5's order-path span names are maintained in `20-architecture.md` §12.3. #913 (E29-T04) adds `oms.submit`, with `oms.validate`, `oms.persist` and `oms.send` as its children, and a span records an exception's class, never its message (C-12.6). No decision is overturned.
