# ADR-0046 — Order-ticket reducer placement: where the sizing and validation reducer runs (E30-K01, #852)

- Status: **proposed** (2026-11-04). Decision deadline: ratification before E30-T01 (#984, `packages/order-ticket-core`)
  opens its first code PR. The decision itself is **TBD by the K01 run**; this skeleton fixes the question, the
  options and the evidence the run must supply, and nothing else (C-3.4).
- Date: 2026-11-04
- Deciders: Owner (`@basiltt`) through the delivery orchestrator (the delegation on #2701); the architect as
  CODEOWNER of `docs/plan/`.
- Consulted: the #852 BQ list (comment 6624019567) and its rulings (comment 6624627208); `docs/plan/spikes/E30-K01.md`;
  `06-performance-and-load-standard.md` §5.2; `14-screens-catalogue.md` SCR-060; `11-user-stories.md` US-ORD-006 and
  US-DOM-007.
- Numbering note: the orchestrator assigned 0046 on #852 (0042 to 0045 are taken).
- Related: #852 (E30-K01, this record is its output), #984 (E30-T01, the consumer), #1155 (E30-Q03, the perf scripts),
  #843 (E29-K01, the demo leg).
- Evidence: `docs/plan/spikes/E30-K01.md` and `E30-K01-results.json` (not yet produced).

## Context and problem statement

SCR-060 requires every ticket input to recompute risk, fee and margin in 8 ms. US-ORD-006 and US-DOM-007 require
gesture to `fetch()` within 50 ms on the client. The ticket shares a renderer with the WebGL chart engine, React and
the DOM overlays. E30-T01 must be told, before it is written, where the pure `size()` + `validate()` reducer runs and
how the submit leaves the client, because moving either later changes the package boundary of
`packages/order-ticket-core`.

## Decision drivers

1. Recompute p95 within 8 ms (SCR-060; E30-T01 narrows it to `size()` + `validate()` on end A).
2. Gesture to `fetch()` p95 within 50 ms for a click and for `Ctrl+Enter` (BQ 2, ruled 2026-11-04).
3. No bypass of the arm check (`ArmToken`) or any server-side gate on the measured path.
4. Chart data never flows through React state (`30-frontend-react.md`); the chart engine renders in a worker, so
   the contention on the main thread is React, DOM overlays and input forwarding.
5. Small payloads across any thread boundary: the structured-clone cost of `OrderDraft` + `Instrument` + `Wallet`.

## Considered options

| Option | Placement                                                                     |
| ------ | ----------------------------------------------------------------------------- |
| A      | Synchronous in the React event handler; the result goes through React state   |
| B      | In a `useSyncExternalStore` store outside React rendering, on the main thread |
| C      | In a dedicated worker, with a structured-clone hop per input                  |

Orthogonal to the placement, the submit dispatch path is either imperative from the handler or through a store, and
`apiFetch`'s CSRF recovery either stays on the submit path (it can issue a second `fetch()`) or is bypassed by a
dedicated transport; the run answers both.

## Decision outcome

**TBD by the K01 run.** The rule the acceptance criteria already fix: if recompute p95 exceeds 8 ms in option A, this
record mandates B or C for E30-T01; if no placement meets 50 ms gesture to `fetch()`, a `32` risk entry and a scope
question to the Architect follow instead.

## Consequences

TBD with the decision. E30-T01 reads this record for: the placement; for C, the message boundary and whether
`TicketContext` snapshots are cloned on every input or held in the worker; where `cv_ticket_recompute_ms` and
`cv_ticket_click_to_ack_ms` are measured; the CI gate's baseline host class; the submit dispatch path.

## Why not the alternatives

TBD with the decision.

## Validation

The harness of `E30-K01` (branch `spike/e30-k01-order-latency`, never merged): 3 placements x 2 chart-engine RunModes
x 2 runs, 1 000 samples per trigger, p95 within 15 % across the two runs. Host class and the pending demo leg
(E29-K01, #843) are recorded in the finding.
