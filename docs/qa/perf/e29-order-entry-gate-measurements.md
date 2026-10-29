# E29 order-entry gate: #964's integration measurements (#3382)

Status: **recorded readings (2026-10-29, four local runs of the integration module, all passed).**
Four of the five criteria hold with wide margins. One part of criterion 1 does not: a refusal on
`POST /orders` is **not** counted in `cv_order_entry_refusals_total{reason}` (finding F1 below). No
production code was changed. No number in this file is invented: each figure is one run's
`MEASURED` line, printed by the test module.

## What was measured, and how

- **Module:** `services/api/tests/integration/oms/test_order_entry_gate_measured_pg.py`
  (`@pytest.mark.integration`, four tests, one a strict `xfail` on F1).
- **Stack, one process per test:**
  - Postgres 16: `postgres:16-alpine` through testcontainers, migrated to head as C6's `pg_dsn` does.
  - `build_feature_flags` over that database, as `create_app` builds it: the flag service, the
    `FlagWriter` that `PUT /admin/feature-flags/{flagKey}` calls, the maintenance gate and its 5 s
    poll. Its gate is composed with an admitting account check and handed to the OMS runtime.
  - The OMS runtime behind `POST /orders` and the exit routes, served as
    `test_place_order_route_pg._serving` serves them, with a `FakeTradingPort` as the venue (C-13.5).
  - The WS gateway: `make_ws_router` with the conformance harness's wiring, served by uvicorn 0.54
    (`websockets-sansio`) on a loopback socket. Three sessions connect over real sockets
    (websockets 17.1 client, `cv.v1.json`), each authenticated, each getting the `auth_ok` snapshot.
- **Clock and origin:** every latency is read on one `time.perf_counter`.
  - A flag write is timed from its COMMIT: the instant the store's row-locked write returns, before
    the writer runs any change hook.
  - A change made in the database is timed from the instant its autocommitted `UPDATE` returns.
  - A store outage is timed from the instant the relay in front of the flag runtime's Postgres is cut.
- **Refusal probe:** the order that measures the refusal is sent the moment the row commits, while
  the writer is still running its hooks and records. Any client's order may arrive then.
- **Repetitions:** each figure is the median and maximum of N = 20 repetitions in one run. A push
  figure is, per repetition, the last of the three sessions to receive the frame.
- **CI repetition count:** in CI the two kill-switch TTL tests run 10 repetitions each (about 100 s
  per test; each repetition waits about two 5 s polls), set by `TTL_REPS`, which reads
  `CV_E29_TTL_REPS` (default 10). At 10 the nearest-rank p90 is the ninth value, so one late poll is
  absorbed; at 5 it would be the maximum. The TTL figures here are N = 20, reproduced with `CV_E29_TTL_REPS=20`. The other
  measurements run at N = 20 everywhere. At either count, fail-closed on TTL expiry and on an
  unreachable flag store is asserted on every repetition, and the 5.5 s bound is unchanged
  (orchestrator ruling, 2026-10-29).
- **What is asserted:** each budget is asserted on the nearest-rank p90 of the 20 repetitions (the
  18th slowest), not on the maximum. On this shared host one scheduling stall can put a single
  reading far past a budget the product meets: a reviewer's re-run under a load of 11.5-14 read a
  refusal median of 28.6 ms with one 505.3 ms outlier, and a max assertion failed (C-13.7). The
  maximum and the slowest three readings are still printed and recorded here. The p90 statistic is
  ratified by the orchestrator (2026-10-29): the safety properties (the 403, no venue create, the
  audit reason) are asserted on all 20 repetitions, the one 505.3 ms outlier at a load of 11-14 is
  the written host-load exception, and on a quiet host the maximum is the figure of record.
- **Host:** the shared 8-vCPU VPS. Other lanes' test runs were active, the 1-minute load average was
  about 11-14, and pytest ran under `nice -n 10`, one process at a time. The figures are an upper
  reading for a quiet host, not a reference-host benchmark.

```text
cd services/api
PATH=<a psql on PATH; C6's pg_dsn bootstraps roles with it>:$PATH \
  pytest -m integration --no-cov -s tests/integration/oms/test_order_entry_gate_measured_pg.py
```

## Results

All latencies are in milliseconds, shown as median / max over N = 20. Run 4 is the run after
review, with the p90 that each budget is now asserted on.

| Measurement                                                                     | Budget | Run 1           | Run 2           | Run 3            | Run 4, median / p90 / max |
| ------------------------------------------------------------------------------- | ------ | --------------- | --------------- | ---------------- | ------------------------- |
| Refusal (403 `reason: maintenance`) after the maintenance commit                | 200    | 23.9 / 33.1     | 21.9 / 27.6     | 20.6 / 29.7      | 26.1 / 39.1 / 57.5        |
| `feature_flags` frame, last of 3 sessions, maintenance on                       | 2 000  | 7.1 / 15.8      | 6.1 / 10.8      | 5.8 / 9.3        | 6.1 / 8.8 / 10.9          |
| Maintenance notice, last of 3 sessions, maintenance on                          | 2 000  | 7.0 / 15.8      | 6.1 / 10.8      | 5.8 / 9.3        | 6.0 / 8.8 / 10.9          |
| `feature_flags` frame, last of 3 sessions, maintenance off                      | 2 000  | 4.8 / 10.6      | 4.3 / 11.2      | 4.5 / 38.5       | 4.8 / 12.4 / 22.5         |
| Maintenance notice, last of 3 sessions, maintenance off                         | 2 000  | 4.7 / 10.6      | 4.3 / 11.2      | 4.4 / 38.5       | 4.8 / 12.4 / 22.5         |
| Flag write returned after its commit (writer hooks and records)                 | none   | 21.8 / 33.1     | 19.2 / 27.6     | 17.9 / 24.8      | 23.1 / 37.5 / 56.1        |
| Entry accepted (202) after the release commit                                   | none   | 233.7 / 325.3   | 184.2 / 279.8   | 191.1 / 271.0    | 256.3 / 315.8 / 333.9     |
| `killswitch.order_entry` set in the database, until the gate closed             | 5 500  | 4983.0 / 5020.7 | 4982.5 / 5048.4 | 4982.9 / 5147.2  | 4975.6 / 5020.5 / 5177.9  |
| `killswitch.order_entry` cleared in the database, until the gate opened         | 5 500  | 4960.1 / 5098.1 | 4951.6 / 4973.5 | 4955.5 / 4979.5  | 4948.3 / 4997.8 / 5024.1  |
| Flag store unreachable, until the gate closed                                   | 5 500  | 5006.5 / 5031.8 | 5010.2 / 5060.3 | 5006.8 / 5029.8  | 5007.2 / 5022.0 / 5030.4  |
| Flag store reachable again, until the gate opened                               | none   | 5088.1 / 5166.7 | 5237.6 / 5305.8 | 5184.9 / 10765.4 | 5238.9 / 5268.6 / 5302.3  |
| `cv_order_entry_refusals_total{reason="maintenance"}` increase over 20 refusals | +20    | +0              | +0              | +0               | +0                        |

### Reading the kill-switch rows

The 5 500 ms bound is the poll period plus one read budget: `REFRESH_S = KILLSWITCH_TTL_S = 5 s`
plus `flags.read_budget_ms`, default 500 ms.

Each repetition starts just after the poll that applied the previous transition. So every reading
sits near the worst phase of the 5 s period, not spread uniformly across it.

## Verdict per criterion

1. **Refusal within 200 ms of the commit: PASS. Counted in `cv_order_entry_refusals_total{reason}`:
   FAIL (F1).**
   - Every probe got the gate's `403 trading_disabled` with `reason: "maintenance"`, worst
     57.5 ms over the four runs (p90 at most 39.1 ms). No create reached the venue.
   - The refusal was recorded write-ahead as `account.disabled_by_policy` with reason `maintenance`,
     20 of 20.
   - The gate is closed by `MaintenanceController.gate_hook`, the first change hook. It runs with no
     await after the commit, so an order the loop serves after the commit meets the closed gate.
   - The count is asserted by `test_a_maintenance_refusal_is_counted_with_its_reason`, marked
     strict `xfail` on F1: it fails today, as F1 says, and turns red once F1 is fixed, so that fix
     must remove the mark.
   - **Scope:** this holds in the process whose writer commits. Another process reads the row on its
     own 5 s poll, within the kill-switch bound below.
2. **The gate is consulted on `POST /orders`, and the native stop is attached: PASS.**
   - Each run has 21 accepted entries: one before the loop and one per release.
   - Every create the venue took carries `stop_loss = 58000`, the request's native stop, and is not
     reduce-only.
   - This is the only create path the module drives. The amend path is covered under criterion 3.
   - The gate under test is `create_app`'s maintenance slot composed with an admitting account
     check (`_Admits` stands in for `account_health.order_entry_check`). So "the gate is
     consulted" is shown for the maintenance and kill-switch legs only; the account legs are
     #4894's tests.
3. **Native stops untouched under maintenance: PASS.**
   - A position seeded at the venue with a native stop of 57000 keeps it through 21 maintenance
     toggles.
   - No `set_trading_stop` call is made in any run.
   - Under maintenance, a stop-tightening amend (58000 to 59000) answers 202, and the venue's amend
     carries `stop_loss = 59000`.
   - All 21 resting entries are cancelled with 202.
   - Under the kill switch and the store outage, both entries' cancels answer 202 (C-2.6, C-4.14).
4. **The push reaches three sessions within 2 s: PASS.**
   - In every repetition, all three sessions received the `feature_flags` frame carrying
     `maintenance.mode` and the `maintenance.enabled` / `maintenance.disabled` notice.
   - The worst latency was 38.5 ms against the 2 000 ms budget.
5. **Kill-switch TTL, fail closed end to end: PASS.**
   - **What exists:** `KILLSWITCH_TTL_S = 5` (`admin/flags/service.py`). A kill-switch-class flag is
     served from the cached snapshot for at most 5 s.
   - `MaintenanceController.run` re-reads `maintenance.mode` and `killswitch.order_entry` every
     `REFRESH_S = KILLSWITCH_TTL_S`, after `FlagService.invalidate()`, so each read is a fresh load.
   - A failed or over-budget load is unknown (`FlagService._load`, `resolve`'s fail-closed value).
     Unknown keeps the gate engaged, and the gate starts engaged until both flags are read.
   - The B18 kill switch is still `InterimKillSwitch` (`oms_wiring.py`). It admits every order and
     has no TTL, so E39-S03 remains open. `killswitch.order_entry` stops order entry through the
     maintenance gate.
   - **Measured, flag set by a statement in the database (not by the writer):** order entry closed
     within at most 5177.9 ms, against the 5 500 ms bound.
   - **Measured, flag store unreachable (the state cannot be confirmed):** order entry closed within
     at most 5060.3 ms.
   - In both cases `POST /orders` was then the 403 while cancels passed.
   - **What the TTL is, and is not:** it bounds how stale the gate's reading may be while
     `MaintenanceController.run` is polling. It is not a dead-man on the gate: the gate holds a
     plain bool that only that poll task refreshes, and the task is started with a stored
     reference but no done-callback. If the task ended other than through `stop()`, the gate would
     keep its last value, open if it was open, with no alert. These measurements show fail-closed
     while the poll lives. A done-callback that logs and pages, or a watchdog that engages the gate
     when no refresh completed within 2 x `REFRESH_S`, is tracked with F1 in #4973.
   - **Margin:** each repetition starts just after a poll, so the closing readings sit at about
     4.98-5.18 s against the 5.5 s bound, about 350 ms of margin under a load of 11-14. It is the
     thinnest margin in the module.
   - Reopening after the store came back has no budget. It is reported above. In one discarded
     local run under load it took longer than 15 s, and run 3's maximum was 10.8 s, so the module
     waits up to 60 s for it. Under heavier load this row is the most likely to approach its bound.

## Finding F1: `POST /orders` refusals are not counted in `cv_order_entry_refusals_total`

- **Where it is counted:** `cv_order_entry_refusals_total{reason}` is incremented only in
  `api.order_entry_gate.order_entry_refusal()`, and no route calls that function.
- **What `POST /orders` does instead:** it refuses through the OMS (`TradingSwitchesBinding` raises
  `OrderEntryRefused`). The route's `audit_refusal` then records the refusal and counts it in
  `oms_submit_rejected_total{code="trading_disabled"}`. That route-side count was read from the
  code, not measured here.
- **Effect:** the series that `20-architecture.md` §12.1 and the metrics catalogue name for the
  order-entry gate stays at 0 while maintenance refuses orders. The `order_entry_refused` log line
  never fires either. `oms_submit_rejected_total{code="trading_disabled"}` is the label that
  `TradingDisabled` (live trading not enabled) also uses, so on no metric can a maintenance window or
  a kill switch be told from live-disabled. Enforcement and the audit record (C-2.9) are intact;
  what is missing is the observability of a safety control.
- **Fix, for a follow-up ticket:** count `order_entry_refusals_total.labels(reason)` and emit
  `order_entry_refused` once at the OMS choke point, where `OrderEntryRefused` is built, or in
  `audit_refusal` when the error is an `OrderEntryRefused`; then remove the strict `xfail` mark.
- **Status:** reported, not fixed here, as the brief requires. The fix is #4973, which also covers the
  unsupervised maintenance poll task above. Until it lands, #964's counter clause is unmet, and the
  strict `xfail` test keeps the gap visible.
