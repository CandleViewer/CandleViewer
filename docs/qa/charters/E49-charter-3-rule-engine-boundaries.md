# E49-C3 Charter: Rule-engine boundaries

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): route level only (its screens are stubs)
- Cites: 03 §11.2 (rule-engine boundary conditions), §7 Rules suite (form to graph round-trip), §9 (sequence gap, DB down)
- Mission: make a rule do something its author did not write, or fail to do what was written.
- Areas:
  - form editor to graph editor and back: every field, every operator, empty and maximal rules
  - a rule firing while the system is degraded (feed stale, DB down, kill switch on)
  - a rule acting on a stale or resyncing book (sequence gap mid-evaluation)
  - two rules acting on one position in the same tick
- Oracles:
  - O3.1 a round trip that loses or changes a field (P1 per 03 §11.3 example)
  - O3.2 a rule firing on data marked stale, or during a resync
  - O3.3 a rule action that bypasses the kill switch, a risk cap or the live gate (sync checks first, C-2.21)
  - O3.4 two conflicting actions both executed on one position
  - O3.5 a rule-placed order without a native SL (P0)
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): both editors: build, connect and save a three-condition rule without a pointer.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: the E35 round-trip property suite and its recorded seed (`test(rule-engine)` #5336), `docs/qa/e35-rule-engine-test-plan.md`.

## Explorable at `origin/main` (2026-11-01)

| Surface                    | State                                                                |
| -------------------------- | -------------------------------------------------------------------- |
| Rules routes R-160..R-164  | stub routes (manifest owner label E14; build epics E36 #62, E37 #66) |
| Rule IR, compiler, runtime | backend (E35 #56); round-trip property tests exist                   |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01, agent baseline, tier A): each route of the area landed for every role with its
  stub heading and the environment badge (C8 sweep); no order, rule, group or replay path exists to
  probe, so none of the oracles above was applied. Not reached: every area above. Findings: E49-R1-05
  (the stub headings name the wrong epics), E49-R1-09 (unbuilt, not a defect).
