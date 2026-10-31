# E10 shell: black-box test plan and coverage map

- Ticket: E10-Q02 (#301), which absorbed the withdrawn E10-Q01 (plan) and E10-X03's per-PR subset.
- Surface: the reduced E10 shell (route tree and guards, hardened Electron main/preload, update-channel
  stub, DEMO/LIVE badge in the chrome, keymap registry, error boundary and crash log).
- The two invariants every step and charter targets: **I1** the environment badge is never absent or
  wrong; **I2** no route guard can be bypassed from the client. The client is never the boundary: the
  server enforces RBAC (C-12.4), proven by the backend RBAC suites, not here.
- Stubs only: the API is answered at the network layer (`@candleviewer/fixtures/e2e/stubs`), the
  gateway by the E08-Q05 WS harness. No secret is read and no live environment is reachable; an egress
  guard fails any test whose browser or shell sends a request past the loopback interface (C-13.5).
  In the shell the guard is installed once the app is ready, so main-process requests made during
  startup, before it is installed, are not seen by it.

## 1. How to run

| What                  | Command (from the repo root)                                                                                                                                  |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Build first           | `pnpm --filter "@candleviewer/web^..." run build && pnpm --filter @candleviewer/web build && pnpm --filter @candleviewer/desktop build`                       |
| Web suite (all specs) | `pnpm --filter @candleviewer/web e2e`                                                                                                                         |
| Web shell specs only  | `pnpm --filter @candleviewer/web e2e e2e/shell/`                                                                                                              |
| Abuse subset only     | `pnpm --filter @candleviewer/web e2e --grep @abuse` (and the same for `@candleviewer/desktop`)                                                                |
| Electron suite        | `xvfb-run -a pnpm --filter @candleviewer/desktop e2e` (Linux; a display is enough elsewhere)                                                                  |
| Packaged smoke        | `electron-builder --dir` in `apps/desktop`, then the Electron suite with `CV_PACKAGED_EXECUTABLE` set to the built executable (the `packaged` project)        |
| Support unit tests    | `pnpm --filter @candleviewer/fixtures test` (the `e2e` subpath's tests are `test/e2e/`); the table check is `apps/web/test/routes/route-expectations.test.ts` |

CI: the `e2e` lane of `pr.yml` runs the web suite sharded in `e2e-web` and the Electron suite,
packaged smoke included, in `e2e-electron`, on every PR its path filter selects. Traces, video and
screenshots are kept on failure for 7 days; the screenshot corpus is uploaded on every run.

## 2. Plan steps and coverage map

Each automated case carries the `@plan-<step>` tag of the step it covers. "Existing" rows are cited,
not rewritten.

| Step | Scope bullet / case                                                                                                                                                | Automated by                                                            | Status                        |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- | ----------------------------- |
| RM-1 | Routing and RBAC: every manifest route × owner, manager, viewer (198 cases), outcome declared in `ROUTE_EXPECTATIONS`; a route without one fails                   | web `e2e/shell/role-matrix.spec.ts`; table vs manifest in the unit test | new                           |
| RM-2 | Routing and RBAC in the shell: one route per access class × 3 roles                                                                                                | desktop `e2e/abuse.spec.ts`                                             | new (subset, see §3), unrun ¹ |
| RM-3 | Admin 404 and forbidden as a viewer; denied routes fetch nothing                                                                                                   | web `e2e/auth/denied.spec.ts`                                           | existing                      |
| RM-4 | Step-up modal                                                                                                                                                      | web `e2e/auth/stepup.spec.ts`                                           | existing                      |
| EL-1 | Electron smoke: launch, sign in, reach `/terminal`, badge; SR-110 on every web contents                                                                            | desktop `e2e/shell-smoke.spec.ts`                                       | new, unrun ¹                  |
| EL-2 | SR-110 on every web contents, SR-112 header and `<meta>` directive by directive, no exchange host (SR-119), OS sandbox (seccomp + no_new_privs, no `--no-sandbox`) | desktop `e2e/shell-smoke.spec.ts`                                       | new, unrun ¹                  |
| EL-3 | The same on the packaged `--dir` build (`app.isPackaged`)                                                                                                          | desktop `e2e/packaged-smoke.spec.ts`                                    | new, unrun ¹                  |
| EL-4 | app:// load path, window.open denial, preload bridge                                                                                                               | desktop `e2e/app-protocol.spec.ts`, `e2e/hardening.spec.ts`             | existing                      |
| HK-1 | `Ctrl+K` reserved: taken by the shell (default prevented), opens nothing; `Ctrl+/` opens the cheatsheet dialog (re-read at #5214's merge)                          | web `e2e/shell/hotkeys-reserved.spec.ts`                                | new                           |
| HK-2 | Rebind, conflict, swap, persist across reload; Electron keymap                                                                                                     | web `e2e/hotkeys.spec.ts`; desktop `e2e/hotkeys.spec.ts`                | existing                      |
| SS-1 | WS dropped: Reconnecting, then Live; badge stays                                                                                                                   | web `e2e/shell/system-states.spec.ts`                                   | new                           |
| SS-2 | Backend killed mid-session: SCR-159 offline page; badge stays                                                                                                      | web `e2e/shell/system-states.spec.ts`                                   | new                           |
| SS-3 | WS kill, stall, desync at the protocol level                                                                                                                       | web `e2e/market-data/ws-harness.spec.ts`                                | existing                      |
| SS-4 | GPU unavailable: the GPU process is killed from main; SCR-159's GPU page takes the canvas; badge stays                                                             | desktop `e2e/system-states.spec.ts`                                     | new, unrun ¹                  |
| AB-1 | Admin deep links as manager and viewer: not found, no admin call                                                                                                   | web `e2e/shell/abuse.spec.ts`                                           | new                           |
| AB-2 | Stale `/me` after a server-side downgrade: the next navigation re-reads `/me` and denies                                                                           | web `e2e/shell/abuse.spec.ts`                                           | new                           |
| AB-3 | Badge suppression by hostile preference values or 200% zoom                                                                                                        | web `e2e/shell/abuse.spec.ts`                                           | new                           |
| AB-4 | Badge suppression by a foreign stylesheet: refused by `style-src 'self'`                                                                                           | web `e2e/shell/abuse.spec.ts`                                           | new                           |
| AB-5 | Renderer reaches no Node global and no raw IPC member on `window.cv`                                                                                               | desktop `e2e/abuse.spec.ts`                                             | new, unrun ¹                  |
| SC-1 | Screenshot corpus: 3 surfaces × 3 themes × 2 densities × 2 viewports, each captured twice and byte-identical                                                       | web `e2e/shell/capture.spec.ts`                                         | new (artefact only)           |
| CH-* | Chrome badge × 3 themes × 2 roles with axe                                                                                                                         | web `e2e/shell-chrome.spec.ts`                                          | existing                      |

¹ Typecheck and lint only so far: the Electron binary could not be fetched on the authoring host,
so no Electron spec, the `electron-builder --dir` packaging, the setuid sandbox-helper step or the
`/proc` seccomp read has run yet. Their first run is CI's `e2e-electron`; until it is green these
rows are unverified.

### 2a. Coverage by ticket Scope bullet

One row per bullet of the ticket's _Scope / Deliverables_ (BQ-02); the steps are the rows above.

| Scope bullet                                                                          | Covered by                                                                                                       | Not covered (see §3)                               |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Auth fixtures: owner, manager, viewer sessions                                        | `@candleviewer/fixtures/e2e/stubs` (network-layer `/me` per role; TOTP is never reached, no demo backend: BQ-12) | a seeded demo backend: the real lane (AGENTS §8.6) |
| Smoke (Electron): launch, login, `/terminal`, badge, SR-110, SR-112, no exchange host | EL-1, EL-2, EL-3                                                                                                 | none                                               |
| Windows (Electron): pop-out round trip, restore onto the primary display              | none                                                                                                             | both (E15)                                         |
| Routing and RBAC (web + Electron): manifest × three roles, admin 404, step-up         | RM-1, RM-2, RM-3, RM-4                                                                                           | the full matrix in Electron (subset RM-2)          |
| Hotkeys and palette: `Ctrl+K`, cheatsheet, rebind, conflict, swap, persist            | HK-1, HK-2                                                                                                       | `Ctrl+K` open and run (SCR-012)                    |
| System states: panel crash, route crash, offline, WS drop, GPU unavailable            | SS-1, SS-2, SS-3, SS-4                                                                                           | panel crash, route crash                           |
| Screenshot corpus: every shell surface × theme × density                              | SC-1                                                                                                             | committed baselines (artefact only, BQ-16)         |
| Flake controls: no `waitForTimeout`, condition waits, quarantine tag and policy       | every spec; `@flaky` nightly project; §4                                                                         | none                                               |
| CI wiring: `e2e-web`, `e2e-electron`, trace and video kept on failure                 | `pr.yml` `e2e` lane, `_job-e2e.yml`; §1                                                                          | marking them required (owner action, BQ-05)        |
| Absorbed E10-Q01: this plan and the charter set                                       | this file; `docs/qa/charters/` (five charters)                                                                   | none                                               |
| Absorbed E10-X03: per-PR abuse subset                                                 | AB-1 to AB-5 (`@abuse`)                                                                                          | the full campaign (E43)                            |

## 3. Deferred and not automated

| Case                                                 | Why                                                                                                                         | Owner                                                           |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Pop-out round trip; restore onto the primary display | windows and pop-outs moved to E15                                                                                           | E15-S02 #435 / E15-Q02 #552                                     |
| `Ctrl+K` palette open and run                        | E10-S05 builds it (filed by #5238); no palette to drive yet                                                                 | SCR-012 command palette, #5236 (E10-S05)                        |
| Forced panel crash, forced route crash               | no trigger a built app can reach, and no `apps/web/src` seam is added (BQ-14, C-4.9); the boundaries' unit tests cover them | E10-Q03 #302 (its axe pass renders the error-boundary fallback) |
| Full 198-case matrix in Electron                     | time budget (≤10 min); the shell runs one route per access class                                                            | this plan (RM-2)                                                |
| Client claims after a downgrade without a navigation | a SPA back/forward keeps the cached `/me` until the next full load; the server is the boundary                              | E43 adversarial campaign                                        |
| An inline `<style>` injected into the page           | `style-src` keeps `'unsafe-inline'` until nonces land (`apps/desktop/src/main/csp.ts`)                                      | E43 / the CSP nonce follow-up                                   |

## 4. Flake policy

C-9.3 governs, not the ticket's "one sprint": a flaky test is quarantined within 24 h with the
`@flaky` tag **and** a P1 ticket, and fixed or deleted within 10 working days. Both Playwright
configs drop `@flaky` tests from the PR lane's projects (`grepInvert`), and the nightly runs them:
`e2e-nightly.yml` sets the lane's `quarantine` input, which runs each config's `flaky-nightly`
project (`CV_E2E_QUARANTINE=1`) and writes its counts to the job summary. A quarantined test is
never silently skipped, and it does not turn the release-blocking nightly red. Waits are on conditions only (no `waitForTimeout`). Each lane writes its count
of tests that passed only on retry to the job summary from the JSON report.

## 5. Exploratory charters

`docs/qa/charters/E10-charter-1-routing-rbac.md` … `-5-shell-browser-parity.md`: routing and RBAC,
chrome and states, keymap conflicts, system states, shell/browser parity. Each targets I1 and I2.
