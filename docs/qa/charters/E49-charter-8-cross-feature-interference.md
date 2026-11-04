# E49-C8 Charter: Cross-feature interference

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): explored, see the run record · refreshed 2026-11-04 to `fdad0285f`: buildable in part (route sweep, alerts centre, role change); the order ticket, replay, workspace and environment parts are parked
- Cites: 03 §11.2 (format), §7 (suites the features belong to), §9 (chaos interplay); ticket addition
- Mission: make one feature corrupt another's state when both are active.
- Areas:
  - alerts firing during replay
  - a rule triggering while the order ticket is armed
  - workspace restore with an account that was deleted
  - an environment switch with open positions
  - today's built surfaces: the environment badge and landing of every route for every role
- Oracles:
  - O8.1 the environment badge is missing or wrong on any screen of the shell (C-2.11)
  - O8.2 a screen with no level-1 heading or no landing (blank route)
  - O8.3 an alert raised from replay data presented as live
  - O8.4 a restored workspace referencing a deleted account without a notice
  - O8.5 an environment switch that carries orders or positions across environments (C-2.11; P0)
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): every route for one role: land, Tab once round the page, note any trap.
- Seeded stack: tier A for the route sweep; B for the interplay of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: `@plan-RM-1` (landing), the E10 shell suite (`apps/web/e2e/shell/`).

## Explorable at the GA-candidate pin `fdad0285f` (2026-11-04)

Re-verified against the code at the pin. A parked row names its owning ticket and the trigger that unparks it; the trigger is always that the route renders a body, not `StubRoute` (`apps/web/src/routes/tree.tsx:82-83`).

| Surface                                                     | State                                                                                                                                  | Evidence                                                                                                                      |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Shell on every route, env badge, system states              | built (E10); route sweep done in run 1                                                                                                 | `apps/web/src/routes/tree.tsx:115-138`                                                                                        |
| Alerts centre R-190 beside the shell states                 | built (E40-S01); new in the refresh: open it during backend-down, lock and sign-out states. The alert detail R-191 stays a stub        | `apps/web/src/routes/tree.tsx:51`, `apps/web/src/features/alerts/AlertsRoute.tsx:22`, `apps/web/src/routes/manifest.ts:87-88` |
| A role change during a session                              | buildable on tier B; the guard re-reads claims on each navigation                                                                      | `apps/web/src/routes/tree.tsx:108-110`                                                                                        |
| Order ticket, replay, workspace restore, environment switch | parked: owner tickets E30 #60, E26 #49, E15 #41 and the environment switch are not shipped. Each unparks when its route renders a body | `apps/web/src/routes/tree.tsx:82-83`                                                                                          |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01): see `docs/qa/e49-run-1-findings.md` §2.
- Session sheet: one `E49-session-sheet.md` copy per session; this block keeps the summary line only.
