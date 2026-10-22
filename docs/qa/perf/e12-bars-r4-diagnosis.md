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
another allocator variable, `LD_PRELOAD`, `LD_AUDIT` or `-X dev`, pymalloc against its variable, tracemalloc
on any leg but the tracemalloc leg or off on that one, or tracemalloc already on before the leg, on any leg
(`-X tracemalloc`, `PYTHONTRACEMALLOC`). One leg a dispatch on cv-bench-01, never two at once:

| Order | Leg           | Length                              | Allocator environment           | Read for                                    |
| ----- | ------------- | ----------------------------------- | ------------------------------- | ------------------------------------------- |
| 1     | `default`     | 24 h: the profile, unchanged        | none                            | the reading: R1-R4 and the W24 slope        |
| 2     | `tracemalloc` | 12 h (`--hours 12 --tracemalloc 6`) | none                            | attribution only; its RSS is never sloped   |
| 3     | `malloc`      | 24 h                                | `PYTHONMALLOC=malloc`           | the W24 slope without pymalloc              |
| 4     | `mmap128k`    | 24 h                                | `MALLOC_MMAP_THRESHOLD_=131072` | the W24 slope with the mmap threshold fixed |

All four legs, and any re-run (a replicate default included), run at one commit. Once the workflow is on
`main`, tag one `main` commit `bench/r4-legs-1` (the workflow refuses any ref but a `bench/` tag), leave the
tag in place, and dispatch every leg with
`gh workflow run perf-bars-memdiag.yml --ref bench/r4-legs-1 -f leg=<leg>`; leave the runner's Python, glibc
and THP alone until the last leg. A leg measured at another head or on another host setup is not comparable
with the default (M3), so `judge` leaves it out. LEAK waits for both allocator legs; MIXED and FRAGMENTATION
are called from the legs in hand (the tracemalloc leg and at least one mover): the other allocator leg can
only add a mover to their list, while a valid re-run of a leg replaces it and can change any outcome.

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

Refinements made with this PR from the methodology review. They narrow ruling (b)'s call; the
orchestrator accepted B1-M4 (2026-10-22, 06:46Z) and N5 (12:26Z), and the store's netting, M-1 (delta 5's
Major 1, not M1), is its ruling of 13:59Z:

- **B1**, to "grows monotonically ⇒ leak": a LEAK run counts only if the snapshots' filtered traced total
  also grew by `LEAK_MIN_GROWTH_MIB` or more over the same hours. The bars store's turnover is no leak.
- **M1**, to "plateau moves with the allocator setting": a move is one-sided, the allocator leg's W24 slope
  below the default's by `MOVE_MIN` or more; a rise is an annotation. The mover must fit the default's W24
  steps, mmap128k for glibc steps and malloc for "other" steps; a mover that does not is INCONCLUSIVE. So
  is a THP or a no-step attribution: `FITS` has no entry for either.
- **M2**, to the same: a move also needs the W24 net rise to drop by 12 × `MOVE_MIN` (1.08 MiB a symbol)
  or more. `judge` lists each leg's rise times, from its 60 s curve.
- **M3**: a leg whose head, scenario sha256, machine profile, glibc, Python or THP mode differs from the
  default's is not comparable with the default, so invalid.
- **M4**, to "while top-N is flat": when no line qualifies but the filtered total rose by `MOVE_MIN` × 3 ×
  10 h (2.7 MiB) or more over hours 2-12, the outcome is INCONCLUSIVE ("Python heap grows, not attributed
  to a line"), never FRAGMENTATION. The top-N is 100 lines (`--top`), not 25, the leaner of the two fixes
  (the other keeps every line's hourly size), so the turnover's lines (8 of 25 at hour 3) crowd out none.
- **M-1**, to B1 and M4: B1's total keeps the store's turnover out only while nothing else grows it, so
  the store's lines are netted first. The lines of the files a live bar is built at
  (`bars/time_builder.py`, `exchange/*/trades.py`) and a stored bar is held at (`bars/reader.py`,
  `domain/sql_names.py`) are one line under `candleviewer/bars/`, `STORE_LINE`, which takes B1 and the
  LEAK test like any line; those lines are not tested alone. A replaced bar moves it by -208 to 0 B, so a
  total rising for any other reason no longer makes the builder's and the parser's lines LEAK lines: M4
  can fire, and a leak elsewhere reads ELSEWHERE. Bars the store keeps past its cap grow it: LEAK IN
  BARS. So does a leak of anything the parser allocates, wherever it is held (trade prints, their stamps,
  prices and sizes): the netting cannot tell it from live bars. In raw snapshots, a live bar adds 832 B
  over the builder's lines for 272-480 B over the parser's, so the parser's lines, summed per file,
  growing faster than about 0.58 of the builder's summed lines point to trade prints, not bars. Compare
  the files, never single lines: one builder line holds a fraction of a bar's 832 B.
  Reading raw snapshots by hand, a LEAK whose LEAK lines are only the turnover's (`bars/time_builder.py`,
  `exchange/*/trades.py`, with `bars/reader.py` among `shrank_h2`) reads as "Python heap grows, not
  attributed to a line" once the total clears M4's 2.7 MiB, as `judge` reads it with those lines netted.
- **N5**, to "grows monotonically": strictly increasing, each hourly snapshot larger than the one before.
  Monotone growth is the leak signature: a leaked object is never freed, so its line only grows, hour
  after hour. A cache or table that reaches its working size plateaus. A line that grows in bursts with
  flat hours between looks like a table resizing, and a leaking table grows that way too, in bursts at
  its table line. Neither is a LEAK line. Their growth reaches the verdict only through the filtered
  total, which M4 reads once no line qualifies, the store's lines netted (M-1). M4 flags it from 2.7 MiB
  over hours 2-12, net of the turnover's fall: from about 0.19 MiB/h a symbol at the -208 B end (below).

How `judge` applies it (the constants and `rule` in `memdiag.py`):

- **Windows.** The W24 slope is the Theil-Sen slope, a symbol, of the soak's own RSS curve (every sample,
  h12-24): R4's figure, and `judge` checks that the default's is R4's. Attribution comes from hours 2-12
  of the tracemalloc leg, and carries over because the same growth runs in both windows: on the laptop,
  +4.66 MiB a symbol over h2-12 and +3.28 over h12-24, with rises on the DedupeRing's grid in both.
- **Units.** `LEAK_MIN_GROWTH_MIB` (1.0) is MiB of the whole process, three symbols; `MOVE_MIN` (0.09
  MiB/h) and R4's limit (0.18) are a symbol's.
- **LEAK lines.** A run is a line's consecutive hourly snapshots from hour 2 on, in each one's top-100 since
  hour 2, each larger than the one before (N5). A library line's growth goes where the newest repo frame
  of its biggest traceback is. Tracebacks are kept for the 5 lines that grew most each hour; a library
  LEAK line with none kept counts as elsewhere.
- **The store's turnover (B1).** The store is at its cap from setup, 1 000 stored bars a series, and each
  series that closes replaces stored bars with live ones at its rate (closes an hour a lane: tick 3 930,
  volume 334.8, time 99.9, range about 12.9). Live bars held a symbol, of 27 000 in series that close:
  5 155 at h2, 10 131 at h12, 11 822 at h24. A stored bar holds 1 312 B at `bars/reader.py`'s and
  `domain/sql_names.py`'s lines; a live one 832 B at `bars/time_builder.py`'s and 272-480 B at
  `exchange/*/trades.py`'s: -208 to 0 B a bar replaced, -208 the end that masks most. Over h2-7 the
  three symbols replace 10 044 bars: `time_builder.py:159` grows +1.99 MiB and `trades.py:64` +2.0-4.0 MiB,
  every hour, while the filtered total falls by up to 2.96 MiB by h12 (14 928 replaced, at the -208 B end).
  The netting (M-1) sums those four files' lines into `STORE_LINE`: at each snapshot from hour 3, their
  growth since hour 2, each line once from `vs_h2` and `shrank_h2` (the lines that shrank most), a line
  in neither counting as unchanged. It falls with the turnover, by up to 2.96 MiB over hours 2-12,
  whatever else grows. B1's total test still masks a Python leak slower than that fall, about 0.1 MiB/h
  a symbol (a run over hours 2-12 needs about 0.13), under R4's 0.18. M4's floor is net of the same
  fall: it flags growth no line explains only from 2.7 + 2.96 = 5.66 MiB over 10 h, about 0.19 MiB/h a
  symbol, just above R4's 0.18. A bursty or diffuse leak between about 0.13 and 0.19 escapes both tests.
  At R4's measured 0.2475 it raises the total by about 4.5 MiB or more over hours 2-12, and with the
  turnover's lines netted, M4 alone catches it. Each snapshot records its filtered total and the lines
  that shrank most since hour 2.
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
  A table that left mmap for the heap nets arena + hblkhd to 0, so its glibc step reads "other" and,
  through `FITS`, a real mmap128k FRAGMENTATION reads INCONCLUSIVE; the uordblks and fordblks deltas in the
  default leg's `steps[]` show such a case, for the orchestrator's ruling. On cv-bench-01 THP explains no
  step: it is `madvise`, and glibc does not advise its heap.
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
