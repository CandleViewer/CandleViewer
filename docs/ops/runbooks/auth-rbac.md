# Auth / RBAC operator runbook (E09-K02)

Status: written 2026-10-09 against `main` at `d9143fb`; corrected 2026-10-13 against `main` after #2154 (QA gaps on #292); the lockout, authz and step-up metrics were updated 2026-10-15 for #2117. Every command, route, metric and audit action
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

## 4. Disable a user and what follows (SR-029)

**BLOCKED — not implemented** as a single action. The cascade (revoke sessions, close sockets,
cancel pending actions, positions decision) is owned by E42-T04 (#965). `DELETE /users/{userId}` does
not exist in `api/users.py`; the only user route there is `PUT /users/{userId}/roles`.

What exists and may be used as separate primitives (no endpoint wires them to a disable):

- `SessionService.revoke_all` (`auth/session_service.py`) and the socket hub
  (`ws/revocation.py`). Metric `auth_revocation_latency_seconds` and
  `auth_session_revocations_total{reason}` record revocations.
- `users.status = disabled` makes login refuse with `403 Account disabled` after a correct password.

Until #965 lands, an operator cannot disable a user end to end. Escalate. The in-process drill
`services/api/tests/security/auth/test_disable_user_drill.py` is a test counterpart only.

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

1. Read the gauge on the metrics listener: expect `net_binding_safe 0`, e.g. `curl -s http://127.0.0.1:9108/metrics | grep net_binding_safe`. Read the reason code from the
   `system` topic event or the API log.
2. Diagnose on the host: list listening sockets for the API process with your platform's tool
   (for example `ss -ltnp`) and compare with the intended bind. On WSL, a Windows port-proxy rule can
   re-expose a loopback listener; check it (`20-architecture.md`, "WSL hazards").
3. Fix the bind or the proxy rule, then restart the API process so the boot check runs; or wait for
   the next hourly pass. There is **no command or endpoint to clear the gate**. `ReadOnlyGate.clear`
   accepts only a fresh passing result, and nothing exposes it to an operator.
4. Verify: `net_binding_safe 1`, and a `system` topic event clears the state with reason
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

1. Find the denial in the audit log: `curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/audit?action=rbac.denied"` (add `&actor_user_id=<id>`).
   The entry names the permission and scope (`auth/scopes.py`, `enforce`).
2. Look up the permission on the route in `22-api-openapi.yaml` (`x-rbac`), then check whether the
   user's role holds it in `rbac_seed.json`.
3. For account-scoped routes, a Manager also needs the account grant: scope decisions are in
   `auth/scopes.py` (`decide`; `OBJECT_REQUIRED`, `ACCOUNT_NOT_GRANTED`).
4. A step-up refusal is a different thing: `403` with code `step_up_required` and an
   `action_class`, audit `auth.step_up_required`.
5. For the route-by-actor matrix test, see `services/api/tests/contract/rbac/test_route_matrix.py` and
   `docs/qa/charters/E09-charter-2-rbac-boundaries.md`.

**`authz_denied_total{permission}`** (the catalogue name; there is no `cv_` prefix) counts each
denial decided by `auth/scopes.py::enforce`. It moves before the `rbac.denied` audit row is written,
so an audit failure never hides a denial. `permission` is the permission code from a closed set (the
generated vocabulary plus `other`). Only routes that call `enforce` are counted, and today those are
all `users:write` routes: `PUT /users/{userId}/roles`, the invite routes (`POST /users`,
`GET /users/invites`, `POST` and `DELETE /users/{userId}/invite`) and the TOTP reset routes. Not
counted:

- permission checks written inline in other route modules (market data, instruments, and so on),
  which write no `rbac.denied` row either: their only trace is the `403` response itself;
- WS subscribe denials: see `cv_ws_subscribe_total{result="forbidden"}` and the audit action
  `ws.subscribe.denied`;
- the owner-floor `409` (audited as `rbac.denied`, see the note below, but a business refusal rather
  than a permission check) and `step_up_required` (§2).

Read it on the metrics listener, for example
`curl -s http://127.0.0.1:9108/metrics | grep '^authz_denied_total'` (every permission is listed at 0
from process start). The `AuthzDeniedSpike` rule fires above 20 denials in 10 minutes
(`sum by (permission) (increase(authz_denied_total[10m]))` shows which permission).

**`auth_stepup_failures_total`** (no labels) counts each failed step-up verification: wrong password,
locked account, wrong or replayed code. The audit row is `auth.step_up_failed` (names the action
class). `auth_step_up_failures_total{action_class}` also exists inside the process but is not served on
the metrics listener, like the other auth counters outside `AUTH_EXPORTED_NAMES` (`auth/metrics.py`);
that gap is tracked in #2319.

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
  or previous) equal to the TOTP or recovery key. Alerts: `CsrfRefusalsHigh`,
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

## Known gaps referenced above

| Gap                                                                       | Reference            |
| ------------------------------------------------------------------------- | -------------------- |
| Break-glass CLI (SR-023)                                                  | #1778 item AB, #2119 |
| `PUT /auth/password` not implemented (no revoke-other-sessions on change) | #2110                |
| Scheduled audit-chain verifier                                            | #2111                |
| Disable-user cascade (SR-029)                                             | #965                 |
| Session rotation on role change and step-up                               | #2101                |
| Lock alerts lost inside quiet hours                                       | #2621                |
| `auth_login_failures_total` declared but not emitted                      | #2319 (item 4)       |

## Execution record

Not executed on staging by a non-author: no staging host exists (#1778 item A); the run is tracked
in #2298. Security review of §3/§5 exists as an agent review on #2115; Ops review is recorded on #2343.
