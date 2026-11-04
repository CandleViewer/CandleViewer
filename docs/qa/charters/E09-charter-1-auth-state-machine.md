# E09-C1 Charter: auth state-machine boundaries

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.

## Charter
Interrupt every auth transition (MFA, step-up, recovery, re-enrolment) to find states where authority is gained, kept, or lost wrongly.

## Oracles (defined up front)
- O1 Any state where a user is authenticated but no audit row exists for the login.
- O2 Any error text/status that differs between an unknown user and a wrong password.
- O3 Any code, challenge or recovery code accepted twice.
- O4 Any elevation that survives its session, its action class or its window.

## Areas covered (in-process evidence)
| Probe | Evidence (re-run 2026-10-09) | Result |
|---|---|---|
| Stale or expired MFA challenge | `tests/unit/auth/test_mfa_service.py::test_verify_expired_challenge_raises_challenge_invalid` | refused (O3 ok) |
| Another user's challenge with my code | `tests/security/auth/test_mfa_abuse.py::test_ac_mfa_06_challenge_for_other_user_cannot_use_my_code` | refused |
| Recovery code while TOTP pending, concurrent consume | `test_ac_mfa_05b_concurrent_recovery_code_consumed_once`, `test_ac_mfa_03_recovery_code_single_use` | consumed once |
| Recovery code forces TOTP re-enrolment | `test_mfa_service.py::test_recovery_code_use_forces_totp_reenrollment` | ok |
| TOTP replay inside skew window | `test_ac_mfa_01_totp_replay_inside_skew_window_rejected` | refused |
| Step-up elevation transplanted to another session/action | `test_ac_stepup_01_elevation_not_transplantable_across_session_or_action`; `test_step_up.py::test_elevation_is_revoked_with_the_session` | refused (O4 ok) |
| Unknown vs wrong password | `test_login_timing_enumeration.py`, `test_ac_enum_01` | indistinguishable (O2 ok) |

Run result: 81 tests passed across the MFA / step-up / recovery / MFA-abuse / step-up-abuse files.

## Not probed (needs a human, a browser or staging)
- Closing the tab mid-MFA, browser back/forward during MFA: SCR-002 is not built; tracked in #1640.
- Server-side expiry of a step-up under a moving clock end to end: needs the server test clock, #2086.
- Password change during an active step-up: no existing test combines them; tracked as #2099.
- Re-enrolling TOTP while an old authenticator is still configured (real device flow).
- Keyboard-only segment: login and step-up have Playwright keyboard cases (`login.spec.ts`, `stepup.spec.ts`); a manual screen-reader pass is not done here.

## Anomalies
None observed in-process. Dismissal reason for the absence of findings: scope was limited to existing coverage; absence of anomalies is not evidence of absence.

## Follow-ups
1. #2099: add an interaction test: password change while a step-up elevation is live must revoke or void the elevation (needs a decision from the auth owner on intended behaviour).
2. E2E for A02/A05/A06/A09/A10/A11 once SCR-002 exists (#1640).

## Since run 1 (status 2026-11-04)
- #1640 (SCR-005/SCR-112 and the SCR-002 gap): closed. #2711 (SCR-002 TOTP step) closed by #5250; the A02/A05/A06/A09/A10 UI halves are in `apps/web/e2e/auth/login.spec.ts`.
- #2086 (server clock for step-up expiry): closed, delivered by #5170 (`apps/web/e2e/auth/step-up-expiry.real.ts`).
- #2099 (password change during a live step-up): closed; `tests/security/auth/test_password_change_step_up.py::test_a_password_change_ends_a_live_step_up_grant_and_the_gated_action_is_refused`. `PUT /auth/password` shipped in #5292 and the TOTP account lockout in #5380.

## Run 2 plan (staging, #2491) · Status: not yet run · planned 2026-11-04
- Format: session-based, 90 min (60-120 time box), human tester on staging with a browser; test accounts only; no live or demo exchange key present. Cites 03 §11.2 and §12.
- Mission: Interrupt every auth step in a real browser against staging, now including password change, the TOTP lockout and the SCR-002 step, to find a state where authority is gained, kept or lost wrongly.
- Areas:
  - SCR-001 -> SCR-002 -> step-up dialog with the tab closed, reloaded, back/forward and a second tab mid-step
  - `PUT /auth/password` while a step-up grant is live and while a second session is open
  - repeated refused TOTP codes against the account lockout, then a valid code
  - US-ONB-001, -002, -003, -005; threat rows U1, U2, U6, U11, U18, U27
- Oracles (the run-1 oracles O1-O4 stay in force):
  - O1.5 a password change leaves a live step-up grant or another session usable
  - O1.6 a refused TOTP code that does not count towards the account lockout, or a lockout that differs after reload
  - O1.7 any step that works twice (code, challenge, recovery code) in the browser
  - O1.8 an action with no audit row or no metric movement (U7, U19); observe for more than 1 s for E09-Q05
- Keyboard-only segment (03 §12): SCR-001 -> SCR-002 -> step-up dialog by Tab, Shift-Tab, Enter and Escape only; focus visible and never trapped.
- Automated neighbours: `apps/web/e2e/auth/login.spec.ts`; `tests/security/auth/test_password_change_step_up.py`; `tests/security/auth/test_password_change_http.py`; `tests/security/auth/test_mfa_abuse.py`; `tests/unit/auth/test_mfa_account_lockout.py`.
- Private routing: anomalies matching a security oracle (bypass, escalation, audit gap) go the same day through SECURITY.md's private channel (GitHub Private Vulnerability Reporting, or a direct message to the owner `@basiltt`), never a public issue; the debrief records only the private report id and a pattern-level label. Other anomalies: issue links.
- Debrief slots: tester, date, build sha, minutes spent; anomalies (the private report id for a security-oracle anomaly, an issue link otherwise); not probed; follow-ups. Filled at the #2491 run.
