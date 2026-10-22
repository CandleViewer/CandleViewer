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
`smaps_rollup`, the THP mode and the thread count. The dispatch sets the allocator variables; the leg
records those it saw and checks pymalloc against them. One leg a dispatch on cv-bench-01, never two at once:

| Order | Leg           | Length                              | Allocator environment           | Read for                                    |
| ----- | ------------- | ----------------------------------- | ------------------------------- | ------------------------------------------- |
| 1     | `default`     | 24 h: the profile, unchanged        | none                            | the reading: R1-R4 and the W24 slope        |
| 2     | `tracemalloc` | 12 h (`--hours 12 --tracemalloc 6`) | none                            | attribution only; its RSS is never sloped   |
| 3     | `malloc`      | 24 h                                | `PYTHONMALLOC=malloc`           | the W24 slope without pymalloc              |
| 4     | `mmap128k`    | 24 h                                | `MALLOC_MMAP_THRESHOLD_=131072` | the W24 slope with the mmap threshold fixed |

A report says `"reading": true` only for a leg with no override, no tracemalloc and no allocator variable.
Its R1-R4 verdict is the runner's own, unchanged.

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

How `judge` applies it (the constants and `rule` in `memdiag.py`):

- The W24 slope is the Theil-Sen slope, a symbol, of the soak's own RSS curve (every sample, h12-24): R4's figure on an unchanged run.
- Post-warm-up snapshots run from hour 2 on. A snapshot's top-N is its 25 lines (`--top`) that grew most since hour 2; a LEAK run needs the line in it at each snapshot of the run. A library line's growth goes where the newest repo frame of its biggest traceback is (kept for the 5 lines that grew most each hour).
- A leg counts only if valid: its length reached, R3 passed, its own allocator setting seen and consistent with pymalloc, tracemalloc on for its leg only, its probe lines matching the soak's samples, and, for the default, a reading. Per leg, a valid report wins over an invalid one, then the latest.
- LEAK also needs both allocator legs, since a move would make it MIXED; until then the outcome is INCONCLUSIVE, naming them.
- A step is an RSS rise of 1 MiB or more between two hourly probe lines, put down to glibc (arena + hblkhd), THP (AnonHugePages) or other, by which rose with it by half of it.

## Re-running `judge`

Download each leg's artifact into a folder of its own under one directory, then judge them all:
`gh run download <run-id> --dir memdiag/<label>` for each leg, then from `services/api`
`uv run python -m bench.ingestion.memdiag judge ../../memdiag`. It reads every leg report (`<label>.json`)
under the directory and writes `memdiag-verdict.json` and `memdiag-verdict.md` there.
