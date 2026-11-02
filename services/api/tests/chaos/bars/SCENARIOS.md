# E12-Q06 - Bars chaos catalogue

Suite: `services/api/tests/chaos/bars/` (marker `chaos`; dense variants also `harness`).
Run, one file at a time: `cd services/api && uv run pytest tests/chaos/bars/<file> -m chaos --no-cov`.
Ticket #529. Delivered in parts: **PR-1** (this one) covers the harness and scenarios 2, 3 and 6;
the rest follow in PR-2.

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

**Negative controls (DoD).** Every scenario has a test that feeds a naive collaborator or a
naive result to the invariant and expects it to fail.

Legend: ✅ passes today. `xfail` is a strict xfail on an open defect; it goes red the moment the
fix lands, so the fix removes the marker.

## Scenario table

| # | Scenario | C-13.6 | PR | Observed | Negative control |
|---|---|---|---|---|---|
| 1 | Process or WS drop mid-bar: resume from store, or marked gapped | #1, #12 | PR-2 | - | - |
| 2 | Tape gap (REST backfill ok / down) | #1, #3 | PR-1 | recovered: bars == golden ✅; unrecovered: `GapEvent`, `trade_gaps_total`, health ✅; bar marked (`gap_before`) ✅ (#529 gap-marking fix) | no-backfill run fails the golden |
| 3 | Out-of-order and duplicate prints | #3 | PR-1 | dup suppressed upstream ✅; reorder amends the closed bar ✅; > 60 s dropped, counted, logged ✅ | a duplicate leaking into a builder breaks conservation |
| 4 | 5xx and 10018 during kline backfill | #5 | PR-2 | - | - |
| 5 | Store restart / write failure | #10 | PR-2 | - | - |
| 6 | Host clock jumps +-2 s, +-2 min | #6 | PR-1 | bars == golden, no drops, no amends, alarm ✅ (#529 fix: bars on the exchange-corrected clock) | the raw host clock drops prints (+2 min) and re-emits amended bars (+2 s) |
| 7 | Kill mid renko rebuild | #12 (extension) | PR-2 | blocked by #535 (no rebuild exists) | - |
| 8 | Delisted or halted symbol | none (extension of #1) | PR-2 | - | - |

## Open defects (strict xfails)

| Test | Why it fails today | Owner |
|---|---|---|
| Replay after writer exhaustion (scenario 5, PR-2) | `BarWriter` drops rows after its 5 attempts; nothing re-emits them | #531 (writer replay) |

## Signals that do not exist (BQ-8)

| Failure | Missing signal | Pinned by |
|---|---|---|
| Unrecovered tape gap | no bars-side health reason: `BarsHealthReason` has no tape-gap member, so the bars report healthy while ingestion reports `trade_gap_unrecovered` | `test_s02_unrecovered_gap_leaves_the_bars_health_unchanged` |

## Mapping to the ticket's observability names

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
- No QuestDB writer, WS publisher or indicator engine on the emit path (PR-2 adds the store seam).
- Not covered here: SR-040 malformed payloads (ingestion `test_s06`; the thin bars-rig test is PR-2), the UX live-region
  assertions (#419) and the performance targets (needs the load harness).

Note: `_rig.py` composes the corrected clock itself (`corrected_now_us(offset, host_now)`), so this
suite does not exercise `app.exchange_corrected_clock`. The wiring is pinned by
`tests/unit/test_bars_clock_wiring.py` (`create_app` hands the corrected clock to the bars).
