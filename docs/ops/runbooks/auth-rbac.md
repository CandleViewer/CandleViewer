# Auth / RBAC operator runbook (E09-K02)

Status: written 2026-10-09 against `main` at `d9143fb`. Every command, route, metric and audit action
below was checked against the code at that commit. Where a procedure needs something that does not
exist yet, it says **BLOCKED — not implemented** and names the tracking reference; no substitute
command is offered. This runbook has **not** been executed on staging (see the last section).

Conventions: REST paths are shown relative to the API base. `$API` is your API base URL and `$TOKEN` a
valid access token of the stated role; both come from your own environment, never from this page. No
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

1. Confirm the lock. A login attempt returns `423 Account locked` with a `Retry-After` header (seconds
   left). The audit log has `auth.account_locked` (severity warning) with the identifier redacted.
   Query as an Owner (a non-owner sees only its own events):
   `GET $API/admin/audit?action=auth.account_locked` — expect one entry per refused attempt.
2. Wait out `Retry-After`. Expect elapsed time of at most 15 minutes. Then the user logs in normally.
3. Verify: `auth.login` appears for the user, and a fresh login returns `200`.

Owner's own account: the same expiry applies. If the Owner has lost the TOTP device, recovery codes
are the path: `POST /auth/mfa/recovery` with the `mfa_token` from the login step and one code
(`api/auth.py`, `auth/mfa_service.py::recover`). A code is single use; `auth.recovery_code_used` is
written, and `auth.recovery_codes_exhausted` when none remain. Re-enrolment is forced when fewer than
three remain (`auth/recovery_codes.py`, `LOW_CODE_THRESHOLD`).

Not available today:

- **Early unlock by an Owner: not implemented, no ticket.** Wait for expiry.
- **Owner alert on lockout: BLOCKED — not verified/implemented.** The review found it unverified
  (see #2102). Do not rely on being notified; check the audit log.
- **`cv_auth_lockouts_total`** is declared `planned` in `metrics_catalogue.py` and is not emitted by
  any code, so it cannot confirm a lock or an unlock. Use the audit log.

Stop and escalate if every Owner account is locked and has no TOTP device or recovery codes: go to
procedure 3.

## 2. Reset a user's TOTP as Owner (US-ONB-010)

Preconditions: you are signed in as an Owner. You cannot reset your own TOTP (the service refuses a
self-reset). The reset needs a step-up for action class `users`. The target is not you.

1. Preview what the reset affects:
   `GET $API/users/{userId}/mfa/reset-preview` — Owner only. Expected `200` with
   `open_position_count`, `positions` (`known` or `unavailable`), `position_source`,
   `requires_acknowledge_unknown_positions`, `message`. Today the position source may be
   `not_deployed`; then positions are reported as unavailable, never as 0.
2. Step up. Call the reset once; it answers `403` naming the `users` action class and starts a
   challenge. Then `POST $API/auth/step-up` with `{"code": "<your current TOTP code>"}`. Expected
   `200` with `elevated_until`. Three wrong codes abandon the action and make your session read-only for
   5 minutes (`403 session_read_only`).
3. `POST $API/users/{userId}/mfa/reset`. If positions are `unavailable`, the first call returns
   `409 positions_unknown`; repeat with body `{"acknowledge_unknown_positions": true}` only after
   you have checked the user's positions another way. Expected `200` with `target_user_id`,
   `methods_revoked`, `sessions_revoked`. The reply contains no secret.
4. The user logs in with their password and re-enrols TOTP (`POST /auth/mfa/enroll`, `.../confirm`).
5. Verify from telemetry: audit action `auth.mfa_reset_by_owner` (severity critical) with the
   target user; counter `auth_mfa_resets_total` rises by 1 on the API process (`auth/metrics.py`).

Note: `auth.mfa_reset` also exists in the audit vocabulary, but the Owner route writes
`auth.mfa_reset_by_owner`. Search for that name.

Expected elapsed time: not measured. E09-X04 did not run a reset drill; this is a gap, not an estimate.

## 3. Break-glass for total Owner lockout (SR-023)

**BLOCKED — not implemented.** There is no break-glass CLI, route or script in the repository
(`docs/security/reviews/e09-auth-review.md` §3, finding R-6). Tracking: Owner item AB on #1778 (no
owning ticket yet). The drill has not been executed.

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

1. **Confirm, read-only.** `POST $API/admin/audit/verify` with `{}` (optional `from_id`, `to_id`).
   Expected `200` with `verified`, `entries_checked`, `first_bad_id`, `checked_at`. `verified: false`
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
event carries the reason, which the degraded-mode banner shows.

Reason codes (`net/binding_check.py`, `net/scheduler.py`):

| Code                            | Meaning                                                       |
| ------------------------------- | ------------------------------------------------------------- |
| `net.public_binding_detected`   | a listener is bound to `0.0.0.0` or `::`                      |
| `net.off_mesh_binding_detected` | a listener is bound outside the loopback/mesh CIDR allow-list |
| `net.binding_check_failed`      | the socket table could not be read (fail-closed)              |
| `net.self_check_timed_out`      | the check exceeded its time limit                             |

1. Read the gauge on the metrics listener: expect `net_binding_safe 0`. Read the reason code from the
   banner or the `system` topic event.
2. Diagnose on the host: list listening sockets for the API process with your platform's tool
   (for example `ss -ltnp`) and compare with the intended bind. On WSL, a Windows port-proxy rule can
   re-expose a loopback listener; check it (`20-architecture.md`, "WSL hazards").
3. Fix the bind or the proxy rule, then restart the API process so the boot check runs; or wait for
   the next hourly pass. There is **no command or endpoint to clear the gate**. `ReadOnlyGate.clear`
   accepts only a fresh passing result, and nothing exposes it to an operator.
4. Verify: `net_binding_safe 1`, and the banner clears via a `system` topic event with reason
   `net.binding_safe`. Orders are accepted again.

Stop and escalate if the failing listener is public and you cannot explain it: treat as an exposure
incident under `SECURITY.md`. Do not disable the check or the gate. Expected elapsed time: up to
one hour if you rely on the hourly pass; a restart runs the check at boot.

## 7. Read the RBAC matrix and answer "why was this denied?"

The permission vocabulary is generated: the single source is the `x-rbac` blocks in
`docs/plan/22-api-openapi.yaml`; `tools/rbac/generate.py` writes
`candleviewer/auth/generated_permissions.py` and the `permissions` list in
`candleviewer/auth/rbac_seed.json`. Which role holds which permission is hand-authored in
`rbac_seed.json` (`roles`, `role_permissions`). Never hand-edit the generated parts; CI
`generated-code` runs `tools/rbac/generate.py --check`.

To answer a denial:

1. Find the denial in the audit log: `GET $API/admin/audit?action=rbac.denied` (add `actor_user_id`).
   The entry names the permission and scope (`auth/scopes.py`, `enforce`).
2. Look up the permission on the route in `22-api-openapi.yaml` (`x-rbac`), then check whether the
   user's role holds it in `rbac_seed.json`.
3. For account-scoped routes, a Manager also needs the account grant: scope decisions are in
   `auth/scopes.py` (`decide`; `OBJECT_REQUIRED`, `ACCOUNT_NOT_GRANTED`).
4. A step-up refusal is a different thing: `403` with code `step_up_required` and an
   `action_class`, audit `auth.step_up_required`.
5. For the route-by-actor matrix test, see `services/api/tests/contract/rbac/test_route_matrix.py` and
   `docs/qa/charters/E09-charter-2-rbac-boundaries.md`.

**`cv_authz_denied_total`**: the catalogue declares `authz_denied_total{permission}` as `planned`
(`observability/metrics_catalogue.py`) and no code increments it. Until it is wired, the audit log is
the only denial telemetry. `auth_stepup_failures_total` is likewise `planned`; the emitted step-up
counters are `auth_step_up_total` and `auth_step_up_failures_total` (`auth/metrics.py`).

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
- **SR-042 origins (`CV_ALLOWED_ORIGINS`).** The CSRF guard refuses any state-changing request
  whose `Origin` is not in this list (or that carries `Sec-Fetch-Site: cross-site`). Set it to every
  app origin (localhost dev port, tailnet hostname, the Electron origin) before rollout.
- **Unit and contract tests** use in-process fakes and keys generated inside the test process; there
  is no shared credential to rotate.
- **Secret scanning.** If a fixture secret leaks, follow `SECURITY.md` and rotate immediately.

## Known gaps referenced above

| Gap                                                                       | Reference                                 |
| ------------------------------------------------------------------------- | ----------------------------------------- |
| Break-glass CLI (SR-023)                                                  | #1778 item AB, no owning ticket           |
| `PUT /auth/password` not implemented (no revoke-other-sessions on change) | #2110                                     |
| Scheduled audit-chain verifier                                            | #2111                                     |
| Disable-user cascade (SR-029)                                             | #965                                      |
| Session rotation on role change and step-up                               | #2101                                     |
| Owner notification on lockout                                             | #2102                                     |
| Authz/lockout metrics declared but not emitted                            | none yet; listed in the PR as new finding |

## Execution record

Not executed on staging by a non-author: deferred → #1778 item U. Security engineer and Ops review:
open (needs owner). Nothing in this runbook has been run by anyone other than its author.
