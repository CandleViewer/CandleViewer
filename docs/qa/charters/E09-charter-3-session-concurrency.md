# E09-C3 Charter: session identity and concurrency

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.

## Charter
Same user in three contexts with sign-out-everywhere, role change and disable racing, to find a context that keeps authority or is falsely evicted.

## Oracles
- O1 A revoked session that still passes a request or keeps a socket.
- O2 A sibling session revoked when only one was targeted.
- O3 A refresh token usable twice, or extending absolute lifetime.
- O4 Any revocation without an audit row.

## Areas covered (in-process evidence)
| Probe | Evidence | Result |
|---|---|---|
| Revoke one leaves siblings | `test_session_service.py::test_revoke_one_session_leaves_others_of_the_same_user_untouched` | no false eviction (O2 ok) |
| Sign-out everywhere (optionally excluding current) | `test_sign_out_everywhere_revokes_all_but_can_exclude_current` | ok |
| Refresh reuse revokes family | `test_session_abuse.py::test_ac_ses_03_refresh_reuse_revokes_family_and_access_tokens` | ok (O3) |
| Absolute lifetime not extendable | `test_ac_ses_04_refresh_cannot_extend_absolute_lifetime` | ok |
| IDOR revoke of another user's session | `test_csrf_cookie_abuse.py::test_ac_csrf_05_idor_cannot_revoke_other_users_session` | refused |
| Socket closed on revocation, others unaffected | `tests/unit/ws/test_revocation.py` (3 tests), chaos S3/S4 in `tests/chaos/auth/test_auth_chaos.py` | ok (O1) |
| Role change / disable during session | `tests/unit/test_ws_permissions.py`, `tests/unit/api/test_users_router.py` | next-request effect shown |
| Postgres outage fails closed | chaos S1 | ok; S1b (real restart) **skipped: docker stack unavailable** |

Run result: 69 passed, 1 skipped (S1b).

## Not probed
- True concurrency of three browser contexts; cookie jars in a real browser.
- Idle-lock and absolute-expiry screens (SCR-005/112): #1640. Server clock for E2E expiry: #2086.
- Concurrent role revocation during a step-up-gated action as a single atomic scenario (AC edge case in the ticket): covered only in parts (step-up needs elevation per session; role change refuses next request); no one test asserts both audit rows in order. Tracked as #2100.

## Anomalies
None observed in-process.

## Follow-ups
1. #2100: add a deterministic interleaving test: manager mid step-up, owner revokes role, action refused, audit order preserved, no partial effect.

## Since run 1 (status 2026-11-04)
- #1640 (idle-lock and expiry screens) and #2086 (server clock): closed (#5170).
- #2100 (role revoked mid step-up): closed. #2593 closed by #5256: the effect now refuses a revoked or disabled owner (`tests/security/auth/test_role_revoked_mid_step_up.py::test_role_revoked_after_the_action_was_authorised_is_refused_at_the_effect`).
- SR-013 session rotation on role change (#2101): open (#5433 in review).

## Run 2 plan (staging, #2491) · Status: not yet run · planned 2026-11-04
- Format: session-based, 90 min (60-120 time box), human tester on staging with a browser; test accounts only; no live or demo exchange key present. Cites 03 §11.2 and §12.
- Mission: Hold the same user in three real browser contexts and race sign-out everywhere, role change, disable and Lock now, to find a context that keeps authority or is falsely evicted.
- Areas:
  - sign-out everywhere and revoke-one from the SCR-112 session list, with the other contexts reloaded
  - disable and role change with a live socket; a role revoked between the step-up and the effect (#5256)
  - Lock now (U51) and idle lock, unlocked with the password only
  - SR-013 session rotation on role change is open (#2101, #5433 in review): record what is observed, do not call it a pass
  - US-ONB-004, -009; threat rows U6, U7, U13, U19, U32, U45, U51
- Oracles (the run-1 oracles O1-O4 stay in force):
  - O3.5 a context that keeps authority or a socket after disable or role change
  - O3.6 the audit order is not revoke then refusal
  - O3.7 a locked session that acts again without the password
  - O3.8 a sibling session evicted when only one was targeted
- Keyboard-only segment (03 §12): the SCR-112 session list: revoke one, then sign out everywhere, by keyboard only.
- Automated neighbours: `tests/security/auth/test_role_revoked_mid_step_up.py`; `tests/security/auth/test_disable_user_e2e.py`; `tests/security/auth/test_revocation_closes_sockets.py`; `tests/security/auth/test_idle_lock_http.py`; `apps/web/e2e/auth/sign-out-everywhere.real.ts`.
- Private routing: anomalies matching a security oracle (bypass, escalation, audit gap) go the same day through SECURITY.md's private channel (GitHub Private Vulnerability Reporting, or a direct message to the owner `@basiltt`), never a public issue; the debrief records only the private report id and a pattern-level label. Other anomalies: issue links.
- Debrief slots: tester, date, build sha, minutes spent; anomalies (the private report id for a security-oracle anomaly, an issue link otherwise); not probed; follow-ups. Filled at the #2491 run.
