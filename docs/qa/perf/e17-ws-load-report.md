# E17 WS load profiles and W5 report (E17-Q03, #568)

Status: **recorded readings (2026-10-23, round 3 and a quiet window): profile A passed on the quiet run, B failed in all three runs, C read over two budgets with the host not quiet (not attributable to the code), W5 is answered, and one warn-only baseline (A) is recorded.** The harness (profiles,
fixture backend, k6 client, verdict, baseline gate, self-check) ran the full profiles on the bench runner, by the
dispatch-only workflow `.github/workflows/perf-ws-load.yml`, flag on, k6 at `/ws`, with `main`'s harness at each
dispatched commit (table "Recorded runs" below). Profile A's three round-3 runs were valid and missed budgets #6
and #3 while other work ran on the host the bench runner shares; one A run in the host-quiet window passed every
budget (fan-out p95 11.8 ms), which names the source of the spread. Profile B's harness verdict was FAIL in all
three runs (the backend did not answer `/metrics` in time, and validity guards tripped too; see the note under the budget table). Profile C ran three valid runs of 30 min in round 3 and three more in the quiet window, and
read over #6 and the local tick-to-pixel line in both sets, with the host not quiet (see the caveat under the budget table). W5 is
answered from run 39912100280 by the rule as fixed after that run, and the quiet-window W5 run replicates the
answer (below). `runner record` refuses a run that is not PASS, so the one baseline is A's quiet run, warn-only;
B and C have none. No number in this file is invented: a cell reads `not run` or `n/a` where no
reading exists, and each figure is one run's reading or, for a set of three, the median of its valid runs, read from the
run's `result.json`.

The harness lives in `services/api/bench/ws/` and `tests/load/ws/`. This file is where its results are written
and is linked from `qa/plans/e17-ws-conformance.md` §4. The ticket named `docs/qa/test-plans/e17-ws-protocol.md`,
which does not exist; plans live under `qa/plans/` and results under `docs/qa/perf/`, as for E09.

## How a run is made

```text
export K6_BIN=<absolute path of the pinned k6 v2.3.0>   # an executable file, never taken from PATH; any other version is refused
cd services/api
uv run python -m bench.ws.runner run A --staging --out-dir <dir>      # also B, C, smoke; --flag off for the control
#   --ws-path /api/v1/ws points k6 there (default /ws); the fixture serves both, as the app does
uv run python -m bench.ws.runner selfcheck --staging --out-dir <dir>
uv run python -m bench.ws.runner w5 --staging --out-dir <dir>         # --duration-s 30 --warmup-s 10: a dry run
uv run python -m bench.ws.runner repro <run 1> <run 2>                 # AC 5
uv run python -m bench.ws.runner gate <run 1> <run 2> <run 3>          # C-13.9: 5 % on the median of 3
uv run python -m bench.ws.runner record <run dir>                      # a PASS run's baseline (local, never CI)
```

`--staging` runs the backend in a systemd user scope (`CPUQuota=400%`, `MemoryMax=8G`, no swap) on cpuset 0-7
and k6 on 8-15, so they never share a CPU (`--backend-cpus` and `--k6-cpus` set the cpusets alone). Exit code 0
is a pass, 1 a budget missed with its check named, 2 an INVALID run (a validity guard tripped, so no budget is
judged). k6 never phones home (`K6_NO_USAGE_REPORT=true`), resolves no extension, and the script refuses a
non-loopback target. A run clears its directory of an earlier run's artefacts and bar state first, but only a
directory the harness made: an empty one, or one that holds the `.cv-bench-ws-run` marker a run writes (a regular
file). Any other is refused, untouched (use an empty `--out-dir`); the refusal and the clear follow no symlink inside it.

**The clock-skew guard** makes a run INVALID when the hello's clock skew is over 5 ms. k6 times each hello's round
trip, and the guard reads the corrected skew `|raw - RTT/2|` of the hello with the shortest round trip (NTP's
minimum-delay filter; on a tie, the smallest corrected skew, then the smallest raw). It used to read the max over the
hellos, so one hello that waited in a queue decided the run, though such a reading is the wait, not the clocks'
offset: on one host clock, profile A's run 3 on `cv-bench-01` read 18.0 ms, all of it one hello's 40 ms raw skew on a
44 ms round trip (the median round trip was 7.5 ms). The minimum-RTT reading is never above that max, so a run the
max admitted stays admitted. `result.json` and the report's guard line name the estimator (`skew_estimator`):
`min_rtt_hello`; `max_over_hellos` when the k6 summary lacks a usable pair (`hellos`) for every timed hello (written
before each VU kept its hello's raw skew and round trip as a pair, one lost, or one with a negative round trip: the
client's clock stepped back); `raw_max` where only the raw skew is read (a run with an injected send delay reports
it, unjudged). When the guard falls back, it says so: a `WARNING` line under the report's guard line, and `warning`
in `result.json`.
`result.json`'s `max_ms` is now `skew_ms`.

**A run is only as long as it says.** A run shorter than its profile (`--duration-s`, `--warmup-s`, the workflow's
`duration_s`) is labelled `smoke`: the gate never holds it to a full baseline, and `record` refuses it, so a short
window can never become a baseline.

**The regression gate** is C-13.9's: more than 5 % on the median of 3 runs fails, and one run can only warn. The
tolerance is a parameter (`--tolerance 0.10` is the ticket's 10 %). `runner gate` takes three runs that all passed and
are of one profile, flag, machine, length and event loop; it refuses (exit 2, naming why) on fewer, on an INVALID run,
on a run that records no loop or on runs that differ, and exits 1 when a run missed a budget or the median regressed.
E08's absolute floor applies to every `_ms` metric: a move of 0.5 ms or less never gates, so a fan-out that goes
from 0.7 to 1.19 ms (+70 %) passes.
A baseline is recorded by `runner record` from a passing, full-length run, as `warn-only`: the gate never fails
against it. Promoting it is a reviewed PR that changes its `gate` key to `gated` once a second run of the same
profile has confirmed it (06 §7.4); a baseline moves only by such a PR.

**Where the recorded runs happen.** `perf-ws-load.yml` runs on `cv-bench-01` (labels `self-hosted, Linux, X64,
bench`; 8 vCores, 32 GiB), on cpus 0-3 for the backend and 4-7 for k6, in the systemd scope when the runner has a
user manager. It is dispatch-only and never starts while the 24 h ingestion soak (`perf-ingestion-nightly.yml`,
job `perf-pack-full`) or a bars-soak memory leg (`perf-bars-memdiag.yml`, job `leg`, up to 23 h), both on the same
runner, is queued or running: its first step refuses (a 404 for the legs' workflow, not on `main` yet, reads as none
running, and any other API error fails the step), rather than sharing a
concurrency group, because GitHub keeps one pending run per group and would cancel a pending soak dispatch, and a
job queued behind a 24 h soak on a one-job-at-a-time runner would only fail GitHub's 24 h queue limit. The
`runs` input defaults to 3 so the gate and the reproducibility check have their runs, and a red run does not end
the loop (the step exits with the worst code of its runs). The `ws_path` input is the path k6 connects to (`/ws` by
default). The checkout keeps no token, the machine profile is named (`bench-runner`, as the soak's
is), and `scripts/tests/test_perf_ws_load.py` pins these properties and runs the load step under `bash -e`.

## What is under load

The backend is the real `/ws` gateway, hub, pipeline and bars runtime on uvicorn at 127.0.0.1, fed by a seeded
feeder that replays the recorded corpus. Main publishes no book `d` (#604) and no trades (no producer), so the
feeder stands in for them, into the real `SequencingHub` and the real `BarBuilderSet`. Footprint and heatmap have
no producer (#2197, #593, #605): their subscriptions are held (`snapshot_pending`), and their frames are not
measured. Sessions are a real `SessionService` over the fake repository, so no credential exists.

| Profile | Shape                                                   | Per connection | Steady window | Gates                                      |
| ------- | ------------------------------------------------------- | -------------- | ------------- | ------------------------------------------ |
| A       | 5 users x 1 connection, reference workspace, 10 symbols | 28 topics      | 1 h           | #6, #3 (roadmap 5.4)                       |
| B       | 1 user x 8 connections, full workspace, 40 symbols      | 128 topics     | 1 h           | every 23 §16.3 row, no backpressure resync |
| C       | 5 users x 1 connection, 4 panes (RW of 4 symbols) each  | 16 topics      | 30 min        | #3 and #6 at the 06 §10.1 concentration    |

Warm-up (5 min, 20 s for the smoke) comes before the steady window and is never measured.

### Recorded deviations from the written shapes

- **The 8-series cap binds below the written shapes.** `bars.*` and `footprint.*` each lease a bar series, and the
  gateway admits 8 distinct series per user (`bars/leases.py`, SR-E12-04). The reference workspace is kept exact
  on BTCUSDT (bars 1 m and footprint 5 m, 2 series), and the other 6 series go to bars on 6 more symbols. So B has
  128 topics per connection, not the 168 of the design: 72 of its requested topics (bars and footprint on 33
  and 39 symbols) cannot be admitted by the product. A real user with a chart and a footprint on every one of 10
  symbols is refused too: a finding for #572 and E12.
- **Book and trades are stand-ins** at the feed tiers of `profiles.json` (hot 50 book `d`/s and 60 prints/s,
  warm 10 and 10, cold 2 and 1; A totals 84 and 87, B 368 and 384). The book is the recorded BTCUSDT book, with
  its prices at 10x the trade prices, and clones replay it from seeded offsets.
- **`/ws` by default; `/api/v1/ws` reaches the same gateway.** 23 §2.1 and the web client say `/api/v1/ws`. Since
  #3916 the gateway is served at both, one router included twice (`include_ws_router`), and the fixture mounts it
  the same way. The harness targets `/ws` by default. `ws_path` (`--ws-path`, the workflow input, the profile
  table's default) points k6's URL at `/api/v1/ws` with no fixture change; under another prefix it is served too.

## Approximations the numbers carry

1. k6's decode-complete mark (`Date.now()` after the CVWB decode) stands in for paint. No paint is measured, and
   the §16.3 per-frame decode rows and fps stay with E17-K01's Chromium numbers.
2. Loopback replaces the network, so the Tailscale hop (budget #3's WAN term) is outside the numbers.
3. Neither machine is the VPS: one asyncio loop is bound by single-core speed, and a laptop core, or a core of the
   bench runner, is faster than a VPS vCPU, so results are optimistic by that factor. The laptop is shared and
   hybrid P/E scheduling is invisible under WSL2. The recorded runs use the bench runner, with the backend held to
   the VPS profile's 4 vCPUs; a run on the VPS itself, before R1 exit, is the final mitigation.
4. k6 offers `permessage-deflate` as its WebSocket library can (no context takeover), so wire bytes are an upper
   bound and server deflate CPU differs from a browser session's.
5. The feeder's own work (parse, book upkeep) runs on the gateway's loop and is inside the backend CPU numbers,
   as ingestion's would be.
6. The fixture runs on the stdlib asyncio loop, so that its Python socket guard sees every lookup, while production
   (`server.run()`, uvicorn `loop=auto`) picks uvloop, which the lock file installs. Fan-out, event-loop lag, the
   window timers and backend CPU (so the W5 CPU per family) are loop-sensitive and err on the pessimistic side
   against production, where item 3 errs on the optimistic one. A baseline therefore compares with this harness's
   own runs only: every run records its loop (`loop` in `run.json`, and in a baseline), and the gate compares a run
   with a baseline only when both record the same one, never across loops or when either side records none.

## Budgets: the §16.3 column of the recorded runs

| Row                              | Source          | Target / hard fail      | Q03, flag on                                                 | Q03, flag off | Verdict                                     |
| -------------------------------- | --------------- | ----------------------- | ------------------------------------------------------------ | ------------- | ------------------------------------------- |
| Fan-out add-on p95               | 06 #6, 23 §16.3 | <= 20 ms                | A 11.8 / B 250 (top bucket) † / C 28.8 ms                    | not run       | A pass; B FAIL; C miss, not attributable    |
| Tick to decode p95 / p99, trades | 06 #3           | < 100 ms / < 250 ms     | A 25 / 48, B 8,237 / 9,756, C 43 / 125 ms                    | not run       | pass (A, C); B FAIL                         |
| Tick to pixel, local, p95        | 23 §16.3        | < 40 ms / > 120 ms      | A 25 / B 8,237 / C 43 ms                                     | not run       | A pass; B FAIL; C > 40 ms, not attributable |
| Bandwidth, reference workspace   | 23 §16.3        | < 350 KiB/s / > 1 MiB/s | A 8.9 / B 2.8 / C 8.8 KiB/s                                  | not run       | pass (A, B, C)                              |
| Full re-snapshot, bytes and time | 23 §16.3        | < 700 KiB, < 400 ms     | A 15.8 KiB, 79 ms / B 15.8 KiB, 48,798 ms / C n/a (no probe) | not run       | A pass; B FAIL (time)                       |
| `upstream_desync` per topic-hour | 23 §16.3        | < 1 / > 5               | A 0 / B 0 † / C 0 /h (by construction)                       | not run       | pass (A, B, C)                              |
| Resyncs from backpressure, gaps  | ticket          | 0                       | A 0, 0 / B 22,605, 129,331, 121,879; 0 / C 0, 0              | not run       | A, C pass; B FAIL                           |
| Event-loop lag p95 / p99         | C-14.2          | < 50 ms / < 100 ms      | A 22.8 / 58.2, B 1,000 / 1,000 † (runs 2, 3), C 56 / 191 ms  | not run       | miss (reported): B, C                       |

Profile B, measured: the harness verdict was FAIL in all three runs (exit code 1; the three runs of dispatch 39881322465, round 3, first leg).
The hard check `scrape.metrics_timeout` failed (the backend did not answer `/metrics` within 15 s in 7, 42 and 40 of 62
scrapes), and validity guards tripped as well (run 1: no re-snapshot sample and 9 unplanned closes; run 2: the feeder
behind its schedule and 2 `cv_errors`; run 3: the feeder behind its schedule and 1 unplanned close), so in runs 2 and 3
the load was below its schedule (run 1's feeder ratio was not judged: its first scrape timed out). The B cells are the
measured values, the median of the three runs unless a run is named: trades tick-to-decode p95 8,237 ms (runs 8,237,
8,527 and 7,609) and p99 9,756 ms, equal to tick-to-pixel p95 by construction; bandwidth 2.8 KiB/s; full re-snapshot
15.8 KiB in 48,798 ms (runs 2 and 3: 50,660 and 46,936 ms; run 1 had no sample); backpressure resyncs 22,605, 129,331 and
121,879, with 0 sequence gaps. The k6-side readings are as measured. The cells marked † are derived from the scrapes that
answered: fan-out p95 at the top bucket (250 ms) in runs 2 and 3 (run 1 did not judge it, its first scrape timed out),
`upstream_desync` 0, and the backend's event-loop lag, which read 1,000 ms (the top bucket) at p95 and p99 in runs 2 and 3.
The backend event loop was therefore not keeping its own timers. **Attribution:** host load does not discriminate
(`variance.other_cores` read about 6.0, 6.05 and 5.95, also on round 2's passing A runs, and 5.5 to 5.9 on round 3's A
runs that missed); the load shape on the gateway's event loop is the remaining candidate, and the fixture feeder shares
the gateway's process and event loop in staging (it is one task beside the uvicorn server and the lag sampler in
`fixture_app.py`, see "What is under load" and approximation 5), so the fix owner can separate the harness's cost from the
product's. Flag off was not run (the control is the lead's call). A is the one run made
in the host-quiet window (run 40007981025, 1 h, `main` at `1b69803c3d3e`); C is the median of the three runs of the
quiet-window dispatch (run 39981663972, `main` at `13c5a83ca630`). A single run is never mixed into a median of
three. Its readings: fan-out p95 11.8 ms (p99 33.9), trades tick-to-decode p95 25 ms and p99 48 ms (with the
window wait, 100 and 118 ms), event-loop lag p95 22.8 and p99 58.2 ms (reported). C's three quiet-window runs read
fan-out p95 32.1, 28.8 and 26.1 ms (budget 20 ms, missed in all three); trades tick-to-decode p95 43, 45 and 41 ms
and p99 140, 125 and 100 ms; tick-to-pixel p95, equal to the tick-to-decode reading by construction, 43, 45 and 41
ms (the 40 ms line missed in all three); event-loop lag p95 55.8, 58.1 and 49.97 ms and p99 191, 192 and 158 ms
(reported, never gating); with the window wait, trades p95 117, 116 and 114 ms (p99 209, 196 and 183).

**Round 3's loaded-host readings, kept as the evidence of the spread.** A (run 39950162313, three valid runs of 1 h,
`main` at `d0d43743b2c7`) read fan-out p95 23.9, 75.4 and 48.3 ms (budget 20 ms, missed in all three); trades
tick-to-decode p95 37, 88 and 70 ms and p99 120, 286 and 227 ms (the 250 ms p99 limit missed in run 2); tick-to-pixel
p95 passed the 40 ms line in run 1 only; event-loop lag p95 43, 97 and 86 ms; the median of those three runs would
read fan-out 48 ms, trades 70 / 227 ms, re-snapshot 15.8 KiB in 182 ms, so the budgets were missed under
contention and met on the quiet run (see AC 5). C's round-3 runs (run 39900923629, `main` at `c5e5aa3d4ff2`) read
fan-out p95 24.0, 27.6 and 28.3 ms, tick-to-pixel p95 41, 41 and 47 ms, event-loop lag p95 47, 49.6 and 50.7 ms.

**Profile C's caveat.** C is recorded as bench quiet, host not quiet. Both of C's legs, round 3 and the quiet-window
re-run (15:50 to 17:36 UTC), were measured with the bench runner quiet but not the host it shares: the re-run ended
before the host-quiet hold began (18:55 UTC). C's misses (fan-out p95 median 28.8 ms against 20, tick-to-pixel 43 ms against 40) are not
attributable to the code; A's host-quiet run passed every budget. A single host-quiet C run follows later as an
appendix; its reading is appended to #568's closing comment and to #399, not to this PR.

Not measurable on main: footprint and heatmap frames in the re-snapshot and bandwidth rows (no producer), and the
decode and fps rows of §16.3 (the browser's). Two rows can pass with little behind them and say so in every report:
`upstream_desync` per topic-hour reads 0 by construction (the feeder is not ingestion), and the full re-snapshot
covers book, trades and the bars the run built, with no footprint or heatmap and a series shallower than the
default history, so a pass there does not show 700 KiB and 400 ms met.

**Tick to decode and the throttle.** With the flag on, trades default to a 100 ms window, so a print waits up to a
window and the including-the-wait variant lands near 100 ms by design, which also fails the 40 ms local line. The
profile parameter `gate_on` picks the variant that gates (default `excluding`, the server's throttle wait out, as
budget #6's span starts at a paced frame's release, D7); the other is reported beside it, and a flag-off control of
A shows nothing throttled. The `<` limits (100 ms, 250 ms, 40 ms) are strict, as k6's thresholds are: a reading at
the limit misses it; budget #6's 20 ms is at or under.

C-14.2 event-loop lag is measured and reported, and no profile gates on it (`gate_loop_lag` is off, the design's
default); the `excluding` variant also leaves out a window timer that fires late, which the `including` variant
beside it shows. Whether loop lag gates is for the follow-up, with recorded numbers in hand.

## W5: per-topic coalescing under `saturated`

The rule is fixed in `bench/ws/w5.py` before any run (relief, latency cost and efficiency per family; keep the
fixed x2 and x4 only when every family carrying 10 % of the bytes shows 50 % relief at x4 at a similar
efficiency, else per-family multipliers). A cohort is put in `lagging` or `saturated` by delaying the `pong` of
the server's `s-rtt-*` probes, and no product code is added. `runner w5` runs 10 phases (an unsubscribed idle
baseline, the mixed workspace in each class, and book, trades and bars alone, healthy and saturated) and writes
`w5.json`; the tables below take its rows. It exits 1, never green, when there is no usable answer (no data, or a
mixed phase left out because it was INVALID or the server applied another class), and when its table has no row;
its first line then reads `W5: no usable answer`, counting any mixed phase left out, never a recommendation.
`--duration-s` and `--warmup-s` replace every phase's window and warm-up, so `runner w5 --duration-s 30 --warmup-s
10` is a dry run of the whole plan (about 9 minutes; the W5 profile does not wait for a 60 s bandwidth window).
The workflow's `duration_s` input sets the window alone, so there the phases keep their own warm-ups (60 s for the
three mixed phases, 30 s for the other seven) and `duration_s=30` takes about 14 minutes. `--rtt-delay-ms` is
refused, because a phase's class is its pong delay.

**The latency cost is staleness, never release-to-decode.** The envelope `ts` is stamped when a window is released
(`sequencing.py`, `pacing._flush`), so a decode minus it cannot see the wait the x2 and x4 multipliers add: every
family would cost the 1 ms floor and the append-family trigger could never fire. A test pins the premise through
the real gateway (an update published into a window is released a window after its source, and the CVWB header
keeps the source). Trades use the feeder-stamped time of the oldest print a frame carries, to decode-complete: the
stamp budget #3 uses, and the merge keeps the oldest. A merged book frame carries its newest update's header and a
bars frame none, so for book and bars the cost is the interval between two releases on the reference symbol's
stream, the longest an update waits in the window (`cv_hold_ms_book`, `cv_hold_ms_bars`). A family without such a
sample is left out, never read as 0 ms.

**Recommendation: per-family multipliers (run 39912100280, re-judged).** The run's own verdict on the rule then in
force was `no_data`: `mixed-healthy` and `mixed-lagging` were left out because the judge took the worst class
announced over the whole socket life, and each cohort had a few brief round-trip excursions (5 and 3 announcements
of the x4 class, against a cohort held in its intended class for 98.1 % and 99.9 % of the probe samples), so no family had a row. The rule was then fixed to judge the class held for most of the steady window
(#4287, `bench/ws/w5.py`; no metric's meaning changed, `HARNESS_VERSION` stays `e17-q03/1`), and the same
artefact was re-judged offline with it: `applied_class` is now the planned class in all three mixed phases, nothing
is skipped, and the answer is per-family multipliers. Reasons the rule gave: book carries 54 % of the bytes but only
27 % relief at x4; trades carries 27 % of the bytes but only 24 % relief at x4; the efficiency spread is 2.6x across
the families. Proposed (lagging, x4): book (x1, x1), trades (x1, x1), bars (x2, x4). The re-judge is not a second
run: the data are one run's. A second run is below.

**Replication (run 39997358579, quiet window, `main` at `4cc2f502f954`, which contains #4287).** Its own verdict
is `no_data`, and not from the class rule: the class judge passed all three mixed phases (the cohorts held
`healthy`, `lagging` and the x4 class for 98.4 %, 99.8 % and 100 % of the probe samples, and no phase was
`overflowing`). The `mixed-saturated` phase was left out by the general clock-skew check (a corrected skew of 6.0
ms against the 5 ms limit; the run is on one host clock, so the 6 ms is the fastest hello's transit asymmetry read
in whole k6 milliseconds), and with that phase gone no family had a row in both classes. With that one check
waived offline, on a copy and not by a rule change (the check is unchanged on `main`), the run gives the same
answer: bars 20 % of the bytes, 54.5 % relief at x4, 721 ms; book 54 %, 27.3 %, 144 ms; trades 27 %, 23.7 %, 282
ms; efficiency spread 2.5x; proposed unchanged. The two runs agree to within 1 point of relief and 5 ms of cost.
Its CPU readings above the idle baseline (0.161) are book 0.300 and 0.279, trades 0.104 and 0.085, bars 0.180 and
0.136 (healthy, x4 class). The recorded answer is the first run's, re-judged; the second supports it and is not
itself green.

| Family | Share of healthy bytes | Relief at x4 | Staleness cost | Efficiency | Merged updates per frame | Proposed (lagging, saturated) |
| ------ | ---------------------- | ------------ | -------------- | ---------- | ------------------------ | ----------------------------- |
| book   | 54 %                   | 27 %         | 141 ms         | 0.0019 /ms | 2.9                      | (x1, x1)                      |
| trades | 27 %                   | 24 %         | 283 ms         | 0.0008 /ms | 1.0                      | (x1, x1)                      |
| bars   | 20 %                   | 54 %         | 717 ms         | 0.0008 /ms | 12.1                     | (x2, x4)                      |

| Backend CPU, core-seconds per second above the idle baseline | healthy | saturated |
| ------------------------------------------------------------ | ------- | --------- |
| book                                                         | 0.229   | 0.174     |
| trades                                                       | 0.052   | 0.057     |
| bars                                                         | 0.153   | 0.124     |

The idle baseline is 0.168 core-seconds per second. Efficiency is relief per millisecond of staleness cost.

Multipliers that adapt at run time, per topic, need a signal from the product (a separate design, not built
here). The recommendation and its numbers are handed to E17-T07 and are written into 23 §16.6 W5 by this change.

## Acceptance criteria

| AC  | How it is verified                                                                                                                   | State                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Profile A, 1 h, flag on: rows #6 and #3 above                                                                                        | pass on the quiet run (40007981025): #6 p95 11.8 ms, #3 p95 / p99 25 / 48 ms. Round 3's three loaded runs missed (#6 p95 23.9 / 75.4 / 48.3 ms; #3 p99 286 ms in run 2), see AC 5                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 2   | Profile B, 1 h: every row above and zero backpressure resyncs                                                                        | recorded as FAIL x3, measured values in the budget table; the fix-or-rebaseline decision is the owner's (the backend did not answer `/metrics` in 7, 42 and 40 of 62 scrapes; validity guards also tripped; in runs 2 and 3 the load was below its schedule; the backend's event-loop lag read 1,000 ms at p95 and p99 in those runs; the cause is not settled, see the attribution sentence under the budget table)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 3   | A bandwidth over 1 MiB/s fails the run with the metric named: `test_bandwidth_over_one_mib_a_second_fails_the_run_naming_the_metric` | pass                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 4   | W5 answered from data                                                                                                                | pass: per-family multipliers, from run 39912100280 re-judged with the fixed rule; the quiet-window run 39997358579 replicates it with one generic check waived offline                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 5   | A second same-profile run within 15 %, or a named variance source: `runner repro`                                                    | source named, with a caveat: A's round-3 run 1 against runs 2 and 3 differs by far more than 15 % (fan-out p95 +215 % and +102 %); the source is load on the host the bench runner shares, reported by a lane sharing it (the harness cannot see by whom). Round 3's A runs ran about 12:01 to 15:17 UTC in that window and missed; the host-quiet A run ran inside the 18:55 to 20:10 UTC hold (about 19:01 to 20:06 UTC) and passed (fan-out p95 11.8 ms). No WS or bars product code changed between round 3's A and the quiet A run (no file under `candleviewer/ws`, `candleviewer/bars` or `candleviewer/bus` differs between `d0d43743b2c7` and `1b69803c3d3e`; other modules did change, and the bench files that changed are the W5 judge and the bench runner, both in #4287). `variance.other_cores` does not separate them: round 2's A runs passed at about 6.0, as high as round 3's. `main` also moved between round 2 (`362590b9371e`) and round 3 (`d0d43743b2c7`), and WS code changed in between; that was not checked here (the check above covers round 3's A to the quiet A only) |

The self-check (an ASGI send delay inside the fan-out span must fail budget #6 by name) is
`runner selfcheck`; its offline twin is `test_an_inflated_fanout_fails_budget_6_which_is_the_self_check`.

## Recorded runs (2026-10-23; flag on, `/ws`)

Every run is on the bench runner, `bench-runner` machine profile, loop `asyncio`, k6 v2.3.0, harness `e17-q03/1`.
Run ids are those of `perf-ws-load.yml`. "Valid" means no validity guard tripped; a valid run can still miss a budget.
"Round 2" is the set of dispatches of 22 Oct; "round 3" is the first set of 23 Oct; "quiet window" is the later set, 15:50 to 20:10 UTC.

| Profile | Run id      | `main` commit  | Finished (UTC)               | Valid  | Result                                                                                                                                                                                                                                                                                                                                    |
| ------- | ----------- | -------------- | ---------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B       | 39881322465 | `ede2113b87fb` | 02:04, 03:09, 04:15          | 0 of 3 | round 3, first leg: FAIL x3: the backend did not answer `/metrics` within 15 s in 7, 42 and 40 of 62 scrapes; also run 1: no re-snapshot sample, 9 unplanned closes; run 2: feeder behind its schedule (1,361,196 of 1,912,379 slots), 2 `cv_errors`; run 3: feeder behind its schedule (1,372,032 of 1,921,400 slots), 1 unplanned close |
| A       | 39740753214 | `362590b9371e` | 08:34, 09:39, 10:45 (22 Oct) | 2 of 3 | round 2: every budget met in all three (fan-out p95 15.4, 13.7 and 14.8 ms; trades tick-to-decode p95 37, 34 and 33 ms); run 3 INVALID on the clock-skew guard then in force (18.0 ms by the max-over-hellos estimator); not a baseline, and not the code of round 3                                                                      |
| C       | 39900923629 | `c5e5aa3d4ff2` | 05:08, 05:44, 06:19          | 3 of 3 | round 3: budgets missed (fan-out p95, tick-to-pixel p95); bench quiet, host not quiet: not attributable to the code                                                                                                                                                                                                                       |
| W5      | 39912100280 | `31dde330f071` | 07:46 (10 phases)            | n/a    | round 3: `no_data` on the rule then in force; re-judged offline above                                                                                                                                                                                                                                                                     |
| A       | 39950162313 | `d0d43743b2c7` | 13:06, 14:11, 15:17          | 3 of 3 | round 3: budgets missed in all three runs (above), under contention                                                                                                                                                                                                                                                                       |
| C       | 39981663972 | `13c5a83ca630` | 16:26, 17:01, 17:36          | 3 of 3 | quiet window: budgets missed in all three runs (fan-out p95, tick-to-pixel p95); bench quiet, host not quiet: not attributable to the code (see the caveat under the budget table)                                                                                                                                                        |
| W5      | 39997358579 | `4cc2f502f954` | 18:57 (10 phases)            | n/a    | quiet window: `no_data` (one phase left out by the clock-skew check); same answer with that check waived offline                                                                                                                                                                                                                          |
| A       | 40007981025 | `1b69803c3d3e` | 20:06                        | 1 of 1 | quiet window, host quiet: PASS, every budget met; the run behind the baseline                                                                                                                                                                                                                                                             |

An earlier A dispatch of round 3 (run 39928968295) was cancelled at 11:25 UTC by a service restart on the bench
runner and left no artefact. The quiet window's first A dispatch (run 40007634911, three runs) was cancelled at once
and re-dispatched with one run. An earlier round's A run (39666312188) was INVALID in all three runs on the
clock-skew guard, which a later change corrected; it is not a reading. The `variance.other_cores` field reads 5.5,
5.9 and 5.7 for round 3's A runs, 6.2, 6.2 and 5.9 for round 3's C, 5.7, 5.7 and 6.1 for the quiet-window C, 5.9, 5.9 and 6.0
for round 2's A runs and 3.0 for the quiet A run. No CPU quota was applied (`cgroup` `none`; the backend was held by cpuset 0-3
only), so there is no quota counter to read: the host was shared and the harness cannot see by whom. Since round 2's A runs
read about 6.0 and passed, the field does not by itself separate a passing run from a missing one.

**Baseline.** `runner record` wrote `services/api/bench/baselines/e17/A.json` from the quiet A run (40007981025):
`harness_version` `e17-q03/1`, `gate` `warn-only`, `run_profile` `full` (steady 3600 s), loop `asyncio`, `main` at
`1b69803c3d3e`. It is a first reading, not a gate: promoting it to `gated` needs a second same-profile run
(06 7.4) in its own reviewed change. B and C have no PASS run, so they have no baseline: the runner's record refuses a run that is not PASS, and nothing is
written by hand. Their numbers are shown beside A's baseline for comparison only, and the 5 % gate (C-13.9) is unchanged.

| Row                      | A baseline (warn-only) | B, median of 3 (FAIL x3) | C, quiet-window median of 3 |
| ------------------------ | ---------------------- | ------------------------ | --------------------------- |
| Fan-out p95              | 11.8 ms                | 250 ms (top bucket) †    | 28.8 ms                     |
| Tick to decode p95 / p99 | 25 / 48 ms             | 8,237 / 9,756 ms         | 43 / 125 ms                 |
| Bandwidth                | 8.9 KiB/s              | 2.8 KiB/s                | 8.8 KiB/s                   |
| Full re-snapshot         | 15.8 KiB, 79 ms        | 15.8 KiB, 48,798 ms      | n/a (no probe)              |
| Event-loop lag p95 / p99 | 22.8 / 58.2 ms         | 1,000 / 1,000 ms †       | 56 / 191 ms                 |

† From the scrapes that answered.

## Harness validation runs (not budget results)

Short runs on this laptop (i7-13850HX, WSL2) that show the harness works end to end at the code of this change.
They are not the recorded profiles: each is a shortened window, so each is labelled `smoke` and can never be a
baseline. The backend ran in the systemd scope on cpuset 0-7 and k6 on 8-15, flag on unless said, with the machine
shared with other work (between 0.5 and 1.8 cores busy outside each run, the W5 phases included). Each run's artefacts (`report.md`,
`result.json`, the k6 summary, both scrapes) are what `runner` writes; none is committed.

**Profile A, the `smoke` profile**, run with `--duration-s 75 --warmup-s 12` (its own are 120 s and 20 s): 5 users x
28 topics, verdict PASS.

| Row                                                       | Measured                                                           |
| --------------------------------------------------------- | ------------------------------------------------------------------ |
| Fan-out p95 (budget 6)                                    | 0.63 ms (100 % of 1,135 sampled frames at or under 20 ms)          |
| Tick to decode p95, throttle wait excluded (budget 3)     | 9 ms                                                               |
| Tick to decode p95, throttle wait included                | 95 ms (the 100 ms trades window, as designed)                      |
| Bandwidth, reference workspace, max 60 s window           | 8.9 KiB/s                                                          |
| Full re-snapshot (book, trades, bars; no footprint frame) | 8.8 KiB in 4 ms                                                    |
| Sequence gaps, backpressure resyncs                       | 0, 0                                                               |
| Connections authenticated, frames, in-place re-auths      | 6 of 6 planned, 36,210, 12 (token renewed over the refresh double) |
| Backend CPU (feeder included), RSS                        | 0.14 core, 184 MiB                                                 |
| k6's CPU, share of its cpuset                             | 1.6 %                                                              |
| Frames carrying `sp`                                      | 3.1 % (about 1 in 32)                                              |

The including-the-wait variant misses the 40 ms local line by design with the flag on: 95 ms against 9 ms excluding
the wait. A flag-off control of the same shape (45 s; INVALID only because no 60 s bandwidth window fits in it) reads
1 ms in both variants, so nothing is held there.

**Self-check** (a 25 ms ASGI send delay inside the fan-out span, 65 s window after 20 s): verdict FAIL, naming
`budget6.cv_ws_fanout_seconds.p95` (0.0 % of 371 sampled frames at or under 20 ms; p95 above the top 250 ms bucket),
`budget3.tick_to_decode.trades.p95` and `.p99` (about 40 s, a queue backed up behind 25 ms sends),
`s16_3.tick_to_pixel.p95`, and the server's own ladder: 135 backpressure re-snapshots and 135 drops. Zero sequence
gaps: each ladder re-snapshot re-baselines the client. `runner selfcheck` reports OK because the named check failed.

**A dry run of the whole W5 plan** (`runner w5 --duration-s 30 --warmup-s 10`: 10 phases in one process, about 9
minutes). It exits 0: the three mixed phases are valid and each ran in the class its `pong` delay set (healthy,
lagging and saturated all announced, the lagging class seen end to end), and `w5.json` is written with a three-row
table. Of the seven other phases two (`trades-healthy`, `trades-saturated`) are valid and five ended INVALID, all
five for want of a trades sample (the verdict reads trades latency and they subscribe none; the idle phase has no
frames at all, so it also trips `fanout_samples`); `bars-saturated` also tripped `fanout_samples` (35 sampled frames
of the 40 needed on a 30 s window) and `clock_skew` (7.0 ms against 5). `analyze` reads their CPU whatever tripped,
so a CPU number can sit behind a guard that is not INVALID by construction. On 30 s windows the recommendation is
not a W5 result; the run shows that the phase loop, the analysis and the exit code work before the hour of recorded
phases. Release-to-decode does not follow the class (under about 30 ms in every phase, and not ordered by it), while
the staleness the rule prices grows with the window (p95, ms, mixed phases):

| p95, ms                                          | healthy (x1) | lagging (x2) | saturated (x4) |
| ------------------------------------------------ | ------------ | ------------ | -------------- |
| Book, interval between releases (`cv_hold_ms`)   | 52           | 102          | 202            |
| Bars, interval between releases                  | 252          | 502          | 1,002          |
| Trades, oldest print to decode                   | 94           | 196          | 380            |
| Trades, release to decode (what was read before) | 3            | 15           | 1              |
| Book, release to decode                          | 8            | 11           | 12             |
| Bars, release to decode                          | 1            | 30           | 1              |

**Shape checks of B and C** (75 s windows, not the recorded profiles): B admitted every topic of its 8 connections and
the probe (9 connections up, no refusal, no error, no gap, 238,746 frames), with fan-out p95 2.5 ms, 0.59 backend
core and 221 MiB, k6 at 7 % of its cpuset, and a full re-snapshot of 8.8 KiB in 51 ms; verdict PASS. C passed (16
topics, 5 users, 28,344 frames, fan-out p95 0.76 ms).

### What the harness runs surfaced

- **Footprint leases a bar series too** (found when A's first run had its topics refused `subscription_limit`): the 8
  distinct series per user bind bars and footprint together, which no document states.
- **A short window cannot judge a 60 s or 5 min row.** The bandwidth row needs one 60 s window and the re-snapshot
  row one probe round in the steady window, else the run is INVALID, never a pass (W5 reads bytes off counters and
  leaves the bandwidth window out).
- **The flag-on throttle** puts tick to decode near 100 ms by construction (above), the reason `gate_on` is a
  parameter. The recorded runs decide which variant is the budget; both are in every report.
- **Release-to-decode is blind to a window.** The saturated cohort above waits 4 times as long in every family and
  the release-to-decode reading does not follow the class, which is why W5 prices the wait itself.
