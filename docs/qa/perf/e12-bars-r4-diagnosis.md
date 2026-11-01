# E12 bars soak memory: what moves R4's slope (E12-T06 D2-G4, #399)

Status: **the combined `judge` verdict is NOT REPRODUCED (2026-10-31); D2-G4 is closed on the
`default` leg as ruled (#399, issuecomment-6545764042), with the nightly's 0.2358 kept on record as a FAIL
reading. The harness and the reading rule below were committed before any dispatch and are unchanged.**

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

## The result (2026-10-31)

Posted on #399 as issuecomment-6545806239. It is analysis of recorded artifacts only: no soak, bench or
leg ran for it. `judge` ran at `main` `00d2418ed` (`memdiag.py` unchanged since the tag) over the four legs'
artifacts.

### The inputs

| Leg                                 | Run         | Artifact (expires)                 | Leg report                                                                                                            | W24 slope, MiB/h a symbol |
| ----------------------------------- | ----------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| `default`                           | 40020104619 | `memdiag-default` (2026-11-23)     | `default.json`, complete (1 441 samples, t = 86 400 s), `reading: true`                                               | **−0.020**                |
| `tracemalloc`                       | 40079474569 | `memdiag-tracemalloc` (2026-11-24) | none: only `tracemalloc.jsonl`, probes h0-h2 and snapshots h1-h2; the step was cancelled at 17.7 h, before the report | attribution only          |
| `malloc`                            | 40169689142 | `memdiag-malloc` (2026-11-25)      | `malloc.json`, complete, allocator self-check passed                                                                  | +0.084                    |
| `mmap128k`                          | 40249045721 | `memdiag-mmap128k` (2026-11-25)    | `mmap128k.json`, complete, allocator self-check passed                                                                | +0.076                    |
| for comparison: nightly `soak_bars` | 39741074901 | `e08-perf-pack-full` (2027-01-20)  | the runner's report, at `362590b93`                                                                                   | **+0.2358 (FAIL)**        |

The three leg reports share head `f496b01e2` (tag `bench/r4-legs-1`), the scenario's sha256 (`10bb3a9a…`),
machine profile `bench-runner`, glibc 2.43, Python 3.12.15 and THP `madvise`, so M3 holds. In every leg the
runner's own R1-R4 pass (R4 −0.020, +0.084 and +0.076, each ≤ 0.18) and R3 holds (1 000 at the cap,
105 062 closes folded, 0 degraded).

### The verdict

**`memdiag judge` (combined, exit 0): NOT REPRODUCED.** The default's W24 slope is −0.020 MiB/h a symbol
(net rise +0.18 MiB), a valid reading whose slope is the runner's R4; `malloc` (+0.084) and `mmap128k`
(+0.076) are valid and comparable with it (M3); `tracemalloc` has no report. Annotation: `uordblks` rose
0.64 of RSS's rise over W24. The rule decides on the `default` leg first, so the allocator legs cannot
change the outcome; they answer BQ-2 below. The output is `memdiag-verdict.{md,json}`, written by `judge`
next to the downloaded artifacts (kept off the repository, as the leg reports are).

### Why the nightly read 0.2358 and the default leg −0.020

Ruled out from the artifacts:

- **The window or the estimator.** Both are the Theil-Sen slope of the lane-added RSS a symbol over
  t = 43 200 to 86 400 s (721 samples). Recomputed from each run's own `_curve`: 0.2358 and −0.0198, the
  reports' figures to four places.
- **The code.** Between `362590b93` (the nightly) and `f496b01e2` (the legs) nothing changed under
  `candleviewer/bars/`; under `bench/ingestion/` only the memdiag harness was added and budget #13's smoke
  reporting changed, neither on the soak's memory path.
- **The hourly probes, as the cause.** They run on the hour and allocate 10-20 KiB. The events that decide
  the two readings (below) fall at h17.60-17.63, h19.90 and h21.03, none on the hour, and are 1.8-4.5 MiB
  each; the allocator legs probe hourly too and read +0.08. A probe nudging the heap layout is not ruled
  out, but it does not explain the size of the difference.

What the curves show: the gross growth in the window is the same. The steps of 1 MiB or more in W24 add
+7.68 MiB of process RSS in the nightly (4.00 at h17.60, 1.84 at h17.83, 1.84 at h23.28) and +7.49 MiB in
the default leg (1.84 at h12.27, 1.84 at h17.63, 1.95 at h19.92, 1.86 at h22.97). Two events differ:

1. **The step near h17.6 is 4.00 MiB in the nightly and 1.84 MiB in the default leg.** It is the scheduled
   large rebuild near the window's middle (the laptop run's h17.57). How far the heap top grows for it
   depends on the free-list state at that moment.
2. **The default leg gave memory back: −4.48 MiB at h19.90 and −1.54 MiB at h21.03.** The glibc arena stayed
   at 319.42 MiB across both falls, so this was pymalloc releasing empty arenas (pymalloc blocks
   2 690 310 → 2 689 552). The nightly has no fall of 0.5 MiB or more in its 24 h.

The step-size staircase, as counterfactuals on the recorded curves (R4's estimator, W24, MiB/h a symbol):

| Curve                                                           | W24 slope |
| --------------------------------------------------------------- | --------- |
| nightly as recorded                                             | 0.2358    |
| nightly with its h17.60 step at 1.84 instead of 4.00            | 0.1671    |
| nightly without the h17.60 step                                 | 0.0955    |
| default as recorded                                             | −0.0198   |
| default without its two releases                                | 0.1323    |
| default without the releases and with a 4.00 MiB step at h17.63 | 0.2144    |

The two runs are one process with one growth pattern, and each of the two events alone moves R4 across
0.18. Theil-Sen over a staircase of 3-4 steps is decided by the size of the step nearest the window's
middle and by whether anything is released after it (the estimator's blind spots are in
[`e12-bars-store-memory.md`](e12-bars-store-memory.md)). Host sharing plausibly shifts the allocation
interleaving that sets both: the nightly ran under load 11-16, took 13 h 46 min of wall time against the
default leg's 11 h 14 min, and had an event-loop lag p95 of 929 ms against 718 ms. The artifacts cannot
prove that.

The decay is the same on the four bench-runner curves: the h2-12 slopes are 0.20-0.37 (nightly 0.309,
default 0.366, malloc 0.233, mmap128k 0.201), the h12-24 slopes −0.02 to 0.24 (the laptop's 0.2475).
Growth slows after warm-up and has not been shown to stop inside 24 h. R4 reads PASS or FAIL by the run:
3 runs pass (default, malloc, mmap128k) and 2 fail (nightly, laptop).

### BQ-2: allocator retention, not a leak

- **`malloc` (pymalloc off, every Python object a glibc allocation).** Over W24, glibc in-use bytes
  (`uordblks`) are flat to falling: slope −0.015 MiB/h a symbol, rise −0.20 MiB a symbol. Free bytes in the
  arena (`fordblks`) rise +0.13 MiB/h, and RSS +0.084. A leak of live objects would raise `uordblks`; it
  does not.
- **`default`.** Over h12-24, process `uordblks` went 294.55 → 294.89 MiB (+0.34 MiB in 12 h), the glibc
  arena 315.97 → 321.25 (+5.28) and `fordblks` 21.42 → 26.36 (+4.94); pymalloc blocks fell from 2 691 821
  to 2 689 426. Every W24 step but one is glibc heap growth with `uordblks` unchanged (±0.015 MiB): the heap
  top grows to fit a transient large allocation and keeps the space as free space afterwards.
- **`mmap128k`.** With allocations of 128 KiB or more on mmap, there is no RSS step of 1 MiB or more after
  h0.48 in the whole 24 h; its W24 rise, +0.92 MiB a symbol, is sub-MiB creep. So the 1.8 and 4.0 MiB steps
  are large tables re-allocated on the heap: allocator high-water retention, not live growth. Under the
  rule this is no move (M1 is one-sided, and its slope is above the default's).
- **`tracemalloc`.** Its data covers h0-h2 only, the warm-up the rule excludes (`WARMUP_H = 2`), with no
  `vs_h2` snapshot, so it cannot qualify a LEAK line. Its hour-2 "+4 744 pydantic instances" are `Bar`s
  built at `bars/time_builder.py:176` (`Bar.model_construct`) and stored at `bars/series_store.py:463`,
  which evicts the oldest past `MAX_HISTORY` (L464-L465, at `f496b01e2`): the store's turnover (M-1), live
  bars replacing hydrated ones, at −208 to 0 B net a bar. R3's `bars_store_at_cap` = 1 000 at every sample
  shows the store stays bounded.

**Answer (ruled, BQ-2):** allocator retention (the glibc heap's high-water mark), not a reference leak. No
`series_store` storage rewrite is owed for R4. GC-untracked storage stays #3641's question (pause time),
with `gc.freeze` as its mitigation. Were R4's residual to be removed rather than ruled, the lever the
evidence supports is the allocator (an mmap threshold, or `malloc_trim` after large rebuilds), not the data
structure, as a separate, measured change. **BQ-3:** no `tracemalloc` re-run; the `malloc` leg answers the
leak question it was to attribute.

### The ruling, and the fragility

D2-G4 is closed on the `default` leg (#399, issuecomment-6545764042): NOT REPRODUCED, as the rule's text
says, the one registered reading taken under the rule's controls, at one head, R1-R4 passing, with this
diagnosis attached. No limit, band or baseline moved, so the nightly's 0.2358 stays on record as a FAIL
reading, explained above as the same staircase. R4 near 0.18 is decided by single step sizes: the two
readings are within one step of each other. On the 30-day projection R4 was derived from: at the worst
reading, 0.2475 MB/h from 178 MB, linear growth would reach 300 MB after about 20 days of continuous
running; the measured growth decays (h2-12 against h12-24 above), so a linear projection overstates it. The tie-break
is one host-quiet nightly `soak_bars`, judged by the same R4 and named in the store-memory record with its
run id when it lands; it does not hold the closing PR.

## Re-running `judge`

From the repo root, download each leg's artifact into a folder of its own under one directory:
`gh run download <run-id> --dir memdiag/<label>`. Then from `services/api`,
`uv run python -m bench.ingestion.memdiag judge ../../memdiag`. It reads every leg report (`<label>.json`)
under the directory, skips and names any it cannot read, and writes `memdiag-verdict.json` and `.md` there.
