# E29-C1 Charter: act on a stale blotter

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the blotters are not built: #5440 and the web halves of E29-S02, E29-S04 and E29-S07 are not merged)
- Cites: `docs/plan/03-testing-strategy.md` §11.2 (OMS / order-path edge cases), §9 (private WS disconnect), §9.1 (reconnect and reconciliation: nothing stale is shown as live), §12 (keyboard-only); `docs/design/E29/E29-D06.md` §3 (S-05 to S-07, S-14 to S-18); `docs/design/E29/E29-D05.md` §8 (live regions)
- Mission: act on a blotter whose data is old and make it look live, or make it let an order through that it should block.
- Areas:
  - a private feed that goes quiet without closing (a stalled socket) and one that closes, then returns
  - wallet health `degraded` and `down` on one account while another stays healthy
  - old marks, and a "Last update" age that stops moving, jumps or never appears
  - an account whose reconciliation fails for 2 minutes: entry refused for it, the others usable, rows shaded with their last-good time
  - an action in each state: submit, amend, cancel, close (entry must block, exits must stay available, C-2.6)
  - a frame older than what the screen holds; the tab hidden, then shown
- Oracles:
  - E29-O1.1 a value, row or total shown as live while its feed is down, stalled or older than its stated age (P0)
  - E29-O1.2 an entry control enabled for an account the server refuses (`account_stale`) or while private feeds are down, or an exit blocked by a stale or blind state
  - E29-O1.3 an age, countdown or "as of" time that is wrong or frozen, or one announced on every tick (D05 RT-17)
  - E29-O1.4 a shaded row without its last-good time, or a banner that names the wrong account or environment
  - E29-O1.5 "Your exchange-side stop-losses are unaffected." shown while an open position has no confirmed stop (P0)
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the banner's actions, the account line's "Resolve…" (Owner), the toolbar and the grid, by Tab, arrows and Enter only; focus stays on a visible control whenever a state changes.
- Seeded stack: tier A for the client states, with HARN's `stall`, `kill`, `sendSystem` and `setFrameAge` (`sendWallet` once slice D lands); tier B with an injected-fault switch for the server's refusal (`docs/qa/e49-exploratory-harness.md` §2). Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E29-TC-010, E29-TC-012, E29-TC-351, E29-TC-352, E29-TC-353, E29-TC-354 and E29-TC-357 in `docs/qa/e29-oms-test-plan.md`; chaos row s1 (`services/api/tests/chaos/oms/test_s1_private_stream_kill.py`).

## Explorable at `origin/main` (2026-11-03)

| Surface                                           | State                                                                                 |
| ------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Positions panel (SCR-063, R-130)                  | not mounted: the panel is #5440                                                       |
| Account lines and banners (S-14 to S-18)          | models and words only (`apps/web/src/features/positions/accountSignals.ts`); no panel |
| HARN `stall`, `kill`, `sendSystem`, `setFrameAge` | on `main` (`apps/web/e2e/support/wsHarness.ts`); `sendWallet` is not built            |
| The `account_stale` refusal and reconciliation    | backend modules and their tests; no UI path                                           |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
