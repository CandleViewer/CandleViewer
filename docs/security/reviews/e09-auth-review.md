# E09 security review — auth, sessions, 2FA, RBAC, audit (E09-X04)

- Ticket: E09-X04 (#300). Threat model: `docs/security/threat-models/e09-auth-rbac.md` (E09-X01).
  Abuse cases: `docs/security/abuse-cases/e09-auth.md` (E09-X02). CI gates:
  `docs/security/auth-security-gates.md` (E09-X03).
- Reviewed against `main` at `06a742b` (2026-10-09). Paths are relative to
  `services/api/candleviewer/` unless they start with `services/` or `docs/`.
- Method: white-box code walk by an agent, plus one automated drill counterpart (§4). This was
  not the conversational review with the epic owner that the ticket describes; that session is
  still needed.

> **Status: pending.** Still open: break-glass drill, security-engineer sign-off, Owner sign-off
> (#1778 item U). This document does **not** say the R0 area-6 security gate is met, and it
> holds no sign-off. E09 cannot be marked Done on the strength of this record.

Verdict key: **PASS** (control exists in code and a named test exercises it) ·
**PARTIAL** (some exists, some gap; ticketed or flagged) · **FAIL-T** (missing, owning ticket
named) · **OPEN** (missing, and no owning ticket was found, so it needs triage) ·
**NOT EXECUTED**.

## 1. Control-by-control verdicts (SR-010..SR-029, SR-050, SR-051)

| Control | Implementation (file:line) | Proving test | Verdict |
|---|---|---|---|
| SR-010 local auth, no anonymous routes | `api/deny_by_default.py:70` `assert_app_routes_declared`, `:84` runtime deny | `tests/unit/api/test_deny_by_default.py::test_runtime_denies_undeclared_route_with_403` | PASS |
| SR-011 Argon2id, params stored, rehash on login | `auth/hashing.py:31` (m=65536,t=3,p=4), `:104` `needs_rehash`; `auth/login_service.py:131` | `tests/unit/auth/test_hashing.py::test_hasher_needs_rehash_true_for_stale_params`; AC-CRED-01 | PASS. The ≥100 ms on-host cost is not measured here (see E09-Q05 / #2097) |
| SR-012 opaque tokens, cookie flags | `auth/session_service.py:115,158` (`secrets.token_urlsafe`); `api/sessions.py:187-189` (HttpOnly, SameSite=strict) | AC-CSRF-03 (`tests/security/auth/test_csrf_cookie_abuse.py`) | PASS. The double-submit CSRF token is a separate item, see F-1/#2090 |
| SR-013 rotate on login, TOTP, step-up, password change, role change | Rotation exists for MFA-completion mint (`api/auth.py:327`) and refresh (`auth/session_service.py:195`). Role change pushes `permission_change` (`api/users.py:199`) but does not re-mint the session id. No step-up rotation found. Password change route not implemented (see SR-028) | AC-SES-01..04; `tests/unit/ws/test_gateway_e2e.py::test_ws_e2e_permissions_sub_check_and_live_role_change` | PARTIAL, finding R-1 (#2101) |
| SR-014 uniform login failures + dummy verify | `auth/login_service.py:105` (`verify_dummy`), `:128` disabled revealed only after correct password | AC-ENUM-01/03; `tests/unit/auth/test_login_timing_enumeration.py` | PASS. AC-ENUM-02 is a design decision (F-2 family) |
| SR-015 per-account + per-IP throttling | `auth/throttle.py:22`; `auth/login_service.py:93` (checked before hash) | `tests/unit/auth/test_login_service.py::test_per_ip_throttle_blocks_independent_of_username`; AC-CRED-03 | PASS |
| SR-016 lockout + owner alert | `auth/login_service.py:44-45` (5 failures, 15 min; stricter than the SR's 10) | `test_lockout_after_five_failures_refuses_even_correct_password`; AC-CRED-04/05 | PARTIAL. The owner alert on lockout was not verified (AC-CRED-05 NOT RUN) |
| SR-017 deny-by-default start-up | `api/deny_by_default.py:70` | `test_build_fails_for_route_without_declaration` | PASS |
| SR-018 route × role matrix | `services/api/tests/contract/rbac/matrix.yaml` | `services/api/tests/contract/rbac/test_route_matrix.py`, `test_scope_and_ws.py` (E09-Q03) | PASS |
| SR-019 list and revoke own sessions | `api/sessions.py:427` (list), `:511` (revoke one) | `tests/unit/api/test_sessions_router.py`; AC-CSRF-05 | PASS |
| SR-020 mandatory TOTP | `auth/mfa_service.py`, MFA leg of `/auth/login` → `/auth/mfa/verify` (`api/auth.py:288`) | `tests/unit/auth/test_mfa_service.py` | PASS for login. First-login enrolment enforcement is UI flow (E09-Q02) and was not reviewed here |
| SR-021 ±1 skew + replay cache | `auth/totp.py:24,79`; `auth/mfa_service.py:126,210` (`record_time_step`) | `tests/unit/auth/test_totp.py::test_verify_code_rejects_beyond_skew_window`; AC-MFA-01 | PASS |
| SR-022 recovery codes | `auth/recovery_codes.py:33` (10), `:50` (≈138 bit), `:65` (HMAC-SHA256 keyed, not Argon2id); `auth/mfa_service.py:265` consume, `:290` regenerate | `test_recovery_code_entropy_is_at_least_128_bits`; AC-MFA-03/04/05 | PASS with deviation D-1 (keyed HMAC in place of Argon2id, recorded in the module docstring). The Owner alert on use did not exist; #2496 adds it (`AuthRecoveryCodeUsed`, a page so quiet hours never mute it; corrected 2026-10-15) |
| SR-023 break-glass CLI | **Not in the repo.** `grep` finds `break-glass`/`SR-023` only in docs | none | **OPEN** (#1778 item AB), see §3 |
| SR-024 timeouts + 12 h trading freshness | `auth/session_service.py:61` (12 h absolute), `:64` (12 min access token), `:69-71` (idle 15 min default, 5–60 min); all stricter than the SR's 8 h / 7 d | `tests/unit/auth/test_session_service.py` | PARTIAL. No separate 12-hour trading-capability freshness check found on order paths (`mfa_satisfied_at` is stored at `:173` but not consulted by `oms`/`risk`), finding R-2 (#2108) |
| SR-025 step-up, 5 min, scoped | `auth/step_up.py:46` (5 min grace), `:51` action classes, `:53` no-grace classes, `:320` `require_elevation`; `api/users.py:141` | `tests/unit/auth/test_step_up.py`; AC-STEP-01..04 | PASS. The SR asks for password + TOTP; the code verifies TOTP only, deviation D-2 |
| SR-026 no target-user on self-service | Semgrep `no-target-user-on-self-service` (E09-X03) | rule fixtures under `security/semgrep/auth/fixtures/` | PASS (static) |
| SR-027 invite creates least-privilege user | `auth/models.py:339` (`InviteRole`: manager/viewer only, owner not invitable); `auth/invite_service.py:137` | `tests/unit/api/test_invites_router.py::test_create_rejects_owner_role_and_duplicate`; AC-INV-01..04 | PARTIAL. An invite may carry `manager` directly; the SR requires `Viewer` plus a separate audited elevation, finding R-3 (#2109) |
| SR-028 password policy + other-session revoke | `auth/invite_service.py:66,93` (≥12 chars, local deny list, identity checks) | invite-redeem tests | PARTIAL. `PUT /auth/password` (OpenAPI `/auth/password`) has no router, so "change revokes other sessions" does not exist yet, finding R-4 (#2110). The full breached-password corpus is deferred (`invite_service.py:68`) |
| SR-029 disable user → sessions, sockets, pending actions | Primitives exist: `auth/session_service.py:409` `revoke_all`, `ws/revocation.py:54-67` hub, `app.py:811` wiring. The `DELETE /users/{userId}` cascade is **not implemented** | `services/api/tests/security/auth/test_disable_user_drill.py` (automated counterpart, §4) | FAIL-T: cascade owned by E42-T04 (#965) |
| SR-050 two-layer authZ | Layer 1 deny-by-default + `x-rbac`; layer 2 `auth/scopes.py:124` `decide`, `:201` `enforce` | AC-AUTHZ-02/04; E09-Q03 matrix | PARTIAL. #2094 isolates the rules-manager layer-2 test |
| SR-051 server-side account resolution | `auth/scopes.py:151` (OBJECT_REQUIRED), `:158` (ACCOUNT_NOT_GRANTED); Semgrep `no-raw-account-id` | AC-AUTHZ-02/03 | PASS (domain layer). Query-construction scoping on list endpoints belongs to the consuming epics |

### 1.1 Other items in the brief

| Item | Implementation | Proving test | Verdict |
|---|---|---|---|
| Audit chain trigger + revoked UPDATE/DELETE | `migrations/versions/0003_audit_log.py:150-154` (chain, append-only, no-truncate triggers) | `services/api/tests/integration/audit/test_audit_repository.py::test_app_role_cannot_update_or_delete`, `::test_truncate_refused_even_for_owner` (integration; not run in this review) | PASS (by inspection + integration test) |
| audit:read grants (SR-067) | `migrations/versions/0016_audit_read_grants.py` | `services/api/tests/integration/auth/test_0016_audit_read_grants_migration.py` | PASS. Fixed in #2083 / PR #2095 |
| Nightly chain verifier + `cv_audit_chain_verified` | On-demand `audit/query.py:155` `verify()` via `api/audit.py:239`; metric `audit_chain_verification_failures_total` in the catalogue | `test_trigger_chain_genesis_and_python_verifier_agree` | PARTIAL. No scheduled nightly job found, finding R-5 (#2111) |
| Tailscale-only binding self-check, fail-closed read-only (US-ONB-008) | `net/middleware.py:54` (mesh CIDR, 403/4403); `net/binding_check.py:155` trips `ReadOnlyGate`; gauge `net_binding_safe` | `tests/unit/net/test_binding_check.py::test_self_check_fails_closed_when_enumeration_raises`, `tests/unit/net/test_read_only_gate.py` | PASS |
| Detections: lockouts, authz denied, binding, break-glass | `observability/metrics_catalogue.py:1430` (`auth_lockouts_total`), `:1498` (`authz_denied_total`), `live` since #2612; `net/metrics.py:7` (`net_binding_safe`) | catalogue tests (they prove a name is declared, not emitted or scraped) | **FAIL-T** (corrected 2026-10-15, #2496; this row first read "PASS for the metrics"). Neither metric was emitted, so `AuthLockouts` and `AuthzDeniedSpike` could not fire (#2117, #2319); #2612 now emits both. `net_binding_safe` was not on the scraped registry and no rule read it: #2496 serves it and adds `NetBindingUnsafe`. The break-glass-use gauge and page follow in a separate PR on #2496, after #2119 (decision R8 on #2119; #2710). The chain-failure route needs the scheduled verifier (R-5, #2111) |

## 2. Findings triage

Dates are when the item was raised. "Due" is a review-by date that the owner still has to confirm.
An accepted risk needs a dated Owner signature. Only F-2 carries one (Owner record 2026-10-09 on #1778); every other open item is not accepted.

| Id | Source | Item | STRIDE | Severity | Owner | Tracking | Raised / due | Status |
|---|---|---|---|---|---|---|---|---|
| F-1 | E09-X02 | No SR-041 double-submit CSRF token; relies on SameSite=Strict + Origin allow-list + bearer header | Tampering | Medium | Architect | #2090 | 2026-10-09 / 2026-10-23 | Open (fix or Owner-signed acceptance) |
| F-2 | E09-X02 | Access tokens not bound to IP/UA; theft detected only on refresh reuse (repro: abuse case AC-SES-06 in `docs/security/abuse-cases/e09-auth.md`) | Spoofing | Low–Medium | Architect + Owner | #2145; #1778 Owner record 2026-10-09 | 2026-10-09 | **Accepted design decision** (Owner, #1778 record 2026-10-09): SR-012 stores IP/UA but does not bind; no change. Residual bearer-theft window bounded by the 12 min access TTL and refresh-reuse detection |
| A-1 | #2083 | `audit:read` grants misaligned with 04 §7.2 / SR-067 | Information disclosure | High (P0) | Security | #2083 → PR #2095 | 2026-10-08 | Fixed (merged) |
| X3-1 | E09-X03 | ZAP authenticated scan needs CI fixture secrets | — (gate coverage) | Medium | Owner | #1778 item D | 2026-10-04 | Open |
| X3-2 | E09-X03 | Git-history gitleaks scan and ZAP end-to-end not run locally | — (gate coverage) | Low | DevSecOps | `auth-security-gates.md` status notes | 2026-10-09 | Open; CI run evidence needed |
| X3-3 | E09-X03 | Two dated `nosem` suppressions on 501 stubs in `api/auth.py:401,422` | Repudiation | Low | Security | in-file `review=2026-12-31` | due 2026-12-31 | Time-boxed |
| FU-1 | E09-Q03 | Rules-manager layer-2 grant check not tested in isolation | Elevation of privilege | Medium | Backend | #2094 | 2026-10-09 | Open |
| FU-2 | E09-Q03 | `rules_actor` uses an inline role compare in place of `PrincipalSnapshot.is_owner` | Elevation of privilege | Low | Backend | #2096 | 2026-10-09 | Open |
| FU-3 | E09-Q05 | Argon2 on-host cost (≥100 ms) not measurable by the k6 profile | Denial of service | Low | Backend | #2097 | 2026-10-09 | Open |
| R-1 | this review | SR-013 rotation missing on step-up and role change (role change only refreshes permissions) | Spoofing | Medium | E09 epic owner | #2101 (scope extended to step-up rotation) | 2026-10-09 | Open |
| R-2 | this review | SR-024 12-hour trading-capability freshness not enforced on order paths | Elevation of privilege | Medium | E09 / OMS owner | #2108 | 2026-10-09 | Open |
| R-3 | this review | SR-027: invites can carry `manager` directly (no Viewer-first elevation) | Elevation of privilege | Low | Architect + Owner | #2109; Owner item AC on #1778 | 2026-10-09 | Open; reconcile SR text or code |
| R-4 | this review | SR-028: `PUT /auth/password` not implemented, so no other-session revocation on change | Spoofing | Medium | E09 epic owner | #2110 (route); #2099 (test) | 2026-10-09 | Open |
| R-5 | this review | No scheduled nightly audit-chain verifier; only on-demand `verify()` | Repudiation | Medium | Security | #2111; E43-T10 (#1238) verifies | 2026-10-09 | Open |
| R-6 | this review | SR-023 break-glass CLI missing | Denial of service (lockout) | High | Owner | Owner item AB on #1778 (no owning ticket; proposed new E09 Story) | 2026-10-09 | **Blocks R0** |
| R-7 | this review | SR-029 disable cascade missing | Elevation of privilege | High | Accounts/admin | E42-T04 (#965) | 2026-10-09 | Open |
| D-1 | this review | SR-022 says Argon2id for recovery codes; code uses keyed HMAC-SHA256 (≈138-bit codes) | — | Info | Security + Owner | Owner item AD on #1778 | 2026-10-09 | Awaiting Owner decision |
| D-2 | this review | SR-025 says password + TOTP for step-up; code requires TOTP only | Spoofing | Low | Architect + Owner | Owner item AE on #1778 | 2026-10-09 | Awaiting Owner decision |

Rows R-1 to R-7 and D-1/D-2 come from this review. Each is now tracked: R-1 #2101, R-2 #2108,
R-3 #2109, R-4 #2110, R-5 #2111, R-7 #965. Owner decisions are on #1778
([items AB–AE](https://github.com/basiltt/CandleViewer/issues/1778#issuecomment-6079001525)): AB is the R-6 break-glass CLI, which has no owning ticket and is proposed as
a new E09 Story; AC is R-3; AD is D-1; AE is D-2. The sign-off is item U.

## 3. Break-glass drill (SR-023): NOT EXECUTED

- **Blocked by a missing artefact.** No offline break-glass CLI exists in the repository. A
  search of every epic backlog (`docs/plan/backlog/*.json`) and of GitHub issues found **no
  ticket that implements it**. E09-K02 (#292) only *documents* the runbook procedure and is
  itself blocked by this ticket. E09-X01 names the CLI as a trust boundary. E43-T04 reviews
  lockout but does not build it. It is raised for an Owner decision as #1778 item AB (a new E09
  Story is proposed).
- **Blocked by environment.** The drill needs a staging host with a staging KEK and an engineer
  who did not write the runbook, with a scribe. An agent cannot provide either.
- Not recorded, because nothing was run: elapsed lockout-to-recovery time, runbook ambiguities,
  refusal without filesystem access or KEK, the audit event, and the UI notice.
- The automated counterpart the ticket asks for
  (`test_break_glass_requires_host_filesystem_and_kek_present`) cannot be written until the CLI
  exists.

## 4. Disable-user drill (SR-029): automated counterpart only

The staging drill by a human is **still required**. What ran is an in-process counterpart:
`services/api/tests/security/auth/test_disable_user_drill.py`.

- Setup: the real `create_app()` and the app's own `RevocationHub`. A real `SessionService` and
  `StepUpService` run over in-memory session/MFA fakes on an injected clock. There are two live
  sessions for the user and an open `/ws` socket that is authenticated and subscribed
  (`book.BTCUSDT.50`). Pending activity is a recorded step-up challenge. A bystander user has a
  session of their own.
- Action: `SessionService.revoke_all(user, reason="user_disabled")`, then
  `RevocationHub.revoke(session_id, "user_disabled")` for each revoked session. The
  `DELETE /users/{userId}` route itself does not exist yet.
- Guidance for the E42-T04 cascade (#965): revoke the sessions first, then end every socket of
  the user as `23-ws-protocol.md` §9.5 requires: `bye` (`code 4403`, `reason user_disabled`,
  `reconnect false`), then the close frame `4403`. Either primitive does that:
  `ConnectionRegistry.user_disabled(user_id)` (reached as `app.state.ws_events.user_disabled`),
  which closes every authenticated socket of the user, or
  `RevocationHub.revoke(session_id, "user_disabled")` for each revoked session. The reason must
  be exactly `user_disabled`: any other reason closes `4401`, which tells the client to refresh
  its token and reconnect. Corrected on 2026-10-15 (#2493). This section first recorded
  `code 4401` for the disable and named the hub without that requirement, because
  `RevocationHub.revoke` then closed `4401` for every reason, against §9.5.
- Observed: both sessions are revoked, with `revoked_at` equal to the action instant on the
  injected clock (0.000 s injected delay). The SR-029 bound is asserted on the injected clock
  only; no wall-clock figure is asserted. Their access tokens are refused. The socket receives
  `bye` (`code 4403`, `reason user_disabled`, `reconnect false`), then the close frame `4403`.
  The pending step-up challenge can no longer be read or completed. The revoked token cannot
  open a new socket. The bystander's session is untouched. Repeating the action is idempotent.
  The operational latency the Owner needs comes only from the staging drill.
- Every WS read has a 5 s deadline. With the `bye` send removed from `RevocationHub.revoke`, the
  test fails in about 5 s ("no WS frame within 5.0s"); it does not hang. The mutation was reverted.
  With `user_disabled` mapped back to `4401` in `RevocationHub.revoke`, the drill and
  `services/api/tests/unit/ws/test_revocation.py` fail on the code (#2493); also reverted.
- **Not covered**, because it does not exist yet and belongs to E42-T04 (#965) or E35:
  `users.status=disabled`, grant revocation, disarming the user's rules (rule-engine pending
  actions), the recorded positions decision in the audit log, and the `users.disable` audit row.
  Pending *rule-engine* actions are therefore **not** shown to be cancelled. Only session-scoped
  pending state is.

## 5. Residual risks

1. **Total Owner lockout has no tested recovery path** (SR-023 / U10). Until a CLI exists and a
   drill passes, losing the TOTP device and the recovery codes means rebuilding identity by
   hand at the database. This is a High residual and blocks R0.
2. **Disable is not yet a single action.** Until E42-T04 lands, an operator has to revoke
   sessions and freeze grants separately. Rules authored by a disabled user stay armed.
3. **Bearer-token theft window** (F-2). It is bounded by the 12 min access-token TTL and by
   refresh-reuse detection.
4. **CSRF depends on the bearer-header model staying true** (F-1 / #2090).
5. **Session fixation surface on privilege change** (R-1). It is mitigated by short token TTLs
   and server-side permission refresh, but the SR-013 rotation set is incomplete.
6. **Audit tampering detection is on-demand only** (R-5) until a nightly verifier and its alert
   route exist.

## 6. Pen-test scoping note for E43

Controls that most warrant external testing before R4 live enablement, in priority order:

1. The deny-by-default route registry and the `x-rbac` → `decide()` second layer (SR-017,
   SR-050, SR-051), using cross-account identifiers in body, path and query, and WS topic options.
2. Session lifecycle: refresh rotation and family revocation, idle and absolute expiry, WS
   revocation on logout or disable, and the bearer-only state-change model (F-1, F-2).
3. Step-up scope and grace window across action classes and sessions (SR-025).
4. The mesh-only middleware and binding self-check on the deployed host (US-ONB-008, RSK-022).
5. Audit append-only guarantees under the application role, and chain verification (E43-T10).
6. The break-glass CLI, once it exists: precondition enforcement (host filesystem + KEK) and
   attempt recording.
7. Login throttling and lockout as a denial-of-service vector (U27, U28), coordinated with
   E43-T04.

Out of scope for this note: the key vault (E27) and the order path beyond its `authorize()`
calls.

## 7. Sign-off

Pending: break-glass drill, security-engineer sign-off, Owner sign-off (#1778 item U; owner
decisions AB–AE: https://github.com/basiltt/CandleViewer/issues/1778#issuecomment-6079001525). No reviewer signature and no gate statement are recorded here.
