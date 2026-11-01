# E27-Q03 (#892): account load, chaos and soak harness (PR-1 plan)

Status: PR-1 of #892 (the harness), built to the orchestrator's rulings of record (#892 comment
6555033109, 2026-11-01). Every place a ruling applies is marked `BQ-nn` (here as `<!-- BQ-nn -->`,
in code as `// BQ-nn` or `# BQ-nn`), and **every `BQ-nn` marker is RULED (orchestrator,
2026-11-01, #892 ruling of record 6555033109)**; section 0 says what each ruling is. A number
the rulings do not name carries no `BQ-nn` marker: it is marked PROPOSED, with its owner, and listed
in section 0a. What ran at
build time: the harness-guard tests, the in-process KEK, memory and alert-rule tests, the seed tests,
ruff, black, mypy `--strict`, a syntax parse of the k6 scripts and an in-process measure of the
stub's own cost. What did not: the stack cases, the k6 scripts and the soak (no account fixture
stack and no k6 binary on the build machine); the results PR runs them. Sources are origin/main as
fetched on 2026-11-01.

## 0. Rulings of record

All rows: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

| BQ    | Ruling                                                                                                                                                                                                                                                                                                                                                                                             | Lands in                                |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| BQ-01 | Accepted: scripts under `tests/load/`, chaos under `services/api/tests/chaos/accounts/`, documents where the ticket names them; the claimed branch `test/e27-health-load-chaos` is kept                                                                                                                                                                                                            | section 1                               |
| BQ-02 | Accepted: k6 for REST and WS, the Python sampler for the soak, pytest for chaos; no Locust (C-13.9 scopes it to ingestion)                                                                                                                                                                                                                                                                         | section 1                               |
| BQ-03 | Accepted: the #2893 stub as is, its own cost measured first; the "raise a Bug" branch is a finding row (filing freeze)                                                                                                                                                                                                                                                                             | section 7, F7                           |
| BQ-04 | Amended: six registered accounts with their own UIDs and key ids, fixture data only in `cvdev/account_fixture/seed.py` (`ACCOUNTS`), no behaviour change; #2893's owner is told (the note is the build's, posted outside this PR)                                                                                                                                                                  | section 4 item 2, F6                    |
| BQ-05 | Accepted: C-13.6 numbers 2, 4, 5 and 6; the KEK case is outside the 14                                                                                                                                                                                                                                                                                                                             | section 2                               |
| BQ-06 | Accepted for netem: C-13.6 names outcomes, not mechanisms, and every chaos suite injects in process (recorded against the ticket's tech note). Amended for the KEK: start-time (TC-120) and running-time, each asserting the shipped behaviour; where the code does not do what the ruling names, a finding row, not a code change and not a skipped test                                          | E27-C5a, E27-C5b, F1 to F5              |
| BQ-07 | Ruled: the probe's documented tolerance is **5 %** (06 section 7.4's gate), interim — ruled 2026-11-01, owner ratification on #2701; 06 row 13 p95 < 150 ms; the wallet throttle 500 ms (`23`:861). Nothing else: the soak bands and the 50 ms wallet tolerance are not ruled (section 0a, PROPOSED)                                                                                               | E27-L1, E27-L2, E27-L3                  |
| BQ-08 | Accepted: a signed read-only probe on the same account set, the substitution recorded                                                                                                                                                                                                                                                                                                              | E27-L2, section 4 item 3                |
| BQ-09 | Accepted, with the runner fact: hosted runners stop at 6 h, so the 24 h soak is a dispatch-only workflow on the self-hosted bench group that never runs a PR's code (the `perf-engine-matrix.yml` rule); that workflow edit rides PR-2 with `security-review`, not PR-1. Two PRs: PR-1 harness `Refs #892` with `Partial:`, PR-2 results with the closing line                                     | E27-S1, section 3                       |
| BQ-10 | Accepted: the in-process cases run in the PR lane; the stack cases and k6 are dispatch profiles; no accounts nightly without a workflow edit, which rides PR-2. Narrowing recorded: the ruling reads "chaos pytest in the PR lane", but only the in-process cases run there; the stack cases are deselected and, with no workflow in PR-1, run nowhere automatically until PR-2's dispatch profile | section 3                               |
| BQ-11 | Accepted: the loopback or compose-name allow-list, unit-tested                                                                                                                                                                                                                                                                                                                                     | `test_e27_harness_guards.py`            |
| BQ-12 | Accepted: two PRs; no closing keyword in PR-1's body or commits                                                                                                                                                                                                                                                                                                                                    | section 1                               |
| BQ-13 | Accepted: the results file plus raw exports; Grafana screenshots dropped, and that is recorded in the results                                                                                                                                                                                                                                                                                      | section 2, "Results go to"              |
| BQ-14 | Amended: the memory criterion is met in process by a walk of live objects after the signing call returns; the critical alert by a rule-unit test of the alert expression against the metric, not a live Alertmanager; both are narrowings (section 4)                                                                                                                                              | E27-M1, E27-A1, section 4 items 5 and 6 |

## 0a. Proposed numbers (not ruled)

BQ-07 rules three numbers and no others. These are PROPOSED; each moves only by a reviewed change,
is pinned by `test_e27_harness_guards.py`, and is ratified on #2701 or in the results PR. Owner: the
06 owners (Architect and Backend leads, `docs/plan/06-performance-and-load-standard.md` line 3).

| Number                                                     | Where                                                        | Reconciled with 06                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Soak RSS band 512 KiB/h                                    | `soak_sampler.py` `BAND_PER_H`                               | Not 06's number. 06 line 213 rules 0.18 MB/h (a MiB) on the per-symbol RSS of the bars soak over the last 12 h, from (300 - 170) MB over 30 days; the account monitor has no 06 memory row, and the sampler reads one process's RSS. The estimator, window and sample floor are 06's (Theil-Sen, last 12 h, at least 100) |
| Soak bands for fds, connections and tasks, 0.5/h each      | `soak_sampler.py` `BAND_PER_H`                               | 06 has no such row; 06 lines 174 and 212 ask for "a documented variance band" without a number                                                                                                                                                                                                                            |
| Wallet throttle tolerance 50 ms                            | `tests/load/k6/accounts/lib/thresholds.js`                   | 06 has no wallet row; 23 line 861 rules the 500 ms throttle and names no tolerance                                                                                                                                                                                                                                        |
| Boot allowance 2 reads, per-key burst cap (set by the run) | `request_log_check.py` (`--boot-allowance`, `--per-key-max`) | 06 has no per-key number; the results file records the values used                                                                                                                                                                                                                                                        |

## 1. What PR-1 ships <!-- BQ-12 -->

PR-1 is the harness only: `Refs #892`, with a `Partial:` line that says the results, the 24 h soak
reading and the go/no-go come in PR-2 (`qa/results/e27/`), which carries the closing line. No
production code, so no safety-invariant path is touched; the one change outside the test trees is
fixture data in the dev-only `cvdev/` package (BQ-04). The size is above the 400-line preference: it
is almost all new test code, and the PR body carries the "why this cannot be split" note; the size
label is the orchestrator's. <!-- BQ-12 -->

| File                                                           | Purpose                                                                                               |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `tests/load/k6/accounts/lib/guard.js`                          | target allow-list for the k6 scripts <!-- BQ-11 -->                                                   |
| `tests/load/k6/accounts/lib/session.js`                        | sign-in (password, TOTP) as in `tests/load/k6/auth.js`                                                |
| `tests/load/k6/accounts/lib/thresholds.js`                     | every number the k6 scripts gate on, pure, pinned under node by the guard tests                       |
| `tests/load/k6/accounts/health_poll.js`                        | E27-L1                                                                                                |
| `tests/load/k6/accounts/key_verify_burst.js`                   | E27-L2                                                                                                |
| `tests/load/k6/accounts/wallet_fanout.js`                      | E27-L3 <!-- BQ-02 -->                                                                                 |
| `tests/load/accounts/guard.py`                                 | the same allow-list for Python                                                                        |
| `tests/load/accounts/request_log_check.py`                     | judges the stub's request log after L1 and L2                                                         |
| `tests/load/accounts/soak_sampler.py`                          | E27-S1 sampler and judge <!-- BQ-09 -->                                                               |
| `services/api/tests/chaos/accounts/_e27_stack.py`              | chaos helper: switch CLI, request log, REST, `/metrics`                                               |
| `services/api/tests/chaos/accounts/test_e27_health_chaos.py`   | E27-C1 to C4 (marked `chaos` and `harness`)                                                           |
| `services/api/tests/chaos/accounts/test_e27_kek_and_memory.py` | E27-C5a, E27-C5b, E27-M1, E27-A1: in process, no stack, ordinary PR lane <!-- BQ-06 --><!-- BQ-14 --> |
| `services/api/tests/chaos/accounts/_e27_memory_probe.py`       | E27-M1's walk and its control, run in a fresh interpreter; a module, not a test                       |
| `services/api/tests/chaos/accounts/test_e27_harness_guards.py` | harness self-tests, no stack, ordinary PR lane                                                        |
| `services/api/tests/chaos/accounts/_e27_stub_cost.py`          | the stub's own cost per signed call, in process (F7); a script, not a test                            |
| `services/api/cvdev/account_fixture/seed.py`                   | `ACCOUNTS`: six registered accounts, fixture data only <!-- BQ-04 -->                                 |
| `services/api/tests/unit/cvdev/test_account_fixture_seed.py`   | pins `ACCOUNTS` (six, own UIDs and key ids, pack key ids, plan 9.2) <!-- BQ-04 -->                    |
| `qa/plans/e27/chaos.md` (this file)                            | the plan, the rulings and the scenario table <!-- BQ-01 -->                                           |

Paths follow option (c) of BQ-01: scripts in the QA load home (C-13.8), chaos beside the existing
`services/api/tests/chaos/accounts/`, documents where the ticket names them. The ticket's
`infra/k6/accounts/` and branch `chore/e27-load-chaos` are a recorded deviation; the branch is
`test/e27-health-load-chaos`.

## 2. Scenario table

Fixtures: the E27-Q01 pack and the #2893 stub on the compose stack (`infra/compose/docker-compose.account-fixture.yml`);
faults are pack scenarios plus `python -m cvdev.account_fixture.cli switch|clock` <!-- BQ-03 --><!-- BQ-06 -->.
"06" is `docs/plan/06-performance-and-load-standard.md`.

| ID      | Scenario                                                                                                          | Harness                                                                                             | C-13.6                                         | Threshold                                                                                                                                                    | Pass / fail rule                                                                                                                                                                                                                                                                                                                             | Results go to                                      |
| ------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| E27-L1  | Steady health polling: 5 users, one read per 60 s each for 30 min, then 1 read/s each for 5 min (one VU per user) | `health_poll.js`, then `request_log_check.py cache`                                                 | none (load)                                    | 06 section 2 row 13: read p95 < 150 ms <!-- BQ-07 -->                                                                                                        | k6 thresholds on both stages (`p(95)<150`, failures < 0.1%); log check: at most 2 signed wallet reads per key at boot (not ruled: the run records the allowance), then at most 1 per 60 s window; no signed wallet read in the log fails                                                                                                     | `k6-summary-health-poll.json`, log-check line      |
| E27-L2  | Verification burst: every stored key tested at one instant, 3 rounds 65 s apart, plus a read-only probe at 1/s    | `key_verify_burst.js`, then `request_log_check.py burst`                                            | none (load)                                    | probe p95 within **5 %** of the no-burst baseline (median of 3 runs; 06 section 7.4): interim — ruled 2026-11-01, owner ratification on #2701 <!-- BQ-07 --> | `e27_false_pass == 0` (a pass with `rest.ok == false`); probe threshold; no order endpoint in the log during the burst; per-key call count at or below the cap the run sets                                                                                                                                                                  | `k6-summary-key-verify-burst.json`, log-check line |
| E27-L3  | Private `wallet` topic to 5 connections, on `compliant`'s 5 s wallet frame (`every_ms` 5000)                      | `wallet_fanout.js`                                                                                  | none (load; 11 does not apply: no slow client) | 23 section 6.2: throttle 500 ms (`23`:861) <!-- BQ-07 -->; 06 has no wallet row. Not exercised by a 5 s stream (F9)                                          | pacing: one account's median gap within 500 ms of the manifest's 5000 ms; floor: `e27_wallet_gap_ms` p5 >= 450 ms (tolerance 50 ms, PROPOSED, section 0a; trivially met at 5 s, not a throttle test); `e27_wallet_seq_gaps == 0`; `cv_ws_overflow_total` flat; at least 20 frames per connection, enforced by `checks` rate 1 <!-- BQ-02 --> | `k6-summary-wallet-fanout.json`                    |
| E27-C1  | Private WS dropped and refused, REST 503, held 5 min, then restored                                               | `test_private_ws_drop_goes_degraded_then_down_then_recovers` (scenario `ws_drop_rest_fail`)         | 2                                              | heartbeat cap 10 s, down cap 30 s (`ACCOUNT_HEARTBEAT_MAX_S`, `ACCOUNT_DOWN_MAX_S`; US-ACCT-010; not a 06 row)                                               | degraded within 5 + 10 s + tick tolerance; down within 5 + 30 s + tick tolerance; down-transition metric moves; never healthy during the hold; healthy again within 120 s of the switch back, no restart                                                                                                                                     | chaos run log, `q03-load-chaos.md`                 |
| E27-C2  | Bybit 5xx during a self-check (read path), 2 min                                                                  | `test_rest_5xx_during_self_check_fails_closed_and_keeps_prior_verdict` (`bybit_5xx`)                | 4 (read path; not order submit)                | none in 06                                                                                                                                                   | `/test` answers 200, `passed` false, `rest.error` `service_unavailable`, no `verification`; `cv_key_verification_total{result="passed"}` flat, `inconclusive` rises; `last_verified_at` unchanged                                                                                                                                            | chaos run log                                      |
| E27-C3  | Rate limit `10018` on the self-check path                                                                         | `test_rate_limit_10018_on_self_check_is_inconclusive_and_does_not_loop` (`rate_limited_10018`)      | 5 (the reserve half is not asserted)           | none in 06                                                                                                                                                   | `rest.error` `rate_limited`, no `verification`, passed counter flat, no further call to the stub for 30 s after the first pass                                                                                                                                                                                                               | chaos run log                                      |
| E27-C4  | Clock beyond `recv_window`                                                                                        | `test_clock_drift_beyond_recv_window_reports_the_clock_reason` (`clock_skew`)                       | 6                                              | none in 06                                                                                                                                                   | `rest.error` `clock_drift`, no `verification`, passed counter flat                                                                                                                                                                                                                                                                           | chaos run log                                      |
| E27-C5a | KEK refused at start (plan TC-120), in process                                                                    | `test_kek_refused_at_start_refuses_key_operations_and_fires_the_page`                               | none (outside the 14; ADR-0009)                | none                                                                                                                                                         | M2 degraded, order entry read-only; add, rotate and verify each raise `KekUnavailable`; `cv_kek_degraded_state` 1 and the `KekUnavailable` page rule fires on it <!-- BQ-06 -->                                                                                                                                                              | PR lane log                                        |
| E27-C5b | KEK source refuses after start, in process                                                                        | `test_kek_refused_after_start_signing_goes_on_from_memory`                                          | none (outside the 14; ADR-0009)                | none                                                                                                                                                         | signing goes on from the KEK in memory and the source is not read again. The ruled refusals and the alert are not what the code does today: F1 to F5, not asserted <!-- BQ-06 -->                                                                                                                                                            | PR lane log, section 7                             |
| E27-M1  | No plaintext credential in live memory after a signing call                                                       | `test_no_live_object_holds_the_marker_secret_after_signing` (control: `..._untracked_container`)    | none                                           | none                                                                                                                                                         | a walk of every object the collector reaches, and the untracked containers under them, finds no str, bytes or bytearray holding the marker secret; the control proves the walk finds a held one <!-- BQ-14 -->                                                                                                                               | PR lane log                                        |
| E27-A1  | The critical alert for a KEK loss                                                                                 | `test_kek_refused_at_start_...` and `test_the_page_rule_evaluator_fires_only_on_the_degraded_value` | none                                           | `KekUnavailable`: `max by (env) (cv_kek_degraded_state) == 1`, `for: 0m`, `severity: page`                                                                   | the rule's own expression, read from `infra/prometheus/alerts/system_page.yml`, evaluated against the gauge M2 sets: fires at 1, silent at 0 and absent; another expression shape fails the test <!-- BQ-14 -->                                                                                                                              | PR lane log                                        |
| E27-S1  | 24 h mini-soak on the fixture stack                                                                               | `soak_sampler.py run`, then `judge`                                                                 | none                                           | 06 section 9 backend-memory row (06 line 213): Theil-Sen slope over the last 12 h, at least 100 samples                                                      | slope of RSS, fds, connections and tasks within the PROPOSED bands (512 KiB/h, 0.5/h, 0.5/h, 0.5/h; section 0a); end state equals the scenario's truth (`--expect` required); a missing series fails, never passes <!-- BQ-09 -->                                                                                                            | `soak.csv`, judge output                           |

Each stack chaos case runs twice (`RUNS = [1, 2]`) and puts the key back on `compliant`. The stack
module carries `chaos` and `harness`, not `integration`: the default addopts and the py lane
deselect `harness`, and the integration lane selects `chaos and integration`, so none of them
collects it; a run that names `-m "chaos and harness"` does. Without the stack its `api` fixture
fails loudly (a stack-less run is an error, never a pass). The in-process module
(`test_e27_kek_and_memory.py`) carries no marker and runs in the ordinary PR lane.

## 3. How to run (stack cases not run yet)

- Stack: the compose line in the override file's header, `CV_ACCOUNT_FIXTURE=compliant`; seed with
  `python -m cvdev.account_fixture.seed users --run-dir <dir>`. Before a load run, switch each key of
  `seed.ACCOUNTS` to `compliant` (`python -m cvdev.account_fixture.cli switch <key> --to compliant`)
  <!-- BQ-04 -->.
- k6: `k6 run -e BASE_URL=... -e CV_E27_FIXTURE_STACK=1 -e CV_E27_PASSWORD=... -e CV_E27_USERS_FILE=... <script>`
  with the pinned k6 of AGENTS.md section 4. The password and TOTP seed come from the seed run directory
  and are never committed or printed.
- Chaos on the stack: `CV_E27_STACK=1 CV_E27_RUN_DIR=<dir> CV_E27_USER=<owner> pytest -m "chaos and harness" --no-cov tests/chaos/accounts/test_e27_health_chaos.py`
  from `services/api`. `CV_E27_KEYS` (burst) is the number of signable keys the stack holds.
  Dry runs shorten the holds with `CV_E27_WS_HOLD_S`, `CV_E27_5XX_HOLD_S`.
- In process: `pytest tests/chaos/accounts/test_e27_kek_and_memory.py tests/chaos/accounts/test_e27_harness_guards.py`
  from `services/api`; they run in the ordinary PR lane (the guard tests need `node` on the path).
- Burst baseline: `key_verify_burst.js` stops at init unless `CV_E27_PROBE_BASELINE_P95_MS` holds
  the no-burst baseline p95 (the median of 3 probe-only runs, 06 section 7.4); there is no default.
- Stub cost (F7): `uv run python -m tests.chaos.accounts._e27_stub_cost --calls 1000` from
  `services/api`.
- Soak <!-- BQ-09 -->: hosted runners stop at 6 h, so the 24 h run is a dispatch-only workflow on the
  self-hosted bench group that never runs a PR's code (the `perf-engine-matrix.yml` rule). That
  workflow edit carries `security-review` and rides PR-2, not PR-1. If the self-hosted runner is
  offline when PR-2 is due, the soak is recorded as **owner-run (OR)**, with the harness proven at
  1 h on a hosted runner.
- CI <!-- BQ-10 -->: no workflow is edited in PR-1. The accounts dispatch profile and any accounts
  nightly are workflow edits and ride PR-2 with `security-review`. "Green twice on main" means two
  runs after that merge.

## 4. Substitutions, deviations and narrowings (written into the results, not hidden)

1. Stub soak, not the demo environment: no demo keys exist in tests (C-13.5) <!-- BQ-09 -->.
2. Six accounts: `seed.ACCOUNTS` names a main account and five sub-accounts, each with its own UID
   and pack key id (fixture data only). Today no seed command registers them, and the stub answers
   each key with its own scenario's UID, so the run reports how many of the six the stack served,
   never claiming six it did not serve (F6) <!-- BQ-04 -->.
3. "Order path unaffected" is a read-only probe on the same account set, not placed and cancelled orders
   <!-- BQ-08 -->.
4. SCR-079, SCR-126 and SCR-127 are UI timings; k6 reads only their REST part.
5. **Narrowing (alert):** "a critical alert is raised" is validated by a rule-unit test of the
   `KekUnavailable` expression against `cv_kek_degraded_state` (a Python evaluation of the rule
   file the repo uses; no promtool binary in the PR lane, and the generated promtool cases in
   `infra/prometheus/tests/system_alerts.test.yml` stay the CI gate), not by a live Alertmanager or
   a page <!-- BQ-14 -->.
6. **Narrowing (memory):** "no plaintext credential recoverable from memory dumps" is met in process
   by a walk of live objects after the signing call returns, with a fixture marker secret made at
   run time. The walk and its positive control run in a fresh interpreter
   (`tests/chaos/accounts/_e27_memory_probe.py`), so their cost is bounded by what that module
   imports, not by what the lane ran before them. It does not see freed memory not yet reused, or
   copies inside C buffers; a core-dump scan is an owner-run item on the dev host <!-- BQ-14 -->.
7. **Narrowing (KEK):** both KEK cases run on M2's own service with a fake source, not on the
   stack: the control CLI has no KEK command (F1). TC-120's HTTP answers (`403` per route, the
   `system` notice) stay with TC-120; these cases assert the typed error under them <!-- BQ-06 -->.
8. Network faults are injected in process (pack scenarios, the switch CLI), never `tc netem` or a
   proxy: C-13.6 names outcomes, not mechanisms; recorded against the ticket's tech note
   <!-- BQ-06 -->.
9. **Deviation (C-13.7, real waits in the stack cases):** C-13.7 binds every test, and the stack
   cases keep bounded wall-clock waits: the per-key test throttle (`test_e27_health_chaos.py`,
   `TEST_THROTTLE_S`), the 5xx hold (`HOLD_5XX_S`), the 30 s no-retry window, the TOTP step retry
   and the poll step of `wait_until` (`_e27_stack.py`). The fixture clock cannot drive them: the
   control CLI's `clock` moves only the stub's scenario time, exchange time and request-log `ts`
   (`cvdev/account_fixture/cli.py` header), while every one of these timers is the api process's
   own: the throttle stamps `datetime.now(UTC)` (`key_test_wiring.py`), the health ages run on
   `CLOCK_BOOTTIME` (`accounts/health.py`), the TOTP step and the retry schedule run on the host
   clock, and `bybit_5xx` answers 503 at every scenario time. Moving the stub's exchange time ahead
   is also the `clock_skew` fault itself (C4), so advancing it inside another case would add a
   second fault. The harness therefore carries no clock helper; every wait is bounded and polls an
   observable. Recorded per the security read of record 6556583904, item 5. **RULED (orchestrator,
   2026-11-01, #5325 delta look 6557442583): deviation accepted.**

## 5. Not asserted (and why)

- Order entry disabled and the dead-man's-switch call during C1: no observable on a public route; plan
  TC-410 and TC-412 cover them.
- Reserve for stop and cancel under L2 and C3: `exchange/bybit/rate_limit.py` says the reserve is built by
  E34-T02, so there is nothing to assert yet.
- `cv_exchange_rate_limit_remaining{uid}` (ticket): no such series in `metrics_catalogue.py` at the fetch.
- Staleness marker wording on an account read after a failed check: the field is not named in 22; the test
  asserts `last_verified_at` is unchanged instead.
- The running-time KEK refusals of add, rotate and verify and the alert after start: F2 to F5.
- C-13.6 number 2's other half, "during an open order → reconciliation correctness": C1 drops the
  private WS with no order open; no case opens an order on the fixture stack, so reconciliation
  after the drop is not asserted here (the OMS chaos suites own it).
- C-13.6 number 6's other half, "orders halted": C4 asserts the `clock_drift` reason on the
  self-check only; order entry during the drift has no observable on a public route here (as for C1,
  plan TC-410 and TC-412).
- The wallet throttle itself (F9): no pack scenario streams below 500 ms.

## 6. Open questions and UNVERIFIED

1. Whether the stub holds the load on a running stack: its in-process cost is measured (F7); its
   throughput behind the api process at k6 rate is untested until PR-2's run.
2. The pack's `compliant` scenario sends a wallet frame every 5 s (`every_ms` 5000,
   `packages/fixtures/accounts/compliant/manifest.json` lines 76-83); no scenario sends one at or below
   the 500 ms throttle. L3 gates what the stream sends (the median per-account gap against the 5 s
   period, the frame count per connection), and its 450 ms floor is met trivially: the throttle is not
   exercised until a sub-500 ms scenario exists. Adding one touches the E27-Q01 pack (shared hotspot);
   recorded as F9, not built here. UNVERIFIED: whether the gateway forwards an unchanged wallet
   payload; if it does not, L3 sees no frames after the snapshot and fails its frame count.
3. Verified in `observability/metrics.py` and `metrics_catalogue.py`: `process_resident_memory_bytes` and
   `process_open_fds` (the process collector) and `cv_ws_connections_in_use` exist and are sampled. No
   asyncio task-count series exists; until one is named the sampler's task column is empty and the soak
   fails that criterion (F8).
4. Request-log JSON key names beyond `signing_key_id` and `method` (the module docstring names those); the
   first run confirms them.
5. Answered: the fixture clock does not reach the monitor's timers (section 4 item 9).
6. Whether `POST .../keys/{keyId}/test` needs a step-up on the fixture stack, and the roster's Owner username.
7. Shape of the `wallet` sub frame: checked against 23 section 6.2 (the `wallet` row: option
   `exchange_account_ids`, throttle 500 ms), the section 12.1 sub example (`{ch: "wallet", opts:
{exchange_account_ids}}`, `sub_ok` `effective.throttle_ms` 500) and 15.4; not run against the gateway.
8. The pack manifest and plan TC-109 word the clock case as a 502; 22 testApiKey says 200 with `rest.error`.
   The test asserts 22.
9. The label of `cv_key_verification_total` is `result` (verified in the catalogue, with `rule`); the
   health series are `cv_account_health_state{state,reason}` and `cv_account_health_transitions_total{state,reason}`.
10. The cases pick the one signable key whose `key_id_masked` ends in `CV_E27_KEY_ID`'s 4-digit serial
    (unique in the pack) and fail when there is not exactly one. One account is assumed, as the health
    series carry no account label (a second healthy account would hide a hold); the amber and red waits
    compare with the counts read before the switch, so a state that already stood does not satisfy them.
11. Open pull requests touching `tests/load`, `tests/chaos` or `qa/` were not checked.

## 7. Findings

Recorded, not fixed here (filing freeze, BQ-03): each is a gap between a ruled behaviour and what
the shipped code does at origin/main of 2026-11-01. None is a code change in this ticket and none
is a skipped test.

| ID  | Ruling                                 | Ruled behaviour                                                                               | What the code does today (evidence)                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Owner to decide                      |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| F1  | BQ-06                                  | Inject the KEK source's refusal through the control CLI after start                           | `cvdev.account_fixture.cli` has `clock` and `switch` only; nothing reaches M2's KEK source on a stack. The running-time case uses M2's fake source in process instead (E27-C5b)                                                                                                                                                                                                                                                                                                      | #2893 / E27-X04                      |
| F2  | BQ-06                                  | After start, a new key **add** refuses with a typed error                                     | M2 loads the KEK once ("No runtime re-load; recovery is a restart", `secrets/service.py` docstring); with the source refusing, key import (`mint_candidate_keys`) holds, signs and stores the key under the KEK in memory                                                                                                                                                                                                                                                            | orchestrator (on #892)               |
| F3  | BQ-06                                  | After start, a key **rotate** refuses with a typed error                                      | `rewrap_deks` refuses only by its own staging rules (`kek_rotation_not_staged` here); the source is not consulted                                                                                                                                                                                                                                                                                                                                                                    | orchestrator (on #892)               |
| F4  | BQ-06                                  | After start, a key **verify** refuses with a typed error                                      | a key self-check signs from memory and passes; `verify_kek_possession` answers `kcv_ok` true, `reason` none. Only the admin break-glass `prove_kek_possession` reads the source again, and it returns a reason, not an error                                                                                                                                                                                                                                                         | orchestrator (on #892)               |
| F5  | BQ-06                                  | After start, the critical alert fires                                                         | `cv_kek_degraded_state` stays 0 and health stays OK, so `KekUnavailable` does not fire; the gauge is set only by a failed start or stranded rows                                                                                                                                                                                                                                                                                                                                     | orchestrator (on #892)               |
| F6  | BQ-04                                  | Six registered accounts on the stack, each answered with its own UID                          | no seed command registers accounts or keys (`secrets`, `init` refuse); the stub answers each key with its own scenario manifest's `account_uid` (`transport.py` `_keyed`), and `pack.ACCOUNT_PARENTS` holds three UIDs. Of `seed.ACCOUNTS`, the main account and sub 1 are answered with their own UID; subs 2 to 5 are not                                                                                                                                                          | #2893 (note to its owner)            |
| F7  | BQ-03                                  | Measure the stub's own cost first; if it cannot serve the burst, that is a finding, not a Bug | measured in process by `services/api/tests/chaos/accounts/_e27_stub_cost.py` (command in section 3; `FixtureTransport.handle_async_request`, Python 3.12.12 on Linux x86_64 under WSL2, 1000 signed calls each, request log on disk, the build laptop under its usual load): key info p50 0.88 ms, p95 1.46 ms, about 1000 calls/s; wallet p50 0.80 ms, p95 1.10 ms, about 1200 calls/s, on one loop. Machine-dependent: the results PR re-runs the script and measures on the stack | orchestrator, in PR-2 (#892)         |
| F8  | ticket (soak)                          | Asyncio task count flat over the soak                                                         | no asyncio task-count series exists; the sampler's task column stays empty and the soak fails that criterion until one is named                                                                                                                                                                                                                                                                                                                                                      | orchestrator (on #892)               |
| F9  | BQ-07                                  | The wallet topic holds its 500 ms throttle (`23`:861)                                         | no pack scenario sends a wallet frame at or below 500 ms: `compliant` sends one every 5 s (`every_ms` 5000), so E27-L3's floor is met by the stream's own pacing and cannot fail on a throttle regression. A sub-500 ms scenario touches the shared E27-Q01 pack, not built here; until it exists, the throttle check is an owner-run item                                                                                                                                           | orchestrator; the E27-Q01 pack owner |
| F10 | orchestrator 2026-11-01 17:58Z (#5325) | The memory probe's child exits once its verdict is written                                    | on CI the `signing` child printed its verdict, reported only `MainThread` alive, then waited in interpreter finalization with no Python frame until the parent's 60 s cap (`db-chaos-5`, CPython 3.12.3 Ubuntu build); not reproduced locally (CPython 3.12.12). The child now flushes and ends with `os._exit` after the verdict, which is the child / parent contract; the criterion is proven before it                                                                           | E27 accounts lane (M2), to follow up |
