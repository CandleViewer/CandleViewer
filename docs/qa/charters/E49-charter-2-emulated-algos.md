# E49-C2 Charter: Emulated algos

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): route level only (its screens are stubs)
- Cites: 03 §11.2 (OMS / order-path edge cases), §9 (WS disconnect private, rate limit 10018), §7 Trading-demo suite (emulated OCO / iceberg / TWAP / chase)
- Mission: leave an emulated algo with a live child order and no parent, or a parent that believes a child it does not have.
- Areas:
  - OCO, iceberg, TWAP and chase across a backend restart
  - the same across a private-stream disconnect and its reconciliation
  - each algo inside a rate-limit window (10006 / 10018): back-off, reserve for stops (C-12.7)
  - orphan detection: kill a parent mid-slice, then look for the children
- Oracles:
  - O2.1 a child order alive on the exchange whose parent is gone (orphan) and nothing flags it
  - O2.2 an OCO where both legs can fill
  - O2.3 a TWAP slice or chase step that exceeds the parent's remaining quantity
  - O2.4 a stop or cancel delayed by normal submits eating the reserved budget (C-12.7)
  - O2.5 a child position-opening order without a native SL (P0)
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the algo panel: create, pause and cancel one algo of each kind with the keyboard alone.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E33 algo suites once built, the statechart contract tests of `tests/xstate_contract/`.

## Explorable at `origin/main` (2026-11-01)

| Surface              | State                                                                       |
| -------------------- | --------------------------------------------------------------------------- |
| Algo UI and runtime  | not built (E33 #65)                                                         |
| Statechart contracts | catalogue entries of `28-statechart-catalogue.md` (the four emulated algos) |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01, agent baseline, tier A): no algo route or screen exists (E33 #65), so none of the
  oracles above was applied. Not reached: every area above. Finding: E49-R1-09 (unbuilt, not a defect).
