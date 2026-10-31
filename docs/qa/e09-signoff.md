# E09 QA sign-off evidence pack (R0 exit)

Ticket: E09-Q06 (#297) for epic E09 (#36, Auth, sessions, 2FA and RBAC). Drafted 2026-10-31 for the orchestrator's docs PR (ruling of record on #297, comment 6547349544, item (b)) from `origin/main` `16d70fee`; the re-assessment behind the ruling read `d721407c`. It updates the FAIL record of 2026-10-16 (comment 6213283229, main `93391b52`). QA supplies the evidence and a **proposed** verdict (section 10); the closing is the orchestrator's under the owner's delegation of 2026-10-29 (#2701, comment 6490317249). Security is referenced here, not signed off (section 8).

Reference note: the R0 exit criteria are `docs/plan/30-release-roadmap.md` §4.3. E09's is #7 (login and TOTP, session rotation, logout-everywhere, an RBAC denial that returns 403, changes nothing and is audited, a tampered audit row that is detectable; line 259). The §4.4 gates that touch E09 are unit coverage (line 270), a11y (line 274) and the threat model (line 276). `docs/plan/07-release-and-prr.md` has no E09 section, so section 7 below is the release-test-report input for the PRR owner.

## 1. Summary

| Area                           | State on 2026-10-31                                                                                                                           | Evidence                                                |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Acceptance criteria            | AC3 pass; AC1 and AC5 partial (the env-only half is deferred); AC2 and AC4 open, owned and dated                                              | section 2                                               |
| Scripted regression (E09 pack) | green when last run: 1685 passed, 0 failed (independent, 2026-10-12); marker and drift guard run in CI's `py` lane; not re-run for this draft | section 3; `qa/plans/e09-regression-pack.md` section D2 |
| Exploratory charters           | 4 of 4 debriefed in-process (one commit, #2098, 2026-10-09); the staging re-run is deferred (#2491)                                           | section 4; `docs/qa/charters/E09-charter-*.md`          |
| Story groups                   | automated half green in every group; carries: B06-B09, the concurrency row, three security-control rows; the manual half is not run           | section 5                                               |
| Coverage (E09 modules)         | as of 2026-10-16: auth 98.0 %, audit 99.7 %, `api/step_up.py` 89.4 %, web slice 91.92 % lines / 81.31 % branches; re-measure at R0            | section 6                                               |
| R0 release-test report         | E2E 15 of 15 on the real lane; k6 figures from a hosted runner; chaos s1-s5 green; a11y automated only                                        | section 7                                               |
| Security deliverables          | threat model Final; delegated sign-off PASS WITH CONDITIONS on 2026-10-29                                                                     | section 8                                               |
| Open defects                   | two labelled P0 (#293, a test ticket, time-gated; #1230, the CSP chore, routed to a frontend / Electron lane), eight P1 labelled, five design-lane children; no PR open at 18:15Z                                        | section 9                                               |
| **Proposed verdict**           | **PASS_WITH_CARRIES pending**                                                                                                                 | section 10                                              |

## 2. Acceptance criteria (E09-Q06)

| AC  | Criterion                                                                             | 2026-10-16        | Now                                                                                     | Evidence and disposition                                                                                                                                                                                                                                                                                                                                                                                                                |
| --- | ------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC1 | Four charters executed with debriefs                                                  | PARTIAL, env-only | PARTIAL, env-only: deferral recorded                                                    | The four debriefs exist (section 4) and are in-process re-runs: no staging build, no time box, no recording; charters 2 and 3 have no keyboard-only segment. The staging re-run is #2491, an env-only deferral (ruling decision 3, comment 6547349544; #1778 AA tracks env runs; review row A7 treats the staging repeat, #2298, as post-GA).                                                                                           |
| AC2 | Epic rollup green before sign-off: coverage, and no open P0 or P1 bug                 | FAIL              | NOT YET MET: carried, owned and dated (section 9)                                       | Coverage half passes as of 2026-10-16 (section 6). Cleared since the record: #2119 #2300 #2304 #2295 #2344 #2490 #2494 #2712 #2725 #294 #296 (ruling), and #2269 #2496 #2636 #2111 #2713 (re-assessment); the threat model is Final (#4965). Open P0 and P1 items are listed in section 9 with owner and date. The design-lane children (#193 #194 #190 #188 #291) do not count: they are design tickets, not bugs (ruling decision 6). |
| AC3 | An AC with no evidence withholds sign-off and files the gap                           | PASS              | PASS                                                                                    | Behaved as specified: sign-off withheld 2026-10-09, gaps filed. B06-B09 (forced password change) is evidenced only by a stubbed spec and a policy unit test until `PUT /auth/password` is mounted: traced to #2330 (policy contract), then #2110 (the route), then #2099 (the mid-step-up test).                                                                                                                                        |
| AC4 | A concurrent role change during an active step-up-gated action: the action is refused | NOT MET           | NOT MET until #2593 merges: the fix is ordered (decision of record, comment 6547353657) | `services/api/tests/security/auth/test_role_revoked_mid_step_up.py` (#2597, 8 tests) pins atomicity and audit order; the refusal at the effect is #2593's (decision of record 6547353657) |
| AC5 | Regression pack re-runnable by a different person                                     | PARTIAL           | PARTIAL: automated half PASS, manual half env-only                                      | Automated: `pytest -m e09_regression` (pack lines 6-19) gave 1685 passed, 1 skipped (S1b), 0 failed on 2026-10-12 in an independent agent run (pack line 157); the drift guard runs in CI's `py` lane. No dedicated lane for the marker: #2716 (P2, `post-ga`). Manual M1-M8 (pack lines 94-101) have never been executed: #2491, env-only.                                                                                             |

## 3. Scripted results

Command (from `services/api`): `uv run pytest -p no:randomly --no-cov -m e09_regression` (pack line 12). The marker covers the pack's paths by list (`services/api/tests/_e09_regression_pack.py`), and its guard (`services/api/tests/qa/test_e09_regression_pack.py`) holds the pack document and that list together and fails when the pack cites a test the marker does not select (pack line 27).

| Run                                                                                                                        | Result                                               | Time                           |
| -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------ |
| 2026-10-12, independent QA agent (owner-delegated, #1778), the pack's path-list form at `8f81382`, loopback-only namespace | 1685 passed, 1 skipped (S1b), 9 deselected, 0 failed | 36.7 s tests, 43.5 s wall      |
| 2026-10-16, the implementing lane (an author run, not independent), main `b11174a3` plus #2678, Python 3.14.4, loopback-only        | 2866 passed, 1 skipped, 0 failed, 9569 deselected    | 74.18 s tests, 1 min 20 s wall |
| 2026-10-16, CI `py` lane run 38858627015 (PR #2539), whole tree                                                            | 13568 passed, 0 failed                               | not recorded                   |

Not re-run for this draft (read-only, no docker): the PR's own `py` lane runs the same tests and the guard, and the pack should be re-run at R0 (condition C1, section 10). The one skip is `services/api/tests/chaos/auth/test_auth_chaos.py` S1b, which needs the docker stack; the CI `integration` job runs it. The A07 timing test is `perf`, outside the marker, and runs in `py-perf` (pack lines 159-161). The Playwright specs `apps/web/e2e/auth/*.spec.ts` run in `e2e-web`; the real-backend lane is in section 7. The pack's corrected lines in this change (SR-122 and SR-016 rows, section C) cite tests that exist on main: `services/api/tests/security/auth/test_no_token_in_logs.py` (#2166) and `services/api/tests/security/auth/test_lockout_owner_alert.py` (#2628).

## 4. Exploratory debrief

Four sessions, run in-process by one AI agent on 2026-10-09 and committed together in #2098: no staging build, no browser recording, no 60-120 minute time box, no docker (each charter says so under "Deviation"). Charters 2 and 3 have no keyboard-only segment. None observed an anomaly in-process (charter 1 adds that this is not evidence of absence). The re-run with a browser on staging is pack step M7, deferred with #2491.

| Charter                                                 | Anomalies       | Follow-ups                                                                                                                   |
| ------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `docs/qa/charters/E09-charter-1-auth-state-machine.md`  | none in-process | #2099 (password change during a live step-up, open); E2E for A02, A05, A06, A09, A10, A11 once SCR-002 exists (#1640, #2711) |
| `docs/qa/charters/E09-charter-2-rbac-boundaries.md`     | none in-process | none beyond the tracked items                                                                                                |
| `docs/qa/charters/E09-charter-3-session-concurrency.md` | none in-process | #2100, the interleaving test (pinned by #2597; the refusal is #2593)                                                         |
| `docs/qa/charters/E09-charter-4-onboarding-lockout.md`  | none in-process | none                                                                                                                         |

The four debriefs are attached to the epic by the comment on #36 that links them with this document (the Security sign-off comment of 2026-10-29, 6503533777, links none).

## 5. Pass or fail per story group

Groups follow the sections of `qa/plans/e09-regression-pack.md` (line numbers are the pack's, after this change). PASS means every automated case of the group is green in the runs of section 3; the manual half is its own group.

| Group                                     | Pack lines   | Verdict           | Note                                                                                                                                                                         |
| ----------------------------------------- | ------------ | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A01-A11 sign-in, TOTP, lockout            | 59-68        | PASS              | The SPA's TOTP step is not built (#2711), so the E2E halves of A02, A05, A06, A09, A10 and A11 wait for it (pack line 127).                                                  |
| B01-B05 enrolment, recovery codes         | 69           | PASS              | Standalone SCR-003 E2E is manual M3, blocked: SCR-003 is not built and has no owner ticket (untracked, pack line 127).                                                       |
| B06-B09 forced password change and policy | 70           | CARRY             | A stubbed spec and a policy unit test only; `PUT /auth/password` is not mounted: #2330, #2110, #2099 (a backend lane).                                                                  |
| C01-C09 session and step-up               | 71-76        | PASS              | The UI half of C02 and C03 is manual M1, C08 latency is manual M4 (k6 figures in section 7); the real lane runs idle lock and step-up expiry on a server clock (#5170).      |
| D01-D06 session management, revocation    | 77-79        | PASS              | Includes the revocation storm (chaos s4, section 7).                                                                                                                         |
| Concurrency: role revoked mid step-up     | 80           | CARRY (AC4)       | Atomicity and audit order pass (#2597); the refusal needs #2593 (the E09 closure lane).                                                                                                     |
| E01-E09 invites, onboarding, RBAC         | 81-86        | PASS              | E08 (no reach from outside the tailnet) is manual M5, env-only.                                                                                                              |
| Audit and fail closed                     | 87-88, 114   | PASS              | The two audit grant tests are `integration` (the CI job runs them); the audit-chain verifier (#2111) closed on 2026-10-23.                                                   |
| Security controls SR-xxx (B2)             | 107-114, 116 | PASS with carries | SR-122 and SR-016 are now evidenced (#2166, #2628). Open: SR-013 on a role change (#2101), SR-112 web-served CSP (#1230), SR-011 per-verify cost on the target host (#2097). |
| CSRF position                             | 122          | PASS              | Double-submit token enforced since #2238 (2026-10-13), which closed #2090.                                                                                                   |
| Manual steps M1-M8                        | 94-101       | NOT RUN, env-only | Needs a staging deploy and a human: #2491 (deferral, section 2).                                                                                                             |

## 6. Coverage and the white-box statement (`docs/plan/03-testing-strategy.md` §11.4)

Coverage, **as of 2026-10-16 (the web slice 2026-10-15), re-measure at R0**: the floors are 85 % lines and 75 % branches for `services/api/**` and 80 % for `apps/web/**` (C-9.4). Main has taken many merges since, so condition C1 (section 10) asks for a fresh run.

| Module                          | Lines                                              | Source                                                    |
| ------------------------------- | -------------------------------------------------- | --------------------------------------------------------- |
| `candleviewer/auth/`            | 98.0 % (97.4 % with branches)                      | CI run 38858627015 coverage table (the 2026-10-16 record) |
| `candleviewer/audit/`           | 99.7 %                                             | same                                                      |
| `candleviewer/api/step_up.py`   | 89.4 %                                             | same                                                      |
| `services/api` total            | 96 %                                               | same                                                      |
| `apps/web/src/features/auth/**` | 91.92 % lines, 94.12 % functions, 81.31 % branches | pack D1, lines 145-149                                    |
| wider auth slice (13 files)     | 94.83 % lines, 86.90 % functions, 86.67 % branches | pack D1                                                   |

White-box statement. This is QA's reading of the §11.4 checklist for E09 from the records cited here, not a fresh code review; the reviewers' own checklist runs on every PR:

- Logic has tests at the right layer: unit, security-abuse, contract, chaos and the timing test (pack lines 29-40).
- New routes have contract tests: the route matrix fails the build for an undeclared served route (pack line 86); the Security sign-off records 161 executed, 86 `not_mounted`, 11 `not_executable` and 0 pending.
- No live endpoints in tests: the pack runs loopback-only (section 3); C-13.5.
- Error paths are exercised: chaos s1-s5 and s1b (section 7); the lockout race (`services/api/tests/unit/auth/test_login_lockout_race.py`).
- Native stop-loss on every order path: not applicable, E09 has no order path; #2108 waits on `POST /orders` (E29).
- Storybook and axe for new UI: only the automated audit of section 7 was read; not re-checked here.

## 7. R0 release-test report (input for the PRR owner)

Each figure names its source; none is invented.

- **E2E on the real backend.** The real-backend auth lane (`.github/workflows/e2e-auth-real.yml`; #2490 closed by #5103, server-clock specs added by #5170) ran 15 of 15 tests green in dispatch run 41203332706 (3.3 minutes), and its mutation probe was red as required (re-assessment of 2026-10-31, #293). The stub-lane specs `apps/web/e2e/auth/*.spec.ts` run in `e2e-web` on every PR. #293 is Done at ten consecutive green runs of the 15-test suite on `main`, dispatch runs included (ruling decision 2; a backend lane keeps the count: comment 6547354097).
- **k6 and Argon2id** (`docs/qa/perf/e09-auth-perf-report.md`, lines 3-7 and 45-60). Hosted runner, `perf-ingestion-nightly` run 40944399030 on 2026-10-29, 3191 checks passed and 0 failed. `GET /auth/session` p95 23.62 ms against 100 (met); `POST /auth/mfa/verify` p95 172.89 ms against 400 (met); Argon2id step p50 217.7 ms against at least 100 (met); `POST /auth/step-up` p95 712.10 ms against 400 is **missed on the hosted runner** and judged only on the reference host. The reference-host run and its host spec are pending: #2105 (lines 100-101).
- **Chaos** (same report, lines 70-87). s1 Postgres outage, s1b real Postgres restart, s2 TOTP step skew, s3 WS gateway restart, s4 revocation storm and s5 session expiry under pressure all passed in CI run 38858627015 (2026-10-16); the `integration` job runs them on every PR. Not covered (lines 98-108): SR-015 and SR-016 over HTTP under load, clock skew on a running stack, a session-store sweeper (none exists).
- **Accessibility** (`docs/qa/a11y/e09-auth-a11y-audit.md`). The automated axe pass found 0 serious or critical violations on the 7 screens it assessed (SCR-001, 004, 006, 017, 019, 123, 154; lines 12-25 and 49). Five rows are "not assessed" (SCR-002, 003, 005, 111, 112, placeholders when it was written); the pack says SCR-005 and SCR-112 are built since (line 127), so those rows predate them and need a re-run. The manual NVDA and two-configuration passes need a human auditor and are pending (lines 67-78), and lines 73-74 still call the owner exception on #295 "NOT yet approved" although #295 closed on 2026-10-04 (the approving record was not found). **No full a11y verdict exists.**
- **Open bugs by severity** (section 9). P0: none as a bug in E09 scope — #293 is a test ticket and #1230 (E43-T01, the CSP chore, `area/auth-rbac`) is a chore routed to a frontend / Electron lane. P1 labelled: #2108 #2152 #2330 #2491 #2711 #2832 #2291 #2621. P2: #2593 (`type/bug`, fix ordered), #2716, #292. No priority label in the re-assessment's lists: #2110 #2101 #2099 #2695 #2904 #2105. Whether each P1 is a bug or a feature was not re-queried, except #2593 (bug) and #2330 and #2711 (features).
- **Not tested.** Anything on staging or in a browser: manual M1-M8 and the charters' staging re-run (#2491); the keyboard-only passes of charters 2 and 3; the human screen-reader passes; the k6 reference-host run (#2105); U10, a Security condition on #36 for before the GA cut.

## 8. Security deliverables (referenced, not signed off)

- **E09-X01** STRIDE (#196): `docs/security/threat-models/e09-auth-rbac.md` reads `Status: Final` (since 2026-10-23); #2832 stays open for the model's Verify names and closes with that correction (ruling decision 4).
- **E09-X04** review (#300), Done: the record is `docs/security/reviews/e09-auth-review.md` §7 (#4965, merged 2026-10-29). The delegated Security-engineer sign-off on #36 (comment 6503533777, 2026-10-29) is **PASS WITH CONDITIONS**: 14 sampled controls present and tested, 63 abuse cases (55 defended with named tests, 5 design decisions, 2 accepted findings, 1 tracked), no open Critical or High. Its conditions, with owners and dates: D12-1 #4961 (2026-11-05; closed 2026-10-30), ENV-1 #2105 (2026-11-26), triage rows R-1, R-2, R-4, FU-1 and M1-M3 (several are items of section 9), #2832, and the post-GA #2298 (the human staging repeat) and U10.
- That comment is the Security sign-off, not the QA sign-off: it links no debrief. The QA sign-off comment and the link to the four debriefs are posted on #36 by the orchestrator.

## 9. Open defects in E09 scope and deferred-defect acknowledgements (GitHub, 2026-10-31)

Source: the re-assessment of 2026-10-31 18:15Z and the ruling of record (comment 6547349544); the last column is the comment that rules the row; security rows carry id, class, clause and owner only. Priorities are the labels at that query; dates and review rows (R-1, R-2, R-4, FU-1, M1-M3, ENV-1) are the due dates in `docs/security/reviews/e09-auth-review.md` section 2, where the ruling gives none.

| Issue | Title                                                  | Class                      | Owner                                                       | Date                          | Ruling                              |
| ----- | ------------------------------------------------------ | -------------------------- | ----------------------------------------------------------- | ----------------------------- | ----------------------------------- |
| #293  | E09-Q02 real-backend auth lane, ten green runs         | P0 test ticket, time-gated | a backend lane (keeps the count)                                       | the tenth green run on `main` | 6547349544 (decision 2); 6547354097 |
| #2711 | SCR-002 TOTP challenge step on the login screen        | P1 feature                 | the E09 closure lane (first item)                           | none in the ruling            | 6547349544                          |
| #2330 | password-policy contract for SCR-004 and SCR-112       | P1 feature                 | a backend lane (password bundle, claimed 19:09Z)                       | none in the ruling            | 6547349544                          |
| #2110 | `PUT /auth/password` route                             | no priority (R-4)          | a backend lane (same bundle)                                           | 2026-11-26                    | 6547349544                          |
| #2099 | password change during a live step-up (test)           | no priority (R-4)          | a backend lane (same bundle)                                           | 2026-11-26                    | 6547349544                          |
| #2593 | step-up authority at the effect (AD-E06, AC4)          | P2 bug, security path      | the E09 closure lane                                        | fix ordered, no date          | 6547353657; 6547349544 (decision 1) |
| #2904 | trading posture after an audit-chain break             | decision, no priority      | ruled fail-closed; the wiring is a backend lane's with the audit CODEOWNER | none                          | 6547349544 (decision 5)             |
| #2152 | key-material custody (review M3, slices S4–S6)         | P1                         | a backend lane                                                         | 2027-02-25                    | 6547349544                          |
| #2101 | session rotation on a role change (SR-013, R-1)        | no priority, `blocked`     | a backend lane                                                         | 2026-11-26                    | 6547349544                          |
| #2291 | rules read scoping (SR-051, review M2)                 | P1, `area/rule-engine`     | a backend lane                                                         | 2026-11-05                    | 6547349544                          |
| #2621 | security-ticket delivery (SR-016, review M1)           | P1                         | a backend lane                                                         | 2026-11-26                    | 6547349544                          |
| #2108 | 12 h trading-capability freshness (R-2)                | P1, `blocked`              | deferred on E29's `POST /orders`                            | 2027-02-04                    | 6547349544                          |
| #2832 | threat-model Verify names                              | P1 docs                    | orchestrator, in the docs PR                                | closes with the fix           | 6547349544 (decision 4)             |
| #2491 | pack M1-M8 and the charters on staging                 | P1, env-only               | deferral (#1778 AA)                                         | post-GA (#2298)               | 6547349544 (decision 3)             |
| #2695 | TOTP throttle scope (severity pending)                 | unrated, needs severity    | severity set in its first comment                           | none                          | 6547349544                          |
| #2094 | rules-manager grant isolation test (FU-1)              | test gap, Medium           | Backend (review row FU-1)                                   | 2026-11-26                    | none (review row FU-1)              |
| #2105 | env-dependent verification (ENV-1)                     | env-only                   | Backend (review row ENV-1)                                  | 2026-11-26                    | 6503533777                          |
| #2716 | CI lane for the `e09_regression` marker                | P2, `post-ga`              | not assigned                                                | post-GA                       | none                                |
| #292  | E09-K02                                                | P2                         | follows #297 to Done                                        | with #297                     | 6547349544                          |

Design-lane children are design tickets, not bugs, and do not count under AC2 (ruling decision 6): #194 (D12) and #193 (D10), P0 in progress (v1 and PR 1 merged); #190 (D07, PR 2 of 3 merged), #188 (D05, PR 2b left) and #291 (D11, untouched), P1. Closed since the record: #4961 (D12-1) on 2026-10-30. Pack gaps carried as the pack's section C lists them: #2097 (review row FU-3: Backend, due 2027-02-04) and #1230 (E43-T01, the CSP chore; labelled P0, routed to a frontend / Electron lane by the orchestrator on 2026-10-31).

## 10. Proposed verdict, conditions and status

**Proposed: PASS_WITH_CARRIES as of 2026-10-31.** The automated half of the pack was green when last run (2026-10-12 and 2026-10-16), the four debriefs exist, AC3 passes, and every open P0 or P1 item has an owner (#1230 routed on 2026-10-31; #2097 per review row FU-3), with a date where the Security sign-off or the review gave one. It is not a clean pass: AC2 and AC4 are open (section 2), and no PR was open for any of them at 18:15Z (since then #2711 has the lane's questions, posted 19:04Z, and the password bundle is claimed, 19:09Z). A clean PASS is not possible within a day; the recorded carries are #2330, #2110 and #2099 (a backend lane), #2152 and #2101 (a backend lane), #2291 (a backend lane) and #2621 (a backend lane), with the dates above if they are still open at the verdict.

| Id  | Condition                                                                                    | Owner        |
| --- | -------------------------------------------------------------------------------------------- | ------------ |
| C1  | At R0, not a gate for Done: the pack re-run on `main` and the section 6 coverage re-measured | QA           |
| C2  | This docs PR merged: the pack's stale lines and this document                                | orchestrator |
| C3  | #2711 merged: the SPA finishes a TOTP sign-in                                                | the E09 closure lane        |
| C4  | #2593 merged: AC4, the action is refused at the effect                                       | the E09 closure lane        |
| C5  | The #293 count completes: ten consecutive green runs of the 15-test suite on `main`          | a backend lane          |

**Status: PASS_WITH_CARRIES pending.** #297 stays In Progress and moves to Done when this docs PR, #2711 and #2593 are merged and the #293 count completes (ruling of record). #292 (E09-K02) and #963 (E42-T01) follow it to Done.
