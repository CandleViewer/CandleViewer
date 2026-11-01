# Bars chaos report - template (E12-Q06, #529)

Copy this file to the run's evidence (PR description or release record) and fill it in. One report
per full nightly run (`chaos-bars-nightly`) or release candidate. The catalogue of what each row
asserts is `SCENARIOS.md`; this file records what a run *observed*.

## Run

| Field | Value |
|---|---|
| Date (UTC) | |
| Commit | |
| Workflow run or local command | `uv run pytest tests/chaos/bars -m "chaos and not flaky" --no-cov` |
| Seed | `tests/chaos/bars/conftest.py` `SEED` (fixed) |
| Integration leg (`test_s05b`) | ran / skipped (no stack) |
| Result | passed / failed / xfailed / skipped counts |

## Scenarios

Result is `pass`, `fail`, `xfail #NNN` (a strict xfail on an open defect) or `skip #NNN`
(blocked). A scenario is only `pass` when its negative control also passed.

| # | Scenario | Result | Signals observed (metric / log / health) | Negative control | Notes |
|---|---|---|---|---|---|
| 1 | WS drop mid-bar; restart mid-bar | | `ingest_ws_up`, `trade_gaps_total{recovered}`, `bars_restore_gap_total` | | |
| 2 | Tape gap, backfill ok / down | | `trade_gaps_total`, `trade_gap_unrecovered` | | |
| 3 | Out-of-order and duplicate prints | | `trade_duplicates_suppressed_total`, `bars_amended_total`, `bars_late_trade_dropped_total` | | |
| 4 | 5xx and 10018 during backfill | | `kline_backfill_rate_limited_total`, `loading_older_bars` | | |
| 5 | Store outage (fake store; container) | | `bars_rows_written_total`, `bars_write_failed_total`, `bars_write_exhausted` | | |
| 6 | Host clock jumps | | `exchange_clock_drift_ms`, `clock_resync_triggered_total` | | |
| 7 | Kill mid renko rebuild | skip #535 | - | - | not runnable until the rebuild exists |
| 8 | Delisted or halted symbol | | `FeedHealthEvent` `delisted` | | |

## Open defects (strict xfails)

| Test | Issue | Opened | Still failing? |
|---|---|---|---|
| `test_s02_first_bar_after_an_unrecovered_hole_is_flagged` | | | |
| `test_s05_rows_dropped_by_an_exhausted_batch_are_replayed_exactly_once` | #531 | | |

## Findings

One line each: an unobservable failure mode is itself a defect, so list any failure that raised
no signal, with the issue filed against the owning ticket.

-

## Not covered by this suite

UX live-region and banner assertions (#419), catch-up CPU and 30 fps targets (load harness),
the `/readyz` bars component under a degraded writer.

## Sign-off

QA: ______  Date: ______
