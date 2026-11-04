# E29-C2 Charter: amend during a partial fill

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the working-orders tab, E29-S02 #912, is not merged)
- Cites: `docs/plan/03-testing-strategy.md` §11.2 (OMS / order-path edge cases); `docs/plan/24-internal-schemas.md` §8.2 (S2, S4, S5, S10); E49-C1 (`E49-charter-1-oms-order-path.md`), whose oracles O1.1 to O1.5 apply here and are not restated
- Mission: end an order in a state the OMS, the exchange and the blotter disagree on, by amending it while it fills.
- Areas (what the blotter shows during the race; E49-C1 probes the order path itself):
  - amend the price of a partially filled order, then the remainder while another fill lands
  - an amend the exchange rejects on a partially filled order (`amend_pending` back to `partially_filled`)
  - two amends in flight; an amend with a stale ETag (`412`)
  - a native-stop row: tighten and loosen through `setPositionTpSl`, never `amendOrder`
  - amend, then lose the stream, then reconnect before the answer arrives
- Oracles (with E49-C1's O1.1 to O1.5):
  - E29-O2.1 the row's state words, pending chip or correction line say something the exchange's order does not
  - E29-O2.2 "Amend rejected — your order is unchanged" is missing, or the prior price and quantity are not restored (S2; P0, the amend illusion)
  - E29-O2.3 a fill that lands during the amend is counted twice, lost, or shown against the wrong version of the order (S4, S5)
  - E29-O2.4 the row reads confirmed before a frame with the new state and price arrives, or never leaves "Amending" (the frame's `change` is `amend` for request, ack and rejection alike)
  - E29-O2.5 a stop loosened, or an `amendOrder` accepted for a native-stop row (C-2.6)
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the working-orders grid: open the cell editor with F2 or Enter, step with the arrows, commit with Enter, revert with Esc, all without a pointer.
- Seeded stack: tier B of `docs/qa/e49-exploratory-harness.md` §2 with an injected-fault switch (a delayed fill, a rejected amend). Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E29-TC-101, E29-TC-102, E29-TC-111, E29-TC-112 and E29-TC-109 in `docs/qa/e29-oms-test-plan.md`; `services/api/tests/xstate_contract/test_b01_order_core.py` (S2, S4).

## Explorable at `origin/main` (2026-11-03)

| Surface                                 | State                                                                                |
| --------------------------------------- | ------------------------------------------------------------------------------------ |
| Working-orders tab, inline amend (S-12) | not built: model, words and goldens only (`apps/web/src/features/positions/orders/`) |
| `amendOrder` and the OMS amend path     | backend routes and tests (`services/api/tests/unit/api/test_order_amend_route.py`)   |
| Fake trading port                       | `services/api/candleviewer/exchange/base/fakes.py` (in-process)                      |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
