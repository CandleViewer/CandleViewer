# E29 OMS submit-ack k6 profile (E29-Q03, #977)

Status: **pre-stage, no run yet.** `tests/load/k6/oms/baseline.json` is `warn-only` with every value `null`. The
nightly and dispatch workflow is the next slice, and it is not a required check (BQ-08).

## What it measures

Budget #4 (`docs/plan/06-performance-and-load-standard.md`, the `Order submit → ack` row of the budget table; it governs over
SCR-060's looser 500 ms live figure): order submit to terminal ack, p95 < 300 ms on demo,
and its backend-added portion, ≤ 50 ms p95 (§5.2, line 124).

- **Timer (BQ-01).** It starts at the `POST /orders` and stops at the first `orders` delta (`23-ws-protocol.md` §6.2.3,
  §15.1) that carries the order's `order_link_id` with `change` `ack` or `reject`. The link comes from the 202
  (`OrderAcceptance`). The POST is asynchronous in the VU, so an ack that lands before the 202 is still timed from the
  POST. The 202's own latency is `oms_submit_http_ms`, reported and not gated.
- **Backend-added.** `order_submit_seconds` is scraped from `/metrics` in `setup` and `teardown`; the delta's p95 less
  one pack draw (`delay_ms`, which the server waits on) is `oms_backend_added_p95_ms`. The jitter is not taken off, so
  the figure errs high. It is report-only until the metric leaves `planned` in the catalogue (BQ-10);
  `CV_E29_BACKEND_GATE=1` turns on `value<=50` and `oms_backend_added_missing` `count==0`, so a run with no
  measurement fails. **Before `CV_E29_BACKEND_GATE=1` the stack needs `delay_ms` 0 (or finer buckets):** `SUBMIT_BUCKETS`'
  first edge is 0.05 s (`metrics_catalogue.py:177`), so at a delay of 40 the p95 is interpolated inside (0.05, 0.1] and
  `oms_backend_added_p95_ms` can read 57.5 on a healthy backend; a move from 55 to 90 ms reads as a ramp, not a step.
- **Native SL (C-2.6).** Every order is a limit entry with `stop_loss` at `CV_E29_SL_PERCENT` percent.
- **Orders.** Buys rest 1 % below and sells 1 % above `CV_E29_PRICE` (keep it near the mark), so they never cross,
  and nothing is cancelled: each account stops at `CV_E29_MAX_ORDERS` (`200`) open orders. The account must be
  one-way mode (no `position_idx` is sent), and its profile's risk caps must admit that many open orders.
- **p50 and p99.** `summaryTrendStats` keeps p50, p95 and p99; read them in the summary JSON
  (`CV_E29_SUMMARY`, default `k6-summary-oms-submit-ack.json`) at `metrics.oms_submit_ack_ms.values["p(50)"]` and
  `["p(99)"]`. There is no stdout summary.

| Metric                                                                           | `gate` profile                   | `calibrate` profile |
| -------------------------------------------------------------------------------- | -------------------------------- | ------------------- |
| `oms_submit_ack_ms`                                                              | `p(95)<300`                      | `p(95)>=<delay_ms>` |
| `oms_ack_missing` (no ack within 5 s, `SUBMIT_TIMEOUT_S`, `oms/commands.py:289`) | `count==0`                       | `count==0`          |
| `oms_submit_refused` (non-202, no link)                                          | `count==0`                       | `count==0`          |
| `oms_backend_added_p95_ms`                                                       | report-only (opt-in `value<=50`) | not gated           |

## How to run against the dev stack

1. Start the account fixture stack (the compose line in `infra/compose/docker-compose.account-fixture.yml`) with
   `CV_ACCOUNT_FIXTURE=compliant`. Before the api starts, put `order_lane.json` in its `CV_ACCOUNT_FIXTURE_DIR` volume,
   for example `{"mode": "pack", "delay_ms": 100, "jitter_ms": 10, "seed": 7, "fill": false}` (#977 slice 1b). `fill` false: with true the lane fills every priced create, so no order rests and the open-order cap means nothing; with false the orders rest, as the Orders bullet says. It is
   read once at boot; restart the api to change it.
2. Seed the roster (`python -m cvdev.account_fixture.seed users --run-dir <dir>`), register a demo account on a pack
   key as `docs/ops/runbooks/account-fixture-stack.md` ("Drive it") does, and give its default profile trading on and the symbol allowed.
3. Run the pinned k6 (`AGENTS.md` §4). The password and TOTP seed come from the seed run directory and are never
   committed or printed. `CV_E29_USER_FILE` (0600) holds `{"identifier": "<owner>", "totp_seed": "<base32>"}`.

```sh
k6 run -e BASE_URL=http://127.0.0.1:8000 -e CV_E29_FIXTURE_STACK=1 \
  -e CV_E29_PASSWORD=... -e CV_E29_USER_FILE=<file> -e CV_E29_ACCOUNT_IDS=<uuid> \
  -e CV_E29_PRICE=<limit inside the instrument's bounds> -e CV_E29_PACK_DELAY_MS=100 \
  tests/load/k6/oms/oms_submit_ack.js
```

Optional: `CV_E29_SYMBOL` (`BTCUSDT`), `CV_E29_QTY` (`0.001`), `CV_E29_SL_PERCENT` (`1`), `CV_E29_RUN_S` (`120`),
`CV_E29_RATE_MS` (`500`, per account), `CV_E29_SUMMARY`. Start runs at least 30 s apart: the API refuses a spent TOTP
step. The guard refuses a target that is not loopback or `api`, any exchange host (C-13.5), and a run without
`CV_E29_FIXTURE_STACK=1`.

## Calibration self-test (BQ-09)

Set `delay_ms` to `100`, restart the api, and run with `-e CV_E29_PROFILE=calibrate -e CV_E29_PACK_DELAY_MS=100`. **One**
pack draw is timed: the timer stops at `change` `ack`, which the OMS emits when the create's REST answer completes
`place` (`B01.order.machine.json:137-143`, `order_steps.py:504`); the pack's push frame is never mapped to `ack`
(`ws_topics.py:151-160`). At delay 100 / jitter 10 the p95 is therefore about 110-140 ms, and the gate floor stays one
draw (100 ms). Under it, the timer misses the venue leg and k6 exits non-zero. The profile refuses a delay under 100 ms,
and `compare_baseline.py` refuses its summary (`cv_profile: calibrate`).

## Gate

`compare_baseline.py` compares the median of three `gate` runs of `oms_submit_ack_ms` p95, `oms_submit_http_ms` p95
and `oms_backend_added_p95_ms` with `baseline.json` at +5 % (06 §7.4, C-13.9), into `compare.json` and `compare.md`.
In `warn-only` (now) a value over +5 % or from fewer than three runs WARNs, and a `null` value is `NO-BASELINE`; in
`gate` those fail, as does a missing metric. Values come only from a green CI run, through a reviewed "update
performance baseline" PR that also moves `mode` to `gate`.

## Deviations

- #977 names `tests/load/oms_submit_ack.js`; it lives under `tests/load/k6/oms/` with its own `lib/` (BQ-07).
- The venue leg is the fixture pack's delay model, not Bybit demo (BQ-02, option (b), ruled 2026-11-04); the demo leg is
  owner-run (BQ-03). The kit is its own copy under `tests/load/k6/oms/` (BQ-07). Rulings: the BQ list
  [#977 comment 6624896607](https://github.com/CandleViewer/CandleViewer/issues/977#issuecomment-6624896607) and the
  blocker note [comment 6624931622](https://github.com/CandleViewer/CandleViewer/issues/977#issuecomment-6624931622).

## Results

| Date     | Run | Profile | Status | Notes |
| -------- | --- | ------- | ------ | ----- |
| none yet |     |         |        |       |
