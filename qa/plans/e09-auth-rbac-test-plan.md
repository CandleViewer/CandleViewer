# E09 auth, session and RBAC — black-box test plan

Ticket: E09-Q01 (issue #227). Owner: QA. Status: **Dry run in progress (partial, §10) — QA lead / Security
sign-off substitution recorded as owner approval pending (§11)**.

This plan is written against the public contract only: `docs/plan/22-api-openapi.yaml` (tags `auth`,
`users`), `docs/plan/23-ws-protocol.md` §4/§9.5, and the screen states in `docs/plan/14-screens-catalogue.md`
§1. It has no knowledge of internal helpers, service classes or database tables beyond the `audit_log`
row shape used to verify observability steps. Story ids `US-ONB-001..010` are from
`docs/plan/11-user-stories.md` §1; security requirements `SR-010..SR-029`, `SR-050`, `SR-051` are from
`docs/plan/04-security-program.md` §6.3–6.4.

## 0. How to use this plan

- **Audience:** a QA engineer with only a staging URL and the fixture set in §6. No author context needed.
- **Determinism:** every case that depends on wall-clock time names the frozen-clock helper (§6.3) and the
  exact TOTP generation helper (§6.2) to use — never a real `sleep`.
- **Case id scheme:** `E09-TC-<group letter><nn>`, groups A–E map to the five sections below.
- **Automation column:** `E09-Q02` (Playwright automation ticket), `E09-Q03` (RBAC matrix pack), or
  `manual-only` with a follow-up ticket reference.
- **Severity mapping** follows `docs/plan/03-testing-strategy.md` §11.3. By definition of this epic: **any
  defect that grants access, a token, or elevated capability without a completed required factor is filed
  `priority/p0-critical`** regardless of the mapping table's default for that defect class.
- **Audit step convention:** any case whose action is listed in §8 includes an explicit final step "verify
  the `audit_log` row exists with the expected `actor`, `action`, `target`".

---

## 1. Group A — Sign-in & second factor (US-ONB-001, US-ONB-002)

Screens: `SCR-001` (Login), `SCR-002` (TOTP challenge). Endpoints: `POST /auth/login`,
`POST /auth/mfa/verify`, `POST /auth/mfa/recovery`.

| Case | Preconditions | Steps | Expected result | Verifies | Automation |
|---|---|---|---|---|---|
| E09-TC-A01 | Fixture `owner-enrolled` (TOTP enrolled, password known) | 1. `POST /auth/login` with correct email+password. | `200`, body `{"status":"mfa_required","challenge_id":...}` no session cookie set yet. | US-ONB-001, SR-020 | E09-Q02 |
| E09-TC-A02 | Continue A01 | 1. `POST /auth/mfa/verify` with a code from `totp_gen(fixture_secret, now)` (§6.2). | `200`, `Set-Cookie` session cookie `HttpOnly; Secure; SameSite=Strict`, body has no token in JSON (SR-012). Audit row `auth.login`. | US-ONB-002, SR-012, SR-013 | E09-Q02 |
| E09-TC-A03 | Fixture `viewer-disabled` | 1. `POST /auth/login` with that user's credentials. | `403` (or documented disabled-user response in `22-api-openapi.yaml`), no session issued. | US-ONB-001, SR-029 | E09-Q02 |
| E09-TC-A04 | Fixture `manager-with-grants` | 1. `POST /auth/mfa/verify` with a TOTP code one step in the future (`totp_gen(secret, now+30s)`). | `200` (±1 step skew allowed per SR-021). | SR-021 | E09-Q02 |
| E09-TC-A05 | Continue A04 with a code two steps away | 1. `POST /auth/mfa/verify` with `totp_gen(secret, now+90s)`. | `401`/`400` invalid-code response; state machine shows `invalid code` per `SCR-002` states. | SR-021, SCR-002 states | E09-Q02 |
| E09-TC-A06 | Same accepted code as A02, replay it | 1. Re-submit the exact code just accepted in a fresh `POST /auth/mfa/verify` (same challenge or a new login). | Rejected — replay cache blocks re-use (SR-021), even though the code is still time-valid. | SR-021 | E09-Q02 |
| **E09-TC-A07** | Fixture `unknown@example.test` (does not exist) and `manager-with-grants` with a wrong password | 1. `POST /auth/login` unknown user. 2. `POST /auth/login` known user, wrong password. | Compare: HTTP status equal, response body shape equal (no field reveals which case), response-time band equal within the tolerance in `03-testing-strategy.md` (dummy Argon2id verification for unknown users, SR-014). A measurable difference in status, body, or timing band is filed as a **P1 defect against SR-014**. | SR-014 | E09-Q02 |
| E09-TC-A08 | `manager-with-grants` | 1. Submit wrong password 10 times in a row (respecting the documented backoff, SR-015). | 11th attempt: account locked 15 min, Owner alert emitted; login blocked even with the correct password until lockout clears or Owner unlocks. | SR-015, SR-016 | manual-only → follow-up `E09-Q02-lockout-automation` |
| E09-TC-A09 | `manager-with-grants`, 5 consecutive wrong TOTP codes | 1. `POST /auth/mfa/verify` wrong code x5. | `SCR-002` shows "locked after 5 tries" state; further attempts rejected until challenge/lockout window expires. | SCR-002 states, SR-016 | E09-Q02 |
| E09-TC-A10 | Continue A01 challenge, wait past challenge TTL using frozen clock (§6.3) | 1. Advance frozen clock past the documented challenge TTL. 2. `POST /auth/mfa/verify` with a valid code. | Rejected as expired; UI (`SCR-002`) returns to `SCR-001` with "Your sign-in expired, please sign in again." | SCR-002 states | E09-Q02 |
| E09-TC-A11 | `owner-enrolled`, locked out of TOTP device | 1. `POST /auth/mfa/recovery` with an unused recovery code from the fixture set. | `200` with an enrolment-only session that may only enrol and confirm a new TOTP (#2344); that recovery code is consumed (single-use, SR-022); a second `POST /auth/mfa/recovery` with the same code, on that challenge or on another one opened before the recovery, is rejected. Owner alerted; audit row `auth.recovery_code_used`. | SR-022 | E09-Q02 |

---

## 2. Group B — Enrolment, recovery codes & forced password change (US-ONB-003)

Screens: `SCR-003` (TOTP enrolment), `SCR-004` (Forced password change). Endpoints:
`POST /auth/mfa/enroll`, `POST /auth/mfa/enroll/confirm`, `PUT /auth/password`.

| Case | Preconditions | Steps | Expected result | Verifies | Automation |
|---|---|---|---|---|---|
| E09-TC-B01 | Fixture `invited-not-onboarded`, first login, TOTP unenrolled | 1. Log in with the temporary password. | User is routed to `SCR-003`/`SCR-004` and cannot reach any other screen (SR-020 "enrolment enforced at first login"). Attempting `GET /auth/session`-gated routes returns 403 until enrolled. | US-ONB-003, SR-020 | E09-Q02 |
| E09-TC-B02 | Continue B01 | 1. `POST /auth/mfa/enroll`. | `200`, response includes provisioning `otpauth://` secret **exactly once**; secret is never echoed again in any later response (per Technical notes: "never echoes the secret after save"). | US-ONB-003 | E09-Q02 |
| E09-TC-B03 | Continue B02 | 1. `POST /auth/mfa/enroll/confirm` with `totp_gen(secret, now)`. | `200`; ten single-use recovery codes returned exactly once, 128-bit each per fixture generator; session id rotated (SR-013). Audit row `auth.mfa_enroll`. | SR-022, SR-013 | E09-Q02 |
| E09-TC-B04 | Continue B03, re-open the enrolment confirmation screen | 1. Attempt to fetch the recovery codes again via any documented route. | No route returns previously-issued recovery codes in plaintext again. | SR-022 | E09-Q02 |
| E09-TC-B05 | User with existing recovery codes | 1. Regenerate recovery codes via the documented flow. | All ten prior codes become invalid; ten new ones issued; audit row records the regeneration. | SR-022 | E09-Q02 |
| E09-TC-B06 | Continue B01 (forced password change) | 1. `PUT /auth/password` with a new password ≥12 chars, not on the breached-password list. | `200`, session id rotated, all other sessions for that user invalidated (SR-013, SR-028). | US-ONB-003, SR-028 | E09-Q02 |
| E09-TC-B07 | Same as B06 | 1. `PUT /auth/password` with an 8-character password. | Rejected (min 12 chars, SR-028), current password unchanged. | SR-028 | E09-Q02 |
| E09-TC-B08 | Same as B06 | 1. `PUT /auth/password` with a known breached password (e.g. `password123456`). | Rejected per the local breached-password check. | SR-028 | E09-Q02 |
| E09-TC-B09 | Same as B06 | 1. `PUT /auth/password` supplying the wrong current password. | Rejected `400`/`403`; no change; no session rotation. | SR-028 | E09-Q02 |

---

## 3. Group C — Session lifetime, idle lock & step-up (US-ONB-004, US-ONB-005)

Screens: `SCR-005` (Session expired / re-auth modal), `SCR-006` (Step-up auth modal). Endpoints:
`POST /auth/refresh`, `POST /auth/step-up`, `GET /auth/session`.

| Case | Preconditions | Steps | Expected result | Verifies | Automation |
|---|---|---|---|---|---|
| E09-TC-C01 | Signed-in `manager-with-grants`, frozen clock at session start | 1. `GET /auth/session` immediately. | `200` within the `≤100 ms p95` smoke budget noted in `14-screens-catalogue.md` (SCR-006 budgets section); returns current session metadata, no secrets. | US-ONB-004 | E09-Q02 |
| E09-TC-C02 | Same session | 1. Advance frozen clock (§6.3) by 8 h + 1 min with no requests in between. | Next authenticated request is rejected as idle-expired; UI shows `SCR-005`. | US-ONB-004, SR-024 | manual-only → follow-up `E09-Q02-idle-timeout` |
| E09-TC-C03 | Same session, activity every 4 h so it never idles out | 1. Advance frozen clock by 7 days + 1 min total, issuing one authenticated request every 4 h. | Despite continuous activity, the session is rejected once the **absolute** 7-day lifetime is exceeded (SR-024: "remember this device" never extends past the absolute cap). Documented in this plan as **manual-only** per the acceptance-criteria "plan stays honest" scenario — the time-travel technique is frozen-clock advancement in the fixed increments above, with a follow-up ticket `E09-Q02-absolute-lifetime` to automate it via the same frozen-clock harness. | SR-024 | manual-only → `E09-Q02-absolute-lifetime` |
| E09-TC-C04 | Session authenticated 13 h ago (frozen clock), trading capability required | 1. Attempt an action gated on "trading capability requires a session authenticated within the last 12 h" (SR-024). | Rejected; `SCR-006` step-up modal is required before the action proceeds. | SR-024, SR-025 | E09-Q02 |
| E09-TC-C05 | Manager attempting to enable live trading | 1. Attempt the live-enablement route without a fresh step-up. | `403`/step-up-required response; `SCR-006` shown. 2. `POST /auth/step-up` with password + TOTP. | Step 1 blocked; step 2 returns `200` and a step-up token/marker valid 5 minutes (SR-025); the `≤400 ms p95` smoke budget noted for step-up issue in `SCR-006` is observed and recorded (informational only — measured budget run is `E09-Q05`). | SR-025 | E09-Q02 |
| E09-TC-C06 | Continue C05, step-up granted | 1. Advance frozen clock 6 minutes. 2. Retry the gated action. | Step-up has expired (>5 min); action is blocked again, `SCR-006` re-shown. | SR-025 | E09-Q02 |
| E09-TC-C07 | Signed-in session | 1. `POST /auth/refresh`. | `200`, cookie refreshed; SR-013 rotation does **not** apply here unless the refresh itself is a checkpoint the contract lists — assert against `22-api-openapi.yaml`'s documented behaviour for this route, not assumption. | US-ONB-004 | E09-Q02 |
| E09-TC-C08 | Signed-in session, TOTP verify timing | 1. Time 20 consecutive `POST /auth/mfa/verify` calls with correct codes. | p95 ≤400 ms per the `SCR-002` budget note (smoke-level sanity; full measured run is `E09-Q05`). | Performance notes (smoke) | manual-only → `E09-Q05` |
| E09-TC-C09 | Manager session tampered | 1. Strip the session cookie from an authenticated request. 2. Edit one byte of the cookie value and resend. | Both: `401`, no session context resolved, no partial trust. | SR-012 | E09-Q02 |

---

## 4. Group D — Sessions list, sign-out everywhere & TOTP reset (US-ONB-009, US-ONB-010)

Screens: `SCR-111` (Profile settings), `SCR-112` (Security settings). Endpoints: `GET /auth/sessions`,
`POST /auth/logout`, `DELETE /auth/mfa/methods/{methodId}`.

| Case | Preconditions | Steps | Expected result | Verifies | Automation |
|---|---|---|---|---|---|
| E09-TC-D01 | `manager-with-grants` signed in on two simulated devices (two cookie jars) | 1. `GET /auth/sessions` from device A. | Lists both sessions with created/last-seen/IP/user-agent metadata (SR-012), no raw session tokens (SR-019). | US-ONB-009, SR-019 | E09-Q02 |
| E09-TC-D02 | Continue D01 | 1. From device A, revoke device B's session id via the documented route. | Device B's next request is `401`; `GET /auth/sessions` from A no longer lists it. Audit row `auth.session_revoke`. | US-ONB-009, SR-019 | E09-Q02 |
| E09-TC-D03 | Continue D01 | 1. `POST /auth/logout` "everywhere" variant per the contract. | All sessions for the user invalidated; every device's next request is `401`. | US-ONB-009 | E09-Q02 |
| E09-TC-D04 | Owner session, target = `manager-with-grants`'s enrolled TOTP method id | 1. Step-up as Owner (SR-025). 2. `DELETE /auth/mfa/methods/{methodId}` for that manager. | `200`; manager's TOTP method removed, forced back through `SCR-003` enrolment on next login; audit row `auth.mfa_reset` with actor = Owner, target = manager. | US-ONB-010, SR-025 | E09-Q02 |
| E09-TC-D05 | Manager signed in, viewing an account-scoped screen live; Owner in a separate session | 1. Owner revokes the manager's grant on that account via the roles/account-access route. 2. The manager's client issues the next request for that account's data. | Next HTTP request for that account returns `403`. The manager's open WS connection receives a `revoked` frame (`reason: account_scope_changed`, per `23-ws-protocol.md` §9.5) naming the removed account. The manager's session id has rotated (SR-013) so any cached cookie from before the change is inert. No cached client-side state (React/Zustand/Jotai) is accepted as evidence of continued access — the plan requires re-querying the server, not trusting the UI's last-known state. | SR-050, SR-051, WS §9.5 | E09-Q02 |
| E09-TC-D06 | Manager account disabled by Owner mid-session | 1. Owner disables the manager. 2. Manager's next request. | `bye` WS close code `4403` (per §9.5) and/or `401`/`403` on REST; all pending sessions terminated (SR-029). | SR-029 | E09-Q02 |

---

## 5. Group E — Invite, onboarding & permission denial (US-ONB-006, US-ONB-007, US-ONB-008)

Screens: `SCR-017` (invited-user onboarding wizard), `SCR-019` (setup checklist), `SCR-123` (admin invite
user), `SCR-154` (permission denied / 403). Endpoints: `GET /invites/{inviteToken}`, `GET|POST /users`,
`GET /onboarding/checklist`, `POST /onboarding/complete`.

| Case | Preconditions | Steps | Expected result | Verifies | Automation |
|---|---|---|---|---|---|
| E09-TC-E01 | Owner session, step-up granted | 1. `POST /users` to invite a new manager (email only). | `200/201`; new user created with role `Viewer`, no account grants, TOTP unenrolled (SR-027 — elevation is a separate, later, audited action). Audit row `roles.grant`/`users.create` per contract naming. | US-ONB-006, SR-027 | E09-Q03 |
| E09-TC-E02 | Continue E01 | 1. `GET /invites/{inviteToken}` with the token from E01, unauthenticated. | `200`, invite metadata only (email, inviter, expiry) — no PII beyond what `SCR-017` needs; expired/consumed tokens return an explicit error, not a generic 500. | US-ONB-006 | E09-Q02 |
| E09-TC-E03 | Continue E02 | 1. Redeem the invite: accept → set password (`SCR-004` embedded) → enrol TOTP (`SCR-003` embedded) → orientation card. | Each step gates the next (SR-020 enrolment-at-first-login applies); on completion the user lands on `SCR-019` setup checklist, still `Viewer` with no grants until the Owner explicitly elevates. | US-ONB-006, US-ONB-007 | E09-Q02 |
| E09-TC-E04 | Continue E03, reused invite token | 1. Attempt to redeem the same invite token a second time. | Rejected — single-use token. | US-ONB-006 | E09-Q02 |
| E09-TC-E05 | Continue E03 | 1. `GET /onboarding/checklist`. 2. Complete one item. 3. `POST /onboarding/complete` before all items are done. | Checklist reflects partial completion (`SCR-019` persistent card, "skip for now" allowed on steps 3–5); `/onboarding/complete` either rejects premature completion or records it as explicitly skipped per the documented contract — assert the exact documented behaviour, not an assumption. | US-ONB-007 | E09-Q02 |
| **E09-TC-E06** | New `Viewer` user from E03, no account grants | 1. Attempt any account-scoped route (e.g. positions list) for any account id. | `403`; UI shows `SCR-154` permission-denied screen, not a blank/broken state. The UI hides the affordance too, but the plan asserts the **server** response independent of UI hiding (server is the control, not the UI — per security program §6.3 note under SR-017). | US-ONB-008, SR-017 | E09-Q03 |
| E09-TC-E07 | `manager-with-grants` (has grants on account X only) | 1. Request account Y's data by tampering the `account_id` in an otherwise-valid, authenticated request. | `403`; response does not leak whether account Y exists (no distinguishable 404 vs 403 that would reveal account enumeration). | SR-050, SR-051 | E09-Q03 |
| E09-TC-E08 | Request originates from a source address outside the Tailscale-only network boundary (simulated per `docs/plan/34-e06-shell-threat-model.md` reachability notes, if a staging proxy allows the simulation) | 1. Attempt to reach the backend from a non-tailnet address. | Connection refused / not reachable — **structural** check, may be `manual-only` if staging cannot simulate network topology; if untestable in this environment, mark the case as **not executable here** and reference the deployment-level check owned by `SR-047`/ops runbooks, not this QA plan. | US-ONB-008 | manual-only (deployment-level; see §7 notes) |
| E09-TC-E09 | Owner session, adding a route/topic without a capability declaration (contract-level, not runtime) | 1. Confirm via the route/RBAC coverage test referenced in `04-security-program.md` (SR-018) that CI fails on missing declarations — this is a build-time gate, not a black-box case; recorded here only to close the traceability gap for SR-017/SR-018 and to point at the owning CI job. | Documented pointer only; no runtime steps. | SR-017, SR-018 | owned by CI (`contract`/`ci-gate`), not this plan |

---

## 6. Test data & fixture appendix

### 6.1 Seeded users (via the CI seed path, `E09-T01` migrations/seed — never hand-edited into Postgres)

| Fixture id | Role | Grants | TOTP | Notes |
|---|---|---|---|---|
| `owner-enrolled` | Owner | all accounts | enrolled, deterministic secret (§6.2) | mandatory per SR-020 |
| `manager-with-grants` | Manager | account X (`trade`) | enrolled | primary happy-path actor |
| `manager-without-grants` | Manager | none | enrolled | used for E09-TC-E06/E07-style denial cases |
| `viewer-disabled` | Viewer | none | unenrolled | `disabled = true`; used for A03, D06-style cases |
| `invited-not-onboarded` | Viewer (pending) | none | unenrolled | created via `POST /users` invite path, token not yet redeemed |

### 6.2 Deterministic TOTP helper

A fixed, test-only TOTP secret (base32, RFC 6238) is provisioned per enrolled fixture user, **documented as
test-only and never present in any non-test seed**. Helper: `totp_gen(secret: str, at: datetime) -> str`
(6-digit code, 30 s step, ±1 step skew tolerance per SR-021) lives alongside the seed fixtures used by
`E09-Q02`/`E09-Q03` automation; black-box cases in this plan reference it by name only, with no secret
value inlined here.

### 6.3 Frozen-clock helper

`freeze_at(t: datetime)` / `advance(delta: timedelta)` — the same clock-injection point used by backend
unit tests (`docs/plan/20-architecture.md` clock-injection convention) is exposed to the seeded e2e
harness only, so idle-timeout (C02), absolute-lifetime (C03), step-up-expiry (C06) and
MFA-challenge-expiry (A10) cases never use a real `sleep`. The server reads auth time as UTC plus the
offset in `CV_TEST_CLOCK_FILE`, which the helper rewrites; there is no HTTP route. `CV_TEST_CLOCK` is
refused unless `CV_ENVIRONMENT=testnet` with no exchange key, so staging (demo) never has it (#2086).
No case in this plan waits on wall-clock time.

- **Where they run.** The cases that need the server clock (A08 once automated, A10, C02, C03, C04
  and the server half of C06) run only on the seeded e2e stack (#2490), never on staging. The SPA
  halves of C04-C06 already run in `stepup.spec.ts`, which moves the browser clock (`page.clock`)
  over a stubbed API (`e09-q02-automation-status.md`).
- **Time keeps flowing.** `freeze_at(t)` sets the offset to `t` minus now. The server clock does not
  stop, so it keeps advancing after the call: assert each expiry with a margin past the limit, as C02,
  C03 and C06 do (1 min), never at the exact boundary.
- **Own database.** The test-clock stack owns its Postgres database and QuestDB namespace and never
  shares them with a demo or live process (C-2.11): rows written under a far-future offset (sessions,
  lockouts, invites) would outlive the run (#2728).

---

## 7. Traceability table (US-ONB-001..010 × cases × automation)

| Story | Title | Test cases | Automation |
|---|---|---|---|
| US-ONB-001 | Password sign-in | A01, A03, A07, A08 | E09-Q02 |
| US-ONB-002 | TOTP second factor | A01, A02, A04, A05, A06, A09, A10 | E09-Q02 |
| US-ONB-003 | TOTP enrolment & recovery codes | B01–B09 | E09-Q02 |
| US-ONB-004 | Session lifetime & idle lock | C01, C02, C03, C07 | C02/C03 manual-only; rest E09-Q02 |
| US-ONB-005 | Step-up re-authentication | C04, C05, C06 | E09-Q02 |
| US-ONB-006 | Invite-based user creation | E01–E04 | E09-Q03 (E01), E09-Q02 (E02–E04) |
| US-ONB-007 | Guided first-run for a new manager | E03, E05 | E09-Q02 |
| US-ONB-008 | Tailscale-only reachability enforcement | E06, E08 | E06 → E09-Q03; E08 manual/deployment-level |
| US-ONB-009 | Sign-out everywhere | D01, D02, D03 | E09-Q02 |
| US-ONB-010 | Owner-initiated TOTP reset | D04 | E09-Q02 |

No `US-ONB-*` id is without at least one case with steps and an expected result, satisfying acceptance
criterion 1. `A11` (recovery-code login) additionally exercises SR-022 beyond a specific story id and is
retained for the negative/abuse-adjacent coverage in §8.

---

## 8. Negative / abuse-adjacent cases owned by QA (deeper adversarial cases live in `E09-X02`)

| Behaviour | Case(s) | Note |
|---|---|---|
| Unknown-user vs wrong-password indistinguishability | E09-TC-A07 | Body, status, timing band all compared; P1 against SR-014 on any difference |
| TOTP replay | E09-TC-A06 | Replay cache asserted, not just skew tolerance |
| Recovery-code reuse | E09-TC-A11, B04 | Single-use enforced; second use rejected |
| Expired MFA challenge | E09-TC-A10 | Frozen-clock advance past challenge TTL |
| Session cookie stripped/edited | E09-TC-C09 | Both stripped and single-byte-tampered variants |
| Role change mid-session | E09-TC-D05 | 403 + WS `revoked` + session-id rotation, no cached-state trust |

Cases requiring deeper adversarial technique (fuzzing, timing side-channels beyond the coarse band check,
concurrent-session race conditions) are explicitly out of scope here and are `E09-X02`'s responsibility;
this plan's negative cases are the black-box, single-actor surface only.

## 8a. Audit-completeness steps (Observability)

Every case above whose action is one of `auth.login`, `auth.login_failed`, `auth.mfa_enroll`,
`auth.mfa_reset`, `auth.password_change`, `roles.grant`, `roles.revoke` includes, as its final numbered
step, "verify the `audit_log` row exists with the expected actor, action and target" (rows: A02, A11, B03,
B05, B06, D02, D04, E01). A missing or malformed audit row is filed as a defect against the acting case's
`SR-*`/story id, not as a separate ticket, so it stays traceable.

## 8b. Accessibility note

Each manual-only case above (A08, C02, C03, C08, E08) records whether it is executable keyboard-only.
A08 (lockout), C02/C03 (frozen-clock idle/absolute timeout) and C08 (timing sanity) are pure API/timing
checks with no UI interaction and are keyboard-only by construction. E08 is a network-topology check, not
a UI interaction. Any case in Groups A–E that turns out to require a mouse to complete is itself filed as
a defect against `docs/plan/05-accessibility-standard.md` §3, separate from the deep audit in `E09-Q04`.

---

## 9. Defect-reporting conventions

Follows `docs/plan/03-testing-strategy.md` §11.3 severity mapping. Overriding rule for this epic: **any
defect where access, a session, a token, or an elevated capability is granted without every required
factor having actually been completed is filed `priority/p0-critical`**, regardless of what §11.3's
default mapping would otherwise assign. All other defects use the standard mapping (functional break →
P1, cosmetic/UX → P2/P3). Every defect references: case id, `US-ONB-*` id, `SR-*` id (if applicable),
the exact request/response or WS frame observed, and — for the dry run in §10 — the attached
screenshot/HAR evidence.

---

## 10. Dry-run execution record

**QA fix note (issue #1623):** §10 previously shipped with an empty, indefinitely-deferred table. Per
the ticket's own Definition of Done item 3 ("one full dry-run execution recorded with a pass/fail table
and attached evidence"), a plan may not leave this permanently pending — it must record a dry run for
every case whose dependency already exists in `main`, and mark every other case honestly rather than
leaving the whole table blank. This section now does that, and is re-run (appended, never overwritten)
as each remaining `E09-S0x` story ticket merges:

1. Executes every case in Groups A–E whose dependency is merged, recording pass/fail below; every case
   whose dependency has not merged is recorded as `blocked-pending-dependency`, never a fabricated pass.
2. Files a defect (per §9) for every fail, including every attempted negative case (A06, A07, A09, A11,
   C09, D05) — a 100% first-pass result is treated as suspicious per the ticket's own acceptance criteria,
   and at minimum the negative cases must show genuine attempt evidence.
3. Is recorded in `qa/plans/e09-auth-rbac-test-plan-dryrun-20260930.md` — the executable evidence is
   `services/api/tests/qa/test_e09_dryrun_group_a.py`, run via `uv run pytest tests/qa -v --no-cov`. As of
   this run only `E09-S01` (#1599, #1609) is merged; the remaining Groups B–E stay
   `blocked-pending-dependency` on `E09-S02..S06`, tracked under `E09-Q06` for the epic-level full pass.

| Case group | Result | Evidence | Defect (if any) |
|---|---|---|---|
| A01, A03, A07 (partial), A08 (router-contract slice) | PASS | `qa/plans/e09-auth-rbac-test-plan-dryrun-20260930.md`, `services/api/tests/qa/test_e09_dryrun_group_a.py` | — |
| A02, A04–A06, A09–A11 | blocked-pending-dependency | requires `POST /auth/mfa/verify`/`recovery` (`E09-S02`) | — |
| B01–B09, C01–C09, D01–D06, E01–E09 | blocked-pending-dependency | require `E09-S02..S06` | — |

**Status:** this plan is submitted for QA lead and Security engineer review now; sign-off has **not**
been given yet — see the dry-run record above and §11 for the owner-approval-pending substitution
recorded per the epic's Agent-delivery adaptations, pending an actual `approved` comment or merge on
issue #227.

---

## 11. Sign-off

- [ ] QA lead sign-off comment posted on issue #227 — **not yet given**; per the epic's binding
  Agent-delivery adaptations (`docs/plan/backlog/E09.json`, owner decision 2026-09-25: "the owner's
  `approved` comment on this issue, or owner merge of the PR" substitutes for QA-lead/Architect/
  CDO/Security-engineer sign-off — no other human role exists), this is recorded as **owner approval
  pending**, not recorded. See `qa/plans/e09-auth-rbac-test-plan-dryrun-20260930.md` §"Owner review".
  Do not treat this box as sign-off; it tracks that the substitution mechanism is documented and
  awaiting the owner's actual `approved` comment or merge on issue #227.
- [ ] Security engineer review of §8/§9 (negative cases, severity mapping) — **not yet given**; same
  owner-approval-pending substitution. §8/§9 negative-case coverage and severity mapping are unchanged
  by this fix, but formal review/sign-off has not been recorded on issue #227.
- [x] Traceability table (§7) confirmed to cover US-ONB-001..010 with no gaps — unchanged by this fix;
  re-confirmed by inspection (all ten `US-ONB-*` rows map to at least one case).
- [x] Automation ownership assigned per case (§7, per-case "Automation" column throughout Groups A–E) —
  `E09-Q02`, `E09-Q03`, or manual-only with the follow-up ticket named inline.
- [x] No live Bybit dependency and no wall-clock `sleep` anywhere in this plan — confirmed by inspection
  (§6.3 frozen-clock helper is used in every clock-dependent case) and by the new dry-run test module
  (no `time.sleep`/`asyncio.sleep`, no network).

