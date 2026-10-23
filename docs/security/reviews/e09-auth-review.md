# E09 security review — auth, sessions, 2FA, RBAC, audit (E09-X04)

- Ticket: E09-X04 (#300). Threat model: `docs/security/threat-models/e09-auth-rbac.md` (E09-X01).
  Abuse cases: `docs/security/abuse-cases/e09-auth.md` (E09-X02). CI gates:
  `docs/security/auth-security-gates.md` (E09-X03).
- Reviewed against `main` at `06a742b` (2026-10-09). Re-examined on 2026-10-23 against
  `origin/main` at `4ce8f438`, with both drills run on a stack built from `b8ccf5a3`: of the files
  cited, only `app.py`, `auth/scopes.py` and `api/step_up.py` differ between the two, by view-as
  work that weakens no E09 control. File:line citations are at `4ce8f438`; later `main` may shift
  them. Code paths are relative to `services/api/candleviewer/` and test paths to `services/api/`;
  paths that start with `services/`, `docs/`, `infra/` or `security/` are from the repository
  root.
- Method: white-box code walk by an agent (read-only on 2026-10-23), plus the two drills of §3 and
  §4 on a dev compose stack. This was not the conversational review with the epic owner that the
  ticket describes; that session is still needed.

> **Status: re-examined 2026-10-23. The R0 area-6 security gate is not met.** The review found
> Critical: none; High: none new. #4254, which corrects the break-glass runbook, merged as
> `e78556cf` (2026-10-23), and nobody has re-run the merged text (DoD 2). The break-glass notice
> was never observed, and its UI half and WCAG check are #306. No armed rule was drilled for AC4.
> The owner has yet to rule on item U, F-2's signature and date, O3, AC4's armed-rule clause, DoD
> 2's re-run, the proposed due dates, U45 and the §3.6.1 residual, and is to confirm F-4 and F-8:
> #2701 item 20 (comment 6364889494). This record holds no signature, and E09 cannot be marked
> Done on it (§7).

Verdict key (AC1): **PASS** (the control exists in code, and a named test or its construction
proves it) · **FAIL-T** (a gap, with its owning ticket named) · **ACCEPTED** (an accepted risk with
a dated Owner signature; no control needs it). SR-023 and SR-029 pass in code; their drills are §3
and §4.

## 1. Control-by-control verdicts (SR-010..SR-029, SR-050, SR-051)

<!-- prettier-ignore -->
| Control | Implementation (file:line) | Proving test | Verdict |
|---|---|---|---|
| SR-010 local auth, no anonymous routes | Deny by default (SR-017). Public to every mesh peer: FastAPI's default `/docs`, `/redoc` and `/openapi.json`, plus `/metrics`, `/readyz` and `/health/*` (`api/deny_by_default.py:20`, `api/contract_conformance.py:50-52`, `app.py:1364-1368`) | `tests/unit/api/test_deny_by_default.py::test_runtime_denies_undeclared_route_with_403` | **FAIL-T** #4206 (L2, `/metrics`), #4222 (L2, the `/readyz` and `/health/*` probes): SR-010 allows only `/healthz` (loopback only), login and static assets |
| SR-011 Argon2id, params stored, rehash on login | `auth/hashing.py:34` (m=65536, t=3, p=4; argon2-cffi's 16-byte salt), `:126`; rehash at `auth/login_service.py:148-152` | `tests/unit/auth/test_hashing.py::test_hasher_needs_rehash_true_for_stale_params`; AC-CRED-01 | PASS. The ≥100 ms on-host cost is FU-3 (#2097) |
| SR-012 opaque tokens, cookie flags | `auth/session_service.py:417` (256-bit), `:331`; cookie flags at `api/sessions.py:423-432` (path `/api/v1/auth`, stricter than `/`); the SR-041 token at `api/csrf.py:194` (#2238) | AC-CSRF-03 (`tests/security/auth/test_csrf_cookie_abuse.py`) | PASS. F-2 (no IP/UA binding) is accepted (§2) |
| SR-013 rotate on login, TOTP, step-up, password change, role change | Rotation at `api/auth.py:707`, `:1061` and `auth/session_service.py:557-576`. A role change only pushes permissions (`api/users.py:477-484`, `:549-660`); a step-up mints nothing (`auth/step_up.py:457-483`); there is no password change route (SR-028) | AC-SES-01..04; `tests/unit/ws/test_gateway_e2e.py::test_ws_e2e_permissions_sub_check_and_live_role_change` | **FAIL-T** #2101 (R-1), #2110 (R-4) |
| SR-014 uniform login failures + dummy verify | Dummy verify at `auth/login_service.py:118-124`. A locked account answers `423` with `Retry-After` whatever password was sent (`api/auth.py:600-609`); an unknown name always gets `401` | AC-ENUM-01/03; `tests/unit/auth/test_login_timing_enumeration.py`; `tests/security/auth/test_observability.py:101-102` pins the `423` (`[401]*5 + [423]` against a ghost's `401`) | **FAIL-T** #1233 (L1). The contract's `/auth/login` lists only 200, 401, 429 and 503 and calls failures "uniform"; the `403` for a disabled user is AC-ENUM-02's documented trade-off |
| SR-015 per-account + per-IP throttling | Per IP, 20 per 60 s (`auth/throttle.py:30-31`); the account locks after 5 failures from any address (SR-016) | `tests/unit/auth/test_login_service.py::test_per_ip_throttle_blocks_independent_of_username`; AC-CRED-03 | **FAIL-T** #1233: no backoff (M1) |
| SR-016 lockout + owner alert | The lock: 5 failures, a fixed 15 minutes, no doubling (`auth/login_service.py:50-51`, `:136-140`; `storage/repositories/users_sqlalchemy.py:145-160`). `AuthLockouts` is a ticket (`infra/prometheus/alerts/system_ticket.yml:154`) | `test_lockout_after_five_failures_refuses_even_correct_password`; AC-CRED-04/05 | **FAIL-T** #2621, #1233 (M1): the ticket is muted in quiet hours, and nothing unlocks the account |
| SR-017 deny-by-default start-up | `api/deny_by_default.py:71-82` (build), `:85-96` (runtime `403`, WS `1008`) | `tests/unit/api/test_deny_by_default.py:19`, `:30` | PASS |
| SR-018 route × role matrix | `services/api/tests/contract/rbac/matrix.yaml` | `services/api/tests/contract/rbac/test_route_matrix.py`, `test_scope_and_ws.py` (E09-Q03) | PASS |
| SR-019 list and revoke own sessions | `api/sessions.py:1487`, `:1625`; `api/users.py:1294`, `:1311` | `tests/unit/api/test_sessions_router.py`; AC-CSRF-05 | PASS |
| SR-020 mandatory TOTP | `api/auth.py:642`; the enrolment-only session (`auth/login_service.py:157-161`, `api/enrolment_guard.py:79`) | `tests/unit/auth/test_mfa_service.py` | PASS |
| SR-021 ±1 skew + replay cache | `auth/totp.py:24`; `auth/mfa_service.py:138-143` | `tests/unit/auth/test_totp.py::test_verify_code_rejects_beyond_skew_window`; AC-MFA-01 | PASS |
| SR-022 recovery codes | `auth/recovery_codes.py:33`, `:36-40`, `:61-67`; `auth/mfa_service.py:310`, `:332`; `api/auth.py:888`, paged by `AuthRecoveryCodeUsed` (#2660). The key is still the environment setting (`auth/service.py:285-292`, `settings.py:393`), the keyring is "unused until S4 and S5b" (`secrets/_auth_keyring.py:1-9`), and the digests do not bind the user (`auth/recovery_codes.py:61-67`) | `test_recovery_code_entropy_is_at_least_128_bits`; AC-MFA-03/04/05 | **FAIL-T** #2152 (M3): the SR, as amended by ADR-0009 Amendment 4, requires a KEK-wrapped, user-bound key, and `live` refuses environment keys. D-1 is decided (§2) |
| SR-023 break-glass CLI | `breakglass.py`; `admin/breakglass.py:5-11`, `:395-411`, `:464-502`; `secrets/service.py:688-707`; the notice at `ws/gateway.py:1682-1688` and `app.py:1699` | `tests/unit/admin/test_breakglass_flow.py:256` (`test_break_glass_requires_host_filesystem_and_kek_present`); the drill (§3) | PASS in code (#2119). The drill passes AC3; AC2 fails, pending (§3) |
| SR-024 timeouts + 12 h trading freshness | 12 h absolute at `auth/session_service.py:87`, carried on refresh at `:576`; `extend` only re-stamps idle (`api/sessions.py:1321-1343`) | `tests/unit/auth/test_session_service.py`; no test pins ≤ 12 h | PASS, by construction. `mfa_satisfied_at` is re-stamped on every refresh (`auth/session_service.py:432`, `:570`), so it cannot be the marker. #2108 (R-2) stays open for a pin or an explicit check (E43-T03, #1232) |
| SR-025 step-up, 5 min, scoped | `auth/step_up.py:72`, `:83`, `:98`, `:457-483` (password and TOTP, #2154), `:658`; the view-as start is handler-gated (`api/step_up.py`) | `tests/unit/auth/test_step_up.py`; AC-STEP-01..04 | PASS. D-2 shipped in #2154. U35's binding is still #2304 |
| SR-026 no target-user on self-service | `security/semgrep/auth/no-target-user-on-self-service.yml`; `undeclared_query_refusal` at `api/auth.py:562` | rule fixtures under `security/semgrep/auth/fixtures/` | PASS |
| SR-027 invite creates least-privilege user | `auth/models.py:376-381` (#2124) | `tests/unit/api/test_invites_router.py::test_create_rejects_owner_role_and_duplicate`; AC-INV-01..04 | PASS. R-3 is fixed (#2124) |
| SR-028 password policy + other-session revoke | Policy at `auth/invite_service.py:69-110`; no `PUT /auth/password` route | invite-redeem tests | **FAIL-T** #2110, #2099 (R-4) |
| SR-029 disable user → sessions, sockets, pending actions | `api/users.py:790`; `admin/user_disable.py:1-30`, `:75`, `:293` (E42-T04, #965) | `tests/security/auth/test_disable_user_e2e.py:427`, `:477`, `:483`; `tests/security/auth/test_disable_user_drill.py` (#4254); the drill (§4) | PASS in code. The drill fails AC4 as written, on the rule-engine clause (§4) |
| SR-050 two-layer authZ | `auth/scopes.py:158-198`, `:265-298`. No order router is mounted, so the OMS layer is E29's | AC-AUTHZ-02/04; E09-Q03 matrix | **FAIL-T** #2094 (FU-1); U30's guard is #1237 (L3) |
| SR-051 server-side account resolution | `auth/scopes.py:201-212` to `OwnerScope` and `GrantScope` (`storage/repositories/accounts.py:28`, `:35`); Semgrep `no-raw-account-id` | AC-AUTHZ-02/03 | **FAIL-T** #2291 (M2): `GET /rules` filters after fetching |

### 1.1 Other items in the brief

<!-- prettier-ignore -->
| Item | Implementation | Proving test | Verdict |
|---|---|---|---|
| Audit chain trigger + revoked UPDATE/DELETE | `migrations/versions/0003_audit_log.py:150-154` (chain, append-only, no-truncate triggers) | `services/api/tests/integration/audit/test_audit_repository.py::test_app_role_cannot_update_or_delete`, `::test_truncate_refused_even_for_owner` (integration; not run in this review) | PASS (by inspection + integration test) |
| audit:read grants (SR-067) | `migrations/versions/0016_audit_read_grants.py` | `services/api/tests/integration/auth/test_0016_audit_read_grants_migration.py` | PASS. Fixed in #2083 / PR #2095 |
| Scheduled chain verifier + `cv_audit_chain_verified` | The job runs the verifier at start-up and nightly (#3017), from `create_app` since #3872 (`app.py:2167-2174`); a failure counts on `audit_chain_verification_failures_total` (`api/audit_verify_runner.py:150`). The verifier cross-checks `audit_checkpoints` (`audit/query.py:484-489`, `:564-569`), but `run_checkpoint` (`audit/checkpoint.py:33`) has no caller | `test_trigger_chain_genesis_and_python_verifier_agree`; `services/api/tests/integration/audit/test_audit_verify_runner_pg.py::test_scheduled_run_finds_a_row_altered_behind_the_chain_and_the_next_run_still_happens` | PASS: R-5 is fixed (#3017, #3059, #3872). No tail-truncation anchor (M4) |
| Tailscale-only binding self-check, fail-closed read-only (US-ONB-008) | `net/middleware.py:85-100`, `:140-150` (mesh CIDR check, then 403 or WS 4403); `net/binding_check.py:155` trips `ReadOnlyGate`; gauge `net_binding_safe` | `tests/unit/net/test_binding_check.py::test_self_check_fails_closed_when_enumeration_raises`, `tests/unit/net/test_read_only_gate.py` | PASS |
| Detections: lockouts, authz denied, binding, chain, break-glass | The table below | `tests/unit/net/test_binding_metric_export.py`, `tests/unit/auth/test_break_glass_alert_metric.py`, `tests/unit/auth/test_break_glass_attempts_metric.py`, `tests/unit/auth/test_break_glass_read_failures_metric.py`; `infra/prometheus/tests/system_alerts.test.yml` (promtool, run in CI) | PASS, with the residuals below (re-examined 2026-10-23). This row first read "PASS for the metrics", and was corrected to FAIL-T on 2026-10-15 (#2496) |

Each detection the threat model asks for, by its actual name, with the ticket's name in brackets.
The rules are in `infra/prometheus/alerts/`:

<!-- prettier-ignore -->
| Series | Where it's set or counted | Exported and wired | Rule |
|---|---|---|---|
| `auth_lockouts_total` (`cv_auth_lockouts_total`) | `auth/login_service.py:214`, `auth/step_up.py:595` | live in the catalogue; `auth/metrics.py:375`; `app.py:2025` | `AuthLockouts` (`system_ticket.yml:154`) |
| `authz_denied_total{permission}` (`cv_authz_denied_total{permission}`) | `auth/scopes.py:298`, `admin/http.py:130`, `api/exchange_keys.py:204` | exported | `AuthzDeniedSpike` (`system_ticket.yml:228`) |
| `net_binding_safe` (`cv_network_binding_ok`) | `net/binding_check.py:155-181` | `net/metrics.py:15-19`; `app.py:2019` | `NetBindingUnsafe` (`system_page.yml:116`, page) |
| `cv_audit_chain_verified_state` (`cv_audit_chain_verified`) | `api/audit_verify.py:140-147` | `observability/audit_query_metrics.py:52-71`; `app.py:2027` | none reads it (#2465, which the counter makes redundant) |
| `audit_chain_verification_failures_total` | the scheduled path, via `api/audit_verify_runner.py:150` | the job, wired at `app.py:2167-2174` (#3872) | `AuditChainVerificationFailed` (`system_page.yml:55`) |
| `cv_audit_verify_*` | the verify job | exported | `AuditVerifyNotPassing` (`system_page.yml:69`) |

- Break-glass: `AuthBreakGlassUsed` (`system_page.yml:145`), `AuthBreakGlassAttempted` (`:165`)
  and `AuthBreakGlassStateReadFailing` (`system_ticket.yml:284`).
- Residuals: tickets are muted in quiet hours (#2621); a pre-audit refusal is invisible;
  `AuthBreakGlassAttempted` needs 7 days of history; Alertmanager delivery has never been drilled
  (`obs` is not in the `core` profile); `AuthzDeniedSpike` has no promtool case, and only the
  Python test checks that it reads `authz_denied_total` (#2746).

## 2. Findings triage

Dates are when the item was raised, then the due date the 2026-10-23 re-examination proposes,
which the owner still has to confirm on #2701 item 20 (comment 6364889494). An accepted risk needs a
dated Owner signature: F-2 rests on #2161's record of 2026-10-10, with no Owner comment found (its
handling is below), and F-4 and F-8 were accepted on 2026-10-22 under the #2701 delegation, which
the owner is to confirm on that item. No other open item is accepted.

The white-box review (an Opus agent) could not verify the operator's A2 to A13 numbering, and it
audited E09-Q03's findings only as far as FU-1, FU-2 and #2291. The Owner column for M1 to L4 and
the SR-ids row is the editor's proposal, and so is F-8's entry in §5.

<!-- prettier-ignore -->
| Id | Source | Item | STRIDE | Severity | Owner | Tracking | Raised / due | Status |
|---|---|---|---|---|---|---|---|---|
| F-1 | E09-X02 | No SR-041 double-submit CSRF token; relies on SameSite=Strict + Origin allow-list + bearer header | Tampering | Medium | Architect | #2090 | 2026-10-09 | **Fixed** by #2238 |
| F-2 | E09-X02 | Access tokens not bound to IP/UA; theft detected only on refresh reuse (repro: abuse case AC-SES-06 in `docs/security/abuse-cases/e09-auth.md`) | Spoofing | Low–Medium | Architect + Owner | #2145; #2161 | 2026-10-09 / review 2027-01-22 | **Accepted design decision** per #2161's record (2026-10-10); no Owner comment found; owner to confirm, with the review date, on #2701 item 20 (comment 6364889494). SR-012 stores IP/UA but does not bind; no change. Residual bearer-theft window bounded by the 12 min access TTL and refresh-reuse detection |
| F-3 | E09-X02 | Two invite refusal paths returned 500 with no audit row (unregistered actions) | Repudiation | Medium | Backend | #2316 | 2026-10-16 | **Fixed** by #2316 |
| F-4 | E09-X02 | A WS `auth` frame replayed on a second socket is accepted while the session is live (AC-WS-02, U13) | Spoofing | Low–Medium | Architect + Owner | #4202 (hardening) | 2026-10-16 / review 2027-01-22 | **Accepted** 2026-10-22 under the #2701 delegation, inside F-2's envelope; hardening in #4202; owner to confirm on #2701 item 20 (comment 6364889494) |
| F-5 | E09-X02 | SR-013 rotation missing on role change and step-up | Spoofing | Medium | E09 epic owner | #2101 | 2026-10-16 | Same as R-1 |
| F-6 | E09-X02 | No scheduled audit-chain verifier | Repudiation | Medium | Security | #2111 | 2026-10-16 | Same as R-5 |
| F-7 | E09-X02 | Invites could carry `manager` | Elevation of privilege | Low | Architect + Owner | #2109 | 2026-10-16 | Same as R-3 |
| F-8 | E09-X02 | Build metadata (the git sha) served before authentication (U26) | Information disclosure | Low | Architect + Owner | #4236, #4222, #4206 | 2026-10-16 / review 2027-01-22 | WS half **fixed** by #4236; the probes in #4222 (open; #4221 closed); the metrics endpoint in #4206. The sha after authentication is **accepted**, review 2027-01-22; owner to confirm on #2701 item 20 (comment 6364889494) |
| O-1..O-4 | E09-X02 | Defended attacks whose defence was partly invisible | Repudiation | Low | — | #2319 | 2026-10-16 | **Closed** by #2319; O-2's alert rules are #2746 (open) |
| A-1 | #2083 | `audit:read` grants misaligned with 04 §7.2 / SR-067 | Information disclosure | High (P0) | Security | #2083 → PR #2095 | 2026-10-08 | Fixed (merged) |
| X3-1 | E09-X03 | ZAP authenticated scan needs CI fixture secrets | — (gate coverage) | Medium | Owner | #1778 item D | 2026-10-04 / 2026-11-26 | Open. The weekly authenticated ZAP runs 38239151651 (2026-10-12) and 39226251666 (2026-10-19) failed at "Check fixture credentials present", and PR runs skip |
| X3-2 | E09-X03 | Git-history gitleaks scan and ZAP end-to-end not run locally | — (gate coverage) | Low | DevSecOps | `auth-security-gates.md` status notes | 2026-10-09 / 2026-11-26 | Open; CI run evidence needed |
| X3-3 | E09-X03 | Two dated `nosem` suppressions on 501 stubs in `api/auth.py:401,422` | Repudiation | Low | Security | in-file `review=2026-12-31` | due 2026-12-31 | **Resolved**: no `nosem` is left in `api/auth.py`. `docs/security/auth-security-gates.md:57-58` still cites the two |
| FU-1 | E09-Q03 | Rules-manager layer-2 grant check not tested in isolation | Elevation of privilege | Medium | Backend | #2094 | 2026-10-09 / 2026-11-26 | Open |
| FU-2 | E09-Q03 | `rules_actor` uses an inline role compare in place of `PrincipalSnapshot.is_owner` | Elevation of privilege | Low | Backend | #2096 | 2026-10-09 | **Fixed** by #2164 |
| FU-3 | E09-Q05 | Argon2 on-host cost (≥100 ms) not measurable by the k6 profile | Denial of service | Low | Backend | #2097 | 2026-10-09 / 2027-02-04 | Open |
| R-1 | this review | SR-013 rotation missing on step-up and role change (role change only refreshes permissions) | Spoofing | Medium | E09 epic owner | #2101 (scope extended to step-up rotation) | 2026-10-09 / 2026-11-26 | Open |
| R-2 | this review | SR-024 12-hour trading-capability freshness not enforced on order paths | Elevation of privilege | Medium | E09 / OMS owner | #2108 | 2026-10-09 / 2027-02-04 | Open. It holds by construction (§1); a pin or an explicit check closes it |
| R-3 | this review | SR-027: invites can carry `manager` directly (no Viewer-first elevation) | Elevation of privilege | Low | Architect + Owner | #2109; Owner item AC on #1778 | 2026-10-09 | **Fixed** by #2124 |
| R-4 | this review | SR-028: `PUT /auth/password` not implemented, so no other-session revocation on change | Spoofing | Medium | E09 epic owner | #2110 (route); #2099 (test) | 2026-10-09 / 2026-11-26 | Open |
| R-5 | this review | No scheduled nightly audit-chain verifier; only on-demand `verify()` | Repudiation | Medium | Security | #2111; E43-T10 (#1238) verifies | 2026-10-09 | **Fixed** by #3017, #3059, #3872 |
| R-6 | this review | SR-023 break-glass CLI missing | Denial of service (lockout) | High | Owner | E09-S11 (#2119), from Owner item AB on #1778 | 2026-10-09 | **Fixed** under #2119 by #2655, #2647, #2682, #2782, #2867, #3886 (audit volume: #3290). The drill is §3 |
| R-7 | this review | SR-029 disable cascade missing | Elevation of privilege | High | Accounts/admin | E42-T04 (#965) | 2026-10-09 | **Fixed** under #965 by #3062, #3096, #3135, #3414, #3440, with the 4403 close by #2581. The drill is §4 |
| D-1 | this review | SR-022 says Argon2id for recovery codes; code uses keyed HMAC-SHA256 (≈138-bit codes) | — | Info | Security + Owner | Owner item AD on #1778 | 2026-10-09 | **Decided** (#1778 AD, `issuecomment-6083128397`): keep the keyed HMAC; SR-022 amended by #2122; the key's move under the KEK is #2152 (M3) |
| D-2 | this review | SR-025 says password + TOTP for step-up; code requires TOTP only | Spoofing | Low | Architect + Owner | Owner item AE on #1778 | 2026-10-09 | **Decided** (AE): password plus TOTP, shipped in #2154 |
| M1 | this review | Lockout as a denial of service: 5 failures from any address lock the account for a fixed 15 minutes while the per-IP throttle allows 20 per 60 s; nothing unlocks it; `AuthLockouts` is a ticket with no `keep_firing_for`, muted 22:00 to 07:00 UTC (`infra/alertmanager/alertmanager.yml:39-45`); and a burst of exactly five writes only `auth.login_failed`, no `auth.account_locked` row (`tests/security/auth/test_lockout_audit_route.py:3-6`), against C-2.9. One mesh peer that knows the Owner's username locks the account with 5 requests and keeps it locked with one per 15-minute window: the counter resets only on a successful login (`storage/repositories/users_sqlalchemy.py:80-91`), so the first failure after a lock expires locks it again (`auth/login_service.py:210-213`). SR-016 says 10 failures; the code locks at 5 | Denial of service | Medium | Security | #1233 (backoff, a counter reset on expiry, the lock record, the unlock decision, 5 against 10; scope extended by comment 6367778083); #2621 (quiet hours) | 2026-10-23 / #2621 2026-11-26; #1233 2027-02-25 | Open. The Owner-unlock clause goes into #1233, or SR-016 is amended (an owner item on #2701). Kill-switch engage needs no code (`api/step_up.py:551-558`), but needs a live session |
| M2 | E09-Q03 | SR-051: `GET /rules` filters after fetching: `list_rules` calls `self._s.all()`, then filters with `_visible` (`rules/manager.py:592-603`). Any future paging or limit before `_visible`, or a bug in it, leaks other managers' rules | Information disclosure | Medium | Backend | #2291 (P1, `sla-breached`) | 2026-10-23 / 2026-11-05 | Open; missing from this table until 2026-10-23 |
| M3 | this review | SR-022 key custody: the recovery-code key is the environment setting, not KEK-wrapped and user-bound (§1) | Spoofing | Medium | Security | #2152 | 2026-10-23 / 2027-02-25 | Open; `live` needs it, since ADR-0009 Amendment 4 refuses environment keys there |
| M4 | this review | U20, no tail-truncation anchor: a superuser who deletes the newest rows leaves a chain that verifies (§1.1). The default checkpoint path is relative (`settings.py:451`), which matters when #1238 wires the job | Repudiation | Medium | Security | #1238; E42's AD-F14 | 2026-10-23 / 2027-02-04 | Open; accepted under AD-F14 until #1238 |
| L1 | this review | SR-014 login oracle: six requests per candidate name reveal whether it exists, and lock it (§1) | Information disclosure | Low | Security | #1233 (scope extended by comment 6367778083) | 2026-10-23 / 2027-02-25 | Open. Fix: answer a lock exactly like a wrong password and keep the record and the metric, or Owner-accept it and change the contract |
| L2 | this review | SR-010 anonymous routes: `/docs`, `/redoc`, `/openapi.json`, `/metrics`, `/readyz` and `/health/*` answer every mesh peer (§1) | Information disclosure | Low | Owner | #4206 (`/metrics`; the docs routes proposed for it), #4222 (`/readyz` and `/health/*`) | 2026-10-23 / 2027-01-22 | Open. Fix: `docs_url=None` and `redoc_url=None`, and the published contract behind authentication |
| L3 | this review | U30 permissive default: `decide()` and `enforce()` default to `scope=Scope.NONE` (`auth/scopes.py:162`, `:269`), with no required argument, no `no-implicit-authorize-default` rule and no `test_authorize_requires_explicit_scope_argument`. Every account-scoped call site checked passes `scope=` explicitly: a regression risk, not a current exploit (C-12.4) | Elevation of privilege | Low | Security | #1237 (E43-T09; nearest fit, scope to be added by comment) | 2026-10-23 / 2027-02-25 | Open |
| L4 | this review | U29: no expired-session reap job (the only reaper is the anonymisation one) | Denial of service | Low | Security | #1232 (E43-T03), its scope extended by comment 6367777597 | 2026-10-23 / 2027-02-04 | Open |
| SR-ids | this review | The threat model's provisional SR-024, -052, -053, -054 and -057 collide with registered SRs in 04 §6.3 and §6.4; RSK-020's text, RSK-021's `(SR-024, U12)`, AC-AUTHZ-03 and the abuse-case U23 row (SR-054) cite the colliding ids | — | Info | Security | #2832 | 2026-10-23 / 2026-11-26 | Open |

Rows R-1 to R-7 and D-1/D-2 come from this review on 2026-10-09; M1 to M4, L1 to L4 and the SR-ids
row from its re-examination on 2026-10-23, which also closed the rows marked fixed. Owner
decisions are on #1778
([items AB–AE](https://github.com/CandleViewer/CandleViewer/issues/1778#issuecomment-6079001525)):
AB, the R-6 break-glass CLI, became E09-S11 (#2119); AC is R-3; AD is D-1; AE is D-2. The sign-off
is item U. E09-Q06 (#297) is open: its findings join this table when it lands. L5, two
corrections to the runbook text that #4254 merged as `e78556cf`, is applied in
`docs/ops/runbooks/auth-rbac.md` (§3 and its Execution record).

**F-2's acceptance.** No comment among #1778's 141 names F-2: the Owner's ★-defaults decision of
2026-10-09 (`issuecomment-6083128397`) covers items N to AE only. The acceptance rests on #2161's
record (merged 2026-10-10; #2145 closed). The owner is asked to confirm F-2, its signature and its
date in one comment: #2701 item 20 (comment 6364889494). The proposed review date is 2027-01-22,
F-4's, which sits inside F-2's envelope; it comes before R4 (2027-02-25) and the GA cut. F-2 has
no entry in `security/accepted-risks.yaml` and gets none: that file is for scanner findings only,
and its `tool` must be one of the scanners (`security/accepted-risks.yaml:22-29`;
`docs/plan/04-security-program.md:1906`, §16.2).

## 3. Break-glass drill (SR-023)

Run cold on 2026-10-23 (#2494), on a dev compose stack, not on staging.

- **Setup.** Compose project `cvdrill`, the `core` profile on the real backend, `testnet`, built
  from `main` `b8ccf5a3`, with a dev-only KEK mounted at `/run/secrets/cv_kek`. The first boot
  enrolled the KEK check value (audit row 16).
- **Operator.** Claude (Sonnet 5.5), not the runbook's author, working from runbook §3 alone and
  keeping their own log, with the Owner's TOTP device treated as lost and no recovery code at hand.
- **Time.** From the handoff (08:27:55Z) to cv-api restarted (08:35:36Z): **7 min 41 s**, healthy
  at 8 min 9 s; about 5 min 47 s without the terminal detour (A1). Step 6, the Owner's
  re-enrolment, was not drilled.
- **Ambiguities.** #4254 (`e78556cf`, merged 2026-10-23) corrects these 12 in runbook §3; the
  operator's A2 to A13 numbering could not be verified (§2):

<!-- prettier-ignore -->
| Ambiguity | Corrected in |
|---|---|
| A1, the terminal must exist on the caller's side | Preconditions |
| Where to record the incident | step 1 |
| What "down" looks like | step 2 |
| Compose's Swarm-only secret warnings | Procedure |
| How to tell cv-api is back | step 5 |
| No query recipe for the post-reset reads | step 4 |
| The run id | step 4 |
| The redacted exit-4 cause | step 4 |
| A7, the KEK variables unset | Preconditions and "Drilling the refusals" |
| A9, who sees the notice | step 7 |
| Each reset raises its own event (N is an id) | step 7 |
| The real backend and the stack's needs | Procedure |

- **Refusals.** Exit 9 with an absent KEK handle (run `367e73ee`, rows 180 and 182) and exit 4
  with a relative audit path (run `78fa320e`, rows 184 and 186). Each wrote its attempt and refusal
  records. A7 is not a CLI defect: with every `CV_KEK_*` variable unset, the source defaults to
  `handle` and the handle to `/run/secrets/cv_kek`, where the stack mounted the KEK
  (`settings.py:523-526`, `secrets/_source.py:26-27`, `:48-70`), and the proof read that KEK and
  matched its enrolled check value (`secrets/service.py:533-552`). An absent handle fails as
  `kek_unavailable` (`secrets/_kek.py:245-247`), as the absent-handle run did, and so does a
  missing source (`:293-295`). A7's side effect was a second reset (run `72860d81`, rows 176 and
  178, event 2).
- **Records.** The 9 runs (2 resets, 7 refusals) left 18 rows (ids 160-166, 172-186, 192-202).
  The reset itself is rows 164 and 166 (1 method and 4 sessions revoked). Two `break_glass_used`
  events (1 and 2) are unresolved: there is no resolve route yet (#2710 item 2).
- **Automated counterparts.** `tests/unit/admin/test_breakglass_flow.py:256` (the refusal without
  the host filesystem or the KEK, and its records);
  `tests/unit/auth/test_break_glass_notice.py::test_notice_after_auth_ok_while_unresolved` (the
  server's notice, in process).

**AC3 (the CLI without its preconditions): PASS.** No run went ahead without the host filesystem
or the KEK, and every refusal wrote its attempt and refusal records. One deviation from AC3's
letter stands, as QA's third round recorded it: with no usable journal and Postgres unreachable,
a run refuses before any check and leaves no record, so it does not page either. That is #2119's
S3 criterion, "a documented pre-audit refusal", and a residual of the threat model (§3.6.1).

**AC2 (break-glass works for someone who has never run it): FAIL, pending.** The reset and its
audit records are shown, but:

1. the notice was never observed (A9);
2. the UI half and its WCAG 2.2 AA check are #306 (E10-S04);
3. nobody has re-run the merged runbook text (DoD 2, an owner call on #2701 item 20).

Owner rulings still needed, on #2701 item 20 (comment 6364889494): item U says "human drills" on
staging, and this was an agent on a dev stack (#1778 item A, #2298); the `live` variant (O3) is
also the owner's; and so is DoD 2's re-run.

## 4. Disable-user drill (SR-029)

Run on 2026-10-23 (#2494), on the same stack, through the real API. Each run signed a manager in
(password, then TOTP), opened a WebSocket and subscribed `positions` for `drill-sub`, a private
subscription; then the Owner signed in, stepped up for `users` and sent
`DELETE /users/{id}?acknowledge_unknown_positions=true`.

<!-- prettier-ignore -->
| Run | `DELETE` to `bye` | `DELETE` answer | Server, `users.disable` to `bye` |
|---|---|---|---|
| 1 | 976.5 ms | 204 in 1,415.9 ms | 46 ms |
| b | 391.3 ms | 204 in 576.6 ms | 38 ms |
| c | 629.4 ms | 204 in 992.5 ms | 72 ms |

- Every run passed the checks: close `4403`, no frame after the `bye`, the next REST call `401`,
  `users.disable` with `positions_decision` `leave`, and one `auth.session_revoked` per session.
- SR-029's "immediately", measured: 391.3 to 976.5 ms from the `DELETE` to the client's `bye`, and
  38 to 72 ms from the `users.disable` record (written ahead of the commit) to that `bye`.
- No armed rule was drilled: the seeder has no path for one.
- Automated counterparts: #4254's tests (`e78556cf`) in
  `tests/security/auth/test_disable_user_drill.py`, which drive the same route from the manager's
  side: `test_a_disable_through_the_route_ends_a_private_subscription_with_bye_and_4403`,
  `test_a_disable_through_the_route_reaches_the_socket_within_the_sr029_bound`,
  `test_a_disable_through_the_route_cancels_a_pending_step_up_challenge`,
  `test_a_disabled_managers_token_opens_no_socket` and
  `test_a_second_disable_answers_204_and_writes_no_record`. They replace the in-process
  counterpart this section first recorded (2026-10-09, the primitives only; its close code
  corrected to `4403` on 2026-10-15, #2493).

**AC4 (disabling a user with a live socket): FAIL as written, on one clause.** The sessions end,
the socket gets `bye` and `4403`, and the positions decision is recorded. The rule-engine clause
rests only on `tests/security/auth/test_disable_user_e2e.py:477`. To clear it, re-run the drill
with an armed rule, or the owner accepts that test: #2701 item 20 (comment 6364889494).

What the drill stack lacked is a residual (§5).

## 5. Residual risks

Each carries a review date, proposed on 2026-10-23 for the owner to confirm on #2701 item 20
(comment 6364889494).

1. **Total Owner lockout in `live`** (U10): with no unused recovery code there is no CLI path
   (O3, the owner's: #2701 item 20 (comment 6364889494)). Review 2027-02-25.
2. **The socket-only window of a disabled user** (U45), accepted by the main-orchestrator's
   ruling, Owner sign-off pending on #2701 item 20 (comment 6364889494). Review with UL1-E2,
   2027-02-04.
3. **Bearer-token theft window** (F-2). It is bounded by the 12 min access-token TTL and by
   refresh-reuse detection. Review 2027-01-22, owner to confirm (#2701 item 20
   (comment 6364889494)).
4. **A WS `auth` frame replayed while the session is live** (F-4), accepted 2026-10-22 under the
   #2701 delegation, inside F-2's envelope; binding the frame is #4202. Review 2027-01-22, owner to
   confirm on #2701 item 20 (comment 6364889494).
5. **Build metadata after authentication** (F-8): the sha reaches every authenticated role,
   accepted 2026-10-22 under the #2701 delegation. Review 2027-01-22, owner to confirm on #2701
   item 20 (comment 6364889494).
6. **Session fixation surface on privilege change** (R-1, #2101). It is mitigated by short token
   TTLs and server-side permission refresh, but the SR-013 rotation set is incomplete. Review
   2026-11-26.
7. **No tail-truncation anchor** (M4): deleting the newest audit rows leaves a chain that
   verifies, until #1238 wires the checkpoint job. Review 2027-02-04.
8. **Break-glass blind spots**: a pre-audit refusal leaves no record and does not page,
   `AuthBreakGlassAttempted` needs 7 days of history, and Alertmanager delivery has never been
   drilled. Review 2027-02-25.
9. **Quiet-hours loss** (#2621): tickets are muted 22:00 to 07:00 UTC, so a lock inside those
   hours is never sent. Review 2026-11-26.
10. **Stack gaps**: what the drill stack lacked is carried on #4249 (comment 6361838859). Review
    with #4249.
11. **Host-level compromise defeats break-glass** (the threat model's §3.6.1): its blast radius is
    a host compromise's, not an auth bypass alone. Accepted 2026-09-29, Owner sign-off pending on
    #2701 item 20 (comment 6364889494). Review 2027-02-25, proposed.

The CSRF residual of 2026-10-09 is gone: #2238 fixed F-1.

## 6. Pen-test scoping note for E43

Controls that most warrant external testing before R4 live enablement, in priority order:

1. The deny-by-default route registry and the `x-rbac` → `decide()` second layer (SR-017,
   SR-050, SR-051), using cross-account identifiers in body, path and query, and WS topic options;
   and `decide()`'s permissive default (U30, L3).
2. Session lifecycle: refresh rotation and family revocation, idle and absolute expiry, the
   enrolment-only window (RR-15), WS revocation on logout or disable, the disable cascade and the
   U45 window, and the bearer-only state-change model (F-1, fixed by #2238; F-2).
3. Step-up scope and grace window across action classes and sessions (SR-025).
4. The mesh-only middleware and binding self-check on the deployed host (US-ONB-008, RSK-022), and
   the routes left anonymous to every mesh peer (L2).
5. Audit append-only guarantees under the application role, and chain verification: the scheduled
   verifier and the missing tail anchor (M4, with #1238, E43-T10).
6. The break-glass CLI: precondition enforcement (host filesystem + KEK), its KEK-default semantics
   (unset `CV_KEK_*` settings fall back to the `handle` source at `/run/secrets/cv_kek`), attempt
   recording and the pre-audit refusal.
7. Login throttling and lockout as a denial-of-service vector (U27, U28, M1) and the login oracle
   (L1), coordinated with E43-T04 (#1233).

Out of scope for this note: the key vault (E27) and the order path beyond its `authorize()`
calls.

## 7. Sign-off

A draft: the reviewer completes it at READY.

- Reviewer: the delivery orchestrator's Fable lens at READY, under #1778 items U and AA.
- Date: filled at READY.
- Open accepted risks (no Owner signature recorded unless stated):
  - F-2: #2161's record of 2026-10-10, with no Owner comment found; its signature and its review
    date (2027-01-22, proposed) are pending on #2701 item 20 (comment 6364889494).
  - F-4 and F-8: accepted 2026-10-22 under the #2701 delegation; review 2027-01-22; owner to
    confirm on #2701 item 20 (comment 6364889494).
  - U45: the main-orchestrator's ruling; review 2027-02-04; Owner sign-off pending on #2701 item 20
    (comment 6364889494).
  - The break-glass residual of the threat model's §3.6.1: review 2027-02-25, proposed; Owner
    sign-off pending on #2701 item 20 (comment 6364889494).
- Owner rulings still needed, all on #2701 item 20 (comment 6364889494): item U, F-2's signature
  and date, O3, AC4's armed-rule clause, DoD 2's re-run, the proposed due dates, U45, the §3.6.1
  residual, and F-4 and F-8.
- Gate statement: "R0 area-6 is met only when §3 and §4 clear the conditions above."

The conditional sign-offs of 2026-10-09 on #300 (the Owner's, from #1778 item U, and the Security
engineer's, owner-delegated) both withheld the gate. Until §3 and §4 clear their conditions, this
record holds no signature and the gate is not met.
