# E40 alerts: load-harness baseline (E40-Q02, part A, slice 1)

Status: **pre-stage baseline. The sqlite leg is measured locally; the Postgres leg is pending the first CI run.**
The budget evidence is the Postgres leg only (BQ-02, default (a)): a number from an in-memory sqlite store says
nothing about the commit cost on `alert_deliveries`. The sqlite rows below are development figures and the
regression reference for the evaluator half. No production code was changed. No figure in this file is estimated:
each is one run's printed row.

Plans and results follow the E17 and E29 pattern: results under `docs/qa/perf/`. The perf dashboard and the nightly
+5 % gate are not built here (BQ-04): the nightly workflow and its compare step are slice 3.

## Budgets

| Budget                                                 | Source                    | Bound        |
| ------------------------------------------------------ | ------------------------- | ------------ |
| Condition met to `alert_deliveries` row committed, p95 | E40-Q02 "Latency budgets" | ≤ 1 s        |
| The same, p99                                          | E40-Q02 "Latency budgets" | ≤ 2 s        |
| Subscriptions for 500 alerts over 40 conditions        | E40-Q02, ADR-0032 Q2      | exactly 40   |
| Storm: 25 qualifying firings in 60 s                   | US-ALRT-002 storm, BQ-07  | 25 conserved |

## Method

- **Load.** The E40-K01 corpus and stream (`services/api/benchmarks/alerts/harness.py`): 500 alerts over 20 symbols
  (`corpus(500, 500)`), a seeded random walk per symbol (seed 7), one tick every 5 ms of exchange time on a seeded
  symbol order. Every alert is `every_time`, no cooldown, `in_app` only. The corpus draws its thresholds from 4 values
  per symbol, so its measured bound is **80** distinct conditions, and both legs share 80 subscriptions. 500
  distinct conditions remain the ticket's design target, not a property of this corpus.
- **Evaluator.** `benchmarks/alerts/latency_leg.py` drives the shipped `AlertEvaluator` (gating, storm suppressor and
  owner gate at their defaults), one `process()` per tick, in order. K01's own harness runs E35's `Evaluator` and a
  stand-in; the leg runs what ships.
- **Sample.** One per committed firing. The sample starts at the `perf_counter` read just before the
  `process()` call for the tick that met the condition, and ends at the `perf_counter` read when `record_firing`
  returns, after its COMMIT and not at any server acknowledgement. That is an upper bound on
  "condition met to row committed": it includes the snapshot build and every earlier firing of the same tick, which
  commit one at a time under the evaluator's lock. Storm summaries are not samples. Percentiles are nearest-rank (rank
  `ceil(p * n)`) on the sorted samples.
- **Stores.** The sqlite leg commits to an in-memory sqlite database (deliveries, outbox and alert counters in one
  commit). The Postgres leg commits through `SqlAlchemyAlertFiringStore` to Postgres 16 (`postgres:16-alpine`,
  testcontainers, migrated to head), with the real owner gate over `SqlAlchemyIdentityProvider` and one active user
  per alert. One user per alert means this leg does not exercise storm suppression (every firing is queued);
  storm conservation is covered by the unit tests in `tests/alerts/test_alert_load_q02.py`.
- **Cross-checks.** The leg fires exactly the K01 harness's deliveries for the same stream (asserted in
  `tests/alerts/test_alert_load_q02.py`). The Postgres test counts the rows afterwards: every sample is an
  `alert_deliveries` row, every queued row has its `alert.deliver` outbox row, the alerts' `fire_count` sums to the
  firings, and the shipped `cv_alert_eval_latency_seconds` histogram saw one observation per queued firing.

## How it runs

- **Postgres leg:** `services/api/tests/integration/bench/test_e40_alert_latency_pg.py`, `@pytest.mark.integration`,
  5 000 ticks. CI runs it in the `py` job's `db-chaos-3` lane (`tools/ci/py-test-lanes.json`, `tests/integration/bench`) and,
  because `_job-integration.yml` runs `integration and not perf and not flaky` over every file under
  `tests/integration` (split by `tools/ci/integration_shards.py`), in one of its four shards; it never runs on the owner's host. It asserts the p95 and p99 budgets and prints one `E40Q02_PG_LEG=` JSON
  line (also a JUnit property, `e40q02_pg_leg`).
- **Sqlite leg, locally:** `cd services/api && uv run python -m benchmarks.alerts.latency_leg 20000`.
- **K01 harness, locally:** `cd services/api && uv run python -m benchmarks.alerts.run out.json`.
- **Unit checks (run in the PR lane):** `tests/alerts/test_alert_load_q02.py`: subscription sharing, storm
  conservation, and the leg's own determinism.

## Measured values

Local host: 28 vCPU WSL2, shared with other agents (load average 1.9 to 5.6 around the runs), Python 3.12.12, base
`1a34a88538f0f341057dd5dff740cf951ea00954`, 2026-11-04.

**Latency leg, 20 000 ticks, three runs.** Each run committed 3 368 firings: 3 334 queued and 34 storm-suppressed
(an alert crossing its level back and forth more than 20 times in 60 s; one user per alert).

| Store         | Run | p50                      | p95      | p99      | max      | Wall    |
| ------------- | --- | ------------------------ | -------- | -------- | -------- | ------- |
| sqlite memory | 1   | 0.217 ms                 | 0.424 ms | 0.645 ms | 1.348 ms | 2.296 s |
| sqlite memory | 2   | 0.216 ms                 | 0.433 ms | 0.619 ms | 2.958 ms | 2.494 s |
| sqlite memory | 3   | 0.249 ms                 | 0.553 ms | 0.953 ms | 3.324 ms | 2.490 s |
| Postgres 16   | CI  | pending the first CI run | pending  | pending  | pending  | pending |

**K01 harness, Q1 (500 alerts, 20 symbols, 20 000 ticks), three runs.** Both options deliver 3 368.

| Option                  | Subscriptions | p95 (runs 1, 2, 3)     | p99 (runs 1, 2, 3)     |
| ----------------------- | ------------- | ---------------------- | ---------------------- |
| A, `shared`             | 500           | 0.146, 0.139, 0.136 ms | 0.234, 0.255, 0.227 ms |
| B, `separate` (shipped) | 80            | 0.172, 0.170, 0.166 ms | 0.268, 0.243, 0.221 ms |

**Subscription sharing:** 500 alerts over 40 distinct conditions on 20 symbols hold 40 subscriptions, and
`cv_alert_subscriptions` reads 40 (asserted, unit level).

**Storm conservation:** 25 qualifying firings for one user inside 60 s give 20 delivered and 5 suppressed rows, all
25 alerts in the delivery history once each, `cv_alert_suppressed_total{reason="storm"}` = 5, 20 outbox rows, and at
the window end one summary delivery stating 5 (asserted for even spacing and for five seeded random arrival patterns).

## Deviations

1. **The Postgres leg has no number yet.** It is CI-only (no docker on the owner's host). Its first green run's
   `E40Q02_PG_LEG=` row goes in the table above.
2. **The stream is the seeded K01 walk, not a recorded market window.** Until a recording exists, the "recorded
   window" of the ticket is that seeded walk. No recorded E25 window exists on `main`
   (`benchmarks/alerts/extras.py` says the same for the storm histogram). Swapping in a recording changes the source,
   not the leg.
3. **The latency sample is an upper bound.** It starts at the tick, not at the instant the condition evaluated true.
4. **No `e40_regression` marker.** Registering one is not a one-line change: the existing packs (`e08_regression`,
   `e09_regression`) come with a path-tagging module and a plan file. The marker is slice 5's (BQ-10).
5. **The corpus bound is 80 distinct conditions (measured).** The 500 alerts draw thresholds from 4 values per
   symbol; 500 distinct conditions stay the ticket's design target. The 40-condition sharing check uses its own
   corpus (unit level).
6. **The frontend frame budget** of the storm scenario waits on the shipped UI (BQ-07).
