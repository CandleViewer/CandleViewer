# E26-K01 — replay seek cost and hot/cold source throughput (200-depth)

Status: **measured locally on a SYNTHETIC day; hot-tier leg in CI; live re-measure pending** (owner
exception #1778 group A pattern; owner-adopted defaults 2026-10-09). Ticket #622. Decision draft:
[ADR-0035](../27-adrs/ADR-0035-replay-source-and-seek.md).
Reproduce: `cd services/api && PYTHONPATH=. python -m bench.replay_seek.run --rows 2000000 --profile dense --out <f>.json`
(`bench/replay_seek/`; unit test `tests/unit/journal_bench/test_replay_seek_bench.py`; real-QuestDB leg
`tests/integration/bench/test_e26_replay_seek_questdb.py`, `integration` marker). Raw output:
[`e26-replay-seek-raw/`](e26-replay-seek-raw/dense-200.md).

> **Every number below is from a SYNTHETIC 200-depth book**, not an E16-recorded day: the recorder is not
> wired yet (#2210, #2188). It ran on a **dev laptop** (i7-8550U, 4C/8T, 16 GB, Windows 11, Python
> 3.12) — not the WSL docker-compose target named in the ticket. Each cell is p50/p95/max over **5 runs**.
> Run-to-run noise on this laptop is large: two full runs differed by up to ~1.5× on the slowest cells.
> Read the numbers as orders of magnitude and ratios between options. They are not budgets.

## 1. Input and what was measured

| Item                          | Dense (BTCUSDT-class)                                                                          | Thin (contrast)                                     |
| ----------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Source                        | seeded synthetic (`synth.py`, seed 26001)                                                      | same, thin profile                                  |
| Changed levels / 100 ms frame | 266 measured (target 220 = §11.1's 190 M rows ÷ 864 k frames; burst and mid-walk add the rest) | 5.4 (corpus `orderbook_BTCUSDT.jsonl` mean is 4.95) |
| Busiest minute                | 3× rate at [600 s, 660 s): 242 k delta rows + 1.2 k trades                                     | 9.2 k rows + 356 trades                             |
| Span measured                 | 910 s (2.42 M delta rows) — **×94.9 to a 24 h day**                                            | 4 000 s (216 k rows) — ×21.6                        |
| Trades                        | E12-T04 generator (`vol_ticks`, rate ×3 in busiest minute)                                     | same                                                |

Seek is measured at the **worst case**: the target is 1 µs before the next snapshot, in the window that
contains the busiest minute (`busy`). A calm window (`calm`) is measured as a second case. A seek only
passes if the rebuilt book **equals the next recorded snapshot exactly**. Every cell passed
(`book ok = True`).

The four stages use the real engines. These names are proposed as the `stage` label values for
`replay_seek_duration_ms` from T04 on:

| `stage`           | What runs                                                                                                       |
| ----------------- | --------------------------------------------------------------------------------------------------------------- |
| `anchor_load`     | read the nearest snapshot ≤ target + `BookState.from_levels`                                                    |
| `delta_apply`     | read deltas [anchor, target] + `BookState.apply` per 100 ms frame (invariants checked each frame)               |
| `builder_restore` | `StateStore` load of the 60 s `BuilderState` + `TimeBarBuilder.restore` + replay of trades since the checkpoint |
| `warmup`          | rebuild 20 × 1 m bars before the checkpoint + an EMA over them                                                  |

Seek is a single-stream re-apply, so it does not depend on the scale factor. Its cost depends on the rows
per window, and the busiest minute is inside the measured window. Seek numbers therefore need **no
extrapolation**. Only the per-day disk and RSS rows are scaled.

## 2. Seek — dense 200-depth (ms, cold tier = real Parquet from the E16-T05 exporter)

|                    Interval | Window | Frames | Total p50 |     p95 |     max | anchor | delta | builder | warmup | Meets 1 s p95?      |
| --------------------------: | ------ | -----: | --------: | ------: | ------: | -----: | ----: | ------: | -----: | ------------------- |
|                       300 s | busy   |  3 000 |     6 000 |   8 582 |   8 582 |      5 | 5 655 |      35 |    307 | **no** (8.6×)       |
|                        60 s | busy   |    600 |     1 859 |   3 731 |   3 731 |      5 | 1 612 |      56 |    176 | **no**              |
|                        30 s | busy   |    300 |     1 000 |   1 027 |   1 027 |      4 |   793 |      23 |    174 | **no (borderline)** |
|    300 s + collapsed deltas | busy   |      — |       928 |   1 328 |   1 328 |      6 |   465 |      22 |    456 | no                  |
| **60 s + collapsed deltas** | busy   |      — |   **384** | **410** | **410** |      5 |   145 |      48 |    177 | **yes**             |
| **30 s + collapsed deltas** | busy   |      — |   **273** | **282** | **282** |      4 |    70 |      26 |    169 | **yes**             |

"Collapsed deltas" is a seek-only change in `seek.apply_collapsed`. It reads the same rows, keeps the
last write per `(side, price)` and builds the book once, instead of applying every intermediate frame.
No intermediate frame is ever observed during a seek, so this is safe, and the result equals the next
snapshot in every run. The hot stand-in (in-memory, rows materialised as dicts like PGWire) was slower
than cold for the same intervals: 300 s busy p50 9 790 ms, 60 s 2 858 ms, 30 s 1 387 ms (see raw). That
is dict materialisation; it is **not** a QuestDB number.

**Thin book**: every interval is ≤ 0.64 s p95 without mitigation (300 s busy p95 638 ms cold). With
collapsed deltas, every interval is ≤ 0.13 s.

### 2.1 Recorder disk cost per snapshot interval (per symbol-day, 200 depth)

| Interval | Snapshots/day | Hot (QuestDB, modelled, UTF-16 STRING) | Cold (ZSTD-6 Parquet, measured bytes/row) |
| -------: | ------------: | -------------------------------------: | ----------------------------------------: |
|    300 s |           288 |                                 4.4 MB |                                    0.6 MB |
|     60 s |         1 440 |                                22.1 MB |                                    2.8 MB |
|     30 s |         2 880 |                                44.2 MB |                                    5.7 MB |

Against the §11.1 delta stream (10.6 GB hot / ~620 MB Parquet per day), even 30 s snapshots add **< 0.5 %
hot / < 1 % cold**. §11.1's "60 s forced" snapshot row (18 MB/day) is the same order as the 60 s line
here (22 MB); the gap is the JSON encoding of 400 levels.

## 3. Source throughput and merge (events/s, p50 of 5)

| Read                                                              |      Dense |    Thin | Note                                      |
| ----------------------------------------------------------------- | ---------: | ------: | ----------------------------------------- |
| Cold, pyarrow dataset scan (Arrow, filter push-down)              |      9.4 M |   8.2 M | real Parquet, E16-T05 layout              |
| Cold, DuckDB `read_parquet` ORDER BY ts → Arrow batches           |      7.3 M |   3.1 M | no `postgres` attach (#2194)              |
| Hot **STAND-IN**, rows → dicts (busiest minute)                   |     0.28 M |  0.27 M | not QuestDB; dict materialisation only    |
| Hot, real QuestDB 8.1.1 via `QuestDbReader`                       |         CI |       — | `E26K01_HOT=` line of the integration job |
| `(ts_event, seq)` merge, deltas + trades, `heapq.merge` of tuples |      2.6 M |   2.6 M | per-event Python; the binding constraint  |
| **Required at 100× through the busiest minute**                   | **0.41 M** | 0.016 M | 243 678 events × 100 / 60 s               |

### 3.1 Read-ahead buffer (peak RSS growth, busiest region, fresh subprocess)

| Window at 1× | Dense rows | Arrow only | Arrow + decoded tuples | Thin (Arrow + tuples) |
| -----------: | ---------: | ---------: | ---------------------: | --------------------: |
|          5 s |       20 k |      66 MB |                  70 MB |                 58 MB |
|         30 s |      121 k |      77 MB |                  94 MB |                 57 MB |
|        120 s |      398 k |     156 MB |                 213 MB |                 62 MB |

About 55 MB of each row is the fixed pyarrow/dataset baseline, so the marginal cost is ~0.4 KB/event
(Arrow + tuple). **Buffer needed to sustain 100× through the busiest minute:** **0** for the cold tier,
because the read (9.4 M/s) and the merge (2.6 M/s) both exceed the 0.41 M/s needed. A reader at the hot
stand-in's 0.28 M/s would fall short by **75 k events = 18.5 s of replay time ≈ 7 MB of Arrow**. A 30 s
prefetched window covers that with margin. The real-QuestDB leg in CI decides which of these two cases the
hot tier is in.

## 4. Recommendations (drafted into ADR-0035)

1. **Snapshot interval: 60 s**, plus the **collapsed-delta seek path**. The 60 s option measured 410 ms
   p95 (dense, busy) against the 1 s target. 300 s fails by 8.6× without collapsing, and still fails
   (1.3 s) with it. 30 s is ~1.5× faster than 60 s, but doubles snapshot disk for a gain the 1 s
   budget does not need. 60 s is also the existing cadence for both `BuilderState` (§3.2) and the
   §11.1 "60 s forced" snapshot. **This is a recorder change requested of E16:** the default
   `snapshot_interval_s` (300 in §13.7) becomes 60. Cost: +18 MB hot / +2.2 MB cold per symbol-day.
2. **Read-ahead: a streamed cursor with a bounded prefetched window of 30 s of replay time** (Arrow
   batches; ~95 MB at dense 1×). This applies to both tiers. For cold the window is never drained at
   100×. For hot it covers the stand-in-sized deficit. 120 s buys nothing extra and costs ~2.3× the RSS.
3. **`source_tier='auto'`: prefer cold when the whole requested range is in manifested Parquet
   partitions, otherwise hot.** Cold read is the fastest path measured, and it keeps replay load off the
   ingest database. Do not split one session across tiers until T04 proves seam-free `(ts_event, seq)`
   ordering at the roll-off boundary. **Provisional** until the CI QuestDB numbers land.
4. **Replay-side checkpoint cache: not required** if (1) ships. Both the 60 s and 30 s intervals meet
   the target with collapsed deltas. If E16 declines the interval change, the fallback is a replay-side
   book checkpoint every 60 s, built lazily on the first pass over a session (Mitigation B in the ADR).
5. **Warm-up becomes the largest stage once deltas are collapsed** (~170 ms dense). It scales with
   `max(warmup_bars)`, so T04 should persist an indicator checkpoint beside the `BuilderState` rather
   than rebuild 20 bars on every seek.

## 5. What this does not establish (deviations)

- **Synthetic, not recorded.** The ticket asks for a real E16 day because real delta-size distributions
  drive re-apply cost. The synthetic dense profile is calibrated to §11.1's mean rows/frame and adds a 3×
  busiest minute, but its size and price distribution is invented. **Follow-up: re-measure on the first
  recorded day** (see §6).
- **No local QuestDB.** The hot column here is an in-memory stand-in. Real hot numbers come from CI's
  `integration` job: 120 s dense span, `IlpWriter` ingest, `build_read_book_snapshot_at` /
  `build_read_book_deltas`, full delta scan.
- **Laptop, not the WSL docker target**, and with high run-to-run variance (§ header).
- **Scaling:** seek needs none (see §1). Disk-per-day is linear in snapshots/day, so it is exact. RSS is
  reported for the windows themselves, so nothing is extrapolated. Not measured: multi-symbol sessions,
  and footprint/heatmap engines (out of scope).

## 6. Follow-up tickets

- #2223 — recorder: default `snapshot_interval_s` 300 → 60 for 200-depth symbols (E16).
- #2224 — replay: collapsed-delta seek path + `replay_seek_duration_ms{stage}` + indicator checkpoint (E26).
- #2225 — re-run this harness on the first E16-recorded 200-depth day on the WSL target, and
  record the CI QuestDB numbers (E26-Q03 input).

A replay checkpoint-cache ticket is **not** filed: per §4.4 it is not required on the chosen path.
