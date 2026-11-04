# E09-C4 Charter: onboarding and lockout

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.

## Charter
Abuse invite links (reuse, expiry, wrong person, double-open) and lockout timing, and follow break-glass docs literally.

## Oracles
- O1 An invite redeemable twice or after expiry or revocation.
- O2 Lockout state that differs after reload or clock change.
- O3 Pre-elevated (Owner) invite possible.
- O4 Break-glass step that cannot be followed as written.

## Areas covered (in-process evidence)
| Probe | Evidence | Result |
|---|---|---|
| Reuse / expired (72 h) / unknown / revoked | `test_invite_service.py` (reuse, expired, unknown, revoked), `test_stepup_invite_abuse.py::test_ac_inv_01..03` | uniform rejection |
| Simultaneous redemption | `test_invite_service.py::test_concurrent_redemptions_exactly_one_wins` | one wins (O1 ok) |
| Pre-elevated invite | `test_owner_role_cannot_be_invited`, `test_ac_inv_04_cannot_invite_pre_elevated_owner` | refused (O3 ok) |
| Abandoned enrolment | `test_abandoned_enrolment_leaves_user_invited`, `test_wrong_totp_code_does_not_activate` | stays invited |
| Lockout and expiry on fixed clock | `test_credential_abuse.py::test_ac_cred_04`, `test_ac_cred_05_lockout_expires_on_fixed_clock`; `tests/unit/auth/test_throttle.py` | ok |
| Lockout UI countdown | `apps/web/e2e/auth/login.spec.ts` (A08 UI half) | stub-level |

Run result: 47 passed (1 deselected integration).

## Not probed
- Lockout countdown across a real page refresh and across a system clock change (browser; server clock #2086).
- Invite opened by the wrong person over HTTP (listed NOT RUN in `docs/security/abuse-cases/e09-auth.md`).
- Break-glass drill: owned by E09-X04 (#300); not run here and not duplicated.
- Keyboard-only walk of the onboarding wizard: covered only by the stubbed Playwright spec.

## Anomalies
None observed in-process.

## Since run 1 (status 2026-11-04)
- #2099 (password change, shared with C1): closed. Lockout owner alert #2102 closed by #2628.
- Break-glass CLI (E09-S11) and the bootstrap first Owner shipped after run 1; the drill itself is still owned by #2298 (E09-X04 #300 closed 2026-10-29; record in `docs/security/reviews/e09-auth-review.md`).

## Run 2 plan (staging, #2491) · Status: not yet run · planned 2026-11-04
- Format: session-based, 90 min (60-120 time box), human tester on staging with a browser; test accounts only; no live or demo exchange key present. Cites 03 §11.2 and §12.
- Preconditions: staging is the keyless testnet build (no exchange key, per U33); the break-glass and bootstrap steps run only under #2298's procedure with cv-api stopped and a disposable Owner; bootstrap is explorable only on a fresh staging database, else 'not probed'.
- Mission: Abuse invite links and the bootstrap token, trip the lockout, and follow the break-glass documentation literally on staging.
- Areas:
  - invite reuse, expiry, wrong person, double-open; invited-user onboarding (SCR-017)
  - first-Owner bootstrap: a reused or copied token, and a non-bootstrap owner invite
  - break-glass CLI (E09-S11) followed step by step as written
  - lockout and the Owner alert; US-ONB-006, -007, -010; threat rows U10, U12, U27, U46-U50
  - U27 re-lock behaviour and the unlock path are open (#1233): record what is observed, do not call it a pass
- Oracles (the run-1 oracles O1-O4 stay in force):
  - O4.5 a bootstrap token that works twice or a second first Owner
  - O4.6 a break-glass step that cannot be followed as written
  - O4.7 a lockout that differs after reload or a clock change, or that raises no Owner alert (U27 re-lock and unlock are open under #1233: record, do not pass)
  - O4.8 an action with no audit row or no metric movement (U7, U19); observe for more than 1 s
- Keyboard-only segment (03 §12): invited-user onboarding (SCR-017) from the link to the first screen by keyboard only.
- Automated neighbours: `tests/unit/auth/test_invite_service.py`; `tests/security/auth/test_stepup_invite_abuse.py`; `tests/security/auth/test_lockout_owner_alert.py`; `tests/unit/auth/test_break_glass.py`; `tests/integration/auth/test_bootstrap_owner_e2e_pg.py`; `apps/web/e2e/auth/onboarding.spec.ts`.
- Private routing: anomalies matching a security oracle (bypass, escalation, audit gap) go the same day through SECURITY.md's private channel (GitHub Private Vulnerability Reporting, or a direct message to the owner `@basiltt`), never a public issue; the debrief records only the private report id and a pattern-level label. Other anomalies: issue links.
- Debrief slots: tester, date, build sha, minutes spent; anomalies (the private report id for a security-oracle anomaly, an issue link otherwise); not probed; follow-ups. Filled at the #2491 run.
