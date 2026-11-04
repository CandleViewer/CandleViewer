# E49-C7 Charter: Admin and RBAC probing

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): explored, see the run record · refreshed 2026-11-04 to `fdad0285f`: buildable on two tiers (client half on A, server half on B)
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

## Explorable at the GA-candidate pin `fdad0285f` (2026-11-04)

Re-verified against the code at the pin. A parked row names its owning ticket and the trigger that unparks it; the trigger is always that the route renders a body, not `StubRoute` (`apps/web/src/routes/tree.tsx:82-83`).

| Surface                                                       | State                                                                                                              | Evidence                                                                                       |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| Shell, guards, 403 / 404, rail, hotkeys                       | built (E10); tier A                                                                                                | `apps/web/src/routes/tree.tsx:44-48`, `apps/web/src/routes/tree.tsx:94-112`                    |
| Sign-in, session, step-up, invites, appearance, hotkey editor | built (E09, E10, E11 settings); tier A, and tier B with the three seeded roles                                     | `apps/web/src/routes/tree.tsx:48-60`                                                           |
| Admin overview R-300 and invite screen R-303                  | built; run each as Owner, Manager and Viewer (the guard answers the last two)                                      | `apps/web/src/features/admin/shell/AdminArea.tsx:34-35`                                        |
| Security centre R-354                                         | placeholder body until E43's SCR-137                                                                               | `apps/web/src/features/admin/shell/AdminArea.tsx:36`                                           |
| Other admin screens R-301, R-302, R-310..R-356                | parked: stub routes (manifest owner label E18; build epic E42 #63). Unparks per route when its page renders a body | `apps/web/src/routes/manifest.ts:99-118`, `apps/web/src/features/admin/shell/AdminArea.tsx:37` |
| View as (SCR-124)                                             | parked: no screen (E42 #63); the backend wiring exists (`view_as_wiring.py`), so O7.6 stays unapplied in the app   | `services/api/candleviewer/view_as_wiring.py`                                                  |
| Server half: refusals of privileged calls with real sessions  | buildable on tier B (Owner, Manager, Viewer seeded); needs a docker host                                           | `services/api/scripts/seed_fixture_user.py:217`                                                |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01): see `docs/qa/e49-run-1-findings.md` §2.
- Session sheet: one `E49-session-sheet.md` copy per session; this block keeps the summary line only.
