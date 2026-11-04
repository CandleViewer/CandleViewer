# E29-C3 Charter: cancel exactly at fill

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the working-orders tab, E29-S02 #912, is not merged)
- Cites: `docs/plan/03-testing-strategy.md` §11.2 (OMS / order-path edge cases); `docs/plan/24-internal-schemas.md` §8.2 (S1, S3, S6) and §8.6 (a cancel's `110001`); E49-C1 (`E49-charter-1-oms-order-path.md`), whose oracles O1.1 to O1.5 apply here and are not restated
- Mission: cancel an order at the instant it fills and make the blotter, the position or the exchange disagree.
- Areas (what the blotter shows during the race; E49-C1 probes the order path itself):
  - a cancel while the fill push is in flight, in both arrival orders: the fill first, and the venue's `110001` first
  - the order parked in `unknown` until reconciliation ends it; the position's size afterwards
  - cancel-all across accounts while some orders fill
  - a second cancel on a row already cancelling; a cancel on a terminal order
  - a recorded stop's row: its cancel while the position is open, and once it is flat
- Oracles (with E49-C1's O1.1 to O1.5):
  - E29-O3.1 the row stays "Cancelling" or reads "Cancelled" while the exchange holds a fill, or ends in neither Filled nor Partial after reconciliation
  - E29-O3.2 a raw exchange error, code or message on the row, a toast or the answer (the code-only rule); wording is not asserted (G-W3)
  - E29-O3.3 a cancel sent again after `110001` or an unknown outcome: more than one cancel at the venue (S1)
  - E29-O3.4 cancel-all counts a filled order as cancelled, or drops an account from its result list
  - E29-O3.5 the position's size after the race differs from the sum of its fills
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): select rows with Space, cancel with the row menu (Shift+F10) and with the bulk control, confirm and read the result list, all by keyboard.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2 with an injected-fault switch (a fill racing a cancel, a `110001` answer). Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E29-TC-104, E29-TC-105, E29-TC-107 and E29-TC-110 in `docs/qa/e29-oms-test-plan.md`; `services/api/tests/xstate_contract/test_b01_order_core.py` (S3).

## Explorable at `origin/main` (2026-11-03)

| Surface                                 | State                                                                                |
| --------------------------------------- | ------------------------------------------------------------------------------------ |
| Working-orders tab, row and bulk cancel | not built: model, words and goldens only (`apps/web/src/features/positions/orders/`) |
| `cancelOrder`, `cancelAllOrders`        | backend routes and tests (`services/api/tests/unit/api/test_order_exits_route.py`)   |
| Fake trading port                       | `services/api/candleviewer/exchange/base/fakes.py` (in-process)                      |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
