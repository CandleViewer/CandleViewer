# ADR-0006 — OMS state machine, idempotency and reconciliation

- Status: **decided**; binding rule 5 and the last clause of rule 6 are superseded by ADR-0044, rule 1 is refined by
  Amendment 1, and rules 2 to 4, the third decision driver and the state list by Amendment 2
- Date: 2026-09-14
- Deciders: Architect, Backend lead, Security engineer, Owner
- Consulted: `docs/research/06-bybit-api.md` §5, §11, §14, §19, `docs/research/09-execution-risk-tools.md` §6, §8, `docs/research/11-backend-tech.md` §2.5, `docs/research/22-architecture-options.md` §6
- Superseded in part by: [ADR-0044](ADR-0044-rest-order-entry-and-code-only-rejections.md) (2026-11-03): binding rule 5
  and the last clause of rule 6, and nothing else
- Related: ADR-0008, ADR-0044, `docs/plan/24-internal-schemas.md`, `docs/plan/20-architecture.md` §3.5

## Context and problem statement

The OMS manages real money across multiple Bybit sub-accounts over a network that will disconnect, a REST API that will rate-limit, and a private WebSocket that will drop. The hardest correctness problem is not the happy path — it is what happens when a submission's acknowledgement is lost. Blind retries risk duplicate positions; blind abandonment risks an unmanaged order. We need a state machine that makes the uncertain case explicit and a recovery procedure that is deterministic.

## Decision drivers

- Bybit supports `orderLinkId`, a client-supplied identifier deduplicated within the retention window — a genuine idempotency primitive.
- Demo retains orders for only 7 days and offers no WS order entry; live offers both REST and WS trade.
- Reconnect reconciliation has a documented shape: re-auth private WS, `GET /v5/order/realtime` + `/v5/position/list` for authoritative state, diff by `orderLinkId`, backfill `GET /v5/execution/list` for the gap window. _(The diff is by the bound `orderId`, not by `orderLinkId`: Amendment 2, item 1.)_
- Error 10002 (clock drift) and 10018 (rate limit) must be distinguishable from business rejections.
- The process may die at any moment; the safety story cannot depend on it being alive (see ADR-0008 for the native-SL invariant).

## Considered options

1. **Explicit state machine including an `Unknown` state, `orderLinkId` idempotency, resolution by reconciliation only.**
2. **Optimistic local state with retry-on-timeout** (resubmit until acknowledged).
3. **Mirror the exchange only** — hold no local state, poll REST for truth.

## Decision outcome

**Chosen: option 1.**

States: `Draft → Validated → Submitting → {Submitted | Rejected | Unknown}`; `Submitted → {PartiallyFilled, Filled, CancelPending, AmendPending}`; `CancelPending → {Cancelled, Filled}`; `AmendPending → {Submitted, Rejected}`. Terminal: `Filled`, `Cancelled`, `Rejected`. _(B1 has 17 states, five of them terminal: Amendment 2, item 2.)_

Binding rules:

1. **`orderLinkId` is generated before the first send** as `{group_id}-{account_short}-{seq}` (≤ 36 chars) _(format superseded by Amendment 1: `docs/plan/24-internal-schemas.md` §8.3)_ and reused unchanged on every retry of that logical order. It is the primary key for correlation everywhere — logs, audit, journal, reconciliation.
2. **Any transport failure after send lands in `Unknown`.** There is **no blind resubmission** from `Unknown`. Resolution comes only from reconciliation: if `GET /v5/order/realtime` (or the execution backfill) finds the `orderLinkId`, the order transitions to its true state; if two consecutive reconciliation passes find nothing, it becomes `Rejected`. _(Refined by Amendment 2, item 3.)_
3. **`oms_unknown_orders > 0` for 60 s pages the operator.** An unknown order is an operational incident, not a background condition. _(Refined by Amendment 2, item 4.)_
4. **Reconciliation runs on startup, on every private-WS reconnect, and every 30 s.** It diffs local state against exchange truth by `orderLinkId`, backfills executions for the gap window `[last_seen_ts, now]`, and emits corrections onto the bus so every view converges. _(Refined by Amendment 2, item 5.)_
5. **Transport selection is a capability decision, not an `if`.** `ExchangeCapabilities.supports_ws_order_entry` chooses WS trade (live) or REST (demo). No environment conditionals outside the adapter. _(Superseded by ADR-0044, decision 1: v1 sends every order over REST.)_
6. **Error taxonomy is mapped in the adapter**: `ClockDriftError` (10002) blocks order entry entirely and raises a distinct alert; `RateLimitError` (10018) feeds the token bucket and rejects submits with `RATE_BUDGET_EXCEEDED` rather than silently queueing them past their usefulness; business rejections carry the exchange message verbatim to the UI. _(The last clause is superseded by ADR-0044, decision 2: the
   exchange's text is code-only to every client and stored redacted.)_
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

### Validation status (2026-11-03, E29-T09 #1029)

None of the three checks above has its measurement recorded. E29-K01's definition of done owns them (#843): the private-WS
soak, the demo order-path numbers and the renegotiation of budget #4 (`06-performance-and-load-standard.md` §5.2), appended
here as its addendum when it reports. E29-T09 closes without that clause (the orchestrator's ruling on #1029, BQ-1). K01 is
parked on one human step, a fresh demo key from the owner ([#843, comment 6492004711](https://github.com/CandleViewer/CandleViewer/issues/843#issuecomment-6492004711));
its harness is built and offline. Until it reports no decision driver above is confirmed by a measurement, and budget #4
is still the assumption (p95 under 300 ms on demo, at most 50 ms of it ours). What exists on `main` (paths under `services/api/`):

- Chaos: scenarios s1 to s4 of `tests/chaos/oms/` (the private stream killed for 60 s, redelivered fills, fills out of
  order, a push after a terminal state), which are E29-T05's halves of the C-13.6 rows (`SCENARIOS.md` there). E29-Q04
  (#1148) owns the rest: the pass's correctness after the kill, the restart, scenario 12, the oracle and Postgres failover.
- Transitions: the B1 contract suite (`tests/xstate_contract/test_b01_order*.py`) runs every arm of
  `28-statechart-catalogue.md` §B1.3 and the persist and restore round trip. It runs on constructed events: the recorded
  Bybit captures the third check names are K01's fixtures.

## Amendment 1 (2026-10-16, E29-T02 #846; decision owner-delegated per #1778, interim, owner veto on #2701)

Refines binding rule 1; does not reverse it ([orchestrator ruling B2 on #846](https://github.com/CandleViewer/CandleViewer/issues/846#issuecomment-6204432470)). The `orderLinkId` format is defined only in `docs/plan/24-internal-schemas.md` §8.3, its owner under C-16.5, and that scheme replaces the `{group_id}-{account_short}-{seq}` shape in rule 1. Generating the id before the first send and reusing it unchanged on every retry are unchanged.

## Amendment 2 (2026-11-03, E29-T09 #1029; decision owner-delegated per #1778, interim, owner veto on #2701)

Refines the third decision driver, the state list and binding rules 2, 3 and 4 to what E29-T01 to E29-T06 shipped; reverses
none of them ([orchestrator ruling BQ-2 on #1029](https://github.com/CandleViewer/CandleViewer/issues/1029#issuecomment-6603185027)).
Rule 5 and the last clause of rule 6 changed outcome, so ADR-0044 supersedes them. Rules 1, 7 and 8 and the core decision
(an explicit `Unknown` state, `orderLinkId` idempotency, resolution by reconciliation) stand. Each item names the document
that owns the detail now (C-16.5); evidence holds on `main` at `b81479ab0`, paths under `services/api/candleviewer/`.

1. **The diff is by the bound `orderId`.** Reconnect reconciliation pairs an exchange order with its row by the
   `orderId` the row has bound, and a row with none bound only by the full match against its persisted terms; an
   `orderLinkId` names a row to look at and proves nothing about who placed the order (SR-E29-03). The execution backfill
   keeps the driver's shape, over a gap window with a 5 s overlap (`24-internal-schemas.md` §8.3 rules 2, 3 and 7, §8.5;
   `oms/pairing.py`).
2. **The chart has 17 states.** B1's `lifecycle` region adds `triggered`, `quarantined`, `untracked`, `held`, `expired` and
   `killed` to the eleven named above; the terminal states are `filled`, `cancelled`, `rejected`, `expired` and `killed`.
   `28-statechart-catalogue.md` §B1 owns the chart and `24-internal-schemas.md` §8.2 the persisted names.
3. **Rule 2: one lookup, at most one re-send, never from `unknown`.** No order in `unknown` is re-sent: reconciliation
   alone resolves it (B1 INV-B1-e, `24` §8.2 S1). One create is re-sent, once: a create a restart resumes, whose send may
   or may not have left (SR-E29-15). It looks the id up first, in open orders and then in history, and adopts an order it
   finds only after the full match; only when neither shows the id, the switches and the clock-drift halt allow it, and
   history still covers it (on live, within `LIVE_RESEND_MAX_AGE_S`, 120 s) is it sent once more under the same id and
   native stop. A duplicate-id rejection is looked up at once, never re-sent under another id (`24` §8.3 rules 3 and 6, §8.6;
   `oms/order_link_resolution.py` `adopt_or_resend`, `oms/commands.py` `_resumed`). The last clause refines too: two
   consecutive misses end an order `rejected`, with `UNRESOLVED_AFTER_RECONCILE` where history still covers the id and
   `DEMO_RETENTION_EXPIRED` on demo past 6 days; but a live order older than the venue's 24 h span is never abandoned: it
   pages once and stays `unknown` (`24` §8.5, "When a history miss decides").
4. **Rule 3: what pages.** An order in `unknown` is still an incident. `oms_unknown_orders` counts the live orders whose B1
   machine is in `unknown` (SR-E29-16, `20-architecture.md` §12.1); an exchange order the OMS has no row for is `untracked`
   and counted by `oms_untracked_orders`. A cancel the venue answers `110001` also parks an order in `unknown`, with the
   reason `already_terminal`, and its own alert, `order_already_terminal`, is a ticket (`24` §8.6). The count's page after
   60 s is still the one rule on `main`: E29-T08 (#916) is open and is to split that page by the reason, and E29-T09's
   closing slice records the rule that shipped when it merges.
5. **Rule 4: the driver, the cadence and the stale lock.** The cadence stands (startup, every private-WS reconnect, every
   30 s, jittered per account), and a pass also runs when B1 asks for one: for a `quarantined` order, or a cancel the venue
   answered `110001`. Its driver is one B19 job per account (`oms/reconcile_job.py`, `28` §B19): a pass never overlaps
   itself. A pass records an exchange order no row is bound to as `untracked`, audited as `order.adopted_untracked`, and
   never manages it: no human adopt action exists in v1 and B1's `adoption_allowed` denies every `ADOPT` (D6, BQ-17). What
   a lookup or the private stream could not pair waits in `oms_handovers` (migration `0058`) for the next pass (`24` §8.3
   rule 7). Two minutes of failed
   fetches (`STALE_AFTER_S`, `oms/reconcile_standing.py`) refuse the account's order entry with `account_stale` (`24` §8.10)
   and lock the job in `stale_lockout`, where no pass runs until the Owner resolves it (`resolveReconciliation`); a good pass
   never clears the lock, and protective paths never consult it (C-2.6). The two Owner routes, `reconcileAccount` (a pass on
   demand) and `resolveReconciliation`, are contract-only on `main` until E29-T06's route PR (#5233) merges, and `24` §8.5
   records them as built then.
