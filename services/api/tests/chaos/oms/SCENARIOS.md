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

Slices 1 and 2 of 4: the harness, the oracle, the meta-test, s5 and s6 (slice 1), and s4b and s7
to s13 (slice 2), in the same lane. Built to the
ruling on #1148's blocking questions (comment 6603186420): BQ-1, BQ-4 and BQ-9 as amended, BQ-6 as
ruled (the oracle holds a native stop sized to each position), the rest as recommended; BQ-5 is
held, and no S1 scenario reaches that point.

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

**Slice 2.** What the slice-1 lens asked of the harness: one venue port per world, held from the
start, which moves an ended order out of its open book (`VenuePort.seed_order`, so the open read
no longer filters); a hand-over store that reads back what it was given (`Handovers`, 21
Sec.3.3.12's rules); and no assertion on the stream consumer's host time (a row's lag, its
`ts_ingest`). It adds the stream's own news (`Venue.status`), an end pushed ahead of the venue's
reads (`end_unread`, `settle`), the venue's `10002` and `10018` (`drift`, `ip_limit`; with the
adapter's `TokenBucketGovernor` a `10018` holds the IP as `rest.py` does, and the port's headroom
and creates are the governor's), a process before the runtime over the same store and venue
(`opened(before=)`), the lane writer's double whose log fills (`Wal`), a watch on the
account's passes (`World.passes`) and their records (`World.reports`), and a fill that leaves
the position without the create's stop (`attached` off), a stop the OMS then writes moving it
no earlier than the next millisecond, pushed (`VenuePort.set_trading_stop`).

| #          | C-13.6            | Keys                      | Fault injected                                                                                                                                               | What the operator sees                                                                                              | Which alert                                                                                             | Expected recovery                                                             | Asserted                                                                                                                                                                                                                                                     | Observed                                                                                                   |
| ---------- | ----------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| s4b        | none (#2 nearest) | E29-T03, E29-T06          | an order cancelled on the stream while the venue's reads still show it open                                                                                  | the order `cancelled`; the account `divergent`, the order in each pass's anomalies until the venue's reads catch up | the pass's `oms_reconcile_anomaly` alert, once an episode; B19's divergence alert (asserted in slice 4) | the next pass after the venue catches up, ≤ 30 s                              | the row and its steps unchanged; listed in each pass's `oms.reconcile` record; alerted once; nothing adopted or sent; one create; the oracle                                                                                                                 | ✅ 26.0 s                                                                                                  |
| s7         | #2                | E29-T05, E29-T06          | the socket lost 29.5 s while an order is part filled; the rest filled in the gap, its pushes lost                                                            | `partially_filled` until the reconnect, then `filled`, the position corrected                                       | `oms_position_drift` page: the pass corrected the position (asserted in slice 4)                        | the reconnect's pass, ≤ 5 s                                                   | stale until the reconnect; that pass lists the correction; usable within 5 s; one create; the gap's fills, the position and its native stop (the oracle)                                                                                                     | ✅ 0.0 s                                                                                                   |
| s8         | #2, repeated      | E29-T05, E29-T06          | a lost ack, then 3 bursts, a second apart, of 4 sockets lost and regained at once                                                                            | the order `unknown`, then `submitted`                                                                               | B1's `order_unknown` page, the storm's only one                                                         | the storm's first pass                                                        | bound by the full match; at most one pass open; each reconnect a pass or a logged skip, none queued; one page; one create; the oracle                                                                                                                        | ✅ 0.0 s                                                                                                   |
| s9         | #7                | E29-T02, E29-T04          | a restart finds an order `submitting` whose create the venue already holds (the process went down after the send); the order's `new` row twice on the stream | the order `submitted` after the restart                                                                             | —                                                                                                       | the restart's sweep                                                           | looked up first, bound by the full match (`adopted_after_lookup`), not sent again: one create; an acknowledgement row maps to no B1 event (24 Sec.8.12): its redelivery is read and changes nothing; the oracle                                              | ✅ at the restart                                                                                          |
| s10        | #6                | E29-T04, E29-T08          | the venue refuses a create `10002`                                                                                                                           | `502` with `10002`; then `503 clock_drift`, `Retry-After` 5, until the clock is measured afresh                     | `oms_clock_halt_trips_total` +1 (its rule: #5542)                                                       | the clock guard's next measurement after the trip                             | nothing recorded or sent while halted, after the trip's own resync too; sent once after; the oracle                                                                                                                                                          | ✅ 1.0 s, test-driven (in production: the resync the trip asks for, ≤ 10 s; the guard's own cadence 300 s) |
| s11        | #5, half          | E29-T04, E29-T06          | the venue answers a pass's read `10018`; the IP hold is `rest.py`'s (`test_rate_limit_10018_holds_every_uid_for_ten_minutes`)                                | `429 exchange_rate_limited`, `Retry-After` 60; after 2 min the account stale, new orders refused                    | `bybit_ip_hold_remaining_seconds` 600; `oms_rate_reject_total` +1; the stale page                       | the hold, 600 s, then the Owner's `resolveReconciliation`                     | nothing recorded or sent; the position keeps its create's native stop; locked stale; entry back after both; the oracle                                                                                                                                       | ✅ 604.8 s, test-driven (in production: ≥ the 600 s hold, then the Owner)                                  |
| s12        | #10               | E29-T03, E29-T04          | the tier refuses the VALIDATE commit (`commit` door)                                                                                                         | `503 store_unavailable`                                                                                             | —                                                                                                       | the tier's return: the same request, its key unspent                          | nothing recorded, no create; the retry sent once; the oracle                                                                                                                                                                                                 | ✅ at once                                                                                                 |
| s13        | #10, audit half   | E29-T04                   | the lane writer's log full, Postgres down; an entry's first fill finds its position without the create's stop                                                | `503 audit_unavailable`; the entry's protection `sl_missing`, its position without a stop                           | the writer's alarm, `oms_lane_audit_alarm`; `SL_ATTACH_FAILED`                                          | the log's drain: a submit at once; the stop at the position's next due attach | the submit refused before anything is recorded or sent; the due stop write withheld: no `set_trading_stop`, `SL_ATTACH_FAILED` paged; after the drain a submit accepted, one more create, and its due attach writes the stop, nothing more paged; the oracle | ✅ at the drain                                                                                            |
| s14 to s16 | #12, #7, #10      | E29-T04, E29-T06, E29-S03 | SIGKILL mid-submission and mid-partial-close; a real node's outage                                                                                           | planned: slice 3, the Postgres tier and the nightly                                                                 |                                                                                                         |                                                                               |                                                                                                                                                                                                                                                              | planned                                                                                                    |

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

Slice 2's rows in `test_teeth.py`: s7 and s8 over the stand-ins fail the oracle (s7 on the order's
state, filled quantity and executions, the gap's `exec_id` and the position's size; s8 on the
order's id and state); s4b's book is the venue's either way (S6), and over the stand-ins nothing
alerts or records its anomaly. Each non-pass scenario's defence removed in the test, the outcome it
forbids happens:

| Scenario | Defence removed                                                              | Then                                                                                                                                                                                                   |
| -------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| s9       | the resumed create's lookups (`commands.find_by_link_id`, `adopt_or_resend`) | the re-send meets the venue's refusal of a reused id, the lookup after it binds the one order, and the oracle fails: 2 creates                                                                         |
| s10      | the clock halt (`ClockHalt.refusal` answers None)                            | the create it refuses reaches the venue                                                                                                                                                                |
| s11      | the IP hold (`TokenBucketGovernor.hold_ip` holds nothing)                    | the create it refuses reaches the venue                                                                                                                                                                |
| s13      | the writer's refusal (`Wal(refuses=False)`: a full log drops)                | the create it refuses reaches the venue: it proves the refusal's cause, not production's fail-closed code, which one-off mutants removed (the submit's and the attach's write-ahead), each failing s13 |

**Deviations, as ruled.** The suite path and the venue (BQ-1, amended): it extends
`services/api/tests/chaos/oms/`, not the ticket's top-level `tests/chaos/oms/`, and its faults are
test doubles on the composed runtime and `FakeTradingPort`, with no mock-exchange control plane and
no container orchestration; the Postgres tier (slice 3) runs on testcontainers. Postgres failover
(BQ-4, amended): an outage of the one node at named commits; a promoted-instance failover is
post-GA, E45-T08's. The partial-close resize (BQ-6): the oracle holds each position's stop to its
size, never weakened to fit; #978 shipped its BQ-1 option A (#5356 merged, 24 Sec.19.73: below
100 % no stop is resized, which is E32-S02's), so that row is an open deviation on #978, with
E32-S02 named. E29-S07's banner, controls and summary (BQ-9, amended):
E29-Q02's (#1147); the server half is slice 4's, s7's "never stale as live" with it. The stores
are in memory. The 10018 reserve for stop and cancel (s11): E34-T02's, its chaos E34-Q04's. s4b's
anomaly is audited in the pass's own record (`oms.reconcile`, 24 Sec.8.5 step 3c), the facade's
`oms.reconcile_anomaly` being the stream's (s4). s4b uses a venue whose reads lag its stream,
which lets the oracle end clean once they catch up. s9's restart is in process; s14 is the
SIGKILL. s13's writer is a double; `test_writer_wal_full_with_postgres_down_refuses_never_drops`
pins the writer's refusal, and its fills show the position without the create's stop, so each
entry's attach is due. s7's outage stays inside the consumer's 30 s silence bound, and its 5 s runs
from the reconnect. The alert names and runbook anchors wait for #5542, the labelled metrics for
#5339.

## Not covered here

- E29-Q04's slices 3 and 4 (#1148): the planned s17 in this lane; the Postgres tier (s14 to s16,
  the SIGKILL child of #12) and the nightly; the labelled metrics, the alerts and E29-S07's server
  half.
- s12's other commit points: a later slice, with a server fix (held privately)
- E29-T06's (#914): the reconciliation pass itself, and keeping a fill with no OMS intent.
