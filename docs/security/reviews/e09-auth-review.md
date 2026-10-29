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
  ticket describes; the E09 gate rests on the owner's rulings and the delegated sign-off (§7).
- Public record: open findings carry only id, severity, area, status and tracker (`SECURITY.md` §1).

> **Status: re-examined 2026-10-23; the owner ruled on 2026-10-29 (§7).** The review found
> Critical: none; High: none new. #4254, which corrects the break-glass runbook, merged as
> `e78556cf` (2026-10-23), and nobody has re-run the merged text (DoD 2). The break-glass notice
> was never observed, and its UI half and WCAG check are #306. No armed rule was drilled for AC4.
> #2701 ledger addendum A, rows A7–A13 (comment 6499102601), rules these and every other owner
> call this record put on #2701 item 20 (comment 6364889494). The R0 area-6 gate is met by those
> rulings plus this record's delegated sign-off (§7).

Verdict key (AC1): **PASS** (the control exists in code, and a named test or its construction
proves it) · **FAIL-T** (a gap, with its owning ticket named) · **ACCEPTED** (an accepted risk with
a dated Owner signature; no control needs it). SR-023 and SR-029 pass in code; their drills are §3
and §4.

## 1. Control-by-control verdicts (SR-010..SR-029, SR-050, SR-051)

<!-- prettier-ignore -->
| Control | Implementation (file:line) | Proving test | Verdict |
|---|---|---|---|
| SR-010 local auth, no anonymous routes | details held in the private repository advisory (maintainers) | — | **FAIL-T** #4206 (L2) |
| SR-011 Argon2id, params stored, rehash on login | `auth/hashing.py:34` (m=65536, t=3, p=4; argon2-cffi's 16-byte salt), `:126`; rehash at `auth/login_service.py:148-152` | `tests/unit/auth/test_hashing.py::test_hasher_needs_rehash_true_for_stale_params`; AC-CRED-01 | PASS. The ≥100 ms on-host cost is FU-3 (#2097) |
| SR-012 opaque tokens, cookie flags | `auth/session_service.py:417` (256-bit), `:331`; cookie flags at `api/sessions.py:423-432` (path `/api/v1/auth`, stricter than `/`); the SR-041 token at `api/csrf.py:194` (#2238) | AC-CSRF-03 (`tests/security/auth/test_csrf_cookie_abuse.py`) | PASS. F-2 (no IP/UA binding) is accepted (§2) |
| SR-013 rotate on login, TOTP, step-up, password change, role change | details held in the private repository advisory (maintainers) | — | **FAIL-T** #2101 (R-1), #2110 (R-4) |
| SR-014 uniform login failures + dummy verify | details held in the private repository advisory (maintainers) | — | **FAIL-T** #1233 (L1) |
| SR-015 per-account + per-IP throttling | details held in the private repository advisory (maintainers) | — | **FAIL-T** #1233 (M1) |
| SR-016 lockout + owner alert | details held in the private repository advisory (maintainers) | — | **FAIL-T** #2621, #1233 (M1) |
| SR-017 deny-by-default start-up | `api/deny_by_default.py:71-82` (build), `:85-96` (runtime `403`, WS `1008`) | `tests/unit/api/test_deny_by_default.py:19`, `:30` | PASS |
| SR-018 route × role matrix | `services/api/tests/contract/rbac/matrix.yaml` | `services/api/tests/contract/rbac/test_route_matrix.py`, `test_scope_and_ws.py` (E09-Q03) | PASS |
| SR-019 list and revoke own sessions | `api/sessions.py:1487`, `:1625`; `api/users.py:1294`, `:1311` | `tests/unit/api/test_sessions_router.py`; AC-CSRF-05 | PASS |
| SR-020 mandatory TOTP | `api/auth.py:642`; the enrolment-only session (`auth/login_service.py:157-161`, `api/enrolment_guard.py:79`) | `tests/unit/auth/test_mfa_service.py` | PASS |
| SR-021 ±1 skew + replay cache | `auth/totp.py:24`; `auth/mfa_service.py:138-143` | `tests/unit/auth/test_totp.py::test_verify_code_rejects_beyond_skew_window`; AC-MFA-01 | PASS |
| SR-022 recovery codes | details held in the private repository advisory (maintainers) | — | **FAIL-T** #2152 (M3) |
| SR-023 break-glass CLI | `breakglass.py`; `admin/breakglass.py:5-11`, `:395-411`, `:464-502`; `secrets/service.py:688-707`; the notice at `ws/gateway.py:1682-1688` and `app.py:1699` | `tests/unit/admin/test_breakglass_flow.py:256` (`test_break_glass_requires_host_filesystem_and_kek_present`); the drill (§3) | PASS in code (#2119). The drill passes AC3, and AC2 is met for R0 by the owner's rulings (§3) |
| SR-024 timeouts + 12 h trading freshness | 12 h absolute at `auth/session_service.py:87`, carried on refresh at `:576`; `extend` only re-stamps idle (`api/sessions.py:1321-1343`) | `tests/unit/auth/test_session_service.py` | PASS, by construction. #2108 (R-2) open. |
| SR-025 step-up, 5 min, scoped | `auth/step_up.py:72`, `:83`, `:98`, `:457-483` (password and TOTP, #2154), `:658`; the view-as start is handler-gated (`api/step_up.py`) | `tests/unit/auth/test_step_up.py`; AC-STEP-01..04 | PASS. D-2 shipped in #2154. U35's binding is still #2304 |
| SR-026 no target-user on self-service | `security/semgrep/auth/no-target-user-on-self-service.yml`; `undeclared_query_refusal` at `api/auth.py:562` | rule fixtures under `security/semgrep/auth/fixtures/` | PASS |
| SR-027 invite creates least-privilege user | `auth/models.py:376-381` (#2124) | `tests/unit/api/test_invites_router.py::test_create_rejects_owner_role_and_duplicate`; AC-INV-01..04 | PASS. R-3 is fixed (#2124) |
| SR-028 password policy + other-session revoke | details held in the private repository advisory (maintainers) | — | **FAIL-T** #2110, #2099 (R-4) |
| SR-029 disable user → sessions, sockets, pending actions | `api/users.py:790`; `admin/user_disable.py:1-30`, `:75`, `:293` (E42-T04, #965) | `tests/security/auth/test_disable_user_e2e.py:427`, `:477`, `:483`; `tests/security/auth/test_disable_user_drill.py` (#4254); the drill (§4) | PASS in code. The drill meets AC4, its rule-engine clause through an accepted test (§4) |
| SR-050 two-layer authZ | details held in the private repository advisory (maintainers) | — | **FAIL-T** #2094 (FU-1), #1237 (L3; scope: comment 6369101975) |
| SR-051 server-side account resolution | details held in the private repository advisory (maintainers) | — | **FAIL-T** #2291 (M2) |

### 1.1 Other items in the brief

<!-- prettier-ignore -->
| Item | Implementation | Proving test | Verdict |
|---|---|---|---|
| Audit chain trigger + revoked UPDATE/DELETE | `migrations/versions/0003_audit_log.py:150-154` (chain, append-only, no-truncate triggers) | `services/api/tests/integration/audit/test_audit_repository.py::test_app_role_cannot_update_or_delete`, `::test_truncate_refused_even_for_owner` (integration; not run in this review) | PASS (by inspection + integration test) |
| audit:read grants (SR-067) | `migrations/versions/0016_audit_read_grants.py` | `services/api/tests/integration/auth/test_0016_audit_read_grants_migration.py` | PASS. Fixed in #2083 / PR #2095 |
| Scheduled chain verifier + `cv_audit_chain_verified` | The job runs the verifier at start-up and nightly (#3017), from `create_app` since #3872 (`app.py:2167-2174`); a failure counts on `audit_chain_verification_failures_total` (`api/audit_verify_runner.py:150`). The verifier cross-checks `audit_checkpoints` (`audit/query.py:484-489`, `:564-569`) | `test_trigger_chain_genesis_and_python_verifier_agree`; `services/api/tests/integration/audit/test_audit_verify_runner_pg.py::test_scheduled_run_finds_a_row_altered_behind_the_chain_and_the_next_run_still_happens` | PASS: R-5 fixed |
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
- Residuals: #2621, #2746.

## 2. Findings triage

Dates are when the item was raised, then the due date the 2026-10-23 re-examination proposes,
which #2701 ledger addendum A row A12 accepts as proposed (§7). An accepted risk needs a dated
Owner signature: F-2 rests on #2161's record of 2026-10-10, which row A8 signs (its
handling is below), and F-4 and F-8 were accepted on 2026-10-22 under the #2701 delegation, which
row A8 confirms. One other open item is accepted: M4, under E42's AD-F14 until #1238 (§7).

The white-box review (an Opus agent) could not verify the operator's A2 to A13 numbering, and it
audited E09-Q03's findings only as far as FU-1, FU-2 and #2291. The Owner column for M1 to L4 and
the SR-ids row is proposed by #4288, which wrote this refresh, and so is F-8's entry in §5.

<!-- prettier-ignore -->
| Id | Source | Item | STRIDE | Severity | Owner | Tracking | Raised / due | Status |
|---|---|---|---|---|---|---|---|---|
| F-1 | E09-X02 | No SR-041 double-submit CSRF token; relies on SameSite=Strict + Origin allow-list + bearer header | Tampering | Medium | Architect | #2090 | 2026-10-09 | **Fixed** by #2238 |
| F-2 | E09-X02 | Access tokens not bound to IP/UA; theft detected only on refresh reuse (repro: abuse case AC-SES-06 in `docs/security/abuse-cases/e09-auth.md`) | Spoofing | Low–Medium | Architect + Owner | #2145; #2161 | 2026-10-09 / review 2027-01-22 | **Accepted design decision** per #2161's record (2026-10-10), signed with its review date by #2701 ledger addendum A row A8 (§7). SR-012 stores IP/UA but does not bind; no change. Residual bearer-theft window bounded by the 12 min access TTL and refresh-reuse detection |
| F-3 | E09-X02 | Two invite refusal paths returned 500 with no audit row (unregistered actions) | Repudiation | Medium | Backend | #2316 | 2026-10-16 | **Fixed** by #2316 |
| F-4 | E09-X02 | A WS `auth` frame replayed on a second socket is accepted while the session is live (AC-WS-02, U13) | Spoofing | Low–Medium | Architect + Owner | #4202 (hardening) | 2026-10-16 / review 2027-01-22 | **Accepted** 2026-10-22 under the #2701 delegation, inside F-2's envelope; hardening in #4202; confirmed by row A8 (§7) |
| F-5 | E09-X02 | SR-013 (R-1) | Spoofing | Medium | E09 epic owner | #2101 | 2026-10-16 | Same as R-1 |
| F-6 | E09-X02 | No scheduled audit-chain verifier | Repudiation | Medium | Security | #2111 | 2026-10-16 | Same as R-5 |
| F-7 | E09-X02 | Invites could carry `manager` | Elevation of privilege | Low | Architect + Owner | #2109 | 2026-10-16 | Same as R-3 |
| F-8 | E09-X02 | Build metadata (the git sha) served before authentication (U26) | Information disclosure | Low | Architect + Owner | #4236, #4222, #4206 | 2026-10-16 / review 2027-01-22 | WS half **fixed** by #4236; the probes **fixed** by #4222 (after #4221); the remainder is #4206. The sha after authentication is **accepted**, review 2027-01-22; confirmed by row A8 (§7) |
| O-1..O-4 | E09-X02 | Defended attacks whose defence was partly invisible | Repudiation | Low | — | #2319 | 2026-10-16 | **Closed** by #2319; O-2's alert rules are #2746 (open) |
| A-1 | #2083 | `audit:read` grants misaligned with 04 §7.2 / SR-067 | Information disclosure | High (P0) | Security | #2083 → PR #2095 | 2026-10-08 | Fixed (merged) |
| X3-1 | E09-X03 | ZAP authenticated scan needs CI fixture secrets | — (gate coverage) | Medium | Owner | #1778 item D | 2026-10-04 / 2026-11-26 | Open. The weekly authenticated ZAP runs 38239151651 (2026-10-12) and 39226251666 (2026-10-19) failed at "Check fixture credentials present", and PR runs skip |
| X3-2 | E09-X03 | Git-history gitleaks scan and ZAP end-to-end not run locally | — (gate coverage) | Low | DevSecOps | `auth-security-gates.md` status notes | 2026-10-09 / 2026-11-26 | Open; CI run evidence needed |
| X3-3 | E09-X03 | Two dated `nosem` suppressions on 501 stubs in `api/auth.py:401,422` | Repudiation | Low | Security | in-file `review=2026-12-31` | due 2026-12-31 | **Resolved**: no `nosem` is left in `api/auth.py`. `docs/security/auth-security-gates.md:57-58` still cites the two |
| FU-1 | E09-Q03 | Rules-manager layer-2 grant check not tested in isolation | Elevation of privilege | Medium | Backend | #2094 | 2026-10-09 / 2026-11-26 | Open |
| FU-2 | E09-Q03 | `rules_actor` uses an inline role compare in place of `PrincipalSnapshot.is_owner` | Elevation of privilege | Low | Backend | #2096 | 2026-10-09 | **Fixed** by #2164 |
| FU-3 | E09-Q05 | Argon2 on-host cost (≥100 ms) not measurable by the k6 profile | Denial of service | Low | Backend | #2097 | 2026-10-09 / 2027-02-04 | Open |
| R-1 | this review | SR-013 session rotation | Spoofing | Medium | E09 epic owner | #2101 | 2026-10-09 / 2026-11-26 | Open |
| R-2 | this review | SR-024 12-hour trading-capability freshness not enforced on order paths | Elevation of privilege | Medium | E09 / OMS owner | #2108 | 2026-10-09 / 2027-02-04 | Open. It holds by construction (§1) |
| R-3 | this review | SR-027: invites can carry `manager` directly (no Viewer-first elevation) | Elevation of privilege | Low | Architect + Owner | #2109; Owner item AC on #1778 | 2026-10-09 | **Fixed** by #2124 |
| R-4 | this review | SR-028 password change | Spoofing | Medium | E09 epic owner | #2110 (route); #2099 (test) | 2026-10-09 / 2026-11-26 | Open |
| R-5 | this review | No scheduled nightly audit-chain verifier; only on-demand `verify()` | Repudiation | Medium | Security | #2111; E43-T10 (#1238) verifies | 2026-10-09 | **Fixed** by #3017, #3059, #3872 |
| R-6 | this review | SR-023 break-glass CLI missing | Denial of service (lockout) | High | Owner | E09-S11 (#2119), from Owner item AB on #1778 | 2026-10-09 | **Fixed** under #2119 by #2655, #2647, #2682, #2782, #2867, #3886 (audit volume: #3290). The drill is §3 |
| R-7 | this review | SR-029 disable cascade missing | Elevation of privilege | High | Accounts/admin | E42-T04 (#965) | 2026-10-09 | **Fixed** under #965 by #3062, #3096, #3135, #3414, #3440, with the 4403 close by #2581. The drill is §4 |
| D-1 | this review | SR-022 says Argon2id for recovery codes; code uses keyed HMAC-SHA256 (≈138-bit codes) | — | Info | Security + Owner | Owner item AD on #1778 | 2026-10-09 | **Decided** (#1778 AD, `issuecomment-6083128397`): keep the keyed HMAC; SR-022 amended by #2122; the follow-up is #2152 (M3) |
| D-2 | this review | SR-025 says password + TOTP for step-up; code requires TOTP only | Spoofing | Low | Architect + Owner | Owner item AE on #1778 | 2026-10-09 | **Decided** (AE): password plus TOTP, shipped in #2154 |
| M1 | this review | SR-016: details held in the private repository advisory (maintainers) | Denial of service | Medium | Security | #1233 (comment 6367778083); #2621 | 2026-10-23 / #2621 2026-11-26; #1233 2027-02-25 | Open |
| M2 | E09-Q03 | SR-051: details held in the private repository advisory (maintainers) | Information disclosure | Medium | Backend | #2291 (P1, `sla-breached`) | 2026-10-23 / 2026-11-05 | Open |
| M3 | this review | SR-022: details held in the private repository advisory (maintainers) | Spoofing | Medium | Security | #2152 | 2026-10-23 / 2027-02-25 | Open |
| M4 | this review | U20: details held in the private repository advisory (maintainers) | Repudiation | Medium | Security | #1238; E42's AD-F14 | 2026-10-23 / 2027-02-04 | Open; accepted under AD-F14 until #1238 |
| L1 | this review | SR-014: details held in the private repository advisory (maintainers) | Information disclosure | Low | Security | #1233 | 2026-10-23 / 2027-02-25 | Open |
| L2 | this review | SR-010: details held in the private repository advisory (maintainers) | Information disclosure | Low | Owner | #4206; #4222 | 2026-10-23 / 2027-01-22 | Open |
| L3 | this review | U30: details held in the private repository advisory (maintainers) | Elevation of privilege | Low | Security | #1237 (E43-T09) | 2026-10-23 / 2027-02-25 | Open |
| L4 | this review | U29: details held in the private repository advisory (maintainers) | Denial of service | Low | Security | #1232 (E43-T03) | 2026-10-23 / 2027-02-04 | Open |
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
record (merged 2026-10-10; #2145 closed), and row A8 signs it (§7). Its review date is 2027-01-22,
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

**AC3 (the CLI without its preconditions): PASS.** One deviation from AC3's letter stands; see
#2119 (S3).

**AC2 (break-glass works for someone who has never run it): met for R0 (§7).** The reset and its
audit records are shown, but:

1. the notice was never observed (A9);
2. the UI half and its WCAG 2.2 AA check are #306 (E10-S04);
3. nobody has re-run the merged runbook text (DoD 2): §7's row A11 accepts the review-based check.

Item U says "human drills" on staging, and this was an agent on a dev stack (#1778 item A): §7's
row A7 accepts it as the R0 evidence, and the human repeat on staging, #2298, is a post-GA
confirmation line, not a gate. The `live` variant (O3) is a dated residual (§7's row A9, §5).

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

**AC4 (disabling a user with a live socket): met (§7).** The sessions end,
the socket gets `bye` and `4403`, and the positions decision is recorded. The rule-engine clause
rests on `tests/security/auth/test_disable_user_e2e.py:477` (`test_rule_disarmed_audited`), which
§7's row A10 accepts as the evidence, with no re-drill.

What the drill stack lacked is a residual (§5).

## 5. Residual risks

Each carries a review date, proposed on 2026-10-23; where a ruling of §7 signs one, it says so.

1. **Total Owner lockout in `live`** (U10): with no unused recovery code there is no CLI path
   (O3: a dated residual, row A9, rehearsed on the GA host before the GA cut). Review 2027-02-25.
2. **The socket-only window of a disabled user** (U45), accepted by the main-orchestrator's
   ruling, confirmed by row A12 (ledger 2 row 30). Review with UL1-E2,
   2027-02-04.
3. **Bearer-token theft window** (F-2). It is bounded by the 12 min access-token TTL and by
   refresh-reuse detection. Accepted by row A8; review 2027-01-22.
4. **A WS `auth` frame replayed while the session is live** (F-4), accepted 2026-10-22 under the
   #2701 delegation, inside F-2's envelope; binding the frame is #4202. Review 2027-01-22,
   confirmed by row A8.
5. **Build metadata after authentication** (F-8): the sha reaches every authenticated role,
   accepted 2026-10-22 under the #2701 delegation. Review 2027-01-22, confirmed by row A8.
6. SR-013 (R-1, #2101). Review 2026-11-26.
7. U20 (M4, #1238). Review 2027-02-04.
8. **Break-glass residuals.** Review 2027-02-25.
9. #2621 (M1). Review 2026-11-26.
10. **Stack gaps**: what the drill stack lacked is carried on #4249 (comment 6361838859). Review
    with #4249.
11. **Host-level compromise defeats break-glass** (the threat model's §3.6.1): its blast radius is
    a host compromise's, not an auth bypass alone. Accepted 2026-09-29, signed by row A12. Review
    2027-02-25.

The CSRF residual of 2026-10-09 is gone: #2238 fixed F-1.

## 6. Pen-test scoping note for E43

Controls that most warrant external testing before R4 live enablement, in priority order:

1. SR-017, SR-050, SR-051 (L3)
2. Session lifecycle: refresh rotation and family revocation, idle and absolute expiry, the
   enrolment-only window (RR-15), WS revocation on logout or disable, the disable cascade and the
   U45 window, and the bearer-only state-change model (F-1, fixed by #2238; F-2).
3. Step-up scope and grace window across action classes and sessions (SR-025).
4. US-ONB-008 (L2)
5. SR-066, SR-063 (M4)
6. The break-glass CLI: precondition enforcement (host filesystem + KEK), its KEK-default semantics
   (unset `CV_KEK_*` settings fall back to the `handle` source at `/run/secrets/cv_kek`), attempt
   recording and the pre-audit refusal.
7. SR-015, SR-016, SR-014 (M1, L1)

Out of scope for this note: the key vault (E27) and the order path beyond its `authorize()`
calls.

## 7. Sign-off: the E09 gate verdict

A draft: the reviewer completes it at READY.

This record is the security gate (E09-X04) of #36, the epic "[E09] Auth, sessions, 2FA & RBAC".
The owner's rulings are #2701 ledger addendum A, rows A7–A13 (comment 6499102601), cited in this
record as "row A7" and so on (§3's A1 to A13 are the operator's ambiguities):

<!-- prettier-ignore -->
| Row | Item | Ruling (2026-10-29) |
|---|---|---|
| A7 | Item U: the drill evidence | The agent-run dev-stack drills (§3, §4) are the R0 evidence; the human repeat on staging, #2298, is a post-GA confirmation line, not a gate |
| A8 | F-2, F-4 and F-8 | F-2 accepted, review 2027-01-22; F-4 and F-8 confirmed as accepted (2026-10-22), review 2027-01-22 |
| A9 | O3, the `live` variant | A dated residual (U10), review 2027-02-25, rehearsed on the GA host before the GA cut: a release-readiness line (E49 / PRR), not an E09 gate |
| A10 | AC4's rule-engine clause | `test_disable_user_e2e.py::test_rule_disarmed_audited` is the evidence; no re-drill |
| A11 | DoD 2: re-running the corrected runbook | The review-based check (#4254's Fable and Sonnet looks and the Opus delta); #2298 re-runs it on a real host |
| A12 | §2's due dates, U45 and the §3.6.1 residual | The due dates accepted as proposed; U45 confirmed (ledger 2 row 30), review 2027-02-04 with UL1-E2; the §3.6.1 residual accepted, review 2027-02-25 |
| A13 | The post-break-glass `system` notice | Its UI half and its WCAG 2.2 AA check are re-homed to #306 as a scope line (render the notice, run the a11y check, observe it once on the dev stack): #306 owns them, and #2494 closed without them |

- Reviewer: the delivery orchestrator's Fable lens at READY, on the head of the PR that adds this
  section: the Security engineer's sign-off under the owner's delegation (#2701 comment 6490317249).
- Date: filled at READY.
- Open accepted risks, each signed by its row above with the review date there: F-2, F-4 and F-8
  (row A8), the dated residual U10 / O3 (row A9), U45 and the §3.6.1 residual (row A12); and M4,
  under E42's AD-F14 until #1238 (`docs/security/threat-models/e42-admin.md` §13.2), its #2701 ask
  (comment 6244844061) accepted by #2701 ledger 2 row 12 (comment 6493096777), review 2027-02-04.
- Gate statement: "R0 area-6 is met by these rulings plus this record's delegated sign-off."

The conditional sign-offs of 2026-10-09 on #300 (the Owner's, from #1778 item U, and the Security
engineer's, owner-delegated) both withheld the gate.
