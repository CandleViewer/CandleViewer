# E29-C6 Charter: keyboard only

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150), formally by E29-Q05 (#1149) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the blotters are not built)
- Cites: `docs/plan/03-testing-strategy.md` §12 (keyboard-only); `docs/plan/05-accessibility-standard.md` §3; `docs/design/E29/E29-D05.md` §5.4 (the focus rule), §6.1 (K-01 to K-16), §6.2 (focus visible and not obscured)
- Mission: complete every blotter task with the keyboard alone, and find where focus is lost, trapped, hidden or sent somewhere it should not go.
- Areas:
  - the strip, toolbar, banner actions, grid and totals in order (K-01); arrows, Home, End, PageUp and PageDown inside the grid (K-02 to K-04); Space and Ctrl+A to select (K-05, K-06)
  - Enter to open SCR-078, the cell editor or a sort (K-07); Shift+F10 or Menu for the row menu (K-08); F2 and Enter in the editor (K-12)
  - Ctrl+Delete and Ctrl+Backspace to close or cancel the targets with the confirm (K-09); Ctrl+Shift+F for Flatten account (K-10); Esc closes and reverts, never cancels (K-11)
  - the shipped Ctrl+W, Ctrl+Shift+W and the panel and region cycles (K-13 to K-15); Alt+Up and Alt+Down in the column picker (K-16)
  - a focused row scrolled out of the window; a focused row whose account is withdrawn; a drawer opened and closed
  - T2 controls: reachable, announced with their reason, and inert
- Oracles:
  - E29-O6.1 focus lost to `body`, trapped, hidden under a sticky column or the actions column, or not visible (D05 §6.2)
  - E29-O6.2 a control reachable only by pointer or hover
  - E29-O6.3 a key that acts outside its documented scope, or one that collides with a reserved chord (Esc cancelling an order; Ctrl+W against the browser)
  - E29-O6.4 an action sent by a hotkey without its confirm, or a T2 control that sends on Enter or Space
  - E29-O6.5 focus not returned to the opener when a dialog or drawer closes, or not moved to the "No longer shown" line on revocation
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the whole session; the debrief lists each screen and every dead end.
- Seeded stack: tier A in the web project; the Electron main-window smoke covers the keyboard and axe path only (G-W1). Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E29-TC-008, E29-TC-011, E29-TC-057, E29-TC-106 and E29-TC-203 in `docs/qa/e29-oms-test-plan.md`; `packages/ui/test/PositionsGrid.test.tsx`.

## Explorable at `origin/main` (2026-11-03)

| Surface                             | State                                                                       |
| ----------------------------------- | --------------------------------------------------------------------------- |
| The treegrid and its keys (CMP-114) | built and tested as a component (`packages/ui/test/PositionsGrid.test.tsx`) |
| SCR-063 panel, SCR-078 drawer       | not mounted: the panel is #5440; the drawer is #979                         |
| The reserved-key fixture            | D05's (`docs/design/E29/E29-D05.md` §6.1); no blotter chord is added        |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
