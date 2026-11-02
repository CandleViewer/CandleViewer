# E49-C4 Charter: Fan-out edges

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): route level only (its screens are stubs)
- Cites: 03 §11.2 (multi-account fan-out edge cases), §7 Multi-account suite, §9 (partial fan-out failure, rate limit 10018), §11.4 (native SL on every fanned-out order); RSK-016
- Mission: make a trade group leave any account exposed: unprotected, over its cap, or silently skipped.
- Areas:
  - partial account failure (1 of N rejects)
  - per-UID rate-limit exhaustion mid-fan-out
  - an account disabled while its group is executing
  - the native-SL invariant under each of the three
- Oracles:
  - O4.1 **every order that reached the exchange carries a native exchange stop-loss**; the debrief records the answer explicitly for each injected fault, and any miss is P0 (Gherkin "The fan-out safety invariant is probed, not assumed")
  - O4.2 the group's aggregate exposure exceeds its configured cap
  - O4.3 a failed or deferred account is not reported per account in the group view
  - O4.4 an automatic retry that could break an account's risk caps without user action (03 §9)
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the trade-group view: open a group, read every account's leg state and retry one, keyboard only.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: the E34 fan-out suites, chaos "partial fan-out failure" and "rate limit 10018" of 03 §9.

## Explorable at `origin/main` (2026-11-01)

| Surface                                      | State                                                                         |
| -------------------------------------------- | ----------------------------------------------------------------------------- |
| Trade groups R-140..R-142, risk R-150..R-151 | stub routes (manifest owner label E12; build epics E28 #57, E34 #58, E39 #59) |
| Fan-out, governor                            | backend (E34); fake trading port in-process                                   |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01, agent baseline, tier A): each route of the area landed for every role with its
  stub heading and the environment badge (C8 sweep); no order, rule, group or replay path exists to
  probe, so none of the oracles above was applied. Not reached: every area above. Findings: E49-R1-05
  (the stub headings name the wrong epics), E49-R1-09 (unbuilt, not a defect).
