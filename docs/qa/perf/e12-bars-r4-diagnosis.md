# E12 bars soak memory: what moves R4's slope (E12-T06 D2-G4, #399)

Status: **harness and reading rule committed before any dispatch; no leg has run, results pending.**

The 24 h `soak_bars` reading in [`e12-bars-store-memory.md`](e12-bars-store-memory.md) fails R4 only: the
RSS the lanes add climbs +0.2475 MB/h a symbol (MB a MiB) over hours 12-24, in steps with long flat runs.
A leak, in `bars/` or elsewhere, or the allocator? Ruled on #399: tracemalloc snapshots by the hour and the
allocator as a controlled variable; the fix follows the diagnosis. No budget, limit, band or baseline moves.

## The legs

`services/api/bench/ingestion/memdiag.py leg` runs one leg in its own process: the unchanged
`runner.run_soak` on the full `soak_bars` profile. Its sampler hands the soak its own RSS reading at every
sample and, once an hour of scenario time, writes a line of probes: pymalloc blocks, glibc `mallinfo2()`,
`smaps_rollup` and the thread count. The report records the head, the scenario file's sha256, the machine
profile, glibc, Python and the THP mode. The dispatch sets the allocator variables; the leg records those it
saw and checks pymalloc against them. A leg whose environment is not its label's does not start (exit 2):
another allocator variable, `LD_PRELOAD` or `-X dev`, pymalloc against its variable, or tracemalloc on any
leg but the tracemalloc leg, or off on that one. One leg a dispatch on cv-bench-01, never two at once:

| Order | Leg           | Length                              | Allocator environment           | Read for                                    |
| ----- | ------------- | ----------------------------------- | ------------------------------- | ------------------------------------------- |
| 1     | `default`     | 24 h: the profile, unchanged        | none                            | the reading: R1-R4 and the W24 slope        |
| 2     | `tracemalloc` | 12 h (`--hours 12 --tracemalloc 6`) | none                            | attribution only; its RSS is never sloped   |
| 3     | `malloc`      | 24 h                                | `PYTHONMALLOC=malloc`           | the W24 slope without pymalloc              |
| 4     | `mmap128k`    | 24 h                                | `MALLOC_MMAP_THRESHOLD_=131072` | the W24 slope with the mmap threshold fixed |

A report says `"reading": true` only for a leg with no override, no tracemalloc and no allocator variable.
Its R1-R4 verdict is the runner's verdict on a process that also probed hourly, after the soak's own RSS
reading (a probe allocates and frees 10-20 KiB; `sampling_cost_ms` includes it). Probe lines, hourly
snapshots and a progress line a probe are flushed as they are taken, so a stopped, killed or crashed leg
leaves them; a stopped or crashed leg's report records why (`stopped`), and a crash is raised after it.

## The reading rule

The orchestrator's ruling for #399 (2026-10-22, 03:23Z): "top-N by file:line grows monotonically across ≥ 6
post-warm-up hourly snapshots ⇒ leak; plateau moves with the allocator setting while top-N is flat ⇒
fragmentation". Made precise here and committed before any dispatch; the thresholds are this harness's:

> - NO VERDICT: the default leg is missing or invalid (it did not reach 24 h, or R3 failed, or the allocator self-check is inconsistent).
> - NOT REPRODUCED: the default leg's W24 slope (h12–24, Theil-Sen, MiB/h per symbol) is ≤ 0.18.
> - LEAK: some file:line in the tracemalloc top-N grows monotonically, strictly increasing, across ≥ 6 consecutive post-warm-up hourly snapshots (warm-up = the first 2 h), with total growth over that run ≥ `LEAK_MIN_GROWTH_MIB = 1.0`. The subtype is IN BARS if ≥ 50 % of that growth is under `candleviewer/bars/`, else ELSEWHERE.
> - FRAGMENTATION: top-N is flat (no LEAK line), and the W24 slope of `malloc` or `mmap128k` differs from the default's by ≥ `MOVE_MIN = 0.09` MiB/h per symbol. The kind is which allocator moved it, plus the hourly step attribution.
> - MIXED: both a LEAK line and an allocator move. The orchestrator rules on it.
> - INCONCLUSIVE: top-N is flat and no allocator leg moves the slope, or legs are still missing. Name the missing legs. Add a `uordblks` growth ratio as an annotation, not as an outcome.

Refinements made with this PR from the methodology review. They narrow ruling (b)'s call, and the
orchestrator accepted them (2026-10-22, 06:46Z):

- **B1**, to "grows monotonically ⇒ leak": a LEAK run counts only if the snapshots' filtered traced total
  also grew by `LEAK_MIN_GROWTH_MIB` or more over the same hours. The bars store's turnover is no leak.
- **M1**, to "plateau moves with the allocator setting": a move is one-sided, the allocator leg's W24 slope
  below the default's by `MOVE_MIN` or more; a rise is an annotation. The mover must fit the default's W24
  steps, mmap128k for glibc steps and malloc for "other" steps; a mover that does not is INCONCLUSIVE.
- **M2**, to the same: a move also needs the W24 net rise to drop by 12 × `MOVE_MIN` (1.08 MiB a symbol)
  or more. `judge` lists each leg's rise times, from its 60 s curve.
- **M3**: a leg whose head, scenario sha256, machine profile, glibc, Python or THP mode differs from the
  default's is not comparable with the default, so invalid.
- **M4**, to "while top-N is flat": when no line qualifies but the filtered total rose by `MOVE_MIN` × 3 ×
  10 h (2.7 MiB) or more over hours 2-12, the outcome is INCONCLUSIVE ("Python heap grows, not attributed
  to a line"), never FRAGMENTATION. The top-N is 100 lines (`--top`), not 25, the leaner of the two fixes
  (the other keeps every line's hourly size), so the turnover's lines (8 of 25 at hour 3) crowd out none.

How `judge` applies it (the constants and `rule` in `memdiag.py`):

- **Windows.** The W24 slope is the Theil-Sen slope, a symbol, of the soak's own RSS curve (every sample,
  h12-24): R4's figure, and `judge` checks that the default's is R4's. Attribution comes from hours 2-12
  of the tracemalloc leg, and carries over because the same growth runs in both windows: on the laptop,
  +4.66 MiB a symbol over h2-12 and +3.28 over h12-24, with rises on the DedupeRing's grid in both.
- **Units.** `LEAK_MIN_GROWTH_MIB` (1.0) is MiB of the whole process, three symbols; `MOVE_MIN` (0.09
  MiB/h) and R4's limit (0.18) are a symbol's.
- **LEAK lines.** A run is a line's consecutive hourly snapshots from hour 2 on, in each one's top-100 since
  hour 2, each larger than the one before: strictly increasing is this harness's "monotonically". A line
  that grows in bursts with flat hours between is no LEAK line; its growth shows in the total (M4). A
  library line's growth goes where the newest repo frame of its biggest traceback is. Tracebacks are kept
  for the 5 lines that grew most each hour; a library LEAK line with none kept counts as elsewhere.
- **The store's turnover (B1).** The store is at its cap from setup, 1 000 stored bars a series, and each
  series that closes replaces stored bars with live ones at its rate (closes an hour a lane: tick 3 930,
  volume 334.8, time 99.9, range about 12.9). Live bars held a symbol, of 27 000 in series that close:
  5 155 at h2, 10 131 at h12, 11 822 at h24. A stored bar holds 1 312 B at `bars/reader.py`'s and
  `domain/sql_names.py`'s lines; a live one 832 B at `bars/time_builder.py`'s and 272-480 B at
  `exchange/bybit/trades.py`'s: -208 B a bar replaced. Over h2-7 the three symbols replace 10 044 bars:
  `time_builder.py:159` grows +1.99 MiB and `trades.py:64` +2.0-4.0 MiB, every hour, while the filtered
  total falls (2.96 MiB by h12, 14 928 replaced). The total test keeps such lines out; it masks a Python
  leak slower than that fall, about 0.1 MiB/h a symbol (a run over hours 2-12 needs about 0.13), under
  R4's 0.18. Each snapshot records its filtered total and the lines that shrank most since hour 2.
- **Validity.** A leg counts only if: its length reached; R3 passed; its own allocator setting seen and
  consistent with pymalloc; tracemalloc on for its leg only, and there with 6 frames or more, a top-N of
  100 or more and snapshots diffed against hour 2 at hours 3-12; its probe lines the soak's own samples,
  after its setup calls and a call a sample; for the default, a reading whose W24 slope is R4's; for another
  leg, comparable with the default (M3). Per leg, a valid report wins over an invalid one, then the latest.
  LEAK also needs both allocator legs (a move would make it MIXED); until then it is INCONCLUSIVE, naming
  them. `judge` skips and names a file it cannot read; reports and verdicts are written whole, then renamed.
- **Steps.** A step is an RSS rise of 1 MiB or more between two samples of the soak's 60 s curve, put down
  by the hourly probes either side to glibc (arena + hblkhd), THP (AnonHugePages) or other, by which rose
  by half of it, with uordblks' and fordblks' changes beside it. Two steps in one hour share their probes.
  On cv-bench-01 THP explains no step: it is `madvise`, and glibc does not advise its heap.
- **The repeat assumption (M2).** One default leg, no replicate: `MOVE_MIN` assumes the step pattern
  repeats from run to run. The rises at h2.12, h2.93, h7.00, h16.80 and h17.57 sit within 1.4 min of the
  DedupeRing's same-size set rebuilds, a schedule the hash seed does not move; those at h12.20 and h22.92
  are off that grid, and nothing yet shows that they repeat. The one-sided move and the net-rise drop bound
  false moves, and the rise times show whether the default's pattern repeated in the allocator legs.

## Re-running `judge`

From the repo root, download each leg's artifact into a folder of its own under one directory:
`gh run download <run-id> --dir memdiag/<label>`. Then from `services/api`,
`uv run python -m bench.ingestion.memdiag judge ../../memdiag`. It reads every leg report (`<label>.json`)
under the directory, skips and names any it cannot read, and writes `memdiag-verdict.json` and `.md` there.
