# Auth / RBAC operator runbook (E09-K02)

Status: written 2026-10-09 against `main` at `d9143fb`; corrected 2026-10-13 against `main` after #2154 (QA gaps on #292); the lockout, authz and step-up metrics were updated 2026-10-15 for #2117, and the login-failure, session and invite signals for #2319; re-enrolment (§2 step 4) was updated 2026-10-16 for #2295, and the recovery sign-in (§1) for #2344; the audit volume (Quick facts and §3) was added 2026-10-17 for #2615; §4 was updated 2026-10-18 for #965 (the served disable and its limits); §12 was added 2026-10-18 for #3009 (the audit lane's offline release), and §13 on 2026-10-19 (its alerts and key rotation); §3 became runnable 2026-10-20 for #2119 (E09-S11), with a dry-run transcript, and was corrected 2026-10-23 from its cold run (#2494, E09-X04) and from the reviews of #4254 and #300; the idle-lock activity paragraph was added 2026-10-21 for #4012; it, §1 and §10 were updated 2026-10-21 for #2300 (unlock is live, extend is served), and the step-up penalty paragraph after it was added for #4051; §4, §10 and the known gaps were updated 2026-10-21 for #3009 (the lane's exit, ADR-0037 Amendment 1); §4's backstop paragraph names the two classifying middleware since 2026-10-22 (#3085 S7); §1, §10 and the known gaps were updated 2026-10-22 for #2914's PR C (the login routes' rows on the lane, ADR-0037 Amendment 2). Every command, route, metric and audit action
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

**What counts as activity for the idle lock (#4012).** The idle clock runs from the session's
`last_seen_at`. A request re-stamps it when its handler authenticates the bearer with
`authenticate_access_token(touch=True)`: the `/me` routes (`GET /me`, `/me/preferences`,
`/me/keymap`), `GET /auth/sessions`, MFA enrolment, and every route whose caller comes from a
session-backed principal resolver (`SessionAuditPrincipalResolver`, `SessionSnapshotResolver`,
`SessionRulesActorResolver`). That is most of the signed-in REST surface: the market-data and chart
reads (`/market/bars`, `/market/trades`, `/market/orderbook`, `/instruments` and its ticker,
`/indicators`), drawings, workspaces, `POST /telemetry/frontend`, the rules, audit and admin
routes, and owner user management. Find the resolvers with
`grep -rn 'touch=True' services/api/candleviewer` and their routers in `candleviewer/app.py`
(`audit_resolver`, `owner_resolver`). `POST /auth/session/extend` re-stamps it through
`SessionService.touch()`, after its write-ahead record; a successful `POST /auth/unlock` re-stamps
it too, in the write that lifts the lock.
Nothing else does: not `GET /auth/session`, `DELETE /me/sessions/{sessionId}`, `POST /auth/logout`,
the idle-lock middleware, the step-up and read-only guards, WS traffic, nor a token refresh, which
carries the presented session's `last_seen_at` to its successor. A tab whose only traffic is its
socket and its token refreshes (about every 11 minutes) therefore locks after its idle timeout, 15
minutes by default: its next refresh is answered `401 session_idle_locked`, and its socket ends
`token_expired` within one access-token lifetime. `POST /auth/unlock` with the password lifts
the lock (§1); `POST /auth/logout` and a new sign-in end it instead. The contract's "Activity is
explicit" model, in which only `POST /auth/session/extend` and `POST /auth/unlock` count, is not
what ships yet: activity stays implicit on the routes above until #2300's last slice, which waits
for the client (#1640).

**A token refresh keeps the step-up penalty (#4051, SR-025).** The successor session carries the
presented one's strike count and read-only window (`step_up_failures`, `readonly_until`), so a
refresh never lifts the downgrade. Step-up grants are never carried. The refresh's
`auth.session_refreshed` record names the penalty in `after_state` as the presented row held it when
the refresh was accepted (counts only); a strike that lands before the claim is carried and recorded
on its own, and one after it is refused, since the presented session is revoked by then.

## 1. Unlock a locked account (SR-016)

**There is no unlock command, endpoint or CLI for this lock.** `POST /auth/unlock` (#2300) lifts a
session's idle lock, never an account lock. A lock is `users.locked_until`, set by the shared
password check after the fifth failure: at login, at a step-up (§2), or at `POST /auth/unlock`,
whose wrong password counts toward it through `StepUpService.verify_password`. It clears in two
ways, both in code:

- it expires 15 minutes after it was set; or
- the next correct-password login after expiry resets the counter (`record_login_success` in
  `auth/repository.py`).

Preconditions: you know the user. Do not ask the user to retry during the lock window: a locked
account refuses even a correct password, at login, at a step-up and at the idle-lock unlock, where
each refusal also counts toward the five failed unlocks that revoke the session.

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
   as `abc***(len=9)`) per refused login attempt, and one with reason `unlock_failed` and the user
   id as actor when a wrong `POST /auth/unlock` password applied the lock.

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
check applies the lock: the fifth failure, or the first failure after an expired lock (at login,
from a wrong step-up password, §2, or from a wrong `POST /auth/unlock` password). At login and in
step-up the failure that trips the lock has no `auth.account_locked` row of its own (it is audited
as `auth.login_failed` or `auth.step_up_failed`), so there this counter is the only record that the
lock itself was applied. At `POST /auth/unlock` that failure's `auth.unlock_failed` row is followed
by an `auth.account_locked` row (reason `unlock_failed`), both written before the answer. The
counter does not name the user, it does not move for attempts refused while locked (at login, the
`auth.account_locked` rows above) and it does not move on a successful login, so it confirms that a
lock happened, not that it ended. Read it on the metrics listener (default `127.0.0.1:9108`, §6):

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
account**: the login rows in step 1 carry only a redacted identifier (first three characters and its
length; an `unlock_failed` row has the user id), and the lock itself is `users.locked_until`. Locks
in one burst arrive as one message (grouped by alert, component and environment). Two limits:

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
the user was disabled since the password step (#3054); `recovery_code` also per `auth.mfa_failed`,
`auth.login_failed` (a user disabled during the sign-in) and `auth.recovery_codes_exhausted` row of
`POST /auth/mfa/recovery`. It does not move for an attempt refused while the account is locked (the
`auth.account_locked` rows above), for a success, or for the WebSocket gateway's `auth.login_failed`
rows (actor `ws`, reason `ws_auth_failed`, written on the third failed `auth` frame of a
connection): `cv_ws_auth_failures_total{reason}` counts those, one per failed frame. Its
`user_mismatch` reason on a first `auth`, or on a re-`auth` whose token names the socket's own
user, means the principal store answered for another user: a server fault to investigate, not a
client error.
Every method is listed at 0 from process start. The `AuthLoginFailureSpike` rule reads it
(`sum(increase(...[10m])) > 10`); `sum by (method) (increase(auth_login_failures_total[10m]))`
shows which factor is attacked.

Owner's own account: the same expiry applies. If the Owner has lost the TOTP device,
`POST $API/auth/mfa/recovery` takes `{"mfa_token":"<from login>","recovery_code":"<code>"}`:

```bash
curl -s -X POST "$API/auth/mfa/recovery" -H 'Content-Type: application/json' \
  -d '{"mfa_token":"<mfa_token>","recovery_code":"<code>"}'
```

Expected `200` with `status: authenticated`, `tokens`, a `user` with `mfa_required` true and
`mfa_enabled` false, and the `cv_refresh` and `__Host-cv_csrf` cookies (#2344). The session is
**enrolment-only**: it lives 15 minutes and may only enrol and confirm a new TOTP, as in §2 step 4
(#2295). The call revokes every MFA method of the user, so the lost device can never be confirmed
again, and every other session of the user. A code is single use. A wrong or spent code, an
expired or locked challenge and any other refusal answer the same `401` and spend nothing; five
wrong codes lock the challenge, so sign in with the password again. That `401` also answers a
user disabled since the password step (`auth.login_failed`, reason `user_disabled`) and a
write-ahead audit record that cannot be written (error log `auth.recovery.audit_unavailable` names
the action). A refusal's own row goes to the audit lane first; one the lane and the sink both
refuse is counted lost (section 10) and the answer stands.
Before anything changes, `auth.recovery_code_used`, one `auth.session_revoked` (reason
`mfa_recovery`) per ended session and `auth.session_created` (`enrolment_only: true`,
`mfa_method: recovery_code`) are written; `auth.recovery_codes_exhausted` is written when none
remain. The spend records a `system_events` row (`auth`, `security.mfa_recovery_used`) in its own
transaction. Re-enrolment is forced after every
recovery sign-in, however many codes remain (`auth/mfa_service.py`); there is no remaining-codes
threshold (#2296). If the 15 minutes run out before the confirm, sign in with the password alone:
with no method left, that sign-in is enrolment-only too.

If the answer is `401` with `sign in again with your password`, the code was spent and every method
revoked, but no session was minted: the error log `auth.recovery.completed_unminted` names the
`user_id`, the `new_session_id` and the `revoked_session_ids` the call meant to end, or ended
beyond its records (the `unplanned` ones below), and an
`auth.mfa_failed` row (reason `unminted`) voids the `auth.session_created` written ahead. Those
sessions may still be live, but while the user has no method one that proved a second factor
answers `401` except to `POST /auth/logout`, one minted on the password alone reaches only the
enrolment operations, and the confirm ends them. Sign in with the password alone (enrolment-only)
and re-enrol. A session minted while the recovery ran ends with the others under its own
`auth.session_revoked` with `unplanned: true`, an outcome row through the lane: one the lane and
the sink both refuse is counted lost (section 10) and the recovery goes on. A recovery whose
transaction did not commit changes nothing, and its refusal row names the records it voids:
`auth.mfa_failed` with reason `lost_race` (a concurrent recovery won) or `store_error` (error log
`auth.recovery.commit_failed`), or `auth.login_failed` (`user_disabled`) when the user was disabled
meanwhile; the status is read under the user-row lock. A user disabled after the spend gets `401`
`account is disabled` and an `auth.login_failed` row that voids the session. An Owner's recovery
sign-in moves
`auth_enrolment_only_sessions_total{role="owner"}` (§2 step 4).

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

4. The user re-enrols on their next sign-in (#2295). The reset also sets their `mfa_required`, so
   `POST /auth/login` with the password answers `200` with an **enrolment-only** session: it lives
   15 minutes and may only call `POST /auth/mfa/enroll`, `POST /auth/mfa/enroll/confirm`,
   `GET /auth/session`, `POST /auth/refresh` and `POST /auth/logout` (anything else is
   `403 mfa_enrollment_required`; the WebSocket closes with `4403`). The user enrols a new TOTP, then
   confirms a code: that revokes their other methods and sessions, replaces their recovery codes
   with 10 new ones (shown once) and returns a full session. If the 15 minutes run out, they sign
   in again. Verify: audit `auth.session_created` with `enrolment_only: true`, then
   `auth.mfa_enrolled` and `auth.recovery_codes_regenerated` for the user; counter
   `auth_enrolments_total{result="completed"}` rises by 1 (`refused` counts wrong codes). A sign-in
   whose user was disabled since the password check gets `403`: its `auth.login_failed` row carries
   `session_id` and `after_state.voids_session_created`, so its `auth.session_created` row is void.
   A confirm whose transaction did not commit changed nothing (the method is still pending, the
   codes and sessions are as they were): the error log `auth.enrolment.commit_failed` names the user
   and the new session, and the refusal row voids that session's `auth.session_created` the same
   way. It is `auth.mfa_failed` with reason `lost_race` (`422`, a concurrent confirm or enrolment
   won) or `store_error` (`500`), or `auth.login_failed` (`user_disabled`, `401`) for a user
   disabled since the confirm read it, read again under the user-row lock (#2911).
   - If confirm answers `503`, the user signs in again. When the error log
     `auth.enrolment.completed_unrotated` names the user, the enrolment completed but the session
     was not rotated: the new TOTP is active (the next sign-in asks for it), its 10 recovery codes
     were never shown, and the sessions the log lists may still be live. The caller's own
     (`session_id`) stays enrolment-only and ends within 15 minutes of its sign-in. Any other id in
     `revoked_session_ids` may be a full session that proved the user's previous factor: it is full
     again now that a method is confirmed. Revoke it at once by resetting the user's TOTP again
     (steps 1 to 3; the reset revokes every session of the user). The user has no recovery codes
     they can read; if they need a set, a reset (this section) makes the next confirm show one.
   - An enrolment-only sign-in by an Owner (`auth_enrolment_only_sessions_total{role="owner"}`
     rising) is expected only after an Owner TOTP reset, a recovery sign-in or a first sign-in.
     Otherwise treat it as U34 in `04-security-program.md` (a stolen password enrolling a TOTP,
     RR-15): find the `auth.session_created` record with `enrolment_only: true` and its source
     IP. The paging rule on that series is not written yet (#2746).
5. Verify from telemetry: audit action `auth.mfa_reset_by_owner` (severity critical) with the
   target user:
   `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=auth.mfa_reset_by_owner"`;
   counter `auth_mfa_resets_total` rises by 1 on the API process (`auth/metrics.py`).

Note: `auth.mfa_reset` also exists in the audit vocabulary, but the Owner route writes
`auth.mfa_reset_by_owner`. Search for that name.

Expected elapsed time: not measured. E09-X04 did not run a reset drill; this is a gap, not an estimate.

## 3. Break-glass for total Owner lockout (SR-023)

Runnable since #2119 (E09-S11): `python -m candleviewer.breakglass`, the offline CLI of SR-023 and
of the break-glass trust boundary (`docs/security/threat-models/e09-auth-rbac.md` §3.6.1). It
resets the named Owner's MFA and nothing else: it mints no login, session, token or recovery code
(decision O2). It has been rehearsed on a local throwaway database (dry-run transcript below in
this section), and on 2026-10-23 a non-author ran it cold on a dev compose stack on the real backend
(#2494, E09-X04: steps 1 to 5, from the handoff to cv-api restarted, took 7 min 41 s, or about
5 min 47 s without a terminal detour; step 6, the Owner's re-enrolment, was not drilled); not on
staging (#1778 item A). U10 is the lockout case of `docs/security/threat-models/e09-auth-rbac.md`;
O1 to O3 and R8 are #2119's decisions (the possession proof, the reset's scope, live gating and the
alert routing); FU-1 is `docs/plan/spikes/e27-kek.md`'s follow-up, #2151.

**When.** The sole Owner cannot sign in: the TOTP device is lost and no unused recovery code is at
hand (U10). An Owner who still holds an unused recovery code signs in with it instead (§1), which
needs no host access. In `live` a total loss (the device and every code) has no CLI path, because
the CLI itself needs one unused code there (O3 below): do not hand-edit `users`, `mfa_methods`,
`recovery_codes` or audit rows; escalate to the repository owner, who decides on direct database
repair under the security process. Record the incident in every case.

**What a run does.** It opens the host journal under the run lock and writes
`auth.break_glass_attempt` into it, then checks, in this order: `--live` against `CV_ENVIRONMENT`,
the KEK, that no other session of cv-api's database role is connected, the Owner, the terminal and
the retyped phrase, and in `live` one recovery code. Then one transaction revokes every MFA method
and live session of the Owner (`revoked_reason` `break_glass`) and raises the critical, unresolved
`system_events` row `auth`/`break_glass_used`, which cv-api announces as a `system` notice (reason
`auth.break_glass_used`) after each client's first WS `auth_ok`. The run's last record is
`auth.break_glass_reset` or `auth.break_glass_refused` with its reason. Every record is critical,
with actor `system:breakglass` and the run's id as `request_id`; the CLI writes it to
`breakglass/journal.wal` under the run lock and flushes it to `audit_log` before it exits. What
Postgres could not take (it was down) stays in the journal, and cv-api folds it into `audit_log` at
its next boot, exactly once. No option skips a check or a record, and nothing secret is printed or
logged.

**Exit status.** The reason in the refusal record is the status name in lower case.

| Status                                                             | Meaning                                                                                                                                                           |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0                                                                  | Reset done, and every record is in `audit_log` or waiting in the journal (the last line says which).                                                              |
| 1 `step_failed`                                                    | A check broke (an error, or no answer within 60 s); nothing changed.                                                                                              |
| 2                                                                  | Usage or settings error (`--owner` missing, invalid settings, `CV_AUTH_RECOVERY_HMAC_KEY_HEX` unset or not 32 bytes of hex): nothing ran and nothing is recorded. |
| 3 `reset_failed`                                                   | The reset transaction failed and rolled back, unless the link broke at COMMIT: an unresolved `break_glass_used` event means it applied.                           |
| 4 `host_fs_unavailable`                                            | `CV_AUDIT_WAL_PATH` is relative, holds `..` or a symlink, or the journal is unusable.                                                                             |
| 5 `api_running`                                                    | cv-api or another break-glass run holds the run lock, or another session of its database role is connected.                                                       |
| 6 `audit_unavailable`                                              | A record could not be written. If it was the attempt, nothing was checked; if it was the closing record, the line above it says how the run ended.                |
| 7 `live_flag_required`, 8 `live_flag_mismatch`                     | `--live` is missing in `live`, or given outside it.                                                                                                               |
| 9 `kek_unproven`                                                   | No KEK, a wrong or retired one, or one no cv-api boot enrolled for this environment: the proof never enrols one (decision O1).                                    |
| 10 `not_owner`                                                     | The name is unknown, deleted, disabled or not an active Owner.                                                                                                    |
| 11 `no_tty`, 12 `confirmation_mismatch`, 13 `confirmation_timeout` | No terminal; the phrase was not retyped exactly; it was not retyped within 5 minutes.                                                                             |
| 14 `recovery_code_required`, 15 `recovery_code_invalid`            | `live` only: no code, or not an unused code of this Owner. Nothing is consumed.                                                                                   |
| 16 `operator_cancelled`                                            | Ctrl-C before the reset began.                                                                                                                                    |
| 130                                                                | A second Ctrl-C: the outcome is unknown. Read the run's audit rows (and look for an unresolved `break_glass_used` event) before running it again.                 |

**Preconditions.**

- cv-api is stopped, and nothing else is connected as its database role: a `psql` session of that
  role counts, so close it.
- Postgres is up.
- The KEK, through cv-api's own custody path: the same `CV_KEK_SOURCE`, `CV_KEK_HANDLE` and
  `CV_KEK_VERSION` as a cv-api start, and for a FIFO `CV_KEK_ACK_PATH` and a FIFO the launcher fills
  for this run (`docs/ops/runbooks/kek-custody.md`). Its check value must already be enrolled for
  this environment by a cv-api boot. In `live` a `file` KEK is refused, as for cv-api, and so is a
  run whose SR-009 process hardening did not take effect. The launcher and systemd steps are not
  drilled yet (FU-1, #2151). Where cv-api has no KEK, the CLI refuses `kek_unproven` and changes
  nothing. The settings default to `CV_KEK_SOURCE=handle`, `CV_KEK_HANDLE=/run/secrets/cv_kek` and
  `CV_KEK_VERSION=1`, so outside `live` a stack that mounts its KEK there passes the proof with the
  three unset: only an unreachable KEK is "no KEK" (Drilling the refusals, below).
- cv-api's recovery-code key, `CV_AUTH_RECOVERY_HMAC_KEY_HEX`, in every environment: without 32
  bytes of hex in it the CLI exits 2 before it runs anything (the `live` rule checks the code with
  it). Never put its value, or any other secret, on a command line or in this file.
- A terminal, on your side too: `docker compose run` allocates the container's only when the shell
  it runs from has one, and never with `-T` or with its output piped (`| tee` included). Over ssh
  use `ssh -t`; from automation, run it under a pty. Without one the run ends `no_tty` (11), and
  still writes its attempt and refusal records.
- In `live`: `--live`, and one unused Owner recovery code from the SR-023 sealed envelope.

**Procedure (compose).** Use the compose files (`-f`) and project (`-p`) of the running stack, as
`docker compose ls` lists them, so that the run gets cv-api's settings, KEK handle and audit volume:
without them a command fails, or runs in another project with a new, empty audit volume. Below,
`$COMPOSE` stands for that prefix, set once:

```bash
COMPOSE="docker compose -p <project> -f infra/compose/docker-compose.yml -f <override> --profile core"
```

The repository's compose files (`infra/compose/`) run the fake backend and set neither
`CV_AUTH_RECOVERY_HMAC_KEY_HEX` nor a KEK for `api`: with them alone the run exits 2, and no boot
ever enrolled a KEK check value, so the stack must add both and run the real backend (its own
override file or environment). The #2494 drill's stack also needed `CV_STORAGE_BACKEND=real`, the
auth keys and pepper, a volume at `/data` owned by uid 10001 and holding a `parquet` directory (the
cold tier's root, `/data/parquet`: the real backend's storage creates nothing and refuses to start
without it; a clean stop also writes `/data/admin-jobs/`, and a recording `/data/recorder-wal`),
`CV_MESH_CIDRS_CSV` naming the compose network (without it the healthcheck itself gets `403`), and
`CV_ALLOWED_ORIGINS` for a client's WebSocket. Every compose command then warns that the secrets'
`uid`, `gid` and `mode` are not supported outside Swarm mode: expected, since the host files carry
them (the audit lane key, below).

1. Record the incident in its ticket before you start: who, when, why, and who has the host. Every
   run that writes its attempt record pages (R8; the limits are under Alerts, below), refused ones
   included, and the pages need that context.
2. Stop cv-api and check that it is down:

   ```bash
   $COMPOSE stop api
   $COMPOSE ps -a api
   ```

   Expected: `api` is `Exited`, and `$COMPOSE ps api` lists no running `api`.

3. Run the CLI as a one-off container of `api`, naming the Owner by username or email, and add
   `--live` in `live`. The line replaces the image entrypoint (`candleviewer.server`, which takes no
   arguments) and has no `-v` and no `--user` of its own (see the audit volume below):

   ```bash
   $COMPOSE run --rm --no-deps --entrypoint python api -m candleviewer.breakglass --owner <owner username or email>
   ```

   Retype the phrase it shows, `reset <owner> on <environment> <6 hex digits>`. In `live` type one
   unused recovery code when asked: it is not echoed, and the reset consumes it.

4. Read the last lines. `Break-glass reset done ...` and `Audit: every record reached audit_log.`
   is the expected end (exit 0). `Audit: records waiting in the host journal: N` means Postgres did
   not take them: they reach `audit_log` at the next cv-api boot. A refusal names its reason (table
   above): fix it and run again; each run is a new attempt with records of its own. The run's id is
   the `run_id` of its `breakglass.run_ended` JSON line (`breakglass.refused_unjournaled` when the
   journal could not be opened: a 4, or a 5 for a held run lock; for a 6,
   `breakglass.attempt_unrecorded` or `breakglass.outcome_unrecorded`), and the `request_id` of its
   records. A `host_fs_unavailable` (4) shows its cause as
   `[redacted:key-shape]`: check `CV_AUDIT_WAL_PATH` and the volume (The audit volume, below). Its
   attempt and refusal still reach `audit_log`, written straight to Postgres. With no usable
   journal and Postgres unreachable too, a 4 or 5 ends
   `Audit: no record could be written (pre-audit refusal)` (as does a 6 whose attempt record
   failed): nothing was checked or changed, no record of the run exists, and so it does not page.
   That is the documented pre-audit refusal of #2119's S3 criterion, a residual of the threat model
   (`docs/security/threat-models/e09-auth-rbac.md` §3.6.1); the JSON line names the reason. To read
   a run's records and the event (read-only):

   ```bash
   $COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT id, action, outcome, event_ts FROM audit_log WHERE request_id = '<run id>' ORDER BY id;
   SELECT id, severity, correlation_id, resolved_at, event_ts FROM system_events
    WHERE component = 'auth' AND kind = 'break_glass_used' ORDER BY id;
   SQL
   ```

   Read between runs, never during one: in a stack whose cv-api logs in as `POSTGRES_USER`, as the
   dev stack's does, an open session of it makes a run refuse `api_running` (5).

5. Start cv-api again (`$COMPOSE start api`). Expected: `$COMPOSE ps api` shows `healthy` within
   about 30 s, and the boot appends `audit.lane_resumed` and `security.kek_loaded`. It refuses to
   boot while a CLI run holds the lock.
6. The Owner signs in with the password, gets an enrolment-only session and enrols TOTP again (§2
   step 4), then seals the 10 new recovery codes in the envelope (SR-023).
7. The `break_glass_used` event stays unresolved, and every client's first WS authentication gets
   the notice, until the Owner resolve route exists (E09-S12, not built; filing it is #2710 item 2).
   Do not edit `system_events` by hand. Another user's full session gets the notice at once (its
   `auth_ok` is followed by a `system` frame with reason `auth.break_glass_used`); the Owner's own
   comes after re-enrolment, since an enrolment-only session's socket closes `4403` (§2 step 4).
   Each reset raises its own event, so a second, mistaken reset leaves a second one, and the CLI's
   `system event N raised` names the event's id, not a count.

**Alerts (R8).** `AuthBreakGlassAttempted` pages for every run that writes its attempt record,
refused ones included (it counts `auth.break_glass_attempt` rows, so a pre-audit refusal does not
page), with three limits: it sees no rise without Prometheus history of the series (a new
Prometheus, or a refused run after cv-api was stopped for over a week); runs under 15 minutes apart
share one page; and the page comes only at the first scrape after cv-api restarts, since the CLI
runs while it is stopped (see the rule's comment in `infra/prometheus/alerts/system_page.yml` and
`docs/plan/07-release-and-prr.md#alert-authbreakglassattempted`). A completed reset still pages
through `AuthBreakGlassUsed`, which needs no history: it pages while a reset's event is unresolved.
`AuthBreakGlassStateReadFailing` is a ticket when cv-api cannot read that state (their sections in
`docs/plan/07-release-and-prr.md`). main-orchestrator ruled this routing (page, page, ticket) on
2026-10-17 under the owner's delegation; it awaits the owner's confirmation on #2119. A severity is
one label in `infra/prometheus/alerts`.

**Drilling the refusals (#2494).** Outside `live` only: an injection that fails to stop would
consume a live recovery code and reset the real Owner (A7 showed one can, in
`docs/security/reviews/e09-auth-review.md` section 3), and in `live` the KEK default is refused
(`secrets/_source.py`). A drill outside `live` pages too, since the rule has no environment filter
and Alertmanager routes by severity alone: every run that writes its attempt record pages (R8;
limits above), so warn the on-call first. Run each injection with `-T`, so that a run which passes
the check under test stops at `no_tty` (11) and never reaches the prompt. Leaving the KEK variables
unset is not "no KEK": they default to the compose secret's path, so a mounted KEK still loads and
the proof passes. Point the handle at an absent path instead; a relative audit path drills 4. Each
still writes an attempt and a refusal record:

```bash
$COMPOSE run -T --rm --no-deps -e CV_KEK_HANDLE=/run/secrets/absent_kek --entrypoint python api -m candleviewer.breakglass --owner <owner>   # 9 kek_unproven
$COMPOSE run -T --rm --no-deps -e CV_AUDIT_WAL_PATH=audit.wal --entrypoint python api -m candleviewer.breakglass --owner <owner>             # 4 host_fs_unavailable
```

**Live gating (O3).** In `live` the CLI requires `--live`, the phrase naming `live`, and one unused
Owner recovery code, verified offline against its hash and consumed in the reset's transaction:
the rule ratified in ADR-0009 Amendment 1. There is no path with `--live` and the phrase alone.
The owner may relax the code requirement (O3, asked on #2701); until then it stays, as ruled on
#2119 on 2026-10-20 (see the comment of that date).

**Dry-run transcript** (2026-10-20, this procedure's CLI as built for #2119, E09-S11 slices 5 and
7, run directly with the settings in its environment as
`docker compose run` passes them: a throwaway local Postgres 16 at head, `CV_ENVIRONMENT=demo`, a
test KEK file enrolled for `demo`, a test recovery-code key, and a seeded `drill_owner` with one
TOTP method and two live sessions; no real credential). The JSON lines are the CLI's structured
log, which shares stdout with its text. Afterwards `audit_log` held the six records of the three
runs, and `drill_owner` had no unrevoked MFA method, no live session and one unresolved
`break_glass_used` event.

```text
$ python -m candleviewer.breakglass --owner drill_owner   # the operator declines at the phrase
{"environment":"demo","event":"secrets.kek_file_source","env":"demo","level":"warning","ts":"2026-10-20T05:47:36.075989Z"}
Break-glass revokes every MFA method and session of drill_owner on demo.
To confirm, type: reset drill_owner on demo 1259F1
> no
{"run_id":"96d783a3-cefb-4042-91eb-7ce4708c48a0","reason":"confirmation_mismatch","event":"breakglass.run_ended","env":"demo","level":"warning","ts":"2026-10-20T05:47:36.135245Z"}
Break-glass ended without a reset (confirmation_mismatch); nothing was changed.
Audit: every record reached audit_log.
$ echo $?
12

$ python -m candleviewer.breakglass --owner drill_owner   # a session of cv-api's database role is connected
{"environment":"demo","event":"secrets.kek_file_source","env":"demo","level":"warning","ts":"2026-10-20T05:47:36.802858Z"}
{"run_id":"fa443d74-7d58-4c5b-933f-8b09792fdb29","reason":"api_running","event":"breakglass.run_ended","env":"demo","level":"warning","ts":"2026-10-20T05:47:36.849498Z"}
Break-glass ended without a reset (api_running); nothing was changed.
Audit: every record reached audit_log.
$ echo $?
5

$ python -m candleviewer.breakglass --owner drill_owner   # the reset
{"environment":"demo","event":"secrets.kek_file_source","env":"demo","level":"warning","ts":"2026-10-20T05:47:37.473797Z"}
Break-glass revokes every MFA method and session of drill_owner on demo.
To confirm, type: reset drill_owner on demo 8042A6
> reset drill_owner on demo 8042A6
{"run_id":"12bcf1d2-b6b3-4f70-affb-05d39f2dab96","reason":null,"event":"breakglass.run_ended","env":"demo","level":"warning","ts":"2026-10-20T05:47:37.533661Z"}
Break-glass reset done for drill_owner on demo: 1 MFA methods and 2 sessions revoked, system event 1 raised. The Owner enrols TOTP again at the next sign-in.
Audit: every record reached audit_log.
$ echo $?
0
```

**The audit volume (#2615).** In compose, cv-api and the break-glass CLI share one audit directory:
the named volume `cv-audit-data`, mounted at `/var/lib/candleviewer/audit`,
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
  $COMPOSE exec api ls -ldn /var/lib/candleviewer/audit
  # cv-api stopped
  $COMPOSE run --rm --no-deps --entrypoint ls api -ldn /var/lib/candleviewer/audit
  ```

**The audit lane key (ADR-0037 decision 6, #3009).** The key is a compose file secret, never on
the audit volume: `CV_AUDIT_LANE_MAC_SOURCE` in `infra/compose/.env` names the host file, which
compose mounts as it is at `/run/secrets/cv_audit_lane_key`, so the file itself must hold 64 hex
digits, mode `0400`, owner and group 10001 (`install -m 0400 -o 10001 -g 10001`). Keep it in a
root-owned `0700` directory outside the checkout and outside every path a compose file bind-mounts
(the dev overlay mounts `services/api/candleviewer`), and give uid 10001 no login on the host:
whoever runs as it can read the key. Unset, the source is `/dev/null`, which a real backend refuses;
compose runs the fake backend today, which never reads it. Rotation and `_PREVIOUS_` retirement
are S4a's rows.

## 4. Disable a user and what follows (SR-029)

`DELETE /users/{userId}` (`api/users.py`, E42-T04 #965) disables a user: Owner only, never your own
account, after a step-up for action class `users` (§2). No position or order source is deployed
yet, so it answers `409 positions_unknown` until it carries `acknowledge_unknown_positions=true`.
Any other query parameter answers `422 validation_failed` and changes nothing. `purge=true`
(E42-T10) then schedules the user's anonymisation 90 days out, `users.delete` written ahead; while
no purge reaper runs it answers `503 purge_unavailable` and changes nothing. The reaper runs on
every deployment with a store, whatever `CV_RETENTION_ENABLED` says, and the lifespan starts it. A
`503 audit_unavailable` or `503 purge_unavailable` whose `detail` says the user is disabled means
the disable committed but no purge is scheduled: repeat the call. Once the date has passed the
reaper anonymises the user and revokes every credential (password, MFA methods, recovery codes,
live sessions) in one transaction, `users.anonymise` written ahead. Its log line
`users_anonymised` counts each batch, and a row it passed over is counted by its error class at
error level; nothing alerts on an overdue purge yet (UL-F6). A run that a failure ended (the read,
the audit writer or the database refusing) is retried after 15 minutes, doubling up to a day. A
socket close that fails is counted on that line too, and the session's B16 record is still written.
To cancel a pending purge, re-enable the user before the date (`PATCH /users/{userId}` with
`status: active`): its `users.enable` record names the cancelled date. Once the user is anonymised
every `PATCH` of that user that would change it (a re-enable, a name, the MFA flag, a role)
answers `409 conflict` and changes nothing, recorded as `rbac.denied` with reason `anonymised`. To find an overdue purge, list
the disabled users whose date has passed and whom the reaper has not anonymised (`psql` runs inside
the `postgres` container, in a read-only session):

```bash
docker compose -f infra/compose/docker-compose.yml --profile core exec -T \
  -e PGOPTIONS='-c default_transaction_read_only=on' postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT id, purge_after FROM users
WHERE status = 'disabled' AND anonymised_at IS NULL AND purge_after <= now()
ORDER BY purge_after;
SQL
```

One transaction sets the status, revokes the sessions and grants and writes `users.disable` ahead;
then each step (sockets, sweep, B16, rule scope, rule disarm, invite) runs alone, so a `204` can hide
a failed one: it logs the error line `users.disable.step`, and a repeat of the call re-runs the
sockets, the sweep, the scope refresh and the disarm. The socket step ends every socket of the user
with `bye` `user_disabled` and `4403`, one still on a session that a refresh rotated and one on
which the user views as another user included (the registry holds that one under its target and
finds it by its viewer). A socket on which another user views as the disabled one ends its view
instead, with `bye` `view_as_expired` and `4403`. The disarm lists the user's armed rules again
after its disarms, so a rule armed meanwhile is disarmed
too. A rule its chart refuses (evaluating, acting, pending confirmation or spent) stays armed with
no grant and no permission to act on (O4, O5); a repeat disarms it once it is back in `armed`, which
a rule pending confirmation or spent reaches only through its confirmation or `RESET_ONCE` (#3226).
A new socket whose `auth` completes around the commit, on a session the user's own refresh rotated,
can register after the socket step. The registry remembers the disabled user for one access-token
lifetime, so that socket gets `bye` `user_disabled` and `4403`, never `auth_ok` (#3413). Only once
1024 other users are disabled within those 12 minutes is the user forgotten, and the socket then gets
`auth_ok` on the deny-all principal, with no private topic, until its token expires (UL1-E2's
residual in `docs/security/threat-models/e42-user-lifecycle.md` §6).

What the cascade builds on, and what to read afterwards:

- `SessionService.revoke_all` (`auth/session_service.py`) and the socket hub
  (`ws/revocation.py`). Metric `auth_session_revocations_total{reason}` counts revocations (served on
  the metrics listener since #2319). `auth_revocation_latency_seconds` (served there since #3415, no
  label) has one observation per revocation the hub attempted a socket close for, a disable's
  per-session closes included: from the revocation reaching the hub to the last of that session's
  closes initiated (`bye` queued and the connection sealed, so no data frame is sent after it) or
  failed. The socket step's per-user close (the WS registry's `user_disabled`) is one more
  observation of a disable that had a socket, from its start to the last of the user's closes
  initiated or failed; the cascade cuts that step off at 2 s. The socket's own close follows in the
  connection's writer and is not measured. `AuthRevocationLatencyHigh` raises a ticket when its p99
  over 15 minutes is above 5 s (`docs/plan/07-release-and-prr.md`, section 9). A close that fails
  is counted and logged on any of its three paths (next bullet).
- A close that fails (#3497, #3635). A close that raised or hit its bound (2 s each: the hub's
  per-session and per-context closes, and the registry's `send_timeout_s`) adds one to
  `ws_session_revocation_close_failures_total` (no
  label; served on the metrics listener, `127.0.0.1:9108`, with `env`), and the closes after it
  still run. The hub logs the error line
  `ws revocation close failed; revoked socket may remain open` with the `session_id`. The socket
  step's per-user close logs the error line
  `ws revocation close failed; disabled user's socket may remain open` with the `user_id` and
  `failed_total`, the process's running count of failed per-user closes (all users together). That
  line is written at most once a minute, and the first failure after a start always logs, so the
  counter, not the lines, is the number. A cancelled close is not counted: the cascade's 2 s cut-off
  of the per-user close is a failed `socket_close` step (`UserLifecycleStepFailed`, section 11), not
  a count here. That cut-off opens before the registry's `send_timeout_s`, so in a disable a hung
  per-user closer is that failed step and only a closer that raised is counted; the hub's closes
  normally run in its own shielded task, where its 2 s bound does end, and count, a hung close (past
  its close-task cap a batch closes inline, and the cascade's cut ends it first). The hub's
  per-context closes of a view-as context's end or start (`close_context`, #3085 S10) run inline in
  the caller, each bounded and counted as the per-session ones are; the view-as service's own 2 s
  bound on them (`CLOSE_TIMEOUT_S`) cuts a hung one first, which the hub sees as a cancellation and
  does not count, and the service logs `admin.view_as.close_failed` with `TimeoutError`. A close
  that failed inside the hub's loop or the per-user loop leaves that step
  `ok`, because each loop goes on to the next socket, so the counter and its lines are the only
  trace. The `WsRevocationCloseFailed` ticket fires on any increase
  (`docs/plan/07-release-and-prr.md`, section 9) and is held 9 h 30 m;
  `ExpectedMetricMissingWsSessionRevocationCloseFailuresTotal` fires if the series is not scraped.
- What an increase means, and what to check. The socket whose close failed can stay open until its
  access token ends, 12 minutes at most, and if its closer raised the connection may also not be
  sealed, so it can keep receiving its read-only streams. REST has refused the session (or the
  disabled user) since the revocation, and orders are REST only, so nothing can be placed through
  that socket. After a view-as context's end the session stays live and holds the ended context.
  The view-as guard's table (`api/view_as_guard.py`) then passes only the viewer's own operations
  (`OWN_OPERATIONS`: leave, the session's own read, refresh and logout among them; a protective
  write too, once its handler is mounted), and every other read or write answers `view_as_expired`
  until the client clears the context with `DELETE /auth/session/view-as`. A socket whose
  per-context close failed keeps the target's read-only streams until its next `auth` or the
  context's own expiry, whichever comes first. With the deployed gateway the closer seals the
  connection without waiting, so a failure is not expected: treat it as a regression and file a
  bug with the lines below. Check:

  ```bash
  curl -s http://127.0.0.1:9108/metrics | grep '^ws_session_revocation_close_failures_total'
  docker compose -f infra/compose/docker-compose.yml --profile core --profile obs logs --since 1h api | grep 'ws revocation close failed'
  docker compose -f infra/compose/docker-compose.yml --profile core --profile obs logs --since 1h api | grep '"event":"users.disable.step"' | grep '"step":"socket_close"'
  ```

  The first is the count since the process started: 0 when no close has failed. The second prints
  both lines, each with the closer's traceback: the hub's names the `session_id`, the per-user
  close's the `user_id`. Whether the socket outlived its revocation: a socket the revocation closed
  has a `ws close` line at that instant (`session_id`, `user_id`, `reason`, `code`) with the
  revocation's `reason` (`user_disabled` and `4403` for a disable); one that outlived it ends later,
  up to 12 minutes on, with `reason` `token_expired`. The third prints a disable's socket steps:
  `failed` is the cascade's own cut-off or a raise out of `user_disabled`, and an `ok` step does not
  show that every socket closed (a close either loop counted leaves it `ok`).

- `users.status = disabled` makes login refuse with `403 Account disabled` after a correct password.

What a `disabled` status does to sessions (#2911). It holds however the status was set, and it is
the backstop for a session that no disable revoked. A `locked` or `invited` status changes none of
it (login refuses `disabled` only):

- `POST /auth/mfa/verify` for a user disabled since the password step answers `401` and mints no
  session. The refusal is audited as `auth.login_failed` (`denied`, reason `user_disabled`) and
  counted in `auth_login_failures_total` on the method the request named (#3054).
- `POST /auth/refresh` with a disabled (or deleted) user's refresh token answers `401`
  `refresh_token_invalid`, before the session is claimed: nothing is rotated or minted, and the
  session is revoked as on a strict-path use (the next two bullets; #3331): reason
  `user_disabled`, counted, logged, published and recorded. Three records follow, in order: the
  write-ahead `auth.session_refreshed` of the attempt, the backstop's
  `auth.disabled_user_session_revoked` and the refusal, `auth.session_refreshed` (`denied`, reason
  `user_disabled`). While the audit sink refuses the write-ahead record the refresh answers `503`
  and revokes nothing; the first refresh after it recovers, or any strict-path use, revokes the
  session. A refresh revokes nothing before its write-ahead record is written (C-2.9), and no
  refresh issues a token while the sink refuses, so the user gains nothing; the outage shows as
  `cv_audit_writer_refused_total{domain="auth"}` (alert `AuditSinkRefusing`) and as
  `auth.session_audit.writer_refused` log lines naming the action. A disable that commits after
  the claim leaves no live successor either: the mint reads the status under a lock on the user
  row, and the disable's own lock queues behind it.
- A session that survives is revoked on its next strict-path use, with reason `user_disabled`: the
  first REST request that authenticates it (every route but `POST /auth/logout`, which accepts it
  so the user can still sign out) or the first socket `auth` that presents its token. The request
  answers `401`, and the sockets already on that session end with `bye` `user_disabled` and
  `4403`; the socket whose first `auth` presented the token gets `err` `auth_failed`
  (`docs/plan/23-ws-protocol.md` §9.5). A handler skips the backstop in one of two ways: it finds
  its session with `_identify` (`api/sessions.py`: an access token inside its lifetime, else the
  `cv_refresh` cookie), whose `peek_access_token` and `peek_refresh` read no user status, and
  never calls `require_active`; or it authenticates with `allow_locked=True` other than through
  `require_active`. `test_only_these_routes_skip_the_backstop` scans the code for both:
  `POST /auth/logout` skips it the first way (#2300), `DELETE /me/sessions/{sessionId}` the second.
  Two middleware read a session the second way only to classify it, `enrolment_only_guard`
  (#2295) and `view_as_guard` (#3085): a request either reaches its route, which meets the
  backstop, or is refused before any route runs (`403 mfa_enrollment_required`, or
  `view_as_read_only` and `view_as_expired`), so neither admits a disabled user's session to
  anything, and its next route revokes it.
  As deployed, `IdleLockMiddleware` (#2300) first authenticates the bearer of every route but the
  operations allowed while idle-locked with `authenticate_access_token`, which ends in
  `require_active`, so `DELETE /me/sessions/{sessionId}` meets the backstop there before its own
  code runs, and only `POST /auth/logout` skips it. A `RuntimeError` from the session store under
  that call is answered `503 store_unavailable`; any other store error (the deployed SQLAlchemy
  repository raises `DBAPIError`, `OSError` or `TimeoutError` on a Postgres outage) reaches the
  boundary handler as `500 internal_error`. Either way no route runs (fail closed).
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
  audit lane's façade, the writer as its fallback (#4021; the writer alone before it, #3120). The
  record comes last, after the revocation: an audit sink that is down never
  undoes the revocation, and never holds the `401` for more than 2 seconds. Any increase means a
  session outlived a disable (SR-029): escalate with the log line and the record.
- A cancelled request loses none of it (#3332). The revoking `UPDATE`, the count, the `WARNING`,
  the publish and the record run as one unit the service owns, under `asyncio.shield`: a request
  cancelled anywhere in it (a client that disconnects, a route timeout) still leaves the row
  revoked, counted, logged, published and recorded once. The cancelled request waits for the
  unit up to the same 2 seconds, then ends; a unit that runs on finishes by itself, and auth's
  shutdown waits for it, up to half of auth's stop bound, before audit and storage stop (a
  `WARNING` `auth.backstop_units_in_flight_at_shutdown` gives the count of any still running).
  A failed unit logs `auth.disabled_user_session_revoke_failed` (ERROR, with `session_id`,
  `user_id` and `error`, the failure's class) whether or not its request still waits; a request
  that still waits also gets the error and is refused `503` or `500`, as before. Once the request
  has left, that line is the failure's only trace. What remains is the process dying
  after the `UPDATE` committed: the row is revoked as `user_disabled` with no count, no `WARNING`,
  no publish (its sockets end at their token deadline instead of at once) and no record, and the
  retry finds the row revoked and adds nothing. The `sessions` row with
  `revoked_reason = 'user_disabled'` is then the only trace, so compare those rows in a window
  with the counter's increase over it (a disable's own transaction and sweep add rows of their
  own).
- When the lane and the audit sink both refuse the record it is dropped, not queued again (C-2.18:
  the lane is its durable retry, `04-security-program.md` section 8.3), and the log says so:
  `auth.disabled_user_session_audit_failed` (ERROR, with `session_id`, `user_id` and `error`, the
  failure's class: `BackstopAuditSaturated` at the in-flight cap, `BackstopAuditNotAttached` for a
  wiring fault). A write still running after the 2 seconds logs
  `auth.disabled_user_session_audit_slow` (with the ids; the record may still land), and if it
  then fails, `auth.disabled_user_session_audit_failed_late` follows with `error` only and no
  session, so count those lines. Each record the port loses (the lane and the writer both refused
  it, the cap dropped it, or its write failed after the request stopped waiting or was still
  running when the shutdown drain gave up) also adds one to
  `auth_audit_outcome_lost_total{action="auth.disabled_user_session_revoked"}`, once however many
  of those it meets, and `AuthAuditOutcomeLost` alerts on it (section 10);
  `BackstopAuditNotAttached` never reaches the port and is not counted. Three losses leave no log
  line that names the session and says
  its record is missing (the `WARNING`, logged as soon as `revoke` returns, names it in the last
  two, and in the first when the process dies after it, but cannot say the record failed): the
  process dies between the revoke and the write (the bullet above); it shuts down while a unit or
  its write is still running (each drain waits, then logs only a count); or the write outlives the
  2-second bound and then fails (its `_audit_slow` line names the session but says the record may
  still land, and the `_audit_failed_late` line that follows names none). A cancelled request is
  no longer one of them (#3332). Only the reconcile step finds all three, and what each
  `_audit_failed_late` line lost. To reconcile, after an outage or any restart, list the sessions
  revoked as `user_disabled` in that window (UTC; `psql` runs inside the `postgres` container, as the user
  and database it was started with, in a read-only session):

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

  As an Owner, look each id up in the two revocation records that can name it as their subject:
  `GET $API/admin/audit?action=auth.session_revoked&action=auth.disabled_user_session_revoked&subject_type=session&subject_id=<id>`.
  `auth.session_revoked` with reason `user_disabled` is the disable's own record of that session
  (B16 writes one for each session a disable revoked, the session its subject since #3402), and
  `auth.disabled_user_session_revoked` is the backstop's. A session with neither is unaudited,
  even when a `users.disable` record names its user: that record names the user and counts the
  sessions (`detail.after.sessions_revoked`) without naming them, so a session that escaped the
  disable and lost its backstop record has that record only. A disable leaves a session it
  revoked with neither record when its B16 step failed (the ERROR line `users.disable.step` with
  `step` `b16_revoke`); when its sweep was cut off after its `UPDATE` committed, so that B16 never
  got the sessions it revoked (the same line, `step` `session_sweep`); when its commit's outcome
  is unknown (a second `users.disable`, `failure`, reason `outcome_unknown`); or when the process
  ended after the commit and before B16 recorded the session, in a crash, a kill or a power loss,
  which leaves no line, because only a live process writes `users.disable.step`. The
  `users.disable` records and the line, if there is one, name the user and no session: attach them
  when you escalate.

  In a window that starts before the release that carries #3402, a session this lookup does not
  find may still have the disable's record, because an `auth.session_revoked` written before that
  release names no subject. Look the session up by its user and the time instead:
  `GET $API/admin/audit?action=auth.session_revoked&actor_user_id=<user_id>&from=<start>&to=<end>`,
  with the session's `user_id` from the SQL above and the window's bounds in UTC (RFC 3339, such
  as `2026-10-17T06:00:00Z`; `to` is exclusive, and B16 writes its record just after the
  revocation, so end the window a little past the last `revoked_at`). Each record gives its
  `session_id` and `reason`, and its actor is the session's user: a session whose id is the
  `session_id` of a record with reason `user_disabled` is covered by the disable's own record. A
  session in neither lookup is unaudited.

- A client that only holds a socket meets the backstop when a REST call or a socket `auth`
  presents a token that is still valid, when it calls `GET /auth/session`, which finds the session
  by its `cv_refresh` cookie once the token has ended and still checks the user's status (#3214:
  `require_active` with `allow_locked=True`), or when it refreshes. The protocol's client flow
  refreshes over REST at `expires_at` − 60 s (`docs/plan/23-ws-protocol.md` §4.1, §4.3), and the
  refused refresh revokes the session, counts it, logs the `WARNING`, publishes it and records it
  as above (#3331): its sockets end then with `bye` `user_disabled` and `4403`, and the
  `AuthDisabledUserSessionRevoked` ticket fires. Only the streaming window remains: until that
  refresh, or the token's deadline at the latest (12 minutes), the socket keeps receiving what it
  could already read. It is an accepted risk, dated 2026-10-17
  (`docs/security/threat-models/e09-auth-rbac.md`, U45; it is UL1-E2's in `e42-user-lifecycle.md`):
  a socket has no write path, since orders are REST only, and #965's disable cascade, now that it
  is routed, closes sockets within 5 s. A client that never refreshes or calls REST again leaves
  its row live until its absolute expiry, 12 hours after the login that started the session chain,
  but unused: its old token is refused as expired before `require_active` runs, and any later use
  of the row revokes it.

**The bootstrap Owner (O5, #3246).** The permission readers and the owner floor count only `active`
users. The first Owner that `0002_rbac_seed` creates (`docs/plan/21-database-schema.md` §10.2) is
seeded `invited`, so it holds no permission and is no Owner for the floor until it is `active`, and
nothing in the app makes it `active`: only redeeming an invite does, and the seed creates none (nor
does any password match its seeded placeholder hash). **BLOCKED — not implemented**: there is no
supported way to activate it (#2710). Do not edit `users` by hand: escalate to the repository owner,
as §3 says, and record it. On testnet, `services/api/scripts/seed_fixture_user.py` seeds an `active`
Owner and audits it.

**A commit lost on the wire (#2710, #3445).** When the commit of a disable fails on the wire, the
`users.disable` record is followed by a `failure` record with reason `outcome_unknown`, and the
call reads the user back once, in a new transaction, within the store's 2-second bound. If the
commit landed (the user reads `disabled`, with the sessions it revoked at its instant), the call
goes on as after any disable and answers `204`: a `users.disable` `success` record with reason
`recovered_after_commit_error`, then the steps, one `auth.session_revoked` per session included.
There is nothing to do unless a step failed (§11). A user with no session leaves no ids to compare,
so a concurrent disable of that user that committed can pass for this one; the user is disabled
either way. The steps run even if the recovered record is refused or not confirmed in time (the
error line `users.disable.read_back` with `outcome` `record_failed`): that record is then missing
or lands late. The trail alone does not show that every step ran: the socket close, the sweep and
the scope refresh write no record, and a refusing audit writer, the likeliest cause, refuses those
of B16 and the disarm too. Read the error lines `users.disable.step` with `outcome=failed`, and
repeat the DELETE if there is one. Nor does the recovery wait on the `outcome_unknown` record: if
it was refused, it is missing between the two `success` records. Each missing record shows as the
error line `users.disable.step` with `step=closing_record` and `outcome=failed`. Otherwise the call
answers `503 store_unavailable` and no step after the commit has run; the error line
`users.disable.read_back` gives the `outcome` (`failed`, `not_disabled` or `other_sessions`). A
request cancelled before the read-back found the change (during the commit, its closing record or
the read-back: the client gone, or a shutdown) runs no step either, and counts no `error`, so
`UserDisableFailed` stays silent; once it has found it, the record and the steps finish in their
own task. Repeat the DELETE, which is safe either way: a repeat of a committed disable answers
`204`, writes no record, ends every socket of the user and re-runs the sweep, the scope refresh
and the disarm, but B16 records none of the sessions that commit revoked. That residual awaits the
Owner's sign-off in `docs/security/threat-models/e42-user-lifecycle.md` §6.

Proven end to end in process on the deployed app
(`services/api/tests/security/auth/test_disable_user_e2e.py`, and
`test_disable_commit_readback.py` for a lost commit) and on Postgres
(`services/api/tests/integration/admin/test_user_disable_route_pg.py`), sockets on `rotated`
sessions included. `services/api/tests/security/auth/test_disable_user_drill.py` drives the same
route from the manager's side: a private subscription's `bye` and close, and the measured time from
the `DELETE` to the `bye`. The dev-stack drill (E09-X04, #2494) is recorded in
`docs/security/reviews/e09-auth-review.md` section 4.

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
Since `0045_audit_chain_hardening` (#889) each insert consumes two ids, so gaps in the ids are
expected and are not a break, and a range of N ids drawn since then holds about N/2 entries: a
call capped at `audit_verify_max_span` (1,000,000 ids by default) checks about 500,000 of them.

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
   - `enforce` routes (`users:write`, `keys:manage`, `keys:read`) and the key store's owner gate (`keys:read`, reason `not_owner:keys:read:granted_accounts`): action `rbac.denied`,
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
permission denial decided by one of three deciders. It moves before the audit row is written, so an
audit failure never hides a denial. `permission` is the permission code from a closed set (the
generated vocabulary plus `other`).

- `auth/scopes.py::enforce` (audit row `rbac.denied`). Only routes that call `enforce` count this
  way, among them the `users:write` routes: `PUT /users/{userId}/roles`, `DELETE /users/{userId}`, the invite routes
  (`POST /users`, `GET /users/invites`, `POST` and `DELETE /users/{userId}/invite`) and the TOTP
  reset routes, and the key routes `createApiKey` (`keys:manage`) and `testApiKey` (`keys:read`).
- The admin-area guard, `admin/http.py` (audit row `admin.area_entered` with outcome `denied`, not
  `rbac.denied`). Every route on an `admin_router` counts, under the router's permission:
  `admin:read` for `GET /admin/overview` and `GET /admin/capacity` today, and a later router on the
  guard counts under its own `admin:*` code. Only a decided denial counts: not a `401`, a `501` or a
  `503` for a missing audit writer, and not an allowed caller whose audit write fails (a `503`).
- The key store's owner gate, for `testApiKey` (`api/exchange_keys.py`, audit row `rbac.denied` with
  reason `not_owner:keys:read:granted_accounts`): a caller `enforce` let through whom the store then
  refuses (SR-051) counts under `keys:read`, even when its audit row cannot be written; then only the warning log `key_test_denial_unaudited` (actor and account ids) names the caller.

Not counted:

- permission checks written inline in other route modules (market data, instruments, and so on),
  which write no `rbac.denied` row either: their only trace is the `403` response itself;
- WS subscribe denials: see `cv_ws_subscribe_total{result="forbidden"}` and the audit action
  `ws.subscribe.denied` (at the 200-subscription cap a refusal is counted as `subscription_limit`, whatever the
  topic would have got; a private family's row records that reason; accepted residual: classification only, #415);
- the owner-floor `409` (audited as `rbac.denied`, see the note below, but a business refusal rather
  than a permission check) and `step_up_required` (§2).

Read it on the metrics listener, for example
`curl -s http://127.0.0.1:9108/metrics | grep '^authz_denied_total'` (every permission is listed at 0
from process start). The `AuthzDeniedSpike` rule fires above 20 denials in 10 minutes
(`sum by (permission) (increase(authz_denied_total[10m]))` shows which permission). Today a spike on
`admin:read` comes from the admin-area guard, one on `users:write` or `keys:manage` from `enforce`, and one on `keys:read` from `enforce` or the key store's owner gate; use the
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
| `auth_refresh_reuse_total`               | a rotated-out refresh token was presented again; the whole session family is revoked                                                                                                        | `auth.refresh_reuse_detected` (critical); a replay of a contained family: `auth.refresh_reuse_replayed` (warning)                                                                        |
| `auth_session_revocations_total{reason}` | sessions revoked; `reason` is from a closed set (logout, logout_all, rotated, rotation_reuse, expired, idle, admin, user_revoked, locked, timeout, unlock_attempts_exceeded) plus `other`   | `auth.session_revoked` for the logout and revoke routes                                                                                                                                  |
| `auth_session_revoke_denied_total`       | `DELETE /me/sessions/{id}` named an id that is not one of the caller's live sessions: a foreign or unknown id (the probe) or the caller's own ended session; the answer is the same 404     | `auth.session_revoke_denied` (denied, warning, reason `not_live_own_session`; object: the id named). Rows are budgeted at 10 a minute per user and 30 overall; every probe is counted.   |
| `users_invites_rejected_total{reason}`   | invite requests refused: unknown, expired, redeemed, revoked, enrollment_invalid, role_tamper (a `role` or `roles` claim) or identity_tamper (`username`, `user_id` or `email` in the body) | `users.invite_rejected` (warning for redeemed, role_tamper and identity_tamper). Tamper requests count against the per-address invite budget: the 11th in a minute gets `429` and no row |

A lone `auth_refresh_reuse_total` hit seconds after a rotation, from the address of the rotation it
follows (compare its `auth.refresh_reuse_detected` row with that rotation's
`auth.session_refreshed` row), is most likely a refresh response the user's own client lost: the
client presented the old token again, the family was revoked, and the user signs in again. That is
by design. Any re-presentation revokes the family, and there is no server grace window
(ADR-0020 decision 5, contract `authRefresh`). The SPA's token client (`apps/web/src/lib/auth`,
#2712) coalesces its refreshes, one at a time across its tabs, so that one client does not present a
token twice. Treat a hit from another address, or more than one, as a stolen token.

An `auth.refresh_reuse_detected` row at `warning`, with `after_state.family_revoked` `false`, is a
different event, and `auth_refresh_reuse_total` does not count it: a rotated-out `cv_refresh` cookie
was presented outside `/auth/refresh`, for example to `GET /auth/session`. Nothing is revoked, the
answer is the uniform `401`, and `auth_session_fixation_attempts_total{reason="rotated"}` counts it.
Rows are written within a per-address and a global budget and the refusal-audit tracker's in-flight
cap, and
`reason="audit_throttled"` counts the attempts past them. The SPA's token client (#2712) writes such
rows on purpose: after a refresh whose answer it lost, it asks `GET /auth/session` before it
presents the possibly spent cookie, and it asks again on each page load until the user signs in
again. A few of these rows from the user's
own address, after that user's last `auth.session_refreshed` row, are expected. Rows from another
address, or across many users' sessions, mean someone holds rotated-out cookies: treat them as
stolen.

A burst on `auth_refresh_reuse_total` may be a replay flood: see section 10 for its rows and bounds.

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

**Enrolment-only refusals (#2295).** `auth_enrolment_refused_total{transport,reason}` (`transport`
is `http` or `ws`, the `channel` of the log lines and audit rows) counts each refusal of an
enrolment-only session; no alert rule reads it yet (#2746). By `reason`:

- `enrolment_only`: an operation outside the five enrolment operations was answered
  `403 mfa_enrollment_required`, or the WebSocket `auth` got `bye mfa_enrollment_required`
  (4403). The audit row is `auth.mfa_enrollment_required` (denied, warning; `after_state` names
  the channel, method and route template, and the row has the source address), at most 20 a
  minute per user. The log line is `auth.enrolment_only.refused`, with `session_id` and `user_id`.
- `expired`: the session was not minted enrolment-only (its expiry lies more than 15 minutes
  ahead, or it proved a second factor its user no longer has): 401, or a failed WS `auth`, and no
  audit row (log `auth.enrolment_only.expired`). A session past its expiry is refused before it is
  classified (401, revoked as `expired`) and is not counted here, except by a `POST /auth/refresh`
  that is the first request to present it after its expiry.
- `unclassified`: the session or its user could not be read, or a session store is wired without
  the user store: `503 store_unavailable`, or a failed WS `auth`. The error line
  `auth.enrolment_only.unclassified` names the exception type, and the `session_id` and `user_id`
  when the session was read but its user's state was not; check the auth database first.
- `audit_throttled`, `audit_slow`, `audit_unavailable`: an `enrolment_only` refusal whose row was
  skipped on purpose (the per-user budget or the in-flight cap; log
  `auth.enrolment_only.refused_unaudited`), was still running after the 2-second wait (it may
  still land; `auth.enrolment_only.audit_slow`), or failed
  (`auth.enrolment_only.audit_unavailable`, or `auth.enrolment_only.audit_failed_late` once
  nobody waits for it). A WebSocket refusal's slow or lost row (not one skipped on purpose) also
  counts once in `cv_ws_audit_failures_total`, so `WsAuditWriteFailed` raises a ticket (SR-186).

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
  above and works unchanged. Without it, the shell serves the UI from `app://candleviewer` (#3410),
  not `file://`, whose requests would carry `Origin: null` (refused by design; never allow-list
  `null`). Desktop writes still need wiring that is not built yet: the backend's address in the
  desktop build, `app://candleviewer` in this list, and a CSRF token path for an `app://` page,
  which cannot read the backend's `__Host-cv_csrf` cookie (see `apps/desktop/README.md`).
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
after it refuses a disabled user's refresh; the answer stays the uniform `401`. A rotated token
presented again is not among them: its row is written ahead, `auth.refresh_reuse_detected`
(`critical`) when this process first contains its family and `auth.refresh_reuse_replayed`
(`denied`, `warning`; ADR-0037 decision 13) for each later presentation of a member of that family.
Each replay the session service refuses (the `401`) is counted on `auth_refresh_reuse_total`. A
replay the refresh throttles refuse (`429`), or that gets a `503` because the lane and the sink both
refused, never reaches the service: the `503` shows on `cv_audit_lane_refused_total{class="shared"}`
and `cv_audit_writer_refused_total{domain="auth"}` and logs `auth.session_audit.writer_refused` with
the action; the `429` shows on neither. One `auth.refresh_reuse.replay_refused` warning
(`session_id` only) per family per 60 s shows a flood. The families are held in a bounded memory
only: at most 4096 session ids (the oldest forgotten first), each for 3600 s since its family's last
containment (a replay the service refuses renews it). After a restart, an eviction or that hour, the
next replay of a family writes one `critical` row again.

The login routes (`api/auth.py`, #2914) write their outcome and refusal rows after the decision too,
and through the lane (ADR-0037 Amendment 2): `auth.login_failed` for a refused sign-in (`401`,
`403`) or a disabled user's refused mint (reason `user_disabled`), `auth.account_locked` (`423`),
`auth.login` for a password step that passed (`200`; no session exists yet), `auth.mfa_failed`
for a refused second factor, recovery or confirm (`401`, `422`) or for a second factor whose mint
then failed in the store (`500`, reason `unminted`: it voids the `auth.session_created` written
ahead, and the error log `auth.mfa_verify.unminted` names the `user_id` and the `new_session_id`),
`auth.recovery_codes_exhausted`, and a recovery's `unplanned` `auth.session_revoked`. Each lost one
is counted under its action and logs one error, `auth.login_audit.outcome_lost`, with `action` and
`error` only (no identifier, address or session id, C-12.6); the answer stands, and the counter the
route moves before the row (`auth_login_failures_total`, `auth_enrolments_total`), where there is
one, still shows the attempt. A mint's write-ahead records are not among them: they stay on the
writer (U42).

Each lost row adds one to `auth_audit_outcome_lost_total{action}` and logs one error,
`auth.session_audit.outcome_lost`, with `action`, `session_id` and `error` (the writer's refusal
class, `inactive`, `cancelled` for a request cancelled part-way, `timeout` for a write that did not
return within the audit timeout, 2 s, or the class name of any other error the writer raised, a
defect that also answers the request `500`: the row in flight may have landed, so check the trail,
and the rows after it were not tried; a sign-out cancelled while it revoked has a `cancelled` line
for each session it targeted and no row for any, so read each `sessions` row (`revoked_at`) to see
which it ended; a refresh of a live token cancelled while the service ran has one `cancelled`
line for `auth.refresh_reuse_detected` whether or not the service found a reuse, so read the
family's `sessions` rows (`revoked_reason` `rotation_reuse`, or `user_disabled` for a disabled
user's refused refresh) before treating it as one); it
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
the missing rows by hand: only the audit writer writes the table. The journal-first lane is rule 2's
durable retry (`04-security-program.md` section 8.3): a row the lane and the writer both refused, or
whose write timed out or was cancelled, is lost, counted and alerted.

The backstop's record, `auth.disabled_user_session_revoked` (section 4), counts on the same series.
`auth` writes it through the lane's façade (the lane first, the writer its fallback), so it counts
only when it is lost: the lane and the writer both refused it, the in-flight cap dropped it, or its
write failed after the revoking request stopped waiting (the 2 second bound, or a cancel) or was
still running when the shutdown drain gave up. A counted record may still have landed (a cancelled
lane append or a durable WAL append can complete late), so check the trail. One count per record,
whichever of these it meets. It logs `auth.disabled_user_session_audit_failed` (or its
`_slow` and `_failed_late` forms), not `outcome_lost`: reconcile it as section 4 says.

While the sink refuses records, refresh, extend and unlock answer `503` and change nothing
(C-2.9), except unlock while the sink is up but its writer refuses (a full or unwritable WAL) for a
lock B16's chart already holds: a wrong password still counts toward the five failed unlocks that
revoke the session and toward the SR-016 lockout, which it can apply with no `auth.unlock_failed` or
`auth.account_locked` row (only `auth_lockouts_total` moves), so ask users not to retry an unlock
meanwhile. A lock the chart must still record (first seen meanwhile, or again after a restart) gets
`503` at its `auth.idle_locked` record, before the password check, and counts nothing. A sign-in
fails closed (nothing is minted), since the write-ahead records of a mint never go to the lane: an
access token lapses within 12 minutes and a longer refusal ends every session and sign-in. The
password step of `POST /auth/login` still answers (its row is an outcome row), and
`POST /auth/mfa/verify` then fails closed with its `401` (`audit sink not active`) at its first
write-ahead record, `auth.mfa_verified`, as at the carried-session record and at the
`auth.session_created` it writes ahead of the mint: the TOTP step is spent, so the user signs in
again from the password step once the sink is back. During an outage that is the sink, not a
defect: `cv_audit_writer_refused_total{domain="auth"}` counts each one. An enrolment-only sign-in
and the enrolment steps answer `503`, and `POST /auth/mfa/recovery` its uniform `401`.
Sign-out, revoke-my-session and reuse containment go to the lane first and answer `503` only while
it refuses too, as a full or read-only audit volume makes it do (accepted residual risk RR-16,
`04-security-program.md` section 16.1). The Owner's revocation of another user's session
(`users.session_revoked`, `api/users.py`) and a user's disablement (`users.disable`) stay on the
writer and fail closed while the sink refuses (ADR-0037 Q1). A
refresh of an idle-locked session is answered `401 session_idle_locked` before its record, whether or not the
sink accepts it, and changes nothing either (#3331). A lock that engages between the route's check
and the service's own leaves the attempt's intent record with no outcome record and no
`outcome_lost` line, and nothing is
rotated. The unlock that follows writes its own record first, so it answers `503` until the sink
recovers. The break-glass
reset (section 3, E09-S11 #2119) is the Owner's emergency path: it runs only with cv-api stopped
and journals to its own host file, never the sink. `AuthAuditOutcomeLost` is a
`ticket`, muted 22:00-07:00 UTC by default (`CV_ALERT_QUIET_HOURS`) and active 15 minutes after the
last loss, so a lone loss at night is not delivered and the page (more than 5 in 15 minutes) does
not cover it (#2621, section 1): in the morning, read the counter and `outcome_lost` log lines.

No page does not mean the sink is healthy: the page reads only outcome rows lost after an action,
while the lane takes the rows of a sign-out, a revoke-my-session, reuse containment and the login
routes' outcomes, and a
refusing sink makes every refresh, extend and unlock fail closed at its write-ahead record with a
`503`, and every sign-in fail closed (nothing is minted). Those refusals
show as `auth.session_audit.writer_refused` log lines (the alert
runbook's third command greps them) and in `cv_audit_writer_refused_total{domain}`, which the
AuditSinkRefusing ticket reads (§13). A page that has cleared is no
better evidence: it sends no `[RESOLVED]` message and clears with its 15-minute window, so the test
refresh in the alert runbook entry (row 7) is the check. A test sign-out is not: it answers `204`
while the lane takes its rows, whether or not the sink takes records.

## 11. A disable or a grant change left a step undone (`UserLifecycleStepFailed`, `UserGrantsPushFailed`, `UserDisableFailed`)

Written 2026-10-18 against `main` at `bb9b2be89` for #965 and #2648 (R7 of each: a step after the
commit is counted and alerted, never rolled back). The alert runbooks are the anchors
`alert-userlifecyclestepfailed`, `alert-usergrantspushfailed` and `alert-userdisablefailed` of
`docs/plan/07-release-and-prr.md`; this section says where their signals come from.

- **Disable steps.** After the transaction of `DELETE /users/{userId}` commits (§4), each step adds
  one to `cv_user_lifecycle_steps_total{step,outcome}` per call, `ok` or `failed` (`skipped` only
  for `b16_revoke` with no session and `invite_revoke` with no invite), and logs one
  `users.disable.step` line with `step`, `outcome`, `attempted`, the `error` class,
  `target_user_id` and `request_id`, at error when it failed. A disable that did not commit counts
  and logs its closing record as the step `closing_record`, written in one attempt: `ok` or
  `failed`. Any `failed` raises the `UserLifecycleStepFailed` ticket. The remedy is a repeat of the
  DELETE, which re-runs the steps that §4 lists; it re-runs neither B16 for the sessions the first
  call revoked nor the invite revoke.
  A lost commit that a read-back found landed (§4) counts its recovered `success` record as
  `closing_record` too, so one call can count two.
- **Disable calls.** `cv_user_lifecycle_total{action,result}` counts each call. An `error` is no
  refusal but a store failure (`user disable store unavailable`, a `503`): no step ran, though its
  commit may have landed, so it raises the `UserDisableFailed` ticket. Read the user's status and
  disable them again if that is still wanted. No refusal alerts: `forbidden` and `self_target` are
  audited (`rbac.denied`); `last_owner` (UL1-D1), `not_found` and `positions_unknown` are not.
  A lost commit that a read-back found landed (§4) counts as `disabled` and answers `204`.
- **Grants push.** A grant change through `PUT /users/{userId}/account-access` (E42-T08) pushes
  `grants_changed` to the user's live sockets once it commits, and counts the push as the step
  `grants_push`: `pushed`, `timeout` (the request stopped waiting after 2 s; the push goes on and
  is counted again when it ends) or `failed`, with one `account access push` line (`outcome`,
  `error`, `target_user_id`). A `timeout` or a `failed` raises the `UserGrantsPushFailed` ticket.
  A failed push is not retried: each socket reads the current grants at its next `auth`. The `PUT`
  has been served since #3267 (#2648, S9c), so its pushes are counted and this ticket can fire.
- Both series are served with `env` on the metrics listener (`127.0.0.1:9108`, §6), every label
  value at 0 from process start, so the first failure after a restart is an increase the tickets
  see. `ExpectedMetricMissingCvUserLifecycleStepsTotal` fires if they are not scraped (one export).

## 12. Release a held audit lane (`audit lane held at boot`; ADR-0037, #3009)

**Partly blocked.** cv-api runs the journal-first audit lane (since #3009's S2b-2a) only with a real
audit backend and a lane key file; compose provisions the key (S2b-2b2, #3737) but runs the fake
backend, which has no lane, and `AuditLaneDrainHeld` is a ticket until the Owner grants its page
(#2701, §13).

**When.** cv-api logs `audit lane held at boot` (critical) with `hold` as `[segment, offset]`: the
lane met a frame under a key id or format version that no configured key knows (§15.6 Hold of
`docs/plan/24-internal-schemas.md`). Every append is then refused (`held`) and each record falls
back to the audit sink, so a sink outage fails closed again. A hold at the end of the data after a
newest segment that no name follows (`seg-` and 20 nines) holds no frame: the command answers 6,
and the remedy is to remove that segment with the Security engineer (§15.6 Hold, rows 13 and 16).
If the marker already sits in that segment, the next boot reads it as ahead (§15.6 row 2) and
writes a critical `marker_lost` row.

1. **Prefer the key.** If the hold followed a key rotation, set `CV_AUDIT_LANE_PREVIOUS_KEY_FILE`
   to the old key and restart: the frames drain and nothing is lost. Release only frames no key
   you hold verifies (a planted or foreign frame, a lost key), with the Security engineer's
   agreement: they never reach `audit_log`; their bytes are kept in `lane/quarantine/`. A hold
   logged as `hold=None` (the marker) is not released: §15.6 Hold names its remedies.
2. **Stop cv-api** until step 4; the command takes `lane.lock` exclusively and refuses (exit 5)
   while cv-api holds it: `docker compose -f infra/compose/docker-compose.yml --profile core stop api`.
3. **Run the command** as a one-off container of the `api` service, as for break-glass (§3: the
   service's volume, key file, `CV_AUDIT_WAL_PATH` and user; no `-v`, no `--user`), with the
   logged hold and your own words. It reads the key only from `CV_AUDIT_LANE_KEY_FILE`:

   ```bash
   docker compose -f infra/compose/docker-compose.yml --profile core run --rm --no-deps --entrypoint python api -m candleviewer.admin.lane_release --hold <segment>:<offset> --operator <you> --ticket <incident> --operator-reason "<why>"
   ```

   The words must be printable and within §15.6 Release's caps. They are stored verbatim in the
   `released` row, shown to every Owner who reads the audit log, and sit on the command line:
   never put a key, token, password or code in them (the break-glass label rule). Keep the output
   with the ticket; the log line goes with the `--rm` container. Exit 0: the held bytes (from the
   hold to the next frame the key verifies, or to the end) are in
   `lane/quarantine/seg-<segment, 20 digits>.lane.<offset>` and the MAC'd note `lane/released`
   is written. Else 2 (an argument refused), 4 (no lane: no real backend, a key file refused, an
   unanchored or unusable lane; after a failed write a note may exist, so run again once the
   volume is sound), 5 (cv-api runs), 6 (no hold at a frame) or 7 (it holds elsewhere, at the
   position the line names; see step 5).

4. **Start cv-api** (`... --profile core start api`). Its boot applies the note.
5. **Read the `released` row** with an Owner token:
   `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=audit.lane_anomaly"`: one
   entry with `reason` `released` (critical), `detail.after` holding your `operator`, `ticket`
   and `operator_reason`, `bytes`, `digest` (the SHA-256 of the quarantined copy) and
   `quarantined`; a `seq_gap` entry follows for the held `seq` values when authentic frames, or
   the boot's own frame (a whole held segment at the end), came after them. `lane/released` goes
   once the drain has passed it: wait for that before stopping cv-api for a second hold, since
   until then the command finds the first (exit 7). If the boot logs `audit lane held at boot`
   again with `note_ignored=True`, the note did not apply there (another key, the lane changed, a
   note an earlier release left), or it applied and a second hold follows: repeat from step 2 with
   the logged position; the new note replaces the old. The `released` row is the release's record.

A second release of the same hold, under the same lane key, makes a `released` row with the first one's keyed
`record_id`: the chain keeps only the first, so the second one's words never reach `audit_log`; keep that
command's output with its ticket (SEC-REM-02).

## 13. The journal-first audit lane: its alerts, key rotation and previous-key retirement (ADR-0037, #3009)

Written 2026-10-19 for #3009 S4a. The alert runbooks are the anchors `alert-auditsinkrefusing`,
`alert-auditlanebacklogaged`, `alert-auditlanerefusing`, `alert-auditlaneanomaly` and
`alert-auditlaneseqregressed` of `docs/plan/07-release-and-prr.md`; this section says where their
signals come from and how the lane key is rotated.

**Partly blocked.** The signals and the retirement rule hold wherever cv-api runs the lane, but
compose runs the fake backend (no lane, §12) and gives the `api` service one lane key secret
(S2b-2b2, #3737) and no `CV_AUDIT_LANE_PREVIOUS_KEY_FILE`: rotating the key under compose is
**BLOCKED — not implemented** until a second file secret and that variable are provisioned (#3009).

- **Signals.** cv-api serves the lane's series (`cv_audit_lane_*`) and the writer's refusals
  (`cv_audit_writer_refused_total{domain}`) on the metrics listener (`127.0.0.1:9108`, §6), read at
  the scrape from memory: per-process counters at 0 from start, and the lane's gauges (depth,
  bytes, the oldest unit's age, the head `seq`, the state, `quarantine/`'s size) only while a lane
  runs. The writer's count is of refusals, not slowness: a hung WAL shows as deadline misses until
  its failure latch refuses.
  A count a boot sets before the first scrape (an anomaly row of its scan, frame 1 of a new lane)
  is read while the process is under 15 minutes old, so a long stop hides none of them.
- **Severity.** Every lane alert is a `ticket` for now. ADR-0037 makes seven of them pages, never
  muted by quiet hours, but a new page needs the Owner (#2701): until it is granted, quiet hours
  (22:00-07:00 UTC) mute them, and the event alerts hold 9 h 30 m so that one firing at night is
  still sent in the morning. "Never muted" applies once they are promoted. A promotion needs more than the
  grant: `absent()` guards on `cv_audit_lane_state`, `cv_audit_lane_anomalies_total` and
  `process_start_time_seconds` (SEC-REM-01). A lane read that fails at a scrape drops every lane family (the
  exporter logs `metrics.scrape_read_failed` and serves the rest), and without the start time the rules that
  read a boot's counts cannot fire, so today neither case alerts.
- **Expected once.** AuditLaneCreated fires at the first boot that creates the lane; acknowledge it.
  At any later boot it means the lane was lost or wiped (AuditLaneSeqRegressed fires with it when
  the old lane had grown).

**Rotate the lane key.** The key is a 32-byte file secret (§3's volume never holds it; ADR-0037
decision 6). `kid`s are logged at boot (`audit.lane.key_loaded`, `kid` and `previous_kid`), never
the key.

1. Provision the new key as a new compose secret file (64 hex digits, mode `0400`, uid 10001), off
   the audit volume. Keep the current one.
2. Point `CV_AUDIT_LANE_PREVIOUS_KEY_FILE` at the current key's file and `CV_AUDIT_LANE_KEY_FILE` at
   the new one, then restart cv-api. New frames, the marker and any release note are made under the
   new key; the old one only verifies the frames that wait. Anomaly ids are keyed under the current
   key, so a run met again after the rotation gets a new `record_id` (a second row for it).
3. A boot that logs `audit lane held at boot` after a rotation means a frame or marker under a key
   it no longer knows: restore the old key as the previous key and restart (AuditLaneDrainHeld).

**Retire the previous key** only when no frame or marker under its `kid` remains: the lane is
empty (`cv_audit_lane_depth` 0 and the drain confirmed since the restart, which rewrites the marker
under the new key), and no backup of the audit volume inside your restore window holds frames under
it: a restored lane whose frames no configured key verifies holds, and only the release (§12)
clears it, never draining those frames. Otherwise keep the old key offline (escrow) for as long as
such a backup may be restored. Then unset `CV_AUDIT_LANE_PREVIOUS_KEY_FILE`, restart, check the
boot's `previous_kid` is gone, and destroy the old secret file.

## Known gaps referenced above

| Gap                                                                       | Reference      |
| ------------------------------------------------------------------------- | -------------- |
| Break-glass drill on staging (SR-023)                                     | #2494, #300    |
| Owner route to resolve a break-glass event (section 3, step 7)            | E09-S12, #2710 |
| `PUT /auth/password` not implemented (no revoke-other-sessions on change) | #2110          |
| Scheduled audit-chain verifier                                            | #2111          |
| Disable-user drill on staging (SR-029)                                    | #2494, #300    |
| Activating the seeded `invited` bootstrap Owner (O5)                      | #2710          |
| No B16 record of a lost disable commit's sessions if not read back        | #2710, #3445   |
| Session rotation on role change and step-up                               | #2101          |
| Lock alerts lost inside quiet hours                                       | #2621          |
| No alert rule reads the session, invite, probe or step-up failure series  | #2746          |
| No alert rule reads the enrolment-only refusal series (section 7)         | #2746          |
| `cv_ws_errors_total{code}` not served (label `code` is not allow-listed)  | #2747          |
| An outcome record the lane and the sink both refuse is lost (counted)     | RR-16          |
| Compose runs the fake backend (no lane); the lane's alerts are tickets    | #3009, #2701   |

## Execution record

§3 was run cold by a non-author on 2026-10-23, on a dev compose stack on the real backend (#2494),
and is recorded in `docs/security/reviews/e09-auth-review.md` section 3. Not executed on staging:
no staging host exists (#1778 item A); the staging run is tracked in #2298. Security review of
§3/§5 exists as an agent review on #2115; Ops review is recorded on #2343.

The audit lane's drill (§12, §13; ADR-0037 S4b-2a, #3009) is an in-process test, not a non-author's walk of those
sections on a staging host: `services/api/tests/unit/audit/test_lane_drill.py` runs the real `AuditService` over an
in-memory chain on a virtual clock. Its Postgres halves run in CI; the lane's rows in
`qa/plans/e04-alert-drill-matrix.md` stay pending.
