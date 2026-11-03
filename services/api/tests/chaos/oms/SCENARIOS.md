# The OMS chaos scenarios: E29-T05's half, and E29-Q04's

Suite: `services/api/tests/chaos/oms/` (marker `chaos`, PR-lane safe, no Docker), from E29-T05's
closing slice (#848). Run: `cd services/api && uv run pytest tests/chaos/oms -m chaos --no-cov`.

**Harness.** `tests/unit/oms/stream_world.py`: the private-stream consumer as the OMS runtime
composes it (`build_stream_consumer`, S8b), over the real facade (`OrderMachines` on B1 and the
in-memory order, execution and recorded-stop stores), `FakeTradingPort` as the venue (each account's
private stream and a fill's order read), `FakeClockHealth` as the clock guard, the shipped stand-ins
(`NoReconciliation`, `NoHandoverStore`, `NoPositionProtection`, `PagingForeignOrderLockout`) and a
recording double for every other port. Each test runs on a `VirtualTimeLoop`
(`tests/unit/audit/audit_waits.py`): the 30 s silence bound, the 15 s refresh and every port bound run
on fake seconds, never the wall clock (C-13.7). The rows are derived in-test from the corpus's docs
transcriptions and read by the adapter's own parser: derived, not evidence (the 2026-10-28 ruling
Q1). The recorded private session is E29-K01's (#843).

**Whose rows.** E29-Q04 (#1148) owns this directory's harness, its oracle (a field-by-field compare
against exchange truth), its nightly and the halves of the C-13.6 rows below that are not E29-T05's.
These four files are E29-T05's halves. They run on every PR (CI's `db-chaos-5` lane, `chaos` only),
and no nightly is added (the ruling Q4).

## Deviations from the composition root

- One loop: the consumer, the facade and the venue share the test's. The lane bridge
  (`oms_streams`) is proven on Postgres by `tests/integration/oms/test_private_stream_replay_pg.py`.
- The venue's private stream is `FakeTradingPort.subscribe_private`, one queue per account: no
  socket, no dial and no backoff (G-8b's, #4135). A status is queued as the adapter yields it.
- B1's command port, and the facade's audit writer and pager, are `order_rig`'s doubles; the
  consumer's audit writer and pager are the world's.

## Catalogue

| #   | C-13.6                                  | Fault injected                                                                  | Declared degradation → recovery                                                                                                                                                                       | Signal                                                                  | Metric                                                                                       | Observed |
| --- | --------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------- |
| s1  | #2, T05's half                          | the stream killed 60 s, an order open                                           | one notice; the silence bound (30 s) ends the session and the refresh (15 s) subscribes again; one request per reconnect, paged once per episode; the order untouched; the fill after it applies once | `system` `oms.account_resyncing` naming the account; `/readyz` `oms` ok | `oms_stream_outcomes_total{stage="consumer"}`: `silence` +1, `reconciliation_unavailable` +2 | ✅       |
| s2  | #7, its idempotency half; #3's analogue | fills redelivered across a reconnect and in the next bundle                     | each fill stored and counted once; the order `filled`                                                                                                                                                 | —                                                                       | —                                                                                            | ✅       |
| s3  | #3's analogue                           | fills in reverse `seq` before the bind; an end older than the order's last push | held, then applied in `seq` order once bound: the in-order totals (INV-B1-a); the old end ignored (S5), no anomaly                                                                                    | —                                                                       | `push` `held` +3, `anomaly` +0                                                               | ✅       |
| s4  | none (#2 the nearest)                   | four ends after `filled` (E29-Q04's "Post-terminal push")                       | the order unchanged; each push `oms.reconcile_anomaly` (`POST_TERMINAL_PUSH`) and alerted                                                                                                             | alert `oms_reconcile_anomaly`                                           | `push` `anomaly` +4                                                                          | ✅       |

## Verification recorded

**Mutation runs** (one mechanism neutered at a time, each run under `timeout 120`, then restored
byte for byte):

| Mechanism                   | Neutered (file:function → behaviour)                                                   | Fails                                 |
| --------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------- |
| One page per episode        | `oms/stream_consumer.py:_resync` → every refused request pages                         | s1                                    |
| The silence bound           | `oms/stream_consumer.py:_consume` → `asyncio.timeout(None)`: a dead session never ends | s1 (and scenario 3's acceptance test) |
| B1's repeat guard           | `statechart/bindings/b01_order.py:_admit` → no `REPEAT` refusal                        | s2 (and scenario 4's)                 |
| The facade's staleness mark | `oms/order_machine.py:_take` → `stale = False`: an older end is taken                  | s3, the stale test                    |
| The reorder buffer's order  | `oms/order_machine.py:_hold` → no sort: held fills leave in arrival order              | s3, the reverse-`seq` test            |
| S6 for an ended order       | `oms/order_machine.py:push` → an evicted order's push returns, unrecorded              | s4 (and scenario 5's)                 |
| The anomaly's count         | `oms/stream_push.py:_attempt` → a `ReconcileAnomaly` counted `paired`                  | s4 (and scenario 5's)                 |

The store's own `exec_id` dedupe (`oms/fakes.py:_commit_fill`), neutered, fails neither s2 nor
scenario 4: B1's repeat guard refuses the push first. The write-ahead contract's
`test_duplicate_fill_never_double_counts` fails on it (`tests/unit/oms/test_write_ahead_fake.py`).
Unmutated: `5 passed`, and six runs in a row green (`-p no:randomly`).

## E29-Q04 (#1148): the composed runtime, the venue and the oracle

Slice 1 of 4: the harness, the oracle, s5, s6 and the meta-test, in the same lane. Built to the
ruling on #1148's blocking questions (comment 6603186420): BQ-1, BQ-4 and BQ-9 as amended, BQ-6 as
ruled (the oracle holds a native stop sized to each position), the rest as recommended; BQ-5 is
held, and nothing here depends on it.

**Harness.** `_world.py`: the OMS runtime as the process composes it (`OmsRuntime`, 20 Sec.6.2),
on `tests/unit/oms/test_oms_runtime.py`'s `World`, extended: the pipeline's submit as `placeOrder`
reaches it; in-memory position, reconciliation-read and hand-over stores, so the runtime composes
E29-T06's pass, not its stand-ins; the account's private stream on `subscribe_private`
(`streamed`); the storage tier's outage switch; and four named doors, `send` (the SEND step's
commit), `place` (the venue's create), `ack` (the commit of the create's answer) and `commit` (the
next commit), faulted through the store's own `fail_next` or the fake's own `script`. Each test
runs on a `VirtualTimeLoop`: the job's 30 s cadence runs on fake seconds (C-13.7).

**The venue.** `_venue.py`: `FakeTradingPort` (G-8) on the world's wall clock, moved through its
public seeding methods only and read through its own reads: fills and partial fills whose totals
are the sum of their executions, and the position an entry opens, with the stop and take-profit
its create attached (Full mode, C-2.6), each pushed on the account's stream or withheld. Its
creates are counted per `order_link_id` from the fake's own call log, outside the app. The venue
facts are 24's documented ones, not measured (E29-K01, #843, is open): derived, not evidence.

**The oracle.** `_oracle.py`, at each scenario's end once the runtime has settled and the job
rests: each order (its ids, its B1 state against 24 Sec.8.12's status table, written there, its
quantity and filled quantity, the sum of its executions on both sides, its average price, price,
trigger, stop, take-profit, `reduce_only`, side and `position_idx`), each execution (the
`exec_id` sets, each one's quantity, price, fee and order), each open position (side, size,
average entry and stop, and a native stop at the venue sized to it, C-2.6: its own Full-mode stop,
or Partial-mode stops adding up to it) and the cardinality (no row the venue does not hold but a
`rejected` or `killed` one, no venue order without a row, one create per id of ours). Any
difference raises `OracleMismatch`, listing every field. An autouse fixture (`conftest.py`) fails
a test whose world the oracle never checked. Recovery times are asserted on virtual time, and
printed (`pytest -rA` shows them): the table's last column.

| #   | C-13.6       | Keys             | Fault injected (door)                                                                       | What the operator sees                                                                                                        | Which alert                                                                                                    | Expected recovery                   | Asserted                                                                                                                                                                                   | Observed        |
| --- | ------------ | ---------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------- |
| s5  | #4, #7       | E29-T04, E29-T06 | `place`: the venue takes the create, its answer is lost; the order rests, or fills unpushed | `202` `unknown`; the order `unknown`, then `submitted`, or `filled` with its fill and its position, the position's stop shown | B1's `order_unknown` page at once; `oms_unknown_orders` > 0 for 60 s is not reached (its rule: #5542)          | the next periodic pass, ≤ 30 s      | one create; bound by the full match (step 3a, or 3b once filled); `oms_unknown_orders` 1 → 0; `oms_reconcile_corrections_total{kind}` `corrected` (`resolved_from_history`) +1; the oracle | ✅ 30.0 s, both |
| s6  | #4 (nearest) | E29-T04, E29-T06 | `place`: the create times out after it left and never lands                                 | `202` `unknown`; after the second pass `rejected`, `UNRESOLVED_AFTER_RECONCILE`                                               | B1's `order_unknown` page at once; `oms_unknown_orders` > 0 for 60 s may page as the second pass lands (#5542) | two periodic passes, ≤ 60 s         | one create, nothing at the venue; one miss kept, the second rejects; `oms_unknown_orders` 1 → 0; `{kind="abandoned"}` +1; the oracle                                                       | ✅ 60.0 s       |
| s17 | #9           | E29-T04, E29-T08 | an entry's stop attach refused at the venue (planned: a later slice)                        | the position held by its native stop all along: the fallback attach or the pass's step 5 restores it                          | `SL_ATTACH_FAILED` paged; `naked_position_alerts_total` +1 (its rule: #5542)                                   | the next pass at the latest, ≤ 30 s | the position never left naked at quiescence; the oracle                                                                                                                                    | planned         |

**Negative controls.** The meta-test (`test_teeth.py`) runs s5 (both) and s6 over the composed
pass, where the oracle is clean, and over the stand-ins the runtime composes without E29-T06's
stores (`World(handover_store=None, reconcile_reads=None)`), where it must raise naming the fields
that differ. Each mechanism below was neutered alone, its tests run, then restored (`git status`
clean); unmutated, the directory passes twice and once in a seeded shuffled order:

| Mechanism                   | Neutered (file:function → behaviour)                                              | Fails                                                                                                                                                                                                       |
| --------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The pass's periodic trigger | `oms/reconcile_job.py:ReconcileJobs._cadence` → returns at once: no periodic pass | s5 (resting, filled) and s6, each also erroring at teardown on its unchecked world, and `test_teeth` over the pass (3); the stand-in runs still pass                                                        |
| The oracle's field compare  | `tests/chaos/oms/_oracle.py:_differing` → compares nothing                        | `test_oracle`'s 23 field cases and its one-mismatch test, and `test_teeth` over the stand-ins (s5 resting, filled); its 9 cardinality, consistency and C-2.6 cases, which do not compare fields, still pass |
| The venue's create count    | `tests/chaos/oms/_oracle.py:_orders` → checks no create count                     | `test_oracle` (`second-create`); s5 still passes, its count being 1                                                                                                                                         |

**Deviations, as ruled.** The suite path and the venue (BQ-1, amended): it extends
`services/api/tests/chaos/oms/`, not the ticket's top-level `tests/chaos/oms/`, and its faults are
test doubles on the composed runtime and `FakeTradingPort`, with no mock-exchange control plane and
no container orchestration; the Postgres tier (slice 3) runs on testcontainers. Postgres failover
(BQ-4, amended): an outage of the one node at named commits; a promoted-instance failover is
post-GA, E45-T08's. The partial-close resize (BQ-6): the oracle holds each position's stop to its
size, and slice 3 asserts the resize completes; if #978 ships its BQ-1 option A, that row stays an
open deviation on #978 with E32-S02 named. E29-S07's banner, controls and summary (BQ-9, amended):
E29-Q02's (#1147); the server half is slice 4's. In this slice the stores are in memory, and
`seed_order` cannot take an ended order out of the fake's open book, so the venue's open read
leaves out the orders the engine ended (`VenuePort.open_orders`); nothing here cancels or amends
one. The alert names and runbook anchors wait for #5542, the labelled metrics for #5339.

## Not covered here

- E29-Q04's slices 2 to 4 (#1148): s4b, s7 to s13 and the planned s17 in this lane; the
  Postgres tier (s14 to s16, the SIGKILL child of #12) and the nightly; the labelled metrics, the
  alerts and E29-S07's server half.
- E29-T06's (#914): the reconciliation pass itself, and keeping a fill with no OMS intent.
