# E42-Q03 (#1216): admin performance, load and chaos (plan, v1)

Status: v1, with part 1 of 5 (the audit query profile and its harness). Every place a business
question could change is marked `[BQ-n]` (the scout's BQ list for #1216, 2026-11-03). Ruled:
**BQ-1** (orchestrator): #1710 and #1711 belong to #889, so two budgets fail by design until they
land. Every other `[BQ-n]` is built on the list's recommended answer and is open to its ruling.

What ran at build time: the harness guard tests (`services/api/tests/chaos/admin/test_e42_harness_guards.py`,
in the ordinary PR lane: no stack, no network), ruff, `mypy --strict`, `node --check` on the k6
scripts and the runner's `--dry-run`. What did not: the dataset load and the k6 run (no Postgres,
Docker or k6 on the build host). The real run happens only in the dispatch-only workflow
`.github/workflows/perf-admin.yml`; a later part records its numbers in
`docs/qa/perf/e42-admin-perf-chaos-report.md`.

## 1. Parts

| Part | Content                                                                                         | State   |
| ---- | ----------------------------------------------------------------------------------------------- | ------- |
| 1    | Dataset driver, guards, the audit query profile, `perf-admin.yml`, `make admin-perf`, this plan | this PR |
| 2    | Chaos relay, scenarios 1, 3, 4, 6 (server halves), 5 in process, `chaos-admin-nightly.yml`      | next    |
| 3    | Browser measures, the frame-scripting parser, the UI halves of the scenarios                    | later   |
| 4    | Export, verify and refusal-flood runs, the added-load method                                    | later   |
| 5    | The report, baselines, runbook rows                                                             | last    |

## 2. Guards (never production, audit rows are permanent) [BQ-9]

- **API target:** the E27 rule (`tests/load/accounts/guard.py`, loaded by path): loopback or the
  compose `api`, an exchange host refused first, no credentials or path in the URL.
- **Database:** a postgres URL on loopback or the compose `postgres`, with no query, naming the
  database its dataset owns: `bulk` -> `admin_perf_test`, `chained` -> `admin_perf1m_test` [BQ-3].
  Both end `_test`, the fixture loaders' rule. The loader's own `current_database()` refusal is the
  second line. AUDIT-CORRUPT never goes into either (part 2 gives it its own database).
- **Environment:** the API's `CV_ENVIRONMENT` and its `/healthz` `environment` are `testnet` or
  `demo`, never `live`.
- **Soak:** the workflow's first step refuses to start while `perf-pack-full` or a bars memory
  `leg` is queued or running on `cv-bench-01`, and fails closed when GitHub does not answer.
- **Port:** the workflow's API binds 58000, a port no compose file or other workflow uses. It
  refuses to start when anything listens there, and after `/healthz` answers it requires the API
  it started to be alive and to own the listener (`bench/admin/api_up.py`), so no sign-in or
  audit row reaches another stack on the bench host. `make admin-perf` trusts the operator to point
  `--base-url` (required, no default) and `CV_ADMIN_PERF_DSN` at the same stack: the harness cannot tie a DSN to the API
  that answers.
- **k6:** only the pinned binary (`K6_BIN`, an absolute path, checked by `bench/ws/runner.py`
  `k6_binary()`), never one found through PATH; its environment is an allow-list (the sign-in
  inputs and `K6_*`), never the DSN, the pepper or a key.
- **Artefact scrub:** it searches for every generated password, key and TOTP secret. Not for the
  session's bearer and CSRF tokens (k6 holds them in memory; `handleSummary` drops the setup data;
  they die with the loopback API at teardown) nor the binary KEK file (never copied into the
  artefact, removed at teardown): writing either to a file only to search for it would add the
  exposure it guards against.
- Python (`tests/load/admin/guard.py`) and k6 (`tests/load/k6/admin/lib/guard.js`) hold the same
  rules; the guard tests run both over one table. No refusal echoes a URL or a DSN.

## 3. The audit query profile (SCR-135, US-ADMIN-009, ADR-0025) [BQ-1, BQ-2]

- **Data:** AUDIT-10M, bulk (`chained=False`, K01's load) in `admin_perf_test`, loaded by
  `bench/admin/datasets.py` through `tests/fixtures/admin/audit_10m.load_audit_10m`. The chain-check
  control (`dataset: chained`, 1 M rows) runs the same profile where every page's chain passes.
- **Server:** Postgres 16.4 with K01's settings (`shared_buffers=2GB`, `maintenance_work_mem=1GB`,
  `work_mem=64MB`), loopback only, and the real API on the host (testnet, real storage, synthetic
  feed), every limiter at its default. One Owner per run, seeded with a real TOTP method.
- **Calls:** `GET /admin/audit?limit=200` for 14 combinations (K01's ten the API has, plus `ip`,
  a selective `q`, a common `q` and the unfiltered page), each at page 1 and at a cursor 90 % deep
  into its own window; 1 warm-up and N=20 a position, one call at a time, paced at 1.05 s under
  the shipped 60 a minute. A `429` stops the run (a harness bug). Each call checks `200`, at most
  200 items, and a non-empty page unless the filter is selective by construction (`subject`,
  `q_selective`).
- **Session:** the access token lives 12 minutes and a run takes about 12; the Owner signs in
  again at a combination boundary once the session is 8 minutes old, so no call uses an expired
  token.
- **Judging:** nearest-rank p50, p95, p99 and max per run; the median of 3 runs is the figure of
  record (`06` section 7.4). Budgets, at most the source's figure (SCR-135 "≤400 ms",
  US-ADMIN-009 "≤2 s"): `common` p95 <= 400 ms, `q` p95 <= 2000 ms. A sample whose call did not
  answer 200 is never a duration: its row is ERRORS. Each results file names its database, mode
  and rows; only `bulk` at 10 M rows is the verdict, any other run is a CONTROL, not a verdict.

| Budget                                      | Required      | Expected today                                      |
| ------------------------------------------- | ------------- | --------------------------------------------------- |
| SCR-135 filter round trip, 12 common combos | p95 <= 400 ms | PASS, except `severity_actor`                       |
| `severity_actor`, page 1                    | p95 <= 400 ms | **FAIL by design** (K01 442.6 ms), #1710            |
| SCR-135 first page, `q_common`              | p95 <= 2 s    | PASS                                                |
| `q_selective`                               | p95 <= 2 s    | **ERRORS or FAIL by design** (4 s stop, 503), #1711 |

A FAIL is filed as a Bug against E42-T02 with the measured p95, the combination, the build SHA and
the dataset. A budget changes only by its source's owner; no row is skipped or widened.

## 4. How to run

- **CI:** dispatch `perf-admin` (inputs `profile: audit`, `dataset: bulk|chained`, `runs: 1-3`,
  `rows`: empty for the dataset's own, `100000` for a dry run). About 25 minutes to load 10 M rows
  and 12 minutes a run.
- **Locally:** `make admin-perf ARGS='--base-url URL --dry-run'` checks the guards and prints the plan (`--base-url`
  has no default: name the API);
  `make admin-perf` needs k6, the API on a loaded dataset and the variables in `bench/admin/run.py`.

## 5. Deviations from the build plan

- The deep cursors are minted in `lib/combos.js`, not by `datasets.py cursors`; the guard tests
  feed every one to the server's own `decode_cursor`. Each is 90 % into its combination's own
  window, so a windowed filter is not measured on an empty page [BQ-2].
- The API takes one `severity`; K01 read `error` and `critical` together [BQ-2].
- The `action` row uses K01's `orders.submit`.
