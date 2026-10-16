# ADR-0006 — OMS state machine, idempotency and reconciliation

- Status: **decided**
- Date: 2026-09-14
- Deciders: Architect, Backend lead, Security engineer, Owner
- Consulted: `docs/research/06-bybit-api.md` §5, §11, §14, §19, `docs/research/09-execution-risk-tools.md` §6, §8, `docs/research/11-backend-tech.md` §2.5, `docs/research/22-architecture-options.md` §6
- Related: ADR-0008, `docs/plan/24-internal-schemas.md`, `docs/plan/20-architecture.md` §3.5

## Context and problem statement

The OMS manages real money across multiple Bybit sub-accounts over a network that will disconnect, a REST API that will rate-limit, and a private WebSocket that will drop. The hardest correctness problem is not the happy path — it is what happens when a submission's acknowledgement is lost. Blind retries risk duplicate positions; blind abandonment risks an unmanaged order. We need a state machine that makes the uncertain case explicit and a recovery procedure that is deterministic.

## Decision drivers

- Bybit supports `orderLinkId`, a client-supplied identifier deduplicated within the retention window — a genuine idempotency primitive.
- Demo retains orders for only 7 days and offers no WS order entry; live offers both REST and WS trade.
- Reconnect reconciliation has a documented shape: re-auth private WS, `GET /v5/order/realtime` + `/v5/position/list` for authoritative state, diff by `orderLinkId`, backfill `GET /v5/execution/list` for the gap window.
- Error 10002 (clock drift) and 10018 (rate limit) must be distinguishable from business rejections.
- The process may die at any moment; the safety story cannot depend on it being alive (see ADR-0008 for the native-SL invariant).

## Considered options

1. **Explicit state machine including an `Unknown` state, `orderLinkId` idempotency, resolution by reconciliation only.**
2. **Optimistic local state with retry-on-timeout** (resubmit until acknowledged).
3. **Mirror the exchange only** — hold no local state, poll REST for truth.

## Decision outcome

**Chosen: option 1.**

States: `Draft → Validated → Submitting → {Submitted | Rejected | Unknown}`; `Submitted → {PartiallyFilled, Filled, CancelPending, AmendPending}`; `CancelPending → {Cancelled, Filled}`; `AmendPending → {Submitted, Rejected}`. Terminal: `Filled`, `Cancelled`, `Rejected`.

Binding rules:

1. **`orderLinkId` is generated before the first send** as `{group_id}-{account_short}-{seq}` (≤ 36 chars) _(format superseded by Amendment 1: `docs/plan/24-internal-schemas.md` §8.3)_ and reused unchanged on every retry of that logical order. It is the primary key for correlation everywhere — logs, audit, journal, reconciliation.
2. **Any transport failure after send lands in `Unknown`.** There is **no blind resubmission** from `Unknown`. Resolution comes only from reconciliation: if `GET /v5/order/realtime` (or the execution backfill) finds the `orderLinkId`, the order transitions to its true state; if two consecutive reconciliation passes find nothing, it becomes `Rejected`.
3. **`oms_unknown_orders > 0` for 60 s pages the operator.** An unknown order is an operational incident, not a background condition.
4. **Reconciliation runs on startup, on every private-WS reconnect, and every 30 s.** It diffs local state against exchange truth by `orderLinkId`, backfills executions for the gap window `[last_seen_ts, now]`, and emits corrections onto the bus so every view converges.
5. **Transport selection is a capability decision, not an `if`.** `ExchangeCapabilities.supports_ws_order_entry` chooses WS trade (live) or REST (demo). No environment conditionals outside the adapter.
6. **Error taxonomy is mapped in the adapter**: `ClockDriftError` (10002) blocks order entry entirely and raises a distinct alert; `RateLimitError` (10018) feeds the token bucket and rejects submits with `RATE_BUDGET_EXCEEDED` rather than silently queueing them past their usefulness; business rejections carry the exchange message verbatim to the UI.
7. **Postgres is the authoritative local store.** In-memory caches are derived and rebuildable. If Postgres is unavailable, order entry is blocked — we never accept an order we cannot durably record.
8. **Amend semantics**: an amend rejection leaves the prior order live and unchanged; the UI is told explicitly, because a user who believes a stop moved when it did not is in danger.

### Consequences

Positive:

- Duplicate orders are structurally prevented, which is the failure mode with the worst financial consequence.
- Every uncertain state is visible, alertable and auditable rather than silently resolved.
- Recovery after a crash is a single well-tested procedure rather than ad-hoc repair.
- `orderLinkId` threading gives end-to-end traceability from the ticket click to the journal entry.

Negative / risks:

- Reconciliation latency means an order can sit in `Unknown` for up to one reconciliation cycle. Accepted and bounded (≤ 30 s, usually immediate because reconnect triggers a pass); the native SL continues to protect the position throughout.
- More states to test. Mitigated by an exhaustive state-transition test matrix and chaos tests that inject timeouts, duplicate acks, out-of-order fills and reconnect storms.

### Why not the alternatives

- **Retry-on-timeout**: the simplest thing that appears to work and the most dangerous. A lost ack on a submitted order plus a retry equals two positions. Rejected outright.
- **Mirror the exchange only**: avoids local-state divergence but cannot support emulated algos, trade groups, rule-driven management or a journal, and polling latency is incompatible with our budgets.

## Validation

- Spike S3: 24 h soak of the private WS client on demo with zero missed executions.
- Chaos suite (`03-testing-strategy.md`): kill the process mid-submission, drop the private WS for 60 s, inject 10018 and 10002, replay duplicate acks — in every case, no duplicate position and no unmanaged order.
- Contract tests against recorded Bybit fixtures for every state transition.

## Amendment 1 (2026-10-16, E29-T02 #846; decision owner-delegated per #1778, interim, owner veto on #2701)

Refines binding rule 1; does not reverse it ([orchestrator ruling B2 on #846](https://github.com/basiltt/CandleViewer/issues/846#issuecomment-6204432470)). The `orderLinkId` format is defined only in `docs/plan/24-internal-schemas.md` §8.3, its owner under C-16.5, and that scheme replaces the `{group_id}-{account_short}-{seq}` shape in rule 1. Generating the id before the first send and reusing it unchanged on every retry are unchanged.
