# E49 exploratory charters: index, format and disposition rules

- Ticket: E49-Q02 (#1336), PR 1 of 2 (`Partial:`; the closing PR carries the two bug bashes).
- Owner of the format: `docs/plan/03-testing-strategy.md` §11.2 (charters), §11.3 (severities and
  SLAs), §12 (keyboard-only clause), §17 (environments). This file cites them; it does not restate them.
- Harness: `docs/qa/e49-exploratory-harness.md`. Run records: `docs/qa/e49-run-<n>-findings.md`.
- Deviation: the ticket names `docs/plan/backlog/artifacts/charters/` for the charters. The established
  location `docs/qa/charters/` is used instead, per the ruling (BQ-03), so one folder holds every charter
  (beside the E04 to E11 ones); the ticket path holds a pointer to this index.

## The eight charters

Each is 90 minutes, one risk area, mission plus oracles plus debrief (03 §11.2). The §11.2 mandated
minimum is covered by charters 1, 3, 4, 5 and 7; 2, 6 and 8 are the ticket's additions.

| #   | Charter                                                                   | Risk area (ticket)           | 03 §11.2 mandated area              | Status after run 1                    |
| --- | ------------------------------------------------------------------------- | ---------------------------- | ----------------------------------- | ------------------------------------- |
| 1   | [OMS order path](E49-charter-1-oms-order-path.md)                         | Order races, reconnects      | OMS / order-path edge cases         | route level only; OMS UI not built    |
| 2   | [Emulated algos](E49-charter-2-emulated-algos.md)                         | OCO, iceberg, TWAP, chase    | (ticket addition; §9 chaos)         | route level only; not built           |
| 3   | [Rule-engine boundaries](E49-charter-3-rule-engine-boundaries.md)         | Form/graph, degraded, stale  | Rule-engine boundary conditions     | route level only; editors not built   |
| 4   | [Fan-out edges](E49-charter-4-fanout-edges.md)                            | Partial failure, native SL   | Multi-account fan-out edge cases    | route level only; not built           |
| 5   | [Chart engine at extremes](E49-charter-5-chart-engine-extremes.md)        | Density, intervals, GPU      | Chart-engine correctness at extreme | not reached in run 1                  |
| 6   | [Replay and recording](E49-charter-6-replay-and-recording.md)             | Retention, gaps, live+replay | (ticket addition; §7 Replay)        | route level only; not built           |
| 7   | [Admin and RBAC probing](E49-charter-7-admin-rbac-probing.md)             | Roles, deep links, sessions  | Admin / RBAC boundary probing       | run 1 explored (shell, guards, stubs) |
| 8   | [Cross-feature interference](E49-charter-8-cross-feature-interference.md) | Feature interplay            | (ticket addition)                   | run 1: route sweep, every role        |

## Session format

1. **Before**: read the charter; bring up the stack tier the charter names (harness doc §2); start the
   recording (harness: Playwright video and trace are always on; a human run screen-records too).
2. **First 45 min, QA alone**: the mission and its areas, in any order; note every observation with the
   oracle it touches (`O<charter>.<n>`).
3. **Keyboard-only segment** (03 §12): at least one screen of the area driven with the keyboard alone;
   the debrief lists the screens and any dead end.
4. **Second 45 min, paired with a domain engineer** (ticket): trace the suspicious observations.
5. **Debrief** (Gherkin "Every charter produces an evidenced debrief"): mission, areas actually probed,
   oracles used, findings with reproduction steps, areas the timebox did not reach. A session with no
   finding still lists what it probed and which oracles it applied ("A charter finds nothing").

## Recorded-fixture rule (C-13.5)

No session reaches a live exchange. Market and exchange data come from recorded, redacted fixtures
(`packages/fixtures`); the browser runs behind the egress guard of `@candleviewer/fixtures/e2e`, which
aborts any request that leaves the loopback interface and fails the session on it. The ticket's
"Demo with fixture replay" means the Demo environment flag on a fixture-replay stack (03 §17 Staging
row), never a live or Demo order. Testnet is for connectivity smoke only (RSK-014). Test accounts only;
any incidental credential exposure is reported and rotated (ticket Security notes).

## Disposition rules (every candidate, zero undecided)

| Disposition        | Meaning                                                                              |
| ------------------ | ------------------------------------------------------------------------------------ |
| `bug P0..P3`       | A defect, graded by 03 §11.3; flaky automation follows C-9.3. Filed meeting 02 §6.1. |
| `not-a-defect`     | One-line reason (by design, harness artefact, unbuilt with its owner epic).          |
| `security-private` | Security class: reported privately (SECURITY.md); the public row has no detail.      |
| `pending filing`   | A graded candidate awaiting its ticket (filing freeze); the closing PR resolves it.  |

- `pending filing` must be 0 at the closing PR; the disposition query counts it as undecided.
- A missing native exchange stop-loss on any submitted order is P0 (charter 4, RSK-016).
- Any state change performed while impersonating (SCR-124) is P0 (charter 7).
- Perf findings route to E46 (#72); screen-reader findings to E49-Q03 (#1395); fixes to E49-S02
  (#1338, P1) and E49-S03 (#1363, P2/P3). Each routing is recorded in the run record.
- Public wording only: the repository is public, so no row names a vulnerability, a host or a secret.

## Findings table schema (every run record)

`ID | Charter | Oracle | Area | Steps | Expected | Actual | Severity | Status | Evidence`. Oracle names
the charter oracle that raised the row (or says why none did). No cell is empty; the
check is `grep -nE '\|\s*\|' docs/qa/e49-run-*-findings.md` on the findings table (no output).

## Bug-bash record template (for the closing PR)

- Two bashes (S23 after wave-1 fixes, S25 on the near-final candidate), 2 h, whole team incl. design,
  security and the Owner, at least two lanes (trading flows; admin, shell and a11y).
- **Warm-up (5 min, scripted)**: sign in on the seeded stack as the lane's role; open the lane's first
  screen; perform the lane's one happy path; open the shared board; post one test card.
- **Free exploration (90 min)**: one card per candidate on the shared board (duplicates visible live).
- **Triage (25 min, same day)**: every card graded by 03 §11.3 or marked not-a-defect with a reason;
  security cards leave the board for the private route; the burn-down shows the arrivals before the next
  working day (E49-T02 arrival panel).
