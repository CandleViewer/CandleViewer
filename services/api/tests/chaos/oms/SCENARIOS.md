# E29-T05 — the private stream's chaos scenarios (T05's half)

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

| #   | C-13.6                                  | Fault injected                                                  | Declared degradation → recovery                                                                                                                                                                       | Signal                                                                  | Metric                                                                                       | Observed |
| --- | --------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------- |
| s1  | #2, T05's half                          | the stream killed 60 s, an order open                           | one notice; the silence bound (30 s) ends the session and the refresh (15 s) subscribes again; one request per reconnect, paged once per episode; the order untouched; the fill after it applies once | `system` `oms.account_resyncing` naming the account; `/readyz` `oms` ok | `oms_stream_outcomes_total{stage="consumer"}`: `silence` +1, `reconciliation_unavailable` +2 | ✅       |
| s2  | #7, its idempotency half; #3's analogue | fills redelivered across a reconnect and in the next bundle     | each fill stored and counted once; the order `filled`                                                                                                                                                 | —                                                                       | —                                                                                            | ✅       |
| s3  | #3's analogue                           | fills in reverse `seq`; an end older than the order's last push | the in-order totals (INV-B1-a); the old end ignored (S5), no anomaly                                                                                                                                  | —                                                                       | `push` `anomaly` +0                                                                          | ✅       |
| s4  | none (#2 the nearest)                   | four ends after `filled` (E29-Q04's "Post-terminal push")       | the order unchanged; each push `oms.reconcile_anomaly` (`POST_TERMINAL_PUSH`) and alerted                                                                                                             | alert `oms_reconcile_anomaly`                                           | `push` `anomaly` +4                                                                          | ✅       |

## Verification recorded

**Mutation runs** (one mechanism neutered at a time, each run under `timeout 120`, then restored
byte for byte):

| Mechanism                   | Neutered (file:function → behaviour)                                                   | Fails                                 |
| --------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------- |
| One page per episode        | `oms/stream_consumer.py:_resync` → every refused request pages                         | s1                                    |
| The silence bound           | `oms/stream_consumer.py:_consume` → `asyncio.timeout(None)`: a dead session never ends | s1 (and scenario 3's acceptance test) |
| B1's repeat guard           | `statechart/bindings/b01_order.py:_admit` → no `REPEAT` refusal                        | s2 (and scenario 4's)                 |
| The facade's staleness mark | `oms/order_machine.py:_take` → `stale = False`: an older end is taken                  | s3, the stale test                    |
| S6 for an ended order       | `oms/order_machine.py:push` → an evicted order's push returns, unrecorded              | s4 (and scenario 5's)                 |
| The anomaly's count         | `oms/stream_push.py:_attempt` → a `ReconcileAnomaly` counted `paired`                  | s4 (and scenario 5's)                 |

The store's own `exec_id` dedupe (`oms/fakes.py:_commit_fill`), neutered, fails neither s2 nor
scenario 4: B1's repeat guard refuses the push first. The write-ahead contract's
`test_duplicate_fill_never_double_counts` fails on it (`tests/unit/oms/test_write_ahead_fake.py`).
Unmutated: `5 passed`, and five runs in a row green (`-p no:randomly`).

## Not covered here

- E29-Q04's (#1148): the pass's correctness after #2, the restart of #7, #12, the oracle and
  Postgres failover.
- E29-T06's (#914): the reconciliation pass itself, and keeping a fill with no OMS intent.
