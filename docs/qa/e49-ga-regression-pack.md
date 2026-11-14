# E49 GA regression pack: coverage map

Ticket: E49-Q01 (#1335), S1. Base: `main` `fdad0285f`. Rulings: the BQ ruling on #1335. Each per-epic
pack page keeps its own cases; the one generated table here is the story-to-test table at the end.

## How a test joins the pack

- **Tag.** A shipped test joins by its title: `@ga-regression` plus exactly one `@ga-area-<slug>`, the
  slug one of `auth`, `trading`, `multi-account`, `rules`, `alerts-journal`, `replay`, `admin`,
  `state-matrix`, `shell` (the title-tag convention `@flaky`, `@e17-regression` and `@electron` follow).
  A `fixme`, `skip`, `fail` or `@flaky` test is never tagged (AGENTS.md section 8). A web pack spec takes
  `test` from `apps/web/e2e/support/pack.ts`; a desktop one launches and closes through
  `apps/desktop/e2e/support/shell.ts`, so each runs behind the egress guard (CI-E2E-005).
- **Stories.** A test names the stories it guards by `@US-<D>-<nnn>` title tokens, or by E17's
  `covers(...)` call. Only an id of the shape `US-<D>-<nnn>` is read; it must be a heading of
  `docs/plan/11-user-stories.md`. `US-<D>-<nnn>#<Scenario>` cites one scenario of that heading and never
  covers the story: its cell keeps the fragment, its status reads `partial`, and its gaps row names every
  scenario no pack test cites. Every gaps reason starts with a word of the gaps file's vocabulary.
- **Entry rule.** E17's (`qa/plans/e17-regression-pack.md`): a tagged test is `candidate (n/10)` until
  10 consecutive green nightly runs with zero retries, then `in`. The count lives in the nightly record
  below, one row per test (`<spec> › <title without tags>`); a red or retried nightly sets it back to 0.
  A story's status is `in (k)`, k its tests that are in, else `candidate (n/10)`, n the most greens any
  one of its tests has.
- **Gate.** `apps/web/test/e2e-ga-pack.test.ts` (`unit-frontend`) builds the map from the specs with
  nothing run: CI-E2E-004 for the tag rules, CI-E2E-003 for the map's (`docs/ci-runbook.md` section 4).
  Must counts by the leading priority token: 184. Gaps: `docs/qa/e49-ga-regression-gaps.md`.

## Per-epic pack pages

| Epic | Page                              | Note                      |
| ---- | --------------------------------- | ------------------------- |
| E04  | `qa/plans/e04-regression-pack.md` |                           |
| E08  | `qa/plans/e08-regression-pack.md` |                           |
| E09  | `qa/plans/e09-regression-pack.md` |                           |
| E17  | `qa/plans/e17-regression-pack.md` | its cases also carry tags |
| E11  | the pack page of #5796            | if #5796 merges as is     |
| E29  | the pack page of #5752            | if #5752 merges as is     |

## Areas

`covered`: shipped and tagged. `parked`: the surface has not shipped; the row names its owner. `gap`: shipped
or required, not in the pack; the row says why. Route owners are those of `apps/web/src/routes/manifest.ts`.

| Area or item                                | State   | Where, and why                                                                                                                                                                                                                                 |
| ------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| auth                                        | covered | the stub-lane specs `apps/web/e2e/auth/*.spec.ts`, `login`, `onboarding`, `invites`, `e09-auth-a11y`; the real lane's `*.real.ts` are not tagged in S1                                                                                         |
| trading                                     | parked  | the terminal R-101 renders a stub (`apps/web/src/routes/tree.tsx:71-80`), owner E15                                                                                                                                                            |
| bars and series                             | parked  | #419: the six `apps/web/e2e/specs/e12-bars/` files are describe-level `test.fixme` (10 tests) until the chart route and SCR-041 (E12-D04), SCR-045 (#521) and SCR-046 (#523) land, as `candles.spec.ts`'s `BLOCKED_UI` says                    |
| multi-account                               | parked  | trade groups R-140 to R-142 and risk R-150 render stubs, owner E12                                                                                                                                                                             |
| rules                                       | parked  | no route body renders the editors, owner E14                                                                                                                                                                                                   |
| alerts centre R-190                         | gap     | shipped (`apps/web/src/routes/tree.tsx:51`), with no spec of its own beyond route-level role and CSP cases                                                                                                                                     |
| journal                                     | parked  | R-180 to R-182 render stubs, owner E17                                                                                                                                                                                                         |
| replay                                      | parked  | R-170 and R-171 render stubs, owner E16; its specs will assert golden outputs (RSK-028)                                                                                                                                                        |
| admin                                       | covered | `apps/web/e2e/admin/*.spec.ts`; the API allow and deny of every route is E09-Q03's `services/api/tests/contract/rbac/matrix.yaml`, keyed by route (`METHOD /path`) and run by `test_route_matrix.py`: no second matrix                         |
| admin past the overview                     | parked  | `apps/web/src/features/admin/shell/AdminArea.tsx:33-37` renders a stub for every admin route but R-300, R-303 and R-354, owner E18                                                                                                             |
| admin R-303 (SCR-123)                       | gap     | shipped (`AdminArea.tsx:35`); no spec of its own, driven inside the `auth/stepup`, `admin/admin-shell` and `e09-auth-a11y` specs                                                                                                               |
| 3 shipped tests untagged in S1              | gap     | their titles are listed in the S1 pull request; they stay in every PR lane                                                                                                                                                                     |
| state-matrix                                | parked  | E49-Q04 (#1362) is open                                                                                                                                                                                                                        |
| shell, web and Electron `dist`              | covered | `apps/web/e2e/shell/`, the shell and system-state specs, `csp/`, the E17 transport specs, the `apps/desktop/e2e` specs that launch through `support/shell.ts`                                                                                  |
| desktop specs that launch Electron directly | gap     | `hardening`, `app-protocol` and `backend-connection-probe` (8 tests) call `_electron.launch` themselves, so CI-E2E-005 keeps them out of the pack until they launch and close through `support/shell.ts`; they stay in the `e2e-electron` lane |
| Electron auto-update prompt                 | parked  | a disabled stub until code signing (`apps/desktop/src/main/updateChannel.ts:1-6,18-20`), E48                                                                                                                                                   |
| Electron floating windows                   | parked  | no window-detach code in `apps/desktop/src/main/`                                                                                                                                                                                              |
| Windows Electron leg                        | parked  | `03-testing-strategy.md` line 208 asks for Windows and Linux; `e2e-electron` runs on ubuntu only (`_job-e2e.yml:223`). Parked until the owner decides (the #2701 digest): a later `windows-latest` leg of `e2e-electron`, or a waiver          |
| web `@electron` tests                       | gap     | the comments said they also run in the Electron lane; no config selects `@electron` (`apps/desktop/e2e/playwright.config.ts`), so S1 corrects the two comments (`auth/login.spec.ts:8`, `auth/session.spec.ts:25`)                             |
| sockets inside a worker                     | gap     | the egress guard cannot see a socket opened in a shared or service worker (`packages/fixtures/src/e2e/egress.ts:40-41`)                                                                                                                        |
| axe on each pack scenario                   | parked  | a DoD item of #1335 for a later slice; today axe runs in the `a11y-axe` job and in the tagged `e17/accessibility`, `e09-auth-a11y`, admin and shell-chrome specs                                                                               |
| SCR-150 cold start 2.5 s                    | parked  | measured, never asserted, by `apps/desktop/e2e/perf/cold-start.perf.ts` (recording only); a smoke assertion is a later #1335 slice                                                                                                             |
| SCR-154 403 render 200 ms                   | parked  | `auth/denied.spec.ts` renders SCR-154 with no timing assertion; a later #1335 slice                                                                                                                                                            |
| SCR-152 reconnect 5 s                       | parked  | the E17 specs drive reconnects on a fake clock; `e17/realtime.nightly.ts` is not in a job yet; a later #1335 slice                                                                                                                             |

## Nightly record

No nightly has been counted yet: every tagged test is `candidate (0/10)`.

| Test | Greens |
| ---- | ------ |

## Story-to-test table (generated)

<!-- ga-map:begin -->

| Story                             | Priority | Area  | Pack tests (by spec)                                                                                                     | Status                    |
| --------------------------------- | -------- | ----- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------- |
| US-ADMIN-011                      | Must     | admin | `apps/web/e2e/admin/admin-overview.spec.ts` (4)                                                                          | candidate (0/10)          |
| US-MKT-003#Feed interrupted       | Must     | shell | `apps/web/e2e/e17/transport-states.spec.ts` (2)                                                                          | partial, candidate (0/10) |
| US-MKT-005#Reconnect, #Subscribed | Must     | shell | `apps/web/e2e/e17/transport-states.spec.ts` (6)                                                                          | partial, candidate (0/10) |
| US-MKT-006#Gap detection          | Must     | shell | `apps/web/e2e/e17/transport-states.spec.ts` (1)                                                                          | partial, candidate (0/10) |
| US-MKT-007#Sequence break         | Must     | shell | `apps/web/e2e/e17/transport-states.spec.ts` (1)                                                                          | partial, candidate (0/10) |
| US-ONB-001                        | Must     | auth  | `apps/web/e2e/auth/login.spec.ts` (3), `apps/web/e2e/auth/session.spec.ts` (3), `apps/web/e2e/login.spec.ts` (7)         | candidate (0/10)          |
| US-ONB-002                        | Must     | auth  | `apps/web/e2e/auth/login.spec.ts` (12)                                                                                   | candidate (0/10)          |
| US-ONB-003                        | Must     | auth  | `apps/web/e2e/auth/onboarding.spec.ts` (4), `apps/web/e2e/e09-auth-a11y.spec.ts` (6), `apps/web/e2e/invites.spec.ts` (2) | candidate (0/10)          |
| US-ONB-004                        | Must     | auth  | `apps/web/e2e/auth/session.spec.ts` (9)                                                                                  | candidate (0/10)          |
| US-ONB-005                        | Must     | auth  | `apps/web/e2e/auth/stepup.spec.ts` (10)                                                                                  | candidate (0/10)          |
| US-ONB-006                        | Must     | auth  | `apps/web/e2e/auth/onboarding.spec.ts` (4), `apps/web/e2e/invites.spec.ts` (2)                                           | candidate (0/10)          |
| US-ONB-007                        | Should   | auth  | `apps/web/e2e/auth/onboarding.spec.ts` (1), `apps/web/e2e/onboarding.spec.ts` (2)                                        | candidate (0/10)          |
| US-ONB-009                        | Should   | auth  | `apps/web/e2e/auth/session.spec.ts` (2)                                                                                  | candidate (0/10)          |
| US-SET-004                        | Must     | shell | `apps/web/e2e/shell-bootstrap.spec.ts` (2)                                                                               | candidate (0/10)          |

<!-- ga-map:end -->
