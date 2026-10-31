# E16-Q04 — Recorder chaos catalogue

Suite: `services/api/tests/chaos/recorder/` (marker `chaos`). Fakes and `tmp_path`: no docker, no
mount, no network, no sleeps, so the PR `py` lane's `db-chaos` shards run it, and
`.github/workflows/chaos-recorder-nightly.yml` runs it again every night (signal `chaos-recorder`)
with one more leg: a 64 MiB ext4 loopback image it mounts with sudo and `CV_CHAOS_LOOPBACK=1`
(`test_loopback.py`; skipped without the flag, refused on anything but a loop-device mount).
Run one file at a time locally, for example:
`cd services/api && uv run pytest tests/chaos/recorder/test_disk_pressure.py -m chaos --no-cov`.

**Scale.** Smoke only (BQ-6): a 1 MB volume, a few hundred messages of the E16-Q04 mix
(`bench/recorder/generator.py`, templates the E08 normalisers parsed out of the 2026-10-05
capture), a 2 s outage on a virtual clock. The ticket's full-scale runs (a 2-minute QuestDB outage,
the negative control recorded at scale, the first green nightly) stay open on #481.

## Scenarios

| Test                                                                                    | C-13.6   | Fault                              | Invariants asserted                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------------- | -------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_disk_pressure.py::test_disk_ladder_76_takes_no_action`                            | #13      | volume 76 % used                   | level NORMAL, no ladder event, no drop, no pause, writer open, produced == written                                                                                                                                                                                                           |
| `…_81_warns_with_suggested_actions`                                                     | #13      | 81 %                               | one WARNING `recorder.disk_budget_warning`, actions `reduce_depth,shorten_retention,unpin`, no acceleration (19 % free)                                                                                                                                                                      |
| `…_91_refuses_auto_record_keeps_explicit`                                               | #13      | 91 %                               | level AUTOSTOP; a new chart-open start refused (`disk_pressure`), the explicit list and the position keep recording; the write gate stays open                                                                                                                                               |
| `…_91_accelerates_reaper_below_15_free`                                                 | #13      | 91 % (9 % free)                    | retention halves the hot window; WARNING before the only drop (the unpinned 20 d partition); pins intact                                                                                                                                                                                     |
| `…_96_pauses_unpinned_auto_symbols`                                                     | #13      | 96 % (4 % free)                    | level HALT; CRITICAL before the pause; only the unpinned auto symbol paused; its rows gated into `backpressure_drop` gaps; the open position keeps writing; produced == written + dropped                                                                                                    |
| `…_pinned_bytes_identical_throughout`                                                   | #13      | 76 → 81 → 91 → 96                  | sha256 of every pinned file unchanged after each step; every pinned skip audited                                                                                                                                                                                                             |
| `…test_order_placed_at_96_percent_succeeds_with_native_sl`                              | #13      | 96 %                               | the real submit pipeline answers 202; its write-ahead audit records (intent, stop) precede the send and name the order, its row is stored (C-2.9); its create carries the native stop (C-2.6)                                                                                                |
| `…test_pinned_assertion_fails_when_pin_predicate_removed`                               | #13      | 91 %, pin check removed            | **negative control**: pinned partitions are dropped and the suite's pinned-bytes assertion fails                                                                                                                                                                                             |
| `test_questdb_down.py::test_questdb_down_spills_then_replays_without_duplicates_or_gap` | #10      | sink refuses every write for 2 s   | spilled to the WAL, replayed after `recover()`: every row once, no gap, no critical event, WAL drained                                                                                                                                                                                       |
| `…test_wal_exhausted_writes_backpressure_drop_gap_and_critical_event`                   | #10      | outage past a 16 KiB WAL budget    | `backpressure_drop` gaps, one `recorder_wal_full` critical per episode, produced == written + dropped; every produced-but-unwritten row's `exch_ts` lies inside a gap for its (stream, symbol), nothing written after a gap's first instant, at least one split delta (C-2.14; see Findings) |
| `test_rolloff_interrupted.py::…killed_between_write_and_verify…`                        | #13 ext. | kill after the Parquet checksum    | hot day kept, no manifest, no watermark, no purge audit; the re-run removes the orphan and drops once                                                                                                                                                                                        |
| `…killed_between_verify_and_drop_converges_on_rerun`                                    | #13 ext. | kill inside `drop_day`             | the day in both tiers (watermark advanced, purge audited write-ahead); the re-run drops it once, one manifest entry                                                                                                                                                                          |
| `…torn_file_after_kill_is_refused_alerted_then_rearchived`                              | #13 ext. | kill after the manifest, file torn | the re-run's read-back refuses it (CRITICAL `archive.verification_failed`) before any drop; its retry re-exports, then one drop and one manifest entry                                                                                                                                       |
| `test_harness_guards.py`                                                                | —        | —                                  | the volume refuses a root outside `tmp_path`; fill and meter arithmetic; the WAL is off the volume (SR-096)                                                                                                                                                                                  |
| `test_loopback.py::test_loopback_ladder_on_a_real_filesystem` (nightly)                 | #13      | 76 → 81 → 91 → 96 % of the image   | NORMAL, WARN, AUTOSTOP, HALT from the kernel's free space; pins intact; at 96 % the position writes, the auto symbol is gated, produced == written + dropped                                                                                                                                 |
| `…test_wal_enospc_on_a_full_filesystem_becomes_gaps_then_recovers` (nightly)            | #13      | WAL on a full image, QuestDB down  | a real `ENOSPC` on the WAL write becomes `backpressure_drop` gaps, produced == written + dropped; after space returns the writer recovers and writes again                                                                                                                                   |
| `test_loopback.py` guards                                                               | —        | —                                  | skipped unless `CV_CHAOS_LOOPBACK=1`; a non-loop-device or oversized mount is refused (a failure); the nightly mounts, runs the leg with the flag and unmounts on every exit path                                                                                                            |

## Thresholds (BQ-3 ruling)

The code wins: `BudgetConfig` warn 80 %, autostop 90 % or free < 15 %, halt 95 % or free < 5 %
(`recorder/budget.py`), and the E07 reaper's 15 % / 5 % free lines. The ticket's 76/81/91/96 are
the fill points, one either side of each line. ADR-0015 decision 6 (80/90/95) agrees; its
Validation section's 85/91/96 does not and is left for an ADR follow-up.

## Deviations

- **Loopback mount in the nightly only** (BQ-5 as re-ruled on #5259). The PR lane runs the ladder
  over `VirtualVolume`, a directory under `tmp_path` with a faked size (the mount layer faked in
  unit tests), so it needs no root and can never fill a real disk. The nightly mounts a 64 MiB
  ext4 loopback image with sudo, as `_job-integration.yml`'s storage chaos stack does
  (`tests/chaos/storage/_stack.py` `CV_CHAOS_LOOPBACK_DIR`), and runs `test_loopback.py` on it:
  the ladder against the kernel's free space, and the WAL's real `ENOSPC` path
  (`writer._drain_spill_buf`'s `OSError` branch). `_loopback.py` refuses any directory that is not
  a loop-device mount point of at most 64 MiB, and skips the leg without `CV_CHAOS_LOOPBACK=1`.
- **The order venue and its stores are in-memory** (BQ-4). The 96 % order test drives the real
  submit pipeline through `tests/unit/oms/submit_rig.rigged()`: its venue is the OMS's in-memory
  `FakeTradingPort` (no `packages/fixtures` capture) and its order, stop and audit stores are
  in-memory, not on the near-full recording volume. What it shows is that the recorder's disk
  ladder never reaches the order path: the order is accepted, audited write-ahead (C-2.9) and
  carries its native stop (C-2.6) while the recording volume is at 96 %.
- **No QuestDB container.** The outage is at the ILP seam (a refusing sink), as the E08 suite's
  `FlakyWriter` does; the 2-minute outage against the compose stack is a nightly-at-scale item.
- **Roll-off quarantine.** A file torn before its manifest is an orphan the re-export removes
  (not quarantined); a file torn after it fails the manifest SHA-256, is refused with a
  CRITICAL and re-exported by the retry. The checksum-mismatch quarantine itself is unit-tested in
  `tests/unit/storage/cold/test_rolloff_ops.py`.
- **Retention is not scheduled by the nightly.** It runs the reaper inside these tests only, so
  the RetentionStale `> 0` guard (#5219) stays; see the PR body.

## Findings

- **A gap can share its first `exch_ts` with written rows** (`test_wal_exhausted_*`, seed 29: a
  BTCUSDT `orderbook_delta` gap starting at the `exch_ts` of written rows). A delta message is one
  WAL record per level, all at one `exch_ts`; when the WAL budget refuses part of a batch
  (`writer._drain_spill_buf`, `records[:written]`), a message can be split, its first levels
  written and the rest dropped into a gap that starts at the same instant. Rows still balance
  exactly (produced == written + dropped). Whether C-2.14 ("a gap never contains written data")
  should hold at message granularity was escalated and **ruled** (coordinator, 2026-10-31, PR
  #5259): C-2.14 is about never fabricating missing history, not per-message atomicity. A split
  is accepted because (a) the `backpressure_drop` gap covers the remainder at the same `exch_ts`,
  pinned by the chaos test: every produced row that was not written has its `exch_ts` inside a gap
  for its (stream, symbol), and at least one delta is split at seed 29; (b) the replayer treats a
  gap as a resync point (C-2.5), pinned by
  `tests/unit/replay/test_replay_books.py::test_a_gap_at_a_split_delta_resyncs_and_never_presents_the_partial_book`
  (at the unit level it calls `injector.reset_book` directly, the call `replay/runner.py` makes at a recorded gap,
  rather than feeding one); and (c) nothing is written strictly inside a gap. No production
  change.
