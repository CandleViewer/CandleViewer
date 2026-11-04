# E29-C7 Charter: screen reader

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150), formally by E29-Q05 (#1149) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the blotters are not built; owner-run, NVDA on Windows and VoiceOver on macOS)
- Cites: `docs/plan/05-accessibility-standard.md` §10; `docs/design/E29/E29-D05.md` §14 (the script SR-01 to SR-13, referenced here and not restated), §7 (names), §8 (live regions, the routing table RT-01 to RT-20, PROPOSED)
- Mission: with a screen reader, find what a sighted user sees that is not spoken, and what is spoken that is wrong, repeated or too often.
- Areas (D05 §14.1's tasks):
  - SCR-063 Positions: switch tabs, sort, filter, group, open a row menu, close in part, export (SR-01); read a row and the totals (SR-02); sort while focus is on a row action (SR-06)
  - account states and the reconnect summary: one utterance, never a countdown (SR-03, SR-08); a revoked account's row, focus on the "No longer shown" line (SR-07)
  - a Manager's row count counts in-scope rows only (SR-09); amend pending, confirmed, rejected (SR-10); a corrected row (SR-11)
  - SCR-078's order, position and trade-group scopes (SR-12); new fills while scrolled away (SR-13)
  - the PnL, side, liquidation tier and maker or taker carried by more than colour
- Oracles:
  - E29-O7.1 a state change with no announcement, or one announced more than once per episode
  - E29-O7.2 a live value announced on every tick (RT-17)
  - E29-O7.3 an accessible name that does not contain its visible label (WCAG 2.5.3), or a state carried by colour alone
  - E29-O7.4 `aria-rowcount` or a position in the set that is wrong, or that counts rows out of the caller's scope
  - E29-O7.5 an assertive announcement for a non-urgent state, or a polite one for an urgent one (a position with no stop, an order's rejection)
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the screen reader's own browse and focus modes over the grid; the debrief notes where a reader's command and the grid's keys collide (D05 H-01, H-02).
- Seeded stack: owner-run: NVDA on Windows in the Electron shell (`docs/plan/05-accessibility-standard.md` §8.1 row 1; Chromium, row 3, for fast iteration) and VoiceOver on macOS (row 4), the two readers E29-Q05's scope names; E29-Q05 runs the same script as its audit. WS-driven states need the web project until HARN's shim is proven in Electron (G-W1). Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E29-TC-003, E29-TC-008, E29-TC-101 and E29-TC-354 in `docs/qa/e29-oms-test-plan.md`; axe in the web project; `docs/design/E29/E29-D05.md` §14.2's Gherkin per surface.

## Explorable at `origin/main` (2026-11-03)

| Surface                                | State                                                                              |
| -------------------------------------- | ---------------------------------------------------------------------------------- |
| The treegrid's names and descriptions  | built as a component (`packages/ui/test/PositionsGrid.test.tsx`, Storybook and VR) |
| SCR-063 panel, SCR-078, SCR-152 states | not mounted or not built: #5440, #979, #1028                                       |
| The live-region routing table          | D05 §8.1, PROPOSED, owner approval pending                                         |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
