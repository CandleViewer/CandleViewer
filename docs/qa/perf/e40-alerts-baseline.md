# E40 alerts k6 baseline (E40-Q02, #1203)

Status: **pre-stage, no run yet. Every value is `null` and the gate is `warn-only`.** This file records where the alert
load numbers come from and how they move. The machine-read baseline is `tests/load/k6/alerts/baseline.json`. The gate
step of the nightly (next PR, `.github/workflows/perf-alerts-nightly.yml`) reads it (BQ-04: no new dashboard).

## What runs

The nightly (next PR) runs these profiles; the Where column names the runner it uses.

| Profile                                      | Script                                          | Where                                    | Verdict                                                                                                                                        |
| -------------------------------------------- | ----------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 50 `alerts` subscribers, 3 runs              | `tests/load/k6/alerts/ws_subscribers.js`        | nightly, `ubuntu-latest`                 | k6 thresholds: 250 ms window floor (p5 >= 225 ms), pacing (p50 <= 400 ms), zero out-of-order, gap, truncated or `unacked_count`-rise deltas    |
| `GET /notifications`, 500 a page, >= 1M rows | `tests/load/k6/alerts/notifications_page.js`    | nightly, `ubuntu-latest`                 | k6 threshold: p95 < 200 ms, following each VU's cursor, over all four sources                                                                  |
| Soak, 200 armed alerts, `smoke` (10 min)     | `tests/load/k6/alerts/soak.js`, `soak_check.py` | nightly, `ubuntu-latest`                 | `alerts_armed`, `alerts_fired`, `fire_count_equals_delivery_rows`, `no_dead_outbox_rows`, report-only for now (see below). Memory: report only |
| Soak, `24h`                                  | same                                            | dispatch `profile=soak24h`, bench runner | as `smoke`                                                                                                                                     |

The seed (`tests/load/k6/alerts/seed_alerts.py`) writes at least 1M rows: 60 % `alert_deliveries` and 40 %
`system_events`, plus 50 000 `rule_events` (under one rule, version and run per Owner) and 50 000 `order_events` (under
one testnet account and order), so the `/notifications` union reads all four sources. It refuses anything but a throwaway
perf stack: the users pattern must be exactly `perf-<8 hex>-%`, the DSN host loopback or the compose `postgres` service,
and the database must hold no other user, no `live` or `demo` exchange account and no `api_keys` row.

## Soak: report-only until the metric-producer bridge lands (#5745 (E35-T15))

The soak (nightly, next PR) and `soak_check.py` report every check, but neither fails the job: the rules metric
source (blocker #5745 (E35-T15)) has no production producer yet (E12/E18–E25 adapters push into `PushedMetricSource`), so no alert can fire on
the stack and `alerts_fired` would fail every night. The check itself is not relaxed. One switch turns the verdict on:
set `CV_E40_SOAK_GATE` to `"1"` in the job `env` of `.github/workflows/perf-alerts-nightly.yml` once that bridge is on
`main`.

## Gate

`compare_baseline.py` takes the median over the three WS runs of `alerts_ack_ms` p95, `http_req_duration` p95 and
`alerts_window_gap_ms` p95, and the `/notifications` run's `http_req_duration{endpoint:notifications}` p95
(`notifications_p95_ms`; its plain `http_req_duration` is kept out of the WS metric), and compares each with this baseline at +5 % (06 §7.4, C-13.9). It writes `compare.json`
and `compare.md` to the artifact and the run summary.

- `warn-only` (now): a value over +5 % or a metric read from too few runs WARNs, and a `null` value is reported as
  `NO-BASELINE`.
- `gate`: a value over +5 %, a missing metric, or a metric read from fewer than three runs (`min_runs`: one for
  `notifications_p95_ms`, the single `/notifications` run) fails the run. The `perf-alerts` nightly issue is then filed.

## Moving the baseline

Values come only from a green nightly's `compare.json` on the CI runner. A reviewed "update performance baseline" PR
sets them and moves `mode` to `gate`, with the run id and the rationale. Baselines only get stricter or stay flat
(06 §7.4).

## Deviations

- BQ-03's default skipped the `/notifications` scenario until S02 S2, on the premise that its sources were not merged.
  That blocker was false: the four-source union (alert deliveries, system, rule and order events) is on `main`, so the
  nightly (next PR) runs the scenario, gated by its p95 threshold and `notifications_p95_ms`.

## Proposed, not ruled

- The 25 ms window-floor tolerance and the 400 ms pacing ceiling (`lib/frames.js`). Owner: the 06 owners, ratified on
  #2701 or in the results PR.
- The memory envelope of the 24 h soak (BQ-06). Report only until the owner sets a number.

## Results

| Date     | Run | Profile | Status | Notes |
| -------- | --- | ------- | ------ | ----- |
| none yet |     |         |        |       |
