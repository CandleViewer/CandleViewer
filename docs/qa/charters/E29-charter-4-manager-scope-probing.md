# E29-C4 Charter: manager scope probing

- Ticket: E29-Q01 (#844), run by E29-Q06 (#1150) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: written, not run (the blotters are not built; the server half exists)
- Cites: `docs/plan/03-testing-strategy.md` §11.2 (admin / RBAC boundary probing), §10 (security testing; overlap with E29-X02, findings shared); `docs/security/threat-models/E29-oms.md` AC-06; `docs/design/E29/E29-D06.md` §3 (S-08, S-22); E49-C7 (`E49-charter-7-admin-rbac-probing.md`) for the shell's guards, not restated
- Mission: as a Manager granted account B only, and as one with a read-only grant, reach account A's rows, orders, fills, counts or actions through the client.
- Areas:
  - crafted `exchange_account_ids` (A alone, A and B mixed, an id that does not exist), on every list and on bulk routes
  - ids of A's orders and positions on the id routes; an Owner's cursor replayed by the Manager; a filter, deep link or CSV export that names A
  - WS: `sub` for A, for A and B, and for `machines.order:{id}.state` of an order of A
  - the Owner withdraws a grant while the Manager has the panel open (S-08, AC-06): rows, focus, a later REST read
  - strings and counts: a Manager's text names and counts only the Manager's accounts; `aria-rowcount` counts in-scope rows only
  - a read-only grant and view-as: every control, by pointer, keyboard and hotkey
- Oracles:
  - E29-O4.1 any row, id, count, label, total or mark card that names an account outside the grant (P0)
  - E29-O4.2 a foreign id answered differently from a missing one (an existence oracle)
  - E29-O4.3 a refusal with no audit record, or a record naming the wrong actor or view-as target
  - E29-O4.4 rows of a withdrawn account still shown, a REST read bringing them back, or focus lost to `body` (SR-E29-11)
  - E29-O4.5 a control enabled for a read-only grant, or a press that sends a request
  - O-ALL.1 (E49) an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the panel's filter bar, "+ Filter" menu and row actions as a Manager and as a Viewer, by Tab, arrows and hotkeys only; a gated control is reachable (`aria-disabled`, not `disabled`) and sends nothing.
- Seeded stack: tier A for the client half, tier B for the server half (`docs/qa/e49-exploratory-harness.md` §2): a Manager session, an Owner session and a third account. Recorded, redacted fixtures only, behind the egress guard (C-13.5); Demo environment flag; test accounts only. E29-X02's route-by-role matrix is the server oracle.
- Automated neighbours: E29-TC-004, E29-TC-011, E29-TC-055, E29-TC-110, E29-TC-205, E29-TC-254 and E29-TC-404 in `docs/qa/e29-oms-test-plan.md`; `services/api/tests/unit/api/test_oms_reads_route.py`; `services/api/tests/contract/rbac/test_scope_and_ws.py`.

## Explorable at `origin/main` (2026-11-03)

| Surface                                        | State                                                                                  |
| ---------------------------------------------- | -------------------------------------------------------------------------------------- |
| Scope on `listPositions`, `listOrders`, fills  | built and tested on the server (`services/api/tests/unit/api/test_oms_reads_route.py`) |
| WS scope and revocation                        | built and tested (`services/api/tests/contract/rbac/test_scope_and_ws.py`)             |
| The panel's filter bar, row actions, T2 states | not mounted: the panel is #5440; mutating controls are #5668 and #912                  |
| Route-by-role matrix for the OMS               | E29-X02, in flight (not on `main`)                                                     |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Not run.
