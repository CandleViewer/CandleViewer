# E09 auth perf and chaos report (E09-Q05, #296)

Status: **k6 profile measured on a GitHub-hosted runner (2026-10-29); the reference-host run stays
pending (#2105).** Every latency figure below comes from the `e09-auth-k6-summary` artifact of
`perf-ingestion-nightly` run 40944399030 (`workflow_dispatch`, `profile=auth`, `main`); none is
invented. A hosted runner is not the reference host, so these figures do not close #2105. The chaos
half has CI evidence (below).

## How the k6 profile runs

- Script: `tests/load/k6/auth.js` (#2848). `setup()` signs each perf user in through the real two-step
  flow: `POST /auth/login` with `identifier` and password, then `POST /auth/mfa/verify` with
  `mfa_token`, `method: totp` and an RFC 6238 code computed in k6 (`tests/load/k6/lib/totp.js`)
  from the seed `services/api/scripts/seed_fixture_user.py --totp-secret-out` wrote for that run.
  It carries `tokens.access_token` and the CSRF token into the scenarios. No seed or password is
  committed; each is made per run.
- `stepup_burst` answers a real challenge: a `POST /admin/recorder/purge` (owner-only, no-grace
  `recorder_purge` class) is refused `403 step_up_required` with a `challenge_id`, then
  `POST /auth/step-up` sends `code`, `password` and that `challenge_id`. The probe's `before` is the
  epoch, so it would purge nothing, and the VU never re-sends it while its one-shot grant lives.
- The API refuses a spent TOTP step (SR-021), so each VU signs in as its own Owner and waits for a
  fresh 30 s step: login_burst, stepup_burst and mfa_verify are paced by the TOTP step, not by
  request rate. The four scenarios run one after another (about 10 minutes).
- Sign-in verification is bounded (#4663: `CV_AUTH_LOGIN_VERIFY_CONCURRENCY`, default 4). A
  login past the bound is refused `429 rate_limited` with `Retry-After`; the script waits as told,
  retries (at most 5 tries) and counts each refusal in `auth_login_busy_refusals`.
- Thresholds: `checks` rate > 0.99 and the four budget rows below marked as gated.
- CI: `perf-ingestion-nightly.yml`, dispatched with `profile=auth` (job `auth-k6`): a keyless
  testnet stack on the runner with `CV_AUTH_PERF_ENABLED`, 10 seeded Owners, the k6 summary kept
  as the `e09-auth-k6-summary` artifact. Never on a schedule or a pull request; no required check.
  A GitHub-hosted runner is not the reference host, so its numbers do not close #2105.

## Reference host and Argon2id

- Reference host spec: pending (#2105; record CPU, RAM and kernel at run time).
- Measured host: GitHub-hosted `ubuntu-latest` (4 vCPU, 16 GB), a keyless testnet stack on loopback
  with 10 seeded Owners, `K6_HOST_CLASS=hosted`.
- Argon2id in force: `DEFAULT_ARGON2_PARAMS` = m=65536 KiB (64 MiB), t=3, p=4
  (`candleviewer/auth/hashing.py`). `setup()` aborts if `GET /auth/_perf/argon2-params` (#2097) does
  not answer or reports less than this floor. On run 40944399030 it answered at or above the floor
  (setup completed and every scenario ran).

## Budgets

Measured on the hosted runner (run 40944399030; p50 / p95 / p99 in ms, n samples):

| Budget                                                | Source  | Gated             | Measured (hosted)                | Verdict (hosted)                             |
| ----------------------------------------------------- | ------- | ----------------- | -------------------------------- | -------------------------------------------- |
| `GET /auth/session` p95 <= 100 ms                     | #13     | yes               | 18.52 / 23.62 / 28.66, n = 3001  | met                                          |
| `POST /auth/step-up` p95 <= 400 ms                    | SCR-006 | on reference host | 316.73 / 712.10 / 720.15, n = 40 | missed on the hosted runner; judged on #2105 |
| `POST /auth/mfa/verify` p95 <= 400 ms                 | SCR-002 | yes               | 113.88 / 172.89 / 196.76, n = 50 | met                                          |
| Argon2id step p50 >= 100 ms (`Server-Timing: argon2`) | SR-011  | yes               | 217.7 / 241.41 / 241.48, n = 20  | met (the cost is preserved)                  |
| Login, rest of the request (p50/p95/p99)              | report  | no                | 44.77 / 118.92 / 140.68, n = 20  | n/a                                          |

- `checks`: 3191 passed, 0 failed (rate 1.0 against > 0.99).
- Sign-ins refused `429 rate_limited` by the verification bound (#4663) and retried as told:
  `auth_login_busy_refusals` = 36.
- The step-up p95 includes one Argon2id verification of the password per call (about 220 ms here),
  so the hosted runner's 4 vCPUs under 10 VUs put it past 400 ms; the profile reports it and does
  not judge it off the reference host (`K6_HOST_CLASS=hosted`).

**The summary artifact.** The k6 summary export carried the setup return value; it is now stripped
before upload. The `auth-k6` job removes `setup_data`, checks it is gone and fails closed (a failed
strip removes the file, and the upload needs the strip to have succeeded), before the report step
and the upload; `scripts/tests/test_perf_auth_k6.py` pins the step, its order and both guards.

There is no session cache in `candleviewer/auth` (ADR-0010 addendum, "Session cache"), so the
profile has no warm/cold split and no cache-off negative control (#2848).

## Chaos outcomes (`services/api/tests/chaos/auth/`, `-m "chaos and integration"`)

C-13.6 mapping: #10 (datastore outage). C-13.6 #6 is `recv_window` drift on the exchange adapter and
is NOT covered here; the TOTP step-skew scenario is only an analogue (SR-021). The rest are auth-specific.
s1 to s5 drive the real SessionService, RevocationHub and WS gateway over an in-memory storage seam;
s1b restarts the compose Postgres. There is no session sweeper in `candleviewer/auth`; expiry is
lazy in `require_active`.

| Scenario                                                        | CI (`pr` run 38858627015, job 116835754521, 2026-10-16) |
| --------------------------------------------------------------- | ------------------------------------------------------- |
| s1 Postgres outage: fail closed, recover                        | PASSED                                                  |
| s1b real Postgres restart (compose stack)                       | PASSED                                                  |
| s2 TOTP step skew: +-1 accepted, +-3 rejected, replay refused   | PASSED                                                  |
| s3 WS gateway restart, no carried auth state                    | PASSED                                                  |
| s4 revocation storm (100 sockets, `bye`/4401)                   | PASSED                                                  |
| s5 session expiry under pressure (lazy expiry, concurrent auth) | PASSED                                                  |

The `integration` job runs them on every pull request.

## Lockout race and clock-skew event (implemented)

- Lockout race (SR-015/016): concurrent wrong passwords lock exactly at the threshold with no lost
  update, and a correct password is refused after the lock: `tests/unit/auth/test_login_lockout_race.py`
  and, on Postgres, `tests/integration/auth/test_login_lockout_race_pg.py` (#2163). The lockout's
  audit rows and the Owner alert series: `tests/security/auth/test_lockout_owner_alert.py` (#2628).
- Clock skew beyond tolerance raises a `system_events` row and a metric
  (`tests/unit/auth/test_totp_skew.py`, #2606).

## Not covered

- The reference-host run and its host spec: pending #2105. The figures above are hosted-runner
  figures; the step-up budget is judged only on the reference host.
- SR-015/016 over HTTP under load: the lockout race is proven at the service and on Postgres, not
  driven by k6 against a running API; "a throttled attacker cannot degrade a legitimate user's
  sign-in" is proven only by unit tests of the per-IP throttle.
- Clock skew on a stack: ±1/±3 and the skew event are proven in process, never with a moved host
  clock against a running API, and not the message the user sees.
- s1 to s5 use an in-memory storage seam; only s1b restarts a real Postgres.
- Session-store pressure with a sweeper: there is no sweeper to load (lazy expiry).
