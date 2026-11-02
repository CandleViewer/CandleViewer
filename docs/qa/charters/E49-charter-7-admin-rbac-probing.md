# E49-C7 Charter: Admin and RBAC probing

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): explored, see the run record
- Cites: 03 §11.2 (admin / RBAC boundary probing), §10 (security testing; overlap with E49-X01 / E49-X02, findings shared), §12 (keyboard-only); `14-screens-catalogue.md` SCR-124; RSK-020
- Mission: as Manager or Viewer, reach a privileged screen, its data or its action, from the client.
- Areas:
  - every privileged action attempted as Manager and as Viewer
  - deep links: odd spellings (case, trailing slash, encoded, matrix params, dot segments, query flags)
  - session changes: a role change, sign-out or lock during a session, then later navigation
  - the "view as" impersonation boundary (SCR-124 is read-only: any state change while impersonating is P0)
- Oracles:
  - O7.1 a guarded route renders its own screen for a role it denies
  - O7.2 a denied route fetches the data it guards
  - O7.3 the rail or a hotkey offers a destination the role may not open
  - O7.4 a gated item stays reachable after a session change
  - O7.5 a signed-out deep link lands anywhere but sign-in
  - O7.6 any state change while impersonating (P0)
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the shell, Settings and the admin invite screen: rail, top bar and forms by Tab and hotkeys only.
- Seeded stack: tier A (client half); B for the server half of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: `@plan-RM-1`, `@plan-RM-2`, `@plan-AB-1`, `@plan-AB-2`, E09 and E10 charters (`E09-charter-2-rbac-boundaries.md`, `E10-charter-1-routing-rbac.md`).

## Explorable at `origin/main` (2026-11-01)

| Surface                                                       | State                                                               |
| ------------------------------------------------------------- | ------------------------------------------------------------------- |
| Shell, guards, 403 / 404, rail, hotkeys                       | built (E10)                                                         |
| Sign-in, session, step-up, invites, appearance, hotkey editor | built (E09, E10, E11 settings)                                      |
| Admin screens R-300..R-356                                    | stub routes, guarded (manifest owner label E18; build epic E42 #63) |
| View as (SCR-124)                                             | not built (E42 #63)                                                 |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01): see `docs/qa/e49-run-1-findings.md` §2.
