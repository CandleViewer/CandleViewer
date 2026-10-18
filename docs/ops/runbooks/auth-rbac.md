# Auth / RBAC operator runbook (E09-K02)

Status: written 2026-10-09 against `main` at `d9143fb`; corrected 2026-10-13 against `main` after #2154 (QA gaps on #292); the lockout, authz and step-up metrics were updated 2026-10-15 for #2117, and the login-failure, session and invite signals for #2319; the audit volume (Quick facts and §3) was added 2026-10-17 for #2615 (its break-glass line is a shape until #2119); §4 was updated 2026-10-18 for #965 (the served disable and its limits). Every command, route, metric and audit action
below was checked against the code at that commit. Where a procedure needs something that does not
exist yet, it says **BLOCKED — not implemented** and names the tracking reference; no substitute
command is offered. This runbook has **not** been executed on staging (see the last section).

Conventions: REST paths are shown relative to the API base. `$API` is your API base URL and `$TOKEN` a
valid access token of the stated role (sent as `Authorization: Bearer $TOKEN`); both come from your own environment, never from this page. No
secret, key material or host address belongs in this file. Paths under `candleviewer/` mean
`services/api/candleviewer/`. The metrics registry in `observability/metrics_catalogue.py` is the
source of metric names; some listed there are `planned` (declared, not yet emitted) and are called
out where relevant.

Quick facts the procedures rely on:

| Fact             | Value                                                                               | Source                                                                           |
| ---------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Lockout          | 5 failed logins lock the account for 15 min; login returns `423` with `Retry-After` | `auth/login_service.py` (`LOCKOUT_THRESHOLD`, `LOCKOUT_DURATION`), `api/auth.py` |
| Step-up grace    | 5 min per action class; `live_enablement` and `killswitch` always need a fresh code | `auth/step_up.py` (`GRACE_WINDOW`, `NO_GRACE_ACTION_CLASSES`)                    |
| Step-up failures | 3 invalid codes abandon the action and make the session read-only for 5 min         | `auth/step_up.py` (`FAILURE_CAP`, `READONLY_WINDOW`)                             |
| Session lifetime | 12 h absolute, 12 min access token, idle lock 15 min default (5–60 min)             | `auth/session_service.py`                                                        |
| Audit volume     | `cv-audit-data` at `/var/lib/candleviewer/audit`; back it up with Postgres          | `infra/compose/docker-compose.yml`, §3                                           |

## 1. Unlock a locked account (SR-016)

**There is no unlock command, endpoint or CLI.** A lock is `users.locked_until`, set by the login
service after the fifth failure. It clears in two ways, both in code:

- it expires 15 minutes after it was set; or
- the next correct-password login after expiry resets the counter (`record_login_success` in
  `auth/repository.py`).

Preconditions: you know the user. Do not ask the user to retry during the lock window: a locked
account refuses even a correct password.

1. Confirm the lock. A login attempt returns `423` with a `Retry-After` header (seconds left):

   ```bash
   curl -si -X POST "$API/auth/login" -H 'Content-Type: application/json' \
     -d '{"identifier":"<user>","password":"<password>"}' | head -n 12
   ```

   Expected: `HTTP/1.1 423`, `retry-after: <seconds, at most 900>`, problem title `Account locked`.
   Then query the audit log as an Owner (a non-owner sees only its own events):

   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.account_locked"
   ```

   Expected: `200` with one `auth.account_locked` entry (severity warning, identifier redacted such
   as `abc***(len=9)`) per refused attempt.

2. Wait out `Retry-After`. Expected elapsed time: at most 15 minutes. Do not attempt a login
   meanwhile. **Warning:** `failed_login_count` is reset only by a _successful_ login, so a single wrong
   password after the lock expires re-locks the account for another 15 minutes. Use the correct
   password on the first attempt.
3. Verify: repeat the login `curl` above with the correct password. Expected `200` with
   `{"status":"mfa_required","mfa_token":"...","methods":["totp"],"expires_in":...}`; the user then
   completes `POST $API/auth/mfa/verify`. Confirm with
   `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.login"`: expect an
   `auth.login` entry for the user.

Telemetry for a lock: counter `auth_lockouts_total` (no labels) rises by 1 when a failed password
check applies the lock: the fifth failure, or the first failure after an expired lock (at login, or
from a wrong step-up password, §2). The failure that trips the lock has no `auth.account_locked` row
of its own: at login it is audited as `auth.login_failed`, in step-up as `auth.step_up_failed`. So
this counter is the only record that the lock itself was applied. It does not name the user, it does
not move for attempts refused while locked (at login, the `auth.account_locked` rows above) and it
does not move on a successful login, so it confirms that a lock happened, not that it ended. Read it
on the metrics listener (default `127.0.0.1:9108`, §6):

```bash
curl -s http://127.0.0.1:9108/metrics | grep '^auth_lockouts_total'
```

Expected: one line `auth_lockouts_total{env="<env>"} <n>`. `n` counts from API process start, so
compare it before and after; a burst of parallel wrong passwords can add more than 1 for one lock. The
`AuthLockouts` rule (`infra/prometheus/alerts/system_ticket.yml`) reads it:
`increase(auth_lockouts_total[10m]) > 0`.

Owner alert for a lock (SR-016, SR-126): the `AuthLockouts` alert is that rule. It is severity
`ticket`, and Alertmanager sends it to the Owner's ticket channel, a Slack-compatible webhook read
from a secret file (`infra/alertmanager/alertmanager.yml`). The message holds the alert name,
component, environment, severity, an occurrence count, the summary "Account lockout occurred" and
the runbook link (`docs/plan/07-release-and-prr.md#alert-authlockouts`). **It does not name the
account**: the audit rows in step 1 carry only a redacted identifier (first three characters and
its length), and the lock itself is `users.locked_until`. Locks in one burst arrive as one message
(grouped by alert, component and environment). Two limits:

- **Quiet hours.** A `ticket` notification inside quiet hours (22:00-07:00 UTC by default,
  `CV_ALERT_QUIET_HOURS`) is muted, not queued, and the alert stays active for only 10 minutes after
  the last lock. So a lock during quiet hours is not delivered, except one in the last 10 minutes
  before the window ends (#2621). The audit log and `auth_lockouts_total` still show it: check them
  in the morning.
- **Delivery is not exercised by any test**: it needs the compose stack and a receiver
  (environment-only, #2105). Offline, `tests/security/auth/test_lockout_owner_alert.py` proves that
  one lock moves the series the rule reads, once, next to the audit rows, and the promtool cases in
  `infra/prometheus/tests/system_alerts.test.yml` prove the rule fires on that series.

Telemetry for failed logins: counter `auth_login_failures_total{method}` rises by 1 per failed
authentication on the `/auth` routes, `method` being the factor that failed: `password` per
`auth.login_failed` row written by `POST /auth/login` (wrong password, unknown identifier,
per-address throttle, or a disabled account after a correct password); `totp`, `webauthn` or
`recovery_code` (as named in the request) per `auth.mfa_failed` row of `POST /auth/mfa/verify`, and
per `auth.login_failed` row (reason `user_disabled`) of the same route when the code was right but
the user was disabled since the password step (#3054); `recovery_code` also per `auth.mfa_failed`
row of `POST /auth/mfa/recovery` and per `auth.recovery_codes_exhausted`. It does not move for an
attempt refused while the account is locked (the `auth.account_locked` rows above), for a success,
or for the WebSocket gateway's `auth.login_failed` rows (actor `ws`, reason `ws_auth_failed`,
written on the third failed `auth` frame of a connection): `cv_ws_auth_failures_total{reason}`
counts those, one per failed frame.
Every method is listed at 0 from process start. The `AuthLoginFailureSpike` rule reads it
(`sum(increase(...[10m])) > 10`); `sum by (method) (increase(auth_login_failures_total[10m]))`
shows which factor is attacked.

Owner's own account: the same expiry applies. If the Owner has lost the TOTP device,
`POST $API/auth/mfa/recovery` takes `{"mfa_token":"<from login>","recovery_code":"<code>"}`:

```bash
curl -s -X POST "$API/auth/mfa/recovery" -H 'Content-Type: application/json' \
  -d '{"mfa_token":"<mfa_token>","recovery_code":"<code>"}'
```

Expected `200` `{"status":"authenticated","forced_totp_reenroll":true}`. **BLOCKED — not
implemented:** this route mints no session, token or cookie (`api/auth.py`), and
`/auth/mfa/enroll[/confirm]` are `501` stubs (re-enrolment: #2295; recovery-session gap: #2344). So recovery codes do **not** currently get the Owner back in. A code is single use;
`auth.recovery_code_used` is written, and `auth.recovery_codes_exhausted` when none remain.
Re-enrolment is forced after every recovery sign-in, however many codes remain
(`auth/mfa_service.py`); there is no remaining-codes threshold (#2296).

Not available today:

- **Early unlock by an Owner: not implemented, no ticket.** Wait for expiry.

Stop and escalate if every Owner account is locked and has no TOTP device or recovery codes: go to
procedure 3.

## 2. Reset a user's TOTP as Owner (US-ONB-010)

Preconditions: you are signed in as an Owner. You cannot reset your own TOTP (the service refuses a
self-reset). The reset needs a step-up for action class `users`. The target is not you.

1. Preview what the reset affects:

   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" "$API/users/$USER_ID/mfa/reset-preview"
   ```

   Expected `200` with `open_position_count`, `positions` (`known` or `unavailable`), `position_source`,
   `requires_acknowledge_unknown_positions`, `message`. Today the position source may be
   `not_deployed`; then positions are reported as unavailable, never as 0.

2. Step up. Call the reset once; it answers `403` naming the `users` action class and starts a
   challenge. Then step up with **password and code** (required since #2154; omitting `password`
   returns `422 password is required`):

   ```bash
   curl -s -X POST "$API/auth/step-up" -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"password":"<your password>","code":"<your current TOTP code>"}'
   ```

   Expected `200` with `elevated_until` (ISO timestamp). A wrong password or wrong code gives the
   identical `401` (`Invalid password or code.`, with `failures_remaining`). **A wrong password also
   increments your login lockout counter**, so five mistakes can lock your own account (see §1).
   Three failures abandon the action and make your session read-only for 5 minutes
   (`403 session_read_only`). Every failed step-up adds 1 to `auth_stepup_failures_total`, and the
   failure that locks your account also adds 1 to `auth_lockouts_total` (metrics listener, §1).

   Both kinds of step-up trouble are audited as `auth.step_up_failed`; `outcome` tells them apart
   (#2304). A wrong password or code (or a locked account) is outcome `failure`, reason
   `users:remaining=<n>`, and counts a strike. A step-up that the service refuses before any
   factor is checked (`400 validation_failed`, for example a `challenge_id` that is stale or
   unknown) is outcome `denied`, object kind `step_up_challenge`, with the rule as reason
   (`challenge_expired`, `challenge_required`, `challenge_mismatch` or `required`); it counts no
   strike and moves no metric. A body outside the request schema and an unknown `action_class`
   are also `400` but write no record. A record the audit writer cannot take within 2 s makes the
   answer `503 audit_unavailable`, not the `400`: nothing changed, so repeat the request once audit
   recovers. Each such `503` logs one error line, `auth.step_up_audit_refused`, with only the error
   class (`AuditUnavailable`, `AuditWriterStopped`, `RuntimeError` for a writer not started yet, or
   `TimeoutError`). To see only factor failures:
   `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.step_up_failed&outcome=failure"`.

   **`auth.step_up_mismatch`** (outcome `denied`, severity `warning`) means a one-shot grant
   (`live_enablement`, `killswitch`, `backups`) was presented with a request other than the one it
   is bound to (another body, path or query). The answer was `403 step_up_required` with a new
   challenge, and the grant was not used up. Find it with
   `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.step_up_mismatch"`:
   `actor_user_id` is the session's user and `subject_id` the challenge the grant answered (the id
   on that user's `auth.step_up_required` and `auth.step_up_granted` rows). The action class and
   both request fingerprints (never a body, password or code) are on the stored record only. One
   row right after a step-up is most often a client that changed the request before re-sending it:
   nothing ran, so the user repeats the action and steps up for the new challenge. Rows the user
   did not cause, or several for one session, mean something in the session sent a request the
   user never approved: nothing executed, but treat the session as exposed and have the user sign
   out everywhere (`POST $API/auth/logout` with `{"all_sessions": true}`). An Owner cannot revoke
   another user's sessions without locking them out (the disable, §4, or the reset, step 4).

   A live arm (`PUT /rules/{ruleId}/mode`) whose mismatch record cannot be written is the same
   `503`, counted in `rule_mode_transitions_total{result="audit_unavailable"}`. The route also
   audits its own refusal as `rule.mode_refused`, within 2 s; when that record cannot be written
   either, the `503` is still answered and the error line `rules.mode_refusal_unrecorded` (rule id
   and error class) is the only trace. A rise of either signal means the audit writer cannot take
   records.

3. Reset:

   ```bash
   curl -s -X POST "$API/users/$USER_ID/mfa/reset" -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{}'
   ```

   If positions are `unavailable`, the first call returns `409 positions_unknown`; repeat with
   `-d '{"acknowledge_unknown_positions": true}'` only after you have checked the user's positions
   another way. Expected `200` with `target_user_id`, `methods_revoked`, `sessions_revoked`. The reply
   contains no secret.

4. **BLOCKED — re-enrolment is not possible today.** `reset_totp` revokes every method; a user with
   no active method gets `501` from `POST /auth/login` (`login_service.py`), and
   `/auth/mfa/enroll[/confirm]` are `501` stubs (`api/auth.py`). After a reset the user
   cannot log back in until #2295 (session-authenticated enrolment and a no-method
   login path) lands. Do not reset a TOTP you cannot afford to leave locked out.
5. Verify from telemetry: audit action `auth.mfa_reset_by_owner` (severity critical) with the
   target user:
   `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.mfa_reset_by_owner"`;
   counter `auth_mfa_resets_total` rises by 1 on the API process (`auth/metrics.py`).

Note: `auth.mfa_reset` also exists in the audit vocabulary, but the Owner route writes
`auth.mfa_reset_by_owner`. Search for that name.

Expected elapsed time: not measured. E09-X04 did not run a reset drill; this is a gap, not an estimate.

## 3. Break-glass for total Owner lockout (SR-023)

**BLOCKED — not implemented.** There is no break-glass CLI, route or script in the repository
(`docs/security/reviews/e09-auth-review.md` §3, finding R-6). Tracking: Owner item AB on #1778 and the CLI ticket #2119 (E09-S11, open). The drill has not been executed.

Preconditions that any future procedure will need, stated now so nobody burns time: shell access to the
host that runs the API **and** access to the key-encryption material held by the host keychain
(`kek_source` in `settings.py`). Without both, there is no recovery path.

What an operator can and cannot do today if the sole Owner is locked out of TOTP with no recovery
codes: nothing supported. Do not hand-edit `users`, `mfa_methods` or `recovery_codes` rows; do not
touch audit rows. Escalate to the repository owner, who decides on direct database repair under the
security process. Record the incident.

**The audit volume (#2615).** In compose, cv-api and the break-glass CLI (once #2119 ships it) share
one audit directory: the named volume `cv-audit-data`, mounted at `/var/lib/candleviewer/audit`,
with `CV_AUDIT_WAL_PATH` fixed at `/var/lib/candleviewer/audit/audit.wal` in
`infra/compose/docker-compose.yml`. It holds the audit WAL and its commit cursor (`audit.wal`,
`audit.wal.committed`) and the break-glass journal and run lock (`breakglass/journal.wal`,
`breakglass/instance.lock`), so a container restart keeps them and the CLI takes its lock where
cv-api looks. The image creates the directory owned by uid 10001, mode `0700`, and Docker copies
that owner into an empty volume: run everything that touches it as the image's user.

- **Backup.** Back it up with Postgres: in the same run, encrypted with the backup key (SR-091),
  with the same retention and off-host copy, and restore the two together with owners and modes
  intact. It holds audit records that cv-api has accepted and Postgres may not have yet, and the
  journal until the next cv-api boot folds it in. Copy the volume first, and start the Postgres dump
  only once the copy ends: the commit cursor (`audit.wal.committed`) marks the records Postgres
  already has, so a copy newer than the dump would skip, on restore, the records committed in
  between; an older copy only replays rows the insert ignores, since `record_id` is unique.
- **Do not delete it.** `docker compose down -v`, `make reset` and, with the stack
  down, `docker volume prune --all` remove it; a plain `down` keeps it.
- **Check it** (read-only). Expected: `drwx------`, owner and group `10001`; another owner, such as
  root for a volume the dev stack created first (its image runs as root), is one cv-api cannot
  write. Use the compose files (`-f`) or project (`-p`) of the running stack, as `docker compose ls`
  lists them: the volume belongs to one project, and a `run` in another can mount a new, empty
  volume that looks healthy. `api` has a fixed address, so a second container of it, such as `run`,
  starts only while cv-api is stopped:

  ```bash
  # cv-api running
  docker compose -f infra/compose/docker-compose.yml --profile core exec api ls -ldn /var/lib/candleviewer/audit
  # cv-api stopped
  docker compose -f infra/compose/docker-compose.yml --profile core run --rm --no-deps --entrypoint ls api -ldn /var/lib/candleviewer/audit
  ```

The CLI will run as a one-off container of the `api` service, so only with cv-api stopped: that is
also the CLI's own rule, since it takes `instance.lock` exclusively and cv-api holds it shared.
`docker compose run` gives that container the service's own volume, `CV_AUDIT_WAL_PATH`, user and
read-only root, so the line has no `-v` of its own and must not set `--user`: a file the CLI creates
as root is one cv-api (uid 10001) cannot open. The image entrypoint is `candleviewer.server`, so the
line replaces it. Postgres must be up. This is the shape only and **does not run until #2119 ships
`candleviewer.breakglass`**; that ticket's runbook slice owns the arguments and the KEK access:

```bash
docker compose -f infra/compose/docker-compose.yml --profile core run --rm --no-deps --entrypoint python api -m candleviewer.breakglass
```

## 4. Disable a user and what follows (SR-029)

`DELETE /users/{userId}` (`api/users.py`, E42-T04 #965) disables a user: Owner only, never your own
account, after a step-up for action class `users` (§2). No position or order source is deployed
yet, so it answers `409 positions_unknown` until it carries `acknowledge_unknown_positions=true`.
Any other query parameter answers `422 validation_failed`, and `purge=true` answers `400` until
E42-T10 serves it; neither changes anything.
One transaction sets the status, revokes the sessions and grants and writes `users.disable` ahead;
then each step (sockets, sweep, B16, rule scope, rule disarm, invite) runs alone, so a `204` can hide
a failed one: it logs the error line `users.disable.step`, and a repeat of the call re-runs the
sockets, the sweep, the scope refresh and the disarm. The socket step ends every socket of the user
with `bye` `user_disabled` and `4403`, one still on a session that a refresh rotated included. The
disarm lists the user's armed rules again after its disarms, so a rule armed meanwhile is disarmed
too. A rule its chart refuses (evaluating, acting, pending confirmation or spent) stays armed with
no grant and no permission to act on (O4, O5); a repeat disarms it once it is back in `armed`, which
a rule pending confirmation or spent reaches only through its confirmation or `RESET_ONCE` (#3226).
A new socket whose `auth` completes around the commit, on a session the user's own refresh rotated,
can register after the socket step and stream until its access token expires, 12 minutes at most
(UL1-E2's residual in `docs/security/threat-models/e42-user-lifecycle.md` §6).

What the cascade builds on, and what to read afterwards:

- `SessionService.revoke_all` (`auth/session_service.py`) and the socket hub
  (`ws/revocation.py`). Metric `auth_session_revocations_total{reason}` counts revocations (served on
  the metrics listener since #2319); `auth_revocation_latency_seconds` is process-local and not served.
- `users.status = disabled` makes login refuse with `403 Account disabled` after a correct password.

What a `disabled` status does to sessions (#2911). It holds however the status was set, and it is
the backstop for a session that no disable revoked. A `locked` or `invited` status changes none of
it (login refuses `disabled` only):

- `POST /auth/mfa/verify` for a user disabled since the password step answers `401` and mints no
  session. The refusal is audited as `auth.login_failed` (`denied`, reason `user_disabled`) and
  counted in `auth_login_failures_total` on the method the request named (#3054).
- `POST /auth/refresh` with a disabled (or deleted) user's refresh token answers `401`
  `refresh_token_invalid`, before the session is claimed: it is neither rotated nor revoked. The
  refusal is audited as `auth.session_refreshed` (`denied`, reason `user_disabled`), after the
  write-ahead record of the attempt. A disable that commits after the claim leaves no live
  successor either: the mint reads the status under a lock on the user row, and the disable's own
  lock queues behind it.
- A session that survives is revoked on its next strict-path use, with reason `user_disabled`: the
  first REST request that authenticates it (every route but those named below, which accept it so
  the user can still sign out) or the first socket `auth` that presents its token. The request
  answers `401`, and the sockets already on that session end with `bye` `user_disabled` and
  `4403`; the socket whose first `auth` presented the token gets `err` `auth_failed`
  (`docs/plan/23-ws-protocol.md` §9.5). A route skips the backstop in one of two ways: it finds
  its session with `_identify` (`api/sessions.py`: an access token inside its lifetime, else the
  `cv_refresh` cookie), whose `peek_access_token` and `peek_refresh` read no user status, and
  never calls `require_active`; or it authenticates with `allow_locked=True` other than through
  `require_active`. `test_only_these_routes_skip_the_backstop` scans the code for both:
  `POST /auth/logout` skips it the first way (#2300), `DELETE /me/sessions/{sessionId}` the second.
- Each such revocation increments `auth_disabled_user_sessions_revoked_total` once (no label; on the
  metrics registry: the private listener `127.0.0.1:9108`) and logs a `WARNING`
  `auth.disabled_user_session_revoked` with `session_id`, `user_id` and `user_status` (`None`: the
  user row is gone). Only the call that revoked the row counts and logs: requests that raced on the
  same session are refused all the same and add nothing, so each stray revocation also moves
  `auth_session_revocations_total{reason="user_disabled"}` by one (that series counts a disable's
  own revocations too). The `AuthDisabledUserSessionRevoked` ticket fires on any increase
  (`docs/plan/07-release-and-prr.md`, section 9). The same call writes one audit record,
  `auth.disabled_user_session_revoked` (warning): the session, its user as the actor and the status
  read in `after_state.user_status` (`detail.after.user_status` in `GET /admin/audit`; `gone` when
  the user row is gone), no IP. `auth` may not import `audit`, so the composition root attaches the
  writer (#3120). The record comes last, after the revocation: an audit sink that is down never
  undoes the revocation, and never holds the `401` for more than 2 seconds. Any increase means a
  session outlived a disable (SR-029): escalate with the log line and the record.
- One loss the count has. The count, the log and the publish follow the revoking `UPDATE`, so a
  request cancelled after that `UPDATE` committed but before the repository's `revoke` returned
  (in the unit of work's commit or exit: a cancel within one local `COMMIT` round trip, such as a
  client that disconnects or a server that shuts down) leaves the row revoked as `user_disabled`
  with no count, no `WARNING`, no publish (its sockets end at their token deadline instead of at
  once) and no `auth_session_revocations_total` increment. The retry finds the row revoked and
  adds nothing, and nothing the backstop emits shows the loss: the `sessions` row with
  `revoked_reason = 'user_disabled'` is the only trace, so compare those rows in a window with the
  counter's increase over it (a disable's own transaction and sweep add rows of their own).
  Before #3029 the count came first, so a cancel there over-counted instead of losing the signal.
  Shielding the bookkeeping after the `UPDATE` is not built: it is the follow-up #3332 (P2), filed
  with the ruling of 2026-10-18 ([comment](https://github.com/basiltt/CandleViewer/issues/3120#issuecomment-6243898535)).
- When the audit sink is down the record is dropped, not queued (C-2.18; exception EX-08,
  `04-security-program.md` section 16.2), and the log says so:
  `auth.disabled_user_session_audit_failed` (ERROR, with `session_id`, `user_id` and `error`, the
  failure's class: `BackstopAuditSaturated` at the in-flight cap, `BackstopAuditNotAttached` for a
  wiring fault). A write still running after the 2 seconds logs
  `auth.disabled_user_session_audit_slow` (with the ids; the record may still land), and if it
  then fails, or fails after its request was cancelled while waiting for it,
  `auth.disabled_user_session_audit_failed_late` follows with `error` only and no session, so count
  those lines. Five losses leave no log line that names the session and says its record is missing
  (the `WARNING`, logged as soon as `revoke` returns, names it in four of them but cannot say the
  record failed): the process dies between the revoke and the write; it shuts down while the write
  is still running (the drain waits 2 seconds, then logs only a count); the request is cancelled
  after the revoking `UPDATE` committed but before `revoke` returned (the bullet above: the count,
  the log and the publish go with the record); the request is cancelled while the revocation is
  published to the sockets, before the record is handed over; or the request is cancelled while it
  waits for the write and the write then fails (an `_audit_failed_late` line says so, with no
  session). Only the reconcile step finds all five, and what each `_audit_failed_late` line lost.
  To reconcile, after an outage or any restart, list the sessions revoked as `user_disabled` in
  that window (UTC; `psql` runs inside the `postgres` container, as the user and database it was
  started with, in a read-only session):

  ```bash
  docker compose -f infra/compose/docker-compose.yml --profile core exec -T \
    -e PGOPTIONS='-c default_transaction_read_only=on' postgres \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
  SELECT id, user_id, revoked_at FROM sessions
  WHERE revoked_reason = 'user_disabled'
    AND revoked_at >= '2026-10-17 06:00+00' AND revoked_at < '2026-10-17 07:00+00'
  ORDER BY revoked_at;
  SQL
  ```

  As an Owner, look each id up in
  `GET $API/admin/audit?action=auth.disabled_user_session_revoked&subject_type=session&subject_id=<id>`:
  one with no record there is unaudited, unless a disable revoked it (its audit records cover it).

- A client that only holds a socket meets the backstop only when a REST call or a socket `auth`
  presents a token that is still valid, or when it calls `GET /auth/session`, which finds the
  session by its `cv_refresh` cookie once the token has ended and still checks the user's status
  (#3214: `require_active` with `allow_locked=True`). A client that only refreshes, as the
  protocol's client flow does, meets none of these. It refreshes over REST at `expires_at` − 60 s
  (`docs/plan/23-ws-protocol.md` §4.1, §4.3), and
  `POST /auth/refresh` refuses a disabled user before the claim (above): nothing is revoked or
  counted and no new token is minted. The socket ends at its token deadline (12 minutes at most),
  and its old token is then refused as expired before `require_active` runs. So for this client
  the counter, the `WARNING`, the publish and the `AuthDisabledUserSessionRevoked` ticket stay
  silent and the row stays un-revoked until its absolute expiry, 12 hours after the login that
  started the session chain: a quiet counter does not prove that no disabled user's session is
  live. The only trace that names the cause is the refusal's audit pair, the write-ahead
  `auth.session_refreshed` record and the denied one with reason `user_disabled`, read as an Owner
  (`curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.session_refreshed&outcome=denied"`).
  If the denied one could not be written, the loss is in
  `auth_audit_outcome_lost_total{action="auth.session_refreshed"}`, the
  `auth.session_audit.outcome_lost` log line and the `AuthAuditOutcomeLost` ticket (section 10).
  The streaming window is an accepted risk, dated 2026-10-17
  (`docs/security/threat-models/e09-auth-rbac.md`, U45; it is UL1-E2's in `e42-user-lifecycle.md`):
  a socket has no write path, since orders are REST only, and #965's disable cascade, now that it
  is routed, closes sockets within 5 s. The live row and the silent counter are accepted too: the
  main-orchestrator confirmed them on 2026-10-18 ([ruling](https://github.com/basiltt/CandleViewer/issues/3120#issuecomment-6243898535)).
  A refused refresh that revokes the row and counts it is not built: it is the follow-up #3331
  (P1), filed with that ruling, next to #3332 (P2), which shields the bookkeeping (above).

**The bootstrap Owner (O5, #3246).** The permission readers and the owner floor count only `active`
users. The first Owner that `0002_rbac_seed` creates (`docs/plan/21-database-schema.md` §10.2) is
seeded `invited`, so it holds no permission and is no Owner for the floor until it is `active`, and
nothing in the app makes it `active`: only redeeming an invite does, and the seed creates none (nor
does any password match its seeded placeholder hash). **BLOCKED — not implemented**: there is no
supported way to activate it (#2710). Do not edit `users` by hand: escalate to the repository owner,
as §3 says, and record it. On testnet, `services/api/scripts/seed_fixture_user.py` seeds an `active`
Owner and audits it.

**A commit lost on the wire (#2710).** When the commit of a disable fails on the wire, the call
answers `503 store_unavailable`, and the `users.disable` record is followed by a `failure` record
with reason `outcome_unknown`: the user may be disabled, and no step after the commit has run.
Repeat the DELETE, which is safe either way: a repeat of a committed disable answers `204`, writes
no record, ends every socket of the user and re-runs the sweep, the scope refresh and the disarm.
B16 records none of the sessions that commit revoked (no `auth.session_revoked` for them); the two
`users.disable` records are the trail. This residual awaits the Owner's sign-off in
`docs/security/threat-models/e42-user-lifecycle.md` §6.

Proven end to end in process on the deployed app
(`services/api/tests/security/auth/test_disable_user_e2e.py`) and on Postgres
(`services/api/tests/integration/admin/test_user_disable_route_pg.py`), sockets on `rotated`
sessions included. The staging drill (E09-X04, #2494) has not run;
`services/api/tests/security/auth/test_disable_user_drill.py` drives the primitives only.

## 5. Audit-chain verification failure

Background: the audit log is append-only and hash-chained. The only verifier today is on demand:
`POST $API/admin/audit/verify` (`api/audit.py`, `audit/query.py::verify`). **A nightly scheduled
verifier does not exist** (finding R-5, #2111), so a break is found only when someone runs it.
There is no alert for it.

Preconditions: Owner session (`audit/access.py`: `verify` and `export` are Owner only).

1. **Confirm, read-only.**
   `curl -s -X POST "$API/admin/audit/verify" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'`
   (optional `from_id`, `to_id`). Expected `200` with `verified`, `entries_checked`, `first_bad_id`, `checked_at`. `verified: false`
   with a non-null `first_bad_id` is the failure. Run it once more over a range that ends just before
   `first_bad_id` to confirm the earlier chain is intact.
2. **Preserve evidence before anything else.** Save both responses verbatim. Take a database
   snapshot or backup copy of the audit table and of Postgres as it stands, using the backup
   procedure in `docs/plan/07-release-and-prr.md` and the E07 backup drill
   (`docs/security/drills/E07-backup-restore-drill.md`). Record time, who ran it and the API
   build version. Do not change the system until this copy exists and is stored off the host.
3. **Notify.** The Owner and the Security engineer, immediately. Treat it as a possible tampering
   incident, not a bug. Follow `SECURITY.md`; do not open a public issue.
4. **Contain.** Keep the system running read-only for the evidence; do not restart services merely to
   "see if it clears".

What NOT to do (each destroys the tamper signal):

- Do not delete, update or "repair" any audit row; the table has no `UPDATE`/`DELETE` grant by design.
- Do not re-run, roll back or add migrations on the audit tables.
- Do not rebuild or truncate the chain to make `verify` pass.
- Do not restore a backup over the live database before the evidence copy is taken and Security agrees.

Verify the incident is recorded: `GET $API/admin/audit?action=...` for the actions around
`first_bad_id`. Stop and escalate at step 1 if `verified` is false; the rest is Security's decision.
Expected elapsed time: `verify` duration is not measured here; for large logs use `from_id`/`to_id`.

## 6. Binding self-check failure (read-only mode)

Background: `candleviewer/net/` checks at boot and then hourly (`net/scheduler.py`,
`interval_s=3600`) that the process's real listening sockets are loopback/mesh-only
(`net/binding_check.py`). On failure the process-wide `ReadOnlyGate` trips and the gauge
`net_binding_safe` is set to 0 (registered as `net_binding_safe` in `net/metrics.py`; the Prometheus
exposition is on the private `/metrics` listener, `metrics_bind` in `settings.py`, default
`127.0.0.1:9108`).

What read-only disables: the OMS validator refuses order placement while the gate is tripped
(`oms/validator.py`, `ReadOnlyCheck`). No flag, config or role overrides it. A `system` WS topic
event carries the reason. **No degraded-mode banner exists in the web app yet (#2299)**; read the reason from
the `system` event or the logs.

Reason codes (`net/binding_check.py`, `net/scheduler.py`):

| Code                            | Meaning                                                       |
| ------------------------------- | ------------------------------------------------------------- |
| `net.public_binding_detected`   | a listener is bound to `0.0.0.0` or `::`                      |
| `net.off_mesh_binding_detected` | a listener is bound outside the loopback/mesh CIDR allow-list |
| `net.binding_check_failed`      | the socket table could not be read (fail-closed)              |
| `net.self_check_timed_out`      | the check exceeded its time limit                             |

1. The `NetBindingUnsafe` page fires as soon as the gauge reads 0
   (`docs/plan/07-release-and-prr.md#alert-netbindingunsafe`). Read the gauge on the metrics
   listener: expect `net_binding_safe{env="<env>"} 0`, e.g. `curl -s http://127.0.0.1:9108/metrics | grep net_binding_safe`
   (served there since #2496; before that the gauge was never on the listener). Read the reason
   code from the `system` topic event, `mesh_reason_code` on `/readyz`, or the API log.
2. Diagnose on the host: list listening sockets for the API process with your platform's tool
   (for example `ss -ltnp`) and compare with the intended bind. On WSL, a Windows port-proxy rule can
   re-expose a loopback listener; check it (`20-architecture.md`, "WSL hazards").
3. Fix the bind or the proxy rule, then restart the API process so the boot check runs; or wait for
   the next hourly pass. There is **no command or endpoint to clear the gate**. `ReadOnlyGate.clear`
   accepts only a fresh passing result, and nothing exposes it to an operator.
4. Verify: `net_binding_safe{env="<env>"} 1`, and a `system` topic event clears the state with reason
   `net.binding_safe`. Orders are accepted again.

Stop and escalate if the failing listener is public and you cannot explain it: treat as an exposure
incident under `SECURITY.md`. Do not disable the check or the gate. Expected elapsed time: up to
one hour if you rely on the hourly pass; a restart runs the check at boot.

## 7. Read the RBAC matrix and answer "why was this denied?"

The permission vocabulary is generated: the single source is the `x-rbac` blocks in
`docs/plan/22-api-openapi.yaml`; `tools/rbac/generate.py` writes
`candleviewer/auth/generated_permissions.py` and the `permissions` list in
`candleviewer/auth/rbac_seed.json`. Which role holds which permission is hand-authored in
`rbac_seed.json` (`roles`, `role_permissions`). Never hand-edit the generated parts; the guard is the
contract test `services/api/tests/contract/rbac/test_rbac_generator.py::test_check_passes_against_committed_output`
(also `python tools/rbac/generate.py --check`); CI `generated-code` covers only `packages/protocol`.

To answer a denial:

1. Find the denial in the audit log. The `permission` label of `authz_denied_total` (below) says
   which decider counted it, and the audit action differs:
   - `enforce` routes (`users:write` today): action `rbac.denied`,
     `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=rbac.denied"` (add
     `&actor_user_id=<id>`). The entry names the permission and scope (`auth/scopes.py`, `enforce`).
   - Admin-area routes on the E42 guard (`admin/http.py`; `permission="admin:read"` today): action
     `admin.area_entered`, not `rbac.denied`. The same action is written for every allowed entry,
     so filter on the outcome:
     `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=admin.area_entered&outcome=denied"`
     (add `&actor_user_id=<id>`). The entry's `subject_id` is the route template, such as
     `/admin/overview`.
2. Look up the permission on the route in `22-api-openapi.yaml` (`x-rbac`), then check whether the
   user's role holds it in `rbac_seed.json`.
3. For account-scoped routes, a Manager also needs the account grant: scope decisions are in
   `auth/scopes.py` (`decide`; `OBJECT_REQUIRED`, `ACCOUNT_NOT_GRANTED`).
4. A step-up refusal is a different thing: `403` with code `step_up_required` and an
   `action_class`, audit `auth.step_up_required`.
5. For the route-by-actor matrix test, see `services/api/tests/contract/rbac/test_route_matrix.py` and
   `docs/qa/charters/E09-charter-2-rbac-boundaries.md`.

**`authz_denied_total{permission}`** (the catalogue name; there is no `cv_` prefix) counts each
permission denial decided by one of two deciders. It moves before the audit row is written, so an
audit failure never hides a denial. `permission` is the permission code from a closed set (the
generated vocabulary plus `other`).

- `auth/scopes.py::enforce` (audit row `rbac.denied`). Only routes that call `enforce` count this
  way, and today those are all `users:write` routes: `PUT /users/{userId}/roles`, `DELETE /users/{userId}`, the invite routes
  (`POST /users`, `GET /users/invites`, `POST` and `DELETE /users/{userId}/invite`) and the TOTP
  reset routes.
- The admin-area guard, `admin/http.py` (audit row `admin.area_entered` with outcome `denied`, not
  `rbac.denied`). Every route on an `admin_router` counts, under the router's permission:
  `admin:read` for `GET /admin/overview` and `GET /admin/capacity` today, and a later router on the
  guard counts under its own `admin:*` code. Only a decided denial counts: not a `401`, a `501` or a
  `503` for a missing audit writer, and not an allowed caller whose audit write fails (a `503`).

Not counted:

- permission checks written inline in other route modules (market data, instruments, and so on),
  which write no `rbac.denied` row either: their only trace is the `403` response itself;
- WS subscribe denials: see `cv_ws_subscribe_total{result="forbidden"}` and the audit action
  `ws.subscribe.denied`;
- the owner-floor `409` (audited as `rbac.denied`, see the note below, but a business refusal rather
  than a permission check) and `step_up_required` (§2).

Read it on the metrics listener, for example
`curl -s http://127.0.0.1:9108/metrics | grep '^authz_denied_total'` (every permission is listed at 0
from process start). The `AuthzDeniedSpike` rule fires above 20 denials in 10 minutes
(`sum by (permission) (increase(authz_denied_total[10m]))` shows which permission). Today a spike on
`admin:read` comes from the admin-area guard and one on `users:write` from `enforce`; use the
matching query in step 1.

**`auth_stepup_failures_total`** (no labels) counts each failed step-up verification: wrong password,
locked account, wrong or replayed code. The audit row is `auth.step_up_failed` with outcome
`failure` (names the action class); rows with outcome `denied` are step-ups refused before any
factor is checked (§2), which this counter does not count. The per-class counter that used to sit
beside it was retired in #2319. No alert rule reads it yet (#2746). `auth_readonly_downgrades_total`
counts sessions made read-only after the third failure.

**Session and invite signals (#2319).** Served on the metrics listener with `env`. No alert rule reads
them yet (#2746), so read them when investigating:

| Series                                   | Meaning                                                                                                                                                                                     | Audit row                                                                                                                                                                                |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auth_refresh_reuse_total`               | a rotated-out refresh token was presented again; the whole session family is revoked                                                                                                        | `auth.refresh_reuse_detected` (critical)                                                                                                                                                 |
| `auth_session_revocations_total{reason}` | sessions revoked; `reason` is from a closed set (logout, logout_all, rotated, rotation_reuse, expired, idle, admin, user_revoked, locked, timeout, unlock_attempts_exceeded) plus `other`   | `auth.session_revoked` for the logout and revoke routes                                                                                                                                  |
| `auth_session_revoke_denied_total`       | `DELETE /me/sessions/{id}` named an id that is not one of the caller's live sessions: a foreign or unknown id (the probe) or the caller's own ended session; the answer is the same 404     | `auth.session_revoke_denied` (denied, warning, reason `not_live_own_session`; object: the id named). Rows are budgeted at 10 a minute per user and 30 overall; every probe is counted.   |
| `users_invites_rejected_total{reason}`   | invite requests refused: unknown, expired, redeemed, revoked, enrollment_invalid, role_tamper (a `role` or `roles` claim) or identity_tamper (`username`, `user_id` or `email` in the body) | `users.invite_rejected` (warning for redeemed, role_tamper and identity_tamper). Tamper requests count against the per-address invite budget: the 11th in a minute gets `429` and no row |

A lone `auth_session_revoke_denied_total` hit is as likely a stale Sessions row (the caller's own
session ended, for example by rotation) as a probe, and the series cannot tell them apart: look the
audit row's `object_id` up in `sessions`; another user's row means a probe. A probe past the row
budget, or while the audit writer is saturated, is still counted and gets no row: the log then says
`auth.session_revoke_denied.unaudited` with `cause` `audit_throttled` or `audit_saturated`, so a rate
of that line is the number of probes left out on purpose.

A hit whose `object_id` has no `sessions` row is an unknown id: treat it as a probe unless the
actor's own history explains it. The caller's own ended session keeps its row, so it is not this
case. Nothing drops a `sessions` row yet: section 7 of `docs/plan/21-database-schema.md` sets the
policy (30 days after expiry) and the job that applies it has not shipped, so today a missing row
means the id was never issued in this database. Once the job ships, an old id has no row either,
and it may be another user's leaked one, so a missing row never makes a hit harmless. To see whose
id it was, search `audit_log` for rows that name it as `session_id` and compare their
`actor_user_id` with the caller's (the `actor_user_id` of the hit's `auth.session_revoke_denied`
row): the caller's own means a stale client, another user's means a probe, as for a live row.
`session_id` is not indexed, so a search on it alone scans the whole table: start from the indexed
`action` or `actor_user_id` with an `event_ts` window, then filter on `session_id`. A search that
finds no row settles nothing (a session minted by a rotation can end unused without one), so read
several different ids with no row from one user as a probe.

A probe whose row was lost by accident is counted too, and the log says why. A write that fails, or
an audit sink that is down (`error` is `inactive`), logs
`auth.session_revoke_denied.audit_unavailable`. A write still running after the 2 seconds the route
waits logs `auth.session_revoke_denied.audit_slow` (the row may still land); if it then fails, or
fails after the client hung up, `auth.session_revoke_denied.audit_failed_late` follows. Those lines
have no series of their own, so count the lines to bound the probes with no row.

Deliberately not served on the metrics listener: `auth_sessions_active` (a process-local gauge that
drifts: it never drops on expiry or rotation, and a restarted process drives it negative; the database
is the truth for live sessions) and `cv_ws_errors_total{code}` (its label name is not on the Semgrep
metric-label allow-list, decision in #2747; the WS cases are covered by the other `cv_ws_*` series).
The other module-level auth counters outside `AUTH_EXPORTED_NAMES` (`auth/metrics.py`) also stay
unscraped.

Note: the role-change route writes `rbac.denied` with detail `owner_floor` when you try to demote the
last active Owner (`409`).

## 8. Rotate fixture/test credentials and CI secrets used by the auth suites

Principles: nothing here prints, stores or commits a secret. Rotation is done by an Owner in the
repository's secret settings, never from an agent session.

- **ZAP authenticated scan.** CI secrets `ZAP_FIXTURE_USER`, `ZAP_FIXTURE_PASSWORD`,
  `ZAP_FIXTURE_TOTP_SECRET` (`docs/security/auth-security-gates.md`, "ZAP"; workflow
  `.github/workflows/dast-auth-zap.yml`). Rotate: create a new fixture user on a non-production
  stack, enrol TOTP, replace the three secrets, run the workflow manually, confirm the logged-in
  indicator check passes. The fixtures are not yet provisioned in CI (gate X3-1 / #1778 item D), so
  there may be nothing to rotate yet.
- **Auth key settings.** `auth_totp_key_hex`, `auth_recovery_hmac_key_hex`, `auth_pepper`
  (`settings.py`). **Do not rotate these casually.** Changing the pepper invalidates every stored
  password hash; changing the recovery HMAC key invalidates every unused recovery code. No migration or
  re-key tool exists for either. Treat as BLOCKED — not implemented; escalate to the Owner.
- **CSRF key (`auth_csrf_key_hex`, SR-041, #2090).** Dedicated 32-byte hex key for the
  `__Host-cv_csrf` token MAC; required on live or `storage_backend=real`. Rotate: set the old value
  as `auth_csrf_previous_key_hex` (verify-only) and a new `auth_csrf_key_hex`, restart, then drop the
  previous key after one refresh lifetime (12 h). A dropped or changed key only forces clients to
  re-fetch the cookie via `GET /auth/session`; no data is lost. Startup refuses a CSRF key (current
  or previous) equal to the TOTP or recovery key. Alerts: `CsrfRefusalsHigh`, `CsrfRefusalAuditDegraded`,
  `CsrfRefusalAuditUnavailable` (`docs/plan/07-release-and-prr.md#alert-csrfrefusalshigh`).
- **SR-042 origins (`CV_ALLOWED_ORIGINS`).** The allow-list decides. The CSRF guard admits a
  state-changing request whose `Origin` is in this exact list, whatever `Sec-Fetch-Site` says (a
  listed app origin on another site works, as on the WS upgrade), and refuses any other `Origin`.
  A request with no `Origin` is refused only when it carries `Sec-Fetch-Site: cross-site` or
  `same-site`. `null` and wildcards are never accepted. Empty (the default) refuses every browser
  write, which is the production fail-closed state. Set it before rollout to each origin the web app
  is served from, scheme + host + port, comma separated, e.g.
  `CV_ALLOWED_ORIGINS=https://candleviewer.<tailnet>.ts.net`. The dev compose override
  (`infra/compose/docker-compose.dev.yml`) defaults it to the Vite dev and preview origins
  (`http://127.0.0.1:5173`, `http://localhost:5173`, `:4173`).
- **Electron desktop shell.** In dev (`CV_DEV_SERVER_URL`) the renderer runs on the Vite origin
  above and works unchanged. The packaged shell loads `file://…/index.html`, so its requests carry
  `Origin: null` and are refused by design (never allow-list `null`), and the backend's
  `__Host-cv_csrf` cookie is not readable from a `file://` page. Packaged-Electron writes need a
  privileged custom scheme or a main-process proxy, which is not part of #2090 (see the PR).
- **Unit and contract tests** use in-process fakes and keys generated inside the test process; there
  is no shared credential to rotate.
- **Secret scanning.** If a fixture secret leaks, follow `SECURITY.md` and rotate immediately.

## 9. A user says their correct TOTP code is refused (clock skew)

The server accepts the current 30 s step and one step either side (SR-021, `TOTP_SKEW_STEPS` in
`auth/totp.py`). A code from a clock further off is refused exactly like a typo: the one generic
`401` at login (`api/auth.py`), the same refusal at enrolment confirmation and step-up. **The user
is never told it is a clock problem** (a distinct answer would be an oracle). The operator is, in
two places, **about six minutes after the refusal** (#2146):

- `auth_totp_clock_skew_total{kind}` on the metrics registry: the private listener
  (`127.0.0.1:9108`) and, today, also the API app's unauthenticated `/metrics` route. `kind` is
  `authenticator_behind` or `authenticator_ahead`.
- One `system_events` row: `component` `auth`, `kind` `totp_clock_skew`, `severity` `warning`,
  `details` `{kind, offset_steps, refused_at}` (a step is 30 s; `event_ts` is the publication,
  `refused_at` the refusal, also in `message`). It holds no user id, code or secret, and nothing
  joins it to a user exactly: match `refused_at` and the source address against the `auth.login`
  audit row (it names the identifier) and the `auth.mfa_failed` row (address only).

The delay is deliberate. A code for a step ahead stays acceptable for up to 5 minutes, and a counter
that moved at once on the public route would tell whoever holds a password which refused guess to
resend. Reports wait in memory for `SKEW_HOLD_S` (`auth/totp_skew.py`; at most 256, the newest beyond
that is dropped and logged as `auth.totp_clock_skew_dropped`) and a restart inside the wait discards
them. Only a code that is right for a step 2 to 10 steps (1 to 5 min) from the server's, and newer
than the method's last accepted code, is reported: a wrong guess, a code further off and a replay
of an accepted code stay silent.

1. Confirm: `curl -s http://127.0.0.1:9108/metrics | grep auth_totp_clock_skew_total` is non-zero
   and rising. The events are in the support bundle (`POST $API/admin/support-bundle`,
   `system_events.json`, `message` only) or in the `system_events` table (`component` `auth`,
   `kind` `totp_clock_skew`).
2. Whose clock? One user, always the same side: that user's device. Several users at once, or
   everyone after the host slept and resumed: the **server**. Check `exchange_clock_drift_ms`, the
   `BybitClockDrift*` alerts (`docs/plan/runbooks/clock-sync.md`) and the host time source first.
3. Fix the clock, not the tolerance. Device: automatic time on (or the authenticator app's time
   correction), then sign in again from the password step. Server: correct the host time. No
   setting widens the window and none may be added (SR-021).
4. Verify: a fresh sign-in succeeds and the counter stops rising.

## 10. An audit outcome record was lost (`AuthAuditOutcomeLost`, `AuthAuditOutcomesLostBurst`)

The alert runbook is `docs/plan/07-release-and-prr.md#alert-authauditoutcomelost`. Two session
routes write a record after the service has acted or refused, so a refusal of the sink cannot undo
the decision and the answer stands. `POST /auth/logout` writes one `auth.logout` row first (naming
its targets in `after_state.session_ids`: the first 50, with the total in
`after_state.session_count`), revokes, then writes one `auth.session_revoked` row per session it
revoked: a refusal at the first row is a `503` that changes nothing, at a later row still a `204`.
`POST /auth/refresh` writes `auth.refresh_reuse_detected` for a concurrent-refresh race after the
service has refused it, and `auth.session_refreshed` (`denied`, reason `user_disabled`, #2911)
after it refuses a disabled user's refresh; the answer stays the uniform `401`.

Each lost row adds one to `auth_audit_outcome_lost_total{action}` and logs one error,
`auth.session_audit.outcome_lost`, with `action`, `session_id` and `error` (the writer's refusal
class, `inactive`, `cancelled` for a request cancelled part-way, `timeout` for a write that did not
return within the audit timeout, 2 s, or the class name of any other error the writer raised, a
defect that also answers the request `500`: the row in flight may have landed, so check the trail,
and the rows after it were not tried; a sign-out cancelled while it revoked has a `cancelled` line
for each session it targeted and no row for any, so read each `sessions` row (`revoked_at`) to see
which it ended; a refresh of a live token cancelled while the service ran has one `cancelled`
line for `auth.refresh_reuse_detected` whether or not the service found a reuse, so read the
family's `sessions` rows (`revoked_reason` `rotation_reuse`) before treating it as one); it
carries no token, address or user. Restore the audit sink first, then list
the gap from those lines. For a lost `auth.session_revoked`, the `auth.logout` row
already names the session (above 50 targets it names only the first 50: the rest are that user's
`sessions` rows with `revoked_reason` `logout_all` and a `revoked_at` at the time of that row) and
the `sessions` row (`revoked_at`, `revoked_reason`) records the revocation; a lost
`auth.refresh_reuse_detected` follows an `auth.session_refreshed` row, and its family is revoked
with reason `rotation_reuse` when the service found the token already rotated (a refresh that lost
the claim race to a concurrent one revoked nothing, so the log line and this row are the only
trace); a lost `auth.session_refreshed` denial leaves the attempt's own `auth.session_refreshed`
row (`success`) uncorrected: nothing was minted, and the user is `disabled` or gone. Never write
the missing rows by hand: only the audit writer writes the table. There is no
automatic retry: that half of rule 2 (`04-security-program.md` section 8.3) is the time-boxed
exception EX-07 (section 16.2), which ends when the journal-first lane (#3009) exists.

While the sink refuses records, sign-out, session revocation and refresh answer `503` and change
nothing (C-2.9): an access token lapses within 12 minutes and a longer refusal ends every session
and sign-in (accepted residual risk RR-16, `04-security-program.md` section 16.1). The break-glass
reset (section 3, E09-S11 #2119, not runnable yet) will be the Owner's emergency path: it runs only
with cv-api stopped and journals to its own host file, never the sink. `AuthAuditOutcomeLost` is a
`ticket`, muted 22:00-07:00 UTC by default (`CV_ALERT_QUIET_HOURS`) and active 15 minutes after the
last loss, so a lone loss at night is not delivered and the page (more than 5 in 15 minutes) does
not cover it (#2621, section 1): in the morning, read the counter and `outcome_lost` log lines.

No page does not mean the sink is healthy: the page reads only outcome rows lost after an action,
while a refusing sink makes every sign-out, revoke and refresh fail closed at its write-ahead record
with a `503` that no counter or alert sees. Those refusals show only as
`auth.session_audit.writer_refused` log lines (the alert runbook's third command greps them); a
counter for them is requested under #3009 and E27 KV-D04 (#2267). A page that has cleared is no
better evidence: it sends no `[RESOLVED]` message and clears with its 15-minute window, so the test
sign-out in the alert runbook entry (row 7) is the check.

## Known gaps referenced above

| Gap                                                                       | Reference            |
| ------------------------------------------------------------------------- | -------------------- |
| Break-glass CLI (SR-023)                                                  | #1778 item AB, #2119 |
| `PUT /auth/password` not implemented (no revoke-other-sessions on change) | #2110                |
| Scheduled audit-chain verifier                                            | #2111                |
| Disable-user drill on staging (SR-029)                                    | #2494, #300          |
| Activating the seeded `invited` bootstrap Owner (O5)                      | #2710                |
| No B16 record of the sessions that a lost disable commit revoked          | #2710                |
| Session rotation on role change and step-up                               | #2101                |
| Lock alerts lost inside quiet hours                                       | #2621                |
| No alert rule reads the session, invite, probe or step-up failure series  | #2746                |
| `cv_ws_errors_total{code}` not served (label `code` is not allow-listed)  | #2747                |
| No durable retry of a lost audit outcome record                           | EX-07, #3009         |
| No durable retry of a lost backstop audit record                          | EX-08, #3009         |
| A refused refresh of a disabled user neither revokes nor counts           | #3331                |
| A cancel after the revoking `UPDATE` loses count, log, publish and record | #3332                |
| No counter or alert for a write-ahead audit refusal (the `503`)           | #3009, #2267         |

## Execution record

Not executed on staging by a non-author: no staging host exists (#1778 item A); the run is tracked
in #2298. Security review of §3/§5 exists as an agent review on #2115; Ops review is recorded on #2343.
