# E12 bars store memory at the 32-spec cap (E12-T06 D2-G4, #399)

Status: **D2-G4 closed on the `default` memdiag leg (run 40020104619, R4 −0.020 MB/h; ruled 2026-10-31,
#399 issuecomment-6545764042). The laptop fallback (+0.2475) and the `cv-bench-01` nightly (+0.2358) stay on
record as FAIL readings of R4; see "D2-G4 closed" below.**

This record holds the D2-G4 fallback reading (coordinator ruling 4): run 39396280082 was cancelled at its
2100-minute timeout with no report, so `soak_bars --profile full` ran once on a laptop, as "The reading" says:
machine profile `laptop-i7-13850HX`, not `cv-bench-01`; 24 h of scenario time in 9 822.5 s of wall time; no
baseline recorded, and the committed baseline is a smoke run, so its gate compared nothing. The rule that
judges it was recorded on #399 before the reading existed and is quoted below. Every cell of the reading
table's 24 h column comes from the laptop run's report or is computed from its curve, and its 1.5 h column is
quoted from #3861; none is invented. The line was a precondition for the flag flip; the flag was removed in #399 (bars are always on), and the line stays recorded here as history.

The line is D2-G4 of #399's flag checklist: "memory at the 32-spec cap measured in the soak lane before
`bars_enabled` flips". Does the bars path hold budget #8 (06 §2 row 8, 300 MB a symbol) at 32 specs a
symbol of 1 000 bars each over 24 h of scenario time, and does it stop growing?

## What is measured

`soak_bars` (`services/api/bench/ingestion/bars_lane.py`, #3861): for each of BTCUSDT, ETHUSDT and SOLUSDT
a `BarBuilderSet` and a `SeriesStore` holding 32 series of 1 000 bars (6 tick, 9 time, 6 volume, 6 range, 5
delta), hydrated through the production tail read from the recorded golden bars and fed by the soak's trade
stream (50 prints and 10 book deltas a second a symbol, seed 7), on a virtual clock (about 3 h of wall time
on the laptop that recorded the baseline). Process RSS is sampled every 60 s (1 441 samples); the judged
figure is the RSS the lanes add, per symbol, in MiB. The lane never read the (since removed) `bars_enabled` flag.

## The pass rule, fixed before the reading (#399, issuecomment-6297719530)

> **D2-G4 pass rule, recorded before the reading exists** (20 Oct). The `soak_bars` leg of
> `perf-ingestion-nightly` run 39396280082 starts after its 24 h `soak_steady` leg, about 08:53Z on 21 Oct (head
> `e784738b5`, which holds #3861 and #3868). D2-G4 closes only if the `soak_bars` verdict of a `--profile full`
> run (24 h of scenario time, 3 symbols x 32 specs x 1 000 bars, `bench/ingestion/bars_lane.py`) meets all four:
>
> 1. **R1, budget #8:** `rss_per_symbol_p95` <= 300 MB (06 §2 row 8, §9: p95 over the 24 h run). It is the RSS
>    the lanes add per symbol, bars path included.
> 2. **R2, flatness:** `memory_flatness` <= 5 % from the hour-2 sample (E08 sign-off B6).
> 3. **R3, cap integrity:** `bars_store_at_cap` 1 000 at every sample, `bars_closes_folded` >= 1,
>    `bars_builders_healthy` 0.
> 4. **R4, plateau:** the Theil-Sen slope of the lane-added RSS per symbol over the last 12 h of scenario time
>    is <= 0.18 MB/h, over at least 100 samples. Derivation: (300 MB - 170 MB, the 1.5 h leg's figure) / 720 h,
>    the growth that would use the headroom in 30 days. The 5 % band alone admits about 0.42 MB/h.
>
> A run that does not reach hour 24 is no reading. A failed line keeps D2-G4 open and `bars_enabled` off; no
> budget, limit, band or baseline is changed to pass. [...]

The quote is an excerpt of the posted comment. Its first paragraph goes on to list what lies outside the
figure (restated under "Noted" below, with the E13 item brought up to date for #3927) and ends "This text
records numbers and sources only."; a second paragraph records the coordinator's ruling, and the comment
continues after it.

Ruled on 20 Oct: the 30-day horizon, so R4 is <= 0.18 MB/h. If run 39396280082 yields no report, a laptop
`--profile full` run of `soak_bars`, labelled with its machine profile, is the fallback reading, and this
record says so. "MB" is the harness's own unit, a MiB, as for R1 (`rss_per_symbol_mb` divides bytes by 2^20,
and the 300 and the 170 are in it), so 0.18 is 0.189 in decimal MB.

R4 reads growth that is sustained across the window, and its estimator (the median of the pairwise slopes)
has two blind spots, measured on synthetic curves of this window. A single step registers only within about 13
minutes of the window's middle (a +10 MB a symbol step reads +0.85 between hours 17.8 and 18.2, and exactly 0
anywhere else). Growth that starts in the last 3.5 h (29 % of the window) reads 0 at any rate. R2's band (5 %
of the process RSS, about 9.5 MB a symbol) stays the guard for a large step. This record cannot show a late
leak: growth that starts in the last ~3.5 h is under-read, and the table holds the RSS at three hours only.

## The reading

Run 39396280082 (`perf-ingestion-nightly`, `profile=full`, runner `cv-bench-01`, machine profile `bench-runner`)
was cancelled at its 2100-minute timeout; its artifact `e08-perf-pack-full` holds no `e08-full` report, so it
gives no reading. The fallback: `uv run python -m bench.ingestion.runner soak_bars --profile full` (no
`--record-baseline`) from `services/api` at `bd82bdce2`, this PR before its rebase and this record's fill (at
its head the PR's runner, scenario file and tests are unchanged, and `budgets.py` and `bars_lane.py` differ
in docstrings only), machine profile `laptop-i7-13850HX`
(i7-13850HX, 28 threads, WSL2, Python 3.12), harness `e08-q04/2`, 20:03:11Z to 22:46:53Z on 21 Oct, wall time
9 822.5 s. Its report (`e08-full-20261021T200311Z.md` and `.json`, kept off the repository) has the check lines
of the `soak_bars` section, the curve `_curve` (the process RSS in MiB at each of the 1 441 samples) and, because
it ran this PR's code, R4 itself as the hard check `rss_plateau_slope`. The hard checks of that section are
`undetected_loss` (#5), R1 `rss_per_symbol_p95`, R2 `memory_flatness`, the three R3 lines `bars_store_at_cap`,
`bars_closes_folded` and `bars_builders_healthy`, and R4; `vcpu_per_symbol_p95` and `storage_gb_day_symbol` are
soft. R4 is also recomputed from `_curve` with this PR's `check_plateau` (the two agree). Save the block as
`r4.py` and run it from `services/api` as `.venv/bin/python -I r4.py <the report's .json>`:

```python
import json
import sys

sys.path.insert(0, ".")  # services/api; -I keeps the working directory off the path
from bench.ingestion import budgets as b

doc = json.load(open(sys.argv[1]))  # the downloaded report: data, never code
m = next(r["verdict"] for r in doc if r["verdict"]["scenario"] == "soak_bars")["metrics"]
pre = round((m["rss_mb_process"]["p95"] - 3 * m["rss_mb_per_symbol"]["p95"]) * 2**20)  # 0: same slope
samples = [b.Sample(float(t), round(mib * 2**20), 0.0, 0.0, 0, 0) for t, mib in m["_curve"].items()]
print(b.check_plateau(samples, 3, 43_200.0, pre))  # 3 symbols, the last 12 h
print(len(samples), max(s.t_s for s in samples))  # a full run: 1441 86400.0
for h in (2, 12, 24):  # lane-added RSS per symbol, MiB
    print(h, round((m["_curve"][str(h * 3600)] - pre / 2**20) / 3, 2))
```

The verdict is PASS only if the six hard checks pass in the report, R4 holds as recomputed, and the run is
complete (the block prints 1441 and 86400.0). A FAIL in any of them means the line is not passed: D2-G4 stays
open, `bars_enabled` stays off and no limit is changed to pass; a FAIL of `undetected_loss` is also a P0 of
budget #5, reported as such. An independent offline script that reads the same curve is a cross-check, not the
verdict.

| Row                                                   | Limit                 | Derived from (a check line is the report's)                                   | 24 h reading (fallback)  | 1.5 h leg (#3861)      |
| ----------------------------------------------------- | --------------------- | ----------------------------------------------------------------------------- | ------------------------ | ---------------------- |
| `undetected_loss` (#5; hard, outside R1 to R4)        | 0 events              | the check line                                                                | 0 events                 | not recorded           |
| R1 `rss_per_symbol_p95`                               | <= 300 MB             | the check line: p95 of the lane-added RSS per symbol                          | 177.6 MB (p50 174.9)     | 169.7 MB (p50 169.2)   |
| R2 `memory_flatness`                                  | <= 5 %                | the check line: the largest deviation from the hour-2 sample, as a %          | 4.26 %                   | 3.0 % (from 480 s)     |
| R3 `bars_store_at_cap`                                | 1 000 at every sample | the check line: the fewest bars any series held, at the lowest sample         | 1 000 at all 1 441       | 1 000 at all 91        |
| R3 `bars_closes_folded`                               | >= 1                  | the check line: the lowest lane                                               | 105 062                  | 6 556                  |
| R3 `bars_builders_healthy`                            | 0 reasons             | the check line: the count of degraded reasons, named in its note              | 0 reasons                | not yet checked        |
| R4 slope, computed from `_curve`                      | <= 0.18 MB/h; >= 100  | the block's `check_plateau` line: `measured`, and its samples (721)           | +0.2475 MB/h, 721: FAIL  | not judged             |
| Verdict                                               | all hold              | the six hard checks (report), R4 (block), a complete run (1441, 86400.0)      | FAIL (R4 only); complete | not applicable         |
| Lane-added RSS per symbol (MiB) at hours 2, 12 and 24 | reported              | the block's rows: `(_curve[h * 3600] - pre / 2**20) / 3`                      | 170.26; 174.92; 178.20   | not recorded           |
| Setup MB a symbol; bytes a bar                        | reported              | metric `bars_setup_mb_per_symbol` (p95); bytes a bar = setup x 2**20 / 32 000 | 145.76 MB; 4 776 B       | 145.6 MB; about 4.7 KB |

The 1.5 h column is a reference: like that leg, the fallback ran `soak_bars` alone in a fresh process, whereas
the nightly runs it after the 24 h `soak_steady` in one process (`runner all`), where the pre-lanes RSS would
include that scenario's heap and the lane-added figure could move either way. The setup row is the check
against 145.6 MB. The R4 figure agrees three ways: the report's `rss_plateau_slope` and the block read
0.2475 MB/h over 721 samples, an independent offline script +0.248; the block prints `1441 86400.0`.

## D2-G4 closed (2026-10-31)

After the fallback above, two more 24 h readings of the same rule exist, both on `cv-bench-01` (machine
profile `bench-runner`), and the diagnosis that reconciles them is in
[`e12-bars-r4-diagnosis.md`](e12-bars-r4-diagnosis.md) ("The result"):

| Reading                                        | Run         | Head        | R4 (MB/h a symbol, 721 samples) | Other checks         |
| ---------------------------------------------- | ----------- | ----------- | ------------------------------- | -------------------- |
| laptop fallback (above)                        | none        | `bd82bdce2` | +0.2475: FAIL                   | pass                 |
| nightly `soak_bars` (`perf-ingestion-nightly`) | 39741074901 | `362590b93` | +0.2358: FAIL                   | pass                 |
| memdiag `default` leg (`perf-bars-memdiag`)    | 40020104619 | `f496b01e2` | −0.020: PASS                    | R1-R3 pass; complete |

The combined `memdiag judge` verdict over the four legs is **NOT REPRODUCED** (#399, issuecomment-6545806239),
and the diagnosis is allocator retention, not a leak: with pymalloc off (`malloc` leg, run 40169689142) the
glibc in-use bytes are flat to falling over hours 12-24 while free bytes in the arena rise, and with
allocations of 128 KiB or more on mmap (`mmap128k` leg, run 40249045721) no step of 1 MiB or more appears
after the first half hour.

**Ruled (BQ-1, 2026-10-31, under the owner's delegation of 2026-10-29):** D2-G4 closes on the `default` leg,
as the diagnosis rule's own text says. That reading is a `--profile full` `soak_bars` run of 24 h meeting
all four checks of the pass rule above, on `cv-bench-01` (in a process that also probed the allocator
hourly, as the diagnosis rule records), so it satisfies the rule as written; no budget,
limit, band or baseline changed. The two FAIL readings stay on record as FAIL readings, not withdrawn: the
diagnosis explains them as the same growth pattern, a staircase of 1.8-4.0 MiB heap steps whose slope over
the window is decided by the size of the step nearest its middle and by whether pymalloc releases memory
after it. The tie-break is one host-quiet nightly `soak_bars`, judged by the same R4 and named here with its
run id when it lands; it does not hold the closing PR.

**Fragility, recorded.** R4 near 0.18 is decided by single step sizes: on the recorded curves, the nightly's
h17.60 step at 1.84 MiB instead of 4.00 reads 0.1671, and the default leg without its two releases reads
0.1323 (0.2144 with a 4.00 MiB step as well), so 3 of the 5 bench and laptop runs pass and 2 fail. A future
reading on either side of 0.18 is not by itself a change in behaviour; a rise in glibc in-use bytes
(`uordblks`) over hours 12-24 would be. On the 30-day projection R4 was derived from: at the worst reading,
+0.2475 MB/h from 178 MB, linear growth would reach budget #8's 300 MB after about 20 days of continuous
running, and the measured growth decays (hours 2-12 at 0.20-0.37 MB/h, hours 12-24 at −0.02 to 0.25).

The standing conditions below still hold at the closing reading's head and at this record's: neither
`bars/series_store.py`, `bars/builder_set.py` nor `bars/models.py` has changed since `e784738b5`, nor the
sink list in `bars_wiring.py` since `4a921a101`. The reading with E13's indicators sink in the lane is owed
by the first host-quiet nightly after #399 merges, and the flip was not held for it ("Noted" below).

## Noted, not part of the verdict

- **The shape of the R4 failure, observed and not diagnosed**: the process RSS never falls; it climbs in
  steps with long flat runs (lane-added 170.26, 174.92 and 178.20 MiB a symbol at hours 2, 12 and 24). Over
  hours 12 to 24 four rises above 1 MiB make up 9.63 of the 9.84 MiB the process gained, and least squares
  over the same window reads +0.285 MB/h a symbol, so the failure is not an artefact of the estimator. One
  run on one laptop, in a fresh process and not on `cv-bench-01`: what follows (a diagnosis, a fix, a repeat
  on `cv-bench-01`) is separate work on #399.
- **Time reads at the reading's head** (SR-E12-02): there a time-kind tail read was bounded by span (twice
  the bars asked for, at most 400 days), not by table rows (`build_tail_scan_bound_query` refused `time`),
  and by the 2 s timeout and 8 concurrent reads, under BR-28's Medium residual (RSK-059). #4069 (#399 R1),
  merged after the reading, bounds a time read by table rows as well, which the E12 threat model records
  as closing that revisit. The soak's stand-in table does not measure database read cost, so this reading
  says nothing of it.
- **The five `delta` series never close in the lane**: the feed alternates buy and sell prints of 0.001,
  below the smallest threshold the wire takes. Their hydrated bars are in the level and their fold path is
  not exercised: neither the level nor R4 says anything about that path.
- **Outside the figure**: the bar writer (up to about 85 MiB a process), the WS publisher, WS delivery
  (#568, #528, after #399), tape replay at restore and E13's indicators sink: E13-T02 (#3927, `4a921a101`)
  added it to `wire_bars` after `e784738b5`, and the reading's head carries it, but the lane at those
  readings composed the store alone (`EmitRouter([self.store])`), so the figure leaves it out (history).
  #399 removes the flag (D2-G4 closed on the default leg, ruled above) and the lane composes the indicators
  sink from #399 on (`EmitRouter([store, indicators])`, no history reader, no listener; no instances are held, so only
  the emit-path overhead is measured). The `soak_bars`
  reading with the sink in the lane is owed by the first host-quiet nightly after #399 merges and is
  recorded on #399's QA record. The flip was not held for it, per the coordinator's ruling of 2026-10-31.
  A passing reading of the earlier lane stands for the D2-G4 line while `bars/series_store.py`,
  `bars/builder_set.py` and `bars/models.py` are as at `e784738b5` and the sink list in `bars_wiring.py` is
  as at `4a921a101`.
