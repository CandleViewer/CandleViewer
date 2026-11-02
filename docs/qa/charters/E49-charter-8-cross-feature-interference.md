# E49-C8 Charter: Cross-feature interference

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): explored, see the run record
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

## Explorable at `origin/main` (2026-11-01)

| Surface                                              | State                                 |
| ---------------------------------------------------- | ------------------------------------- |
| Shell on every route, env badge, system states       | built (E10)                           |
| Alerts, workspaces, order ticket, environment switch | not built (E40 #67, E15 #41, E30 #60) |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01): see `docs/qa/e49-run-1-findings.md` §2.
