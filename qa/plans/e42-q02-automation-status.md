# E42-Q02 (#1215) automation status

Version 2, as built by parts 1 and 2 (the API half) of 6: the real-lane admin harness, the route-guard
walk, the first cross-session spec, and the flags and maintenance real specs; no product code. Case ids are `docs/qa/e42-admin-test-plan.md` (E42-Q01, #962),
101 cases. This file maps the 61 at the `e2e` layer; the contract, integration, security, perf, a11y
and unit cases belong to E42-X03, the E42-T0x modules, E42-Q03 and E42-Q05, and part 6 points at them.

- **Specs:** `apps/web/e2e/admin/` (repo convention; the ticket says `tests/e2e/admin/`, the deviation
  E09-Q02 recorded). The ticket's eight spec names are the stories' own stub specs, which Q02 never
  edits [BQ-1]: on `main` today S01's `admin-shell.spec.ts` and `admin-overview.spec.ts`; the others
  land with their stories. Q02 adds the guard walk, the cross-session specs and the tab-order spec.
- **Stub lane** (`*.spec.ts`, the `e2e` job on every pull request touching `apps/web/**`):
  `admin-routes.spec.ts` [BQ-6] walks every `/admin` route of the router's own manifest as a manager
  and as a viewer: the 404 an unknown route shows, word for word and with the same page title, with no
  admin code and no admin or users call; R-360 is the one closed exception (a manager's renders, a
  viewer's is the 403); one axe scan. Its pure half, `admin/adminRoutes.ts`, is the ticket's
  meta-test, repeatable: `apps/web/test/e2e-admin-routes.test.ts` feeds it synthetic unguarded routes.
- **Real lane** (`*.stack.ts`, `e2e/playwright.admin-stack.config.ts`, one test at a time):
  `.github/workflows/e2e-admin-real.yml`, nightly at 03:39 UTC and on dispatch, never on a pull
  request; non-required [BQ-2, BQ-3, BQ-9]. Job `testnet`: a throwaway stack as `e2e-auth-real.yml`
  builds it, with fixture users seeded by role. It files an issue on a red nightly: its `report` job
  comments on, or opens, the `e2e-admin-real` signal's issue (`_nightly-issue.yml`) from main only.
- **Harness:** `support/real/stack.ts` reads a role per user and claims by role (E09's file reads as
  before); `support/real/adminWorld.ts` opens page actors (the SPA's session, its socket tapped) and API
  actors (the bearer kept in the page; real step-ups, `elevate` and `withChallenge`). A refresh and a
  step-up each rotate the session, so the two kinds never share one. Both sign in as a real client
  does: the password on SCR-001, the TOTP code from the user's own seed at `/auth/mfa/verify`, and
  the real `/auth/step-up`; nothing bypasses MFA or step-up. Unit tests:
  `apps/web/test/e2e-admin-lane.test.ts`.
- **Timings** [BQ-4]: judged on the server's audit stamps where they exist, the runner's figure kept
  beside them; one `test-results/timings/<case>.json` per case and run, uploaded 14 days as
  `e2e-admin-timings` pass or fail, so the series is the trend.

Statuses: **S** a story's stub spec; **Q** a Q02 spec; **X** another layer's owner, named; **B**
blocked, with its reason; **M** manual by design, with its reason; **P** planned in the part named,
waiting on the merge named.

| Cases                              | Status                                                                                                                                                                                                                                                |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AD-S01-01                          | S `admin-shell`, `admin-overview`; Q `admin-cross-session.stack.ts` (the real half: the band first, the overview read, no step-up, each admin read's `admin.area_entered` allowed)                                                                    |
| AD-S01-02                          | S `admin-shell` (three routes); Q `admin-routes.spec.ts` (every route, both roles); the server half X E42-X03's matrix                                                                                                                                |
| AD-S01-03, AD-S01-05               | S `admin-overview`; AD-S01-03's 800 ms is X E42-Q03                                                                                                                                                                                                   |
| AD-S01-04, N02, N03, N04           | S `admin-shell` (the challenged invite, re-sent once); the real half X `step-up-expiry.real.ts` (E09-Q02)                                                                                                                                             |
| AD-S01-N06                         | S `admin-overview` (S01's marker), and each later story's spec its own; the registry check X (unit)                                                                                                                                                   |
| AD-X-01                            | Q `admin-cross-session.stack.ts` (audit records: each session revoked within 5 s, `bye user_disabled` then 4403, the next call refused, SCR-001, a stale `ETag` refused); the rule bullet X E42-T04's drill (#4254); the order bullet P part 5 [BQ-2] |
| AD-S02-01, -02, -03, -04, -06, N04 | P part 3, after #1023: S `admin-users`; Q `admin-lifecycle.stack.ts`                                                                                                                                                                                  |
| AD-S02-05, N05                     | P with #1023: S `admin-users`                                                                                                                                                                                                                         |
| AD-S03-01, -02, N04, N05           | P part 5, after #1134: S `admin-user-detail`; Q `admin-grants.stack.ts` (the demo job)                                                                                                                                                                |
| AD-S03-03, -04                     | B: no position source (Q-4)                                                                                                                                                                                                                           |
| AD-S03-05, N02                     | P part 3, after #1134: S `view-as`; Q `admin-view-as.stack.ts`; AD-S03-05's protective-writes half B (the six handlers are not mounted)                                                                                                               |
| AD-S03-06                          | P part 3, after #1134: S `admin-user-detail`; Q `admin-lifecycle.stack.ts` (two owners)                                                                                                                                                               |
| AD-S04-01, -02, -03, -05, -07      | P part 4, after #1135: S `admin-audit`; Q `admin-audit.stack.ts` (the corrupt database for -03); the 2 s and 400 ms X E42-Q03                                                                                                                         |
| AD-S04-04                          | API half P part 4, after #1135; UI half B (Q-19)                                                                                                                                                                                                      |
| AD-S04-06                          | P with #1135: S `admin-audit`                                                                                                                                                                                                                         |
| AD-S05-01, -05, N01                | S `admin-flags`, `admin-maintenance` (#1024); Q `admin-flags.stack.ts` (the API half: each role's push within 10 s, the owner-only key to the owner alone, two writes in a second, maintenance on and off); the UI half P part 2, after #1024         |
| AD-S05-02, -03, -06                | S `admin-flags` (#1024); Q `admin-flags.stack.ts` for -02 (the API half; the UI half through SCR-006 P part 2, after #1024); -03's `fail_closed` B (no seed reaches it)                                                                               |
| AD-S05-04                          | P with #1024: S `admin-flags`; the API half X E42-Q06 (#1219)                                                                                                                                                                                         |
| AD-S05-07                          | B (Q-29)                                                                                                                                                                                                                                              |
| AD-S06-01, -02, -03, -04, -07      | P with #1084: S `admin-health`, `admin-backups`; AD-S06-04's "stale since" B (Q-27); backups on a real stack B (#3319)                                                                                                                                |
| AD-S06-05, -06                     | B: the restore is not mounted, and backups answer `501`                                                                                                                                                                                               |
| AD-S06-N01                         | P part 4, after #1084: S `admin-incidents`; Q `admin-audit.stack.ts` (the chain break's incident)                                                                                                                                                     |
| AD-S07-01, -06                     | B: S07 not built; the plan's fixture transport refuses every request (E27's stack may change that)                                                                                                                                                    |
| AD-S07-02, -03, -07                | P with #1136: S `admin-onboarding`; -07's step-up path Q once S07 merges                                                                                                                                                                              |
| AD-S07-04                          | B: `POST /trade-groups` is not mounted                                                                                                                                                                                                                |
| AD-S08-01, -04                     | P with #1137: S `admin-inspector`; the real read M (in process only: no deployed key provider)                                                                                                                                                        |
| AD-S08-02                          | B (Q-7)                                                                                                                                                                                                                                               |
| AD-X-02                            | P part 5: Q `admin-grants.stack.ts` (the demo job)                                                                                                                                                                                                    |
| AD-X-03                            | Q `admin-flags.stack.ts` (the notice half: a manager's notice within 2 s, its role's fields only); the order half P part 5, `admin-grants.stack.ts`                                                                                                   |
| Tab order: elevate, delete a user  | P part 3: Q `admin-tab-order.spec.ts`; "run a restore" B (the restore is not mounted)                                                                                                                                                                 |

Real lane, by case (`apps/web/e2e/admin/admin-cross-session.stack.ts`; every title ends `@regression`):

- **AD-S01-01:** "E42-Q02 AD-S01-01 (real half) an owner opens /admin: the band first, the overview
  read, no step-up asked, each admin read recorded as allowed".
- **AD-X-01:** "E42-Q02 AD-X-01 the owner disables a signed-in manager: its records show every session
  revoked within 5 s, bye user_disabled then 4403, the next call refused, then SCR-001". The 5 s is
  judged on the server's stamps: from the `users.disable` record, written ahead of its commit, to the
  last of the manager's `auth.session_revoked` (`user_disabled`) records. The runner's figure (the
  refusal, bounded at 15 s) is kept beside it as trend data.

Real lane, by case (`apps/web/e2e/admin/admin-flags.stack.ts`, part 2, the API half; every title
ends `@regression`):

- **AD-S05-01:** an all-roles flag (`rules.graph_editor`) written by an owner in its `flags` grace
  reaches an owner's, a manager's and a viewer's socket; the 10 s (Q-21) is judged from the write's
  write-ahead `flags.change` record to the last socket's frame `ts`. The owner-only
  `maintenance.keep_recorder`, written there and back, reaches the owner's socket alone; the
  all-roles write back is the barrier, so no sleep.
- **AD-S05-02:** with no grace, `trading.one_click` answers `403 step_up_required` (`flags`) and
  writes nothing; after the step-up the one re-send lands. `killswitch.order_entry` engages in the
  grace with no challenge, and its release is challenged (`killswitch`) and answered with a fresh
  code. No `flags.change` for either challenged request; the step-up records in QA's order.
- **AD-S05-N01:** `rules.form_editor` written twice inside a second, the second on the first's
  `updated_at`: the records in order (the gate), and a manager and a viewer end on the second value
  within 10 s; the gap between the two records is kept as trend data (1 s), not asserted.
- **AD-S05-05 and AD-X-03 (notice half):** maintenance on in the `flags` grace, off as a challenged
  `killswitch` release; a manager gets `maintenance.enabled` (`warning`) and `maintenance.disabled`
  (`info`) notices with `kind`, `severity`, `message` and `reason` alone; the 2 s is judged from the
  write's write-ahead record, since `maintenance.enabled` is written after the push [BQ-4].
- Every test reads a flag before writing it and writes back what it read, and a `test.afterEach` puts
  every flag it read back even when the test failed half way (a step-up answered, no new grace or
  owner); none writes or names `trading.live_enabled` (the file's last hook checks every request's
  URL and body, and that it saw some).

Both files:

- **The refresh budget:** the lane's API allows 10 cookie-presenting refreshes a minute; the fixture
  paces the run under 8. Each test declares its count: 10 in all (AD-S01-01 1; AD-X-01 3, the
  manager's page load, its refused call and its SCR-001 page load; AD-S05-01 3, AD-S05-02 0,
  AD-S05-N01 2, AD-S05-05 1, one per page load; an API actor presents none).
- **Users:** the workflow seeds 7 owners, 4 managers and 2 viewers, one per claim;
  `apps/web/test/e2e-admin-workflow.test.ts` holds the seeds at least the specs' claims.

Manual by design: the screen-reader script (E42-Q05's), the exploratory charters (E42-Q04's) and
CH-AD-1 to CH-AD-5 (`docs/qa/e42-admin-test-plan.md` §4).

Recorded deviations (orchestrator ruling on #1215 part 1, 2026-11-04):

- **C1, two actor kinds** (page and API): a step-up rotates the session, so the SPA and a test-held
  bearer cannot share one. Both sign in through the real login, TOTP and step-up: no test-only bypass.
- **C2, AD-X-01 declares 3 refreshes**, not the plan's 2: the reason is the rotation on step-up, which
  keeps the owner an API actor; the manager's page load, its refused call and its SCR-001 page load
  each present `cv_refresh`.
- **C3, no pull request trigger:** the lane runs nightly and on dispatch only (no label trigger).
- **C4, registered as a nightly signal:** its row in `scripts/tests/test_nightly_issue.py`, and its
  `report` job files an issue on a red nightly from main.

The other `[BQ-n]` marks above are the places a later ruling could change.

Not done here: part 2's UI half (after #1024) and parts 3 to 6, as the table says; the real lane's ten consecutive green nightlies after
the merge, and the stub specs' nightly `--repeat-each=10` job [BQ-5]; the contract module (part 6)
[BQ-8]. #1215 stays open until the blocked list is empty [BQ-10].
