# E12-Q06 - Bars chaos catalogue

Suite: `services/api/tests/chaos/bars/` (marker `chaos`; dense variants also `harness`).
Run, one file at a time: `cd services/api && uv run pytest tests/chaos/bars/<file> -m chaos --no-cov`.
Ticket #529. Delivered in two parts: **PR-1** (#5319) the harness and scenarios 2, 3 and 6;
**PR-2** scenarios 1, 4, 5, 7 (placeholder) and 8, the report template and the nightly. All eight
scenarios are covered; scenario 7 is a skipped placeholder until #535 builds the rebuild.

**Harness.** A production `BarBuilderSet` is registered on the bus of the ingestion `Rig`
(`tests/chaos/ingestion/`: stub exchange, virtual clock, seeded jitter, `settle()`), used through
its public attributes only. The bars see the rig's own `TradeStream` output. `tick()` is driven
from the virtual clock once per virtual second; `BarBuilderSet.start()` (a real-time ticker) is
never called and a guard in `conftest.py` makes it fail if it is. The only sink is a
`CaptureSink`; no store, no network, recorded corpus only (C-13.5).

**Golden.** What the venue printed (`StubExchange.trades`, untouched by wire faults), folded
through E12-Q02's runner (`bench.bar_conformance.runner.run_set`) and compared with E12-Q02's
comparator. The only difference ignored is the golden tail bar's `closed` flag (the runner does
not tick past the last print). `test_harness_guards.py` proves a clean run equals it.

**Store seam (PR-2).** `BarsRig(extra_sinks=[WriterSink(BarWriter(FlakyRowSink))])`: the real
writer on the virtual clock over an in-memory table keyed like the DEDUP key, with outage windows.
`test_s05b` swaps in the real QuestDB container (`chaos` + `integration`); it stops that container,
so it runs only on GitHub Actions or with `CV_CHAOS_STACK=1` on a stack you own, else it skips.

**Negative controls (DoD).** Every scenario has a test that feeds a naive collaborator or a
naive result to the invariant and expects it to fail.

Legend: ✅ passes today. `xfail` is a strict xfail on an open defect; it goes red the moment the
fix lands, so the fix removes the marker.

## Scenario table

| # | Scenario | C-13.6 | PR | Observed | Negative control |
|---|---|---|---|---|---|
| 1 | Process or WS drop mid-bar: resume from store, or marked gapped | #1, #12 | PR-2 | WS drop mid-bar: backfilled, bars == golden, no bar closed twice, `ingest_ws_up` 1 -> 0 -> 1 ✅; restart mid-bar: golden, same epoch, replayed closes identical ✅; tape lag past the ring: `bars_restore_gap_total`, `bar_restore_gap`, WARN ✅ | no backfill loses prints; restart without the tape loses prints; a tape that reaches the ring raises no alarm |
| 2 | Tape gap (REST backfill ok / down) | #1, #3 | PR-1 | recovered: bars == golden ✅; unrecovered: `GapEvent`, `trade_gaps_total`, health ✅; bar marked (`gap_before`) ✅ (#529 gap-marking fix) | no-backfill run fails the golden |
| 3 | Out-of-order and duplicate prints | #3 | PR-1 | dup suppressed upstream ✅; reorder amends the closed bar ✅; > 60 s dropped, counted, logged ✅ | with `TradeStream`'s ring replaced by a no-op (monkeypatched), a duplicated frame is double counted by the volume, tick, range and renko folds |
| 4 | 5xx and 10018 during kline backfill | #5 | PR-2 | every 3rd page limited: complete, nothing lost; 4 limits in a row: full-jitter delays in `[1, cap]`; `loading_older_bars` while earlier pages stay readable; 5 in a row: partial, resumed without refetching; 5xx retried ✅ | the bounds helper rejects an immediate retry and a delay past 60 s |
| 5 | Store restart / write failure | #10 | PR-2 | short outage (< 7.5 s): store == golden, nothing dropped ✅; nothing reported persisted while the store rejects ✅; long outage: dropped loudly (`bars_write_failed_total{reason="transient_exhausted"}`, `degraded`, ERROR), stored + dropped == submitted ✅; replay of dropped rows: xfail (#531); real QuestDB stop/start: `test_s05b` (nightly) | a sink that acks and discards fails the golden |
| 6 | Host clock jumps +-2 s, +-2 min | #6 | PR-1 | bars == golden, no drops, no amends, alarm ✅ (#529 fix: bars on the exchange-corrected clock) | the raw host clock drops prints (+2 min) and re-emits amended bars (+2 s) |
| 7 | Kill mid renko rebuild | #12 (extension) | PR-2 | skipped placeholder: blocked by #535 (no rebuild exists) | - |
| 8 | Delisted or halted symbol | none (extension of #1) | PR-2 | bars == golden; at most the clock close after the last print, no empty bar; feed `delisted`, demand refused, bars healthy ✅ | filler empty bars fail the helper |

SR-040 (malformed payloads, BQ-14, PR-2): `test_sr040_hostile_print.py`. A hostile REST backfill row
never reaches the bus or a bar (the gap is reported unrecovered); negative control: the helper
fails on a leaked row or a NaN price.

## Harness behaviours the scenarios rely on

| Behaviour | Where it matters |
|---|---|
| No grace period on an `on_clock` tick at a bar's exact close: a tick with `now` equal to a time bar's close closes it, so a print that arrives after that tick is late (amends it), it does not fold in. `BarsRig.run` therefore ticks after the step's frames: a frame published at a bar's close time carries prints stamped 5 ms earlier and still belongs to that bar | scenarios 2, 3 and 6: the amend counts and the golden's last time bar |
| The golden's tail `closed` flag is ignored for time series only; an activity series' tail is forming in both the golden and the rig, so it must match | every golden comparison (`golden.diffs(kind=...)`) |

## Open defects (strict xfails)

| Test | Why it fails today | Owner |
|---|---|---|
| `test_s05_rows_dropped_by_an_exhausted_batch_are_replayed_exactly_once` | `BarWriter` drops rows after its 5 attempts; nothing re-emits them (heal = hydrate or rebuild, not built) | #531 (writer replay) |

## Signals that do not exist (BQ-8)

| Failure | Missing signal | Pinned by |
|---|---|---|
| Unrecovered tape gap | no bars-side health reason: `BarsHealthReason` has no tape-gap member, so the bars report healthy while ingestion reports `trade_gap_unrecovered` | `test_s02_unrecovered_gap_leaves_the_bars_health_unchanged` |

## Mapping to the ticket's observability names

(PR-2 adds: `ingest_ws_up{socket="public"}`, `bars_rows_written_total{kind}`,
`bars_write_failed_total{reason}`, the ERROR `bars_write_exhausted`,
`kline_backfill_rate_limited_total`, `kline_backfill_pages_total{result}`, the progress status
`loading_older_bars`, `bars_restore_gap_total` with the `bar_restore_gap` health reason, and the
feed event `FeedHealthEvent(state="delisted")`.)

The ticket's metric names mostly do not exist. The tests assert the real signal of the owning
module: `trade_gaps_total{recovered}`, health `trade_gap_unrecovered`, `GapEvent.label()` (words,
not a colour), `trade_duplicates_suppressed_total`, `bars_amended_total`,
`bars_late_trade_dropped_total{reason}` (+ the `bars_late_trade_dropped` WARN log),
`exchange_clock_drift_ms`, `clock_resync_triggered_total{reason="host_step"}`,
`ClockGuard.health_severity()`.

## Deviations from the composition root

- Virtual clock, seeded RNG and the stub transport, as in the ingestion suite.
- The set's "now" is composed in `_rig.py` as `corrected_now_us(ClockGuard.offset_us,
  rig.host_now_us)`, the same composition as `app.exchange_corrected_clock`, which
  `tests/unit/test_bars_clock_wiring.py` pins in the app. `clock="raw"` is the pre-#529
  wiring and exists only for the negative controls.
- No WS publisher or indicator engine on the emit path. The store seam is opt-in (scenario 5).
- Scenario 4 drives `KlineBackfillService` with a fake `KlineFetcher` over the recorded kline
  corpus (the stub exchange has no kline route), so `bybit_rate_limited_total` is not exercised;
  that is the ingestion suite's scenario 5. Scenario 1b has no exchange: the recorded trade corpus
  is published on a real bus.
- Scenario 5's series are volume and tick bars: a 5 s time bar has no wire interval code, so it
  can never be persisted (`BarPersistError`).
- Not covered by the PR-2 tests: the `/readyz` bars component while the writer is degraded (the
  writer's `degraded` flag and the ERROR log are asserted), a bars-side stale flag after a delist.
- Not covered here: the UX live-region
  assertions (#419) and the performance targets (needs the load harness).

Note: `_rig.py` composes the corrected clock itself (`corrected_now_us(offset, host_now)`), so this
suite does not exercise `app.exchange_corrected_clock`. The wiring is pinned by
`tests/unit/test_bars_clock_wiring.py` (`create_app` hands the corrected clock to the bars).
