# E29-C5 Charter: reconnect storm while a partial close is in flight

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the Close controls are #5668 and the reconciliation UI is #1028; the server half exists)
- Cites: `docs/plan/03-testing-strategy.md` §11.2 (OMS / order-path edge cases), §9 (private WS disconnect), §9.1 (the four assertions); `docs/plan/24-internal-schemas.md` §8.2 (S1, S4, S5) and §8.5; E49-C1 (`E49-charter-1-oms-order-path.md`), whose oracles O1.1 to O1.5 apply here and are not restated
- Mission: lose the private stream repeatedly while a partial close fills, and end with a book that differs from the exchange, a close sent twice, or a remainder with no stop.
- Areas (E49-C1 stops at one reconnect):
  - a 50 % reduce-only close, then three drops of the stream in 60 s, with a fill in each gap
  - the close's answer lost (post-send timeout, the order `unknown`) and the Close pressed again
  - fills duplicated and reordered across reconnects; the gap's fills backfilled
  - the remainder's native stop, kept or flagged, and never larger than the position
  - a backend restart in the middle (tier B)
  - the notices: one `oms.account_resyncing` per episode, and the account line and summary the blotter shows
- Oracles (with E49-C1's O1.1 to O1.5):
  - E29-O5.1 two reduce-only closes at the venue for one press, or a close re-sent under a new `orderLinkId` (S1, C-2.10; P0)
  - E29-O5.2 the remainder has no native stop, or a stop larger than the position (C-2.6; P0)
  - E29-O5.3 the position or the fills after reconciliation differ from the exchange's (`03` §9.1's third assertion)
  - E29-O5.4 a notice per drop instead of one per episode, a missing notice, or an announcement per drop
  - E29-O5.5 an opposite-side position opened by the close (E29-S03 «Never reverses»)
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): Close from the row menu (Shift+F10), the confirm, and the account line's actions during the storm, by keyboard only.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2 with an injected-fault switch (kill the private stream, delay an answer, restart the API). Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E29-TC-053, E29-TC-150 to E29-TC-153, E29-TC-155, E29-TC-156, E29-TC-350 and E29-TC-355 in `docs/qa/e29-oms-test-plan.md`; chaos rows s1 to s4 (`services/api/tests/chaos/oms/`); E29-Q04's reconnect rows (#1148, in flight).

## Explorable at `origin/main` (2026-11-03)

| Surface                               | State                                                                               |
| ------------------------------------- | ----------------------------------------------------------------------------------- |
| Row Close, Close all, Flatten account | not built (E29-S01b, #5668); the partial-close sizing UI is #978's remaining PR     |
| `closePosition` and the close sizing  | backend routes and tests (`services/api/tests/unit/oms/test_e29_s03_acceptance.py`) |
| Private-stream consumer and chaos     | `services/api/tests/chaos/oms/` (s1 to s4); reconciliation UI is #1028              |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
