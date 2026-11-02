# E49-C6 Charter: Replay and recording

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): route level only (its screens are stubs)
- Cites: 03 §7 Replay suite, §9 (sequence gap, DB down); not in the §11.2 mandated list (ticket addition)
- Mission: make replay show something that never happened, or hide something that did.
- Areas:
  - seek across a retention boundary (hot to cold tier)
  - replay a window that contains a recording gap
  - replay while live panels are open in the same workspace
- Oracles:
  - O6.1 a replayed footprint, profile, CVD or heatmap that differs from the golden capture (03 §7)
  - O6.2 a gap rendered as continuous data, with no gap marker
  - O6.3 replay data reaching a live panel, or live data reaching a replay panel
  - O6.4 any order path reachable from a replay session
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the replay bar: load, play, pause, seek and change speed with the keyboard alone.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: `docs/qa/exploratory/E07-charter-1-tier-boundary.md`, `E07-charter-3-retention-safety.md`.

## Explorable at `origin/main` (2026-11-01)

| Surface             | State                                                      |
| ------------------- | ---------------------------------------------------------- |
| Replay R-170, R-171 | stub routes (manifest owner label E16; build epic E26 #49) |
| Recorder, retention | backend (E16 #42); E07 tier-boundary charters exist        |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01, agent baseline, tier A): each route of the area landed for every role with its
  stub heading and the environment badge (C8 sweep); no order, rule, group or replay path exists to
  probe, so none of the oracles above was applied. Not reached: every area above. Findings: E49-R1-05
  (the stub headings name the wrong epics), E49-R1-09 (unbuilt, not a defect).
