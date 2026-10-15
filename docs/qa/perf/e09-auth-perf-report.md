# E09 auth perf and chaos report (E09-Q05, #296)

Status: **harness delivered; k6 numbers pending CI/nightly run.** k6 and the docker compose
stack are not available on the authoring machine, so no latency figure below was measured.
No number in this file is invented.

## Reference host and Argon2id

- Reference host spec: pending CI/nightly run (record CPU, RAM, kernel at run time).
- Argon2id in force: `DEFAULT_ARGON2_PARAMS` = m=65536 KiB (64 MiB), t=3, p=4
  (`candleviewer/auth/hashing.py`). `tests/load/k6/auth.js` `setup()` aborts if below this floor.

## Budgets

| Budget                                                          | Source        | Measured               | Verdict |
| --------------------------------------------------------------- | ------------- | ---------------------- | ------- |
| `GET /auth/session` p95 <= 100 ms, warm cache                   | #13           | pending CI/nightly run | pending |
| `GET /auth/session` cold-cache p95                              | reported only | pending CI/nightly run | pending |
| `POST /auth/step-up` p95 <= 400 ms                              | SCR-006       | pending CI/nightly run | pending |
| `POST /auth/mfa/verify` p95 <= 400 ms                           | SCR-002       | pending CI/nightly run | pending |
| Argon2id step p50 >= 100 ms                                     | SR-011        | pending CI/nightly run | pending |
| Negative control (`CV_CACHE_DISABLED=1`) fails bootstrap budget | ticket        | pending                | pending |

## Chaos outcomes (`services/api/tests/chaos/auth/`, `-m "chaos and integration"`)

C-13.6 mapping: #10 (datastore outage). C-13.6 #6 is `recv_window` drift on the exchange adapter and
is NOT covered here; the TOTP step-skew scenario is only an analogue (SR-021). The rest are auth-specific.
The tests drive the real SessionService, RevocationHub and WS gateway over an in-memory storage seam.
There is no dedicated session sweeper in `candleviewer/auth`; expiry is lazy in `require_active`.

| Scenario                                                                                          | Local result (in-process fakes, Python 3.14) |
| ------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| Postgres restart (fail closed, recover)                                                           | pass                                         |
| Postgres restart vs compose stack (integration-only, real assertions)                             | skipped locally (no docker); runs in CI      |
| TOTP step skew +-1 accepted, +-3 rejected (#6 analogue; replay refusal cited to test_mfa_service) | pass                                         |
| WS gateway restart, no carried auth state                                                         | pass                                         |
| Revocation storm (100 sockets, `bye`/4401)                                                        | pass                                         |
| Session expiry under pressure (lazy expiry, concurrent auth)                                      | pass                                         |

## Not covered yet (follow-ups)

- Rate-limit / lockout race under load (SR-015/016) and the "skew raises a system event" check
  need the staging stack; not implemented in this PR.
- Argon2 param floor and step timing (#2097): run the API with `CV_ENVIRONMENT=testnet`, no
  exchange key and `CV_AUTH_PERF_ENABLED=true` (the API refuses the switch anywhere else and logs
  `auth.perf_instrumentation_enabled` at boot), sign in as the owner (`CV_PERF_USER`,
  `CV_PERF_PASSWORD`, `CV_PERF_TOTP`) and set `CV_ARGON2_TIMING=1`. `setup()` asserts the floor
  from the owner-only `GET /auth/_perf/argon2-params`; `login_burst` reads
  `Server-Timing: argon2;dur=<ms>`, sent only on the 200 `mfa_required` challenge. With the switch
  off both checks are skipped with a logged note (the route answers 404, no header). The measured
  run is #2105.
