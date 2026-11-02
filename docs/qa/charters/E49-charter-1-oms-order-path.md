# E49-C1 Charter: OMS order path

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): route level only (its screens are stubs)
- Cites: 03 §11.2 (OMS / order-path edge cases), §9 (exchange 5xx, rate limit 10018, private WS disconnect), §9.1 (reconnect / reconciliation sequence), §7 Trading-demo suite
- Mission: make one order end up in a state the OMS, the exchange and the screen disagree on.
- Areas:
  - amend and cancel racing a fill (same order, inside one round trip)
  - partial fills, then amend the remainder; reduce-only against a position that shrinks meanwhile
  - amend a bracket leg while the parent is filling
  - submit at the instant of a private-stream reconnect (before, during, after reconciliation)
- Oracles:
  - O1.1 an order shown on screen differs from the exchange's (state, qty, price, filled qty) after reconciliation
  - O1.2 a retry goes out under a new `orderLinkId` (C-2.10) or a duplicate order exists
  - O1.3 a position-opening order without a native exchange stop-loss (C-2.6; P0)
  - O1.4 an order action without an audit record (C-2.9)
  - O1.5 a 5xx create is resent instead of going to `unknown` (03 §9)
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the order ticket and the open-orders table: place, amend and cancel with the keyboard alone (shortcuts and confirm path).
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: the E29 OMS suites, chaos scenarios of 03 §9 (WS disconnect private, exchange 5xx, rate limit 10018), `@plan-RM-1` for the routes.

## Explorable at `origin/main` (2026-11-01)

| Surface                                                | State                                                                |
| ------------------------------------------------------ | -------------------------------------------------------------------- |
| Order ticket, open orders, positions UI (R-130..R-132) | stub routes (manifest owner label E12; build epics E30 #60, E29 #55) |
| OMS core, reconciliation                               | backend modules and their tests; no UI path                          |
| Fake trading port                                      | `services/api/candleviewer/exchange/base/fakes.py` (in-process)      |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01, agent baseline, tier A): each route of the area landed for every role with its
  stub heading and the environment badge (C8 sweep); no order, rule, group or replay path exists to
  probe, so none of the oracles above was applied. Not reached: every area above. Findings: E49-R1-05
  (the stub headings name the wrong epics), E49-R1-09 (unbuilt, not a defect).
