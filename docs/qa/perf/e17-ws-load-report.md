# E17 WS load profiles and W5 report (E17-Q03, #568)

Status: **harness delivered; the recorded profile runs are pending.** The profiles, the fixture backend, the k6
client, the verdict, the baseline gate and the self-check are built and were validated on short runs (below).
Profiles A, B and C have not been run for their full durations, so no §16.3 budget has a recorded number yet and
W5 is not answered yet. No number in the budget tables of this file is invented: a row says `pending` until a
recorded run fills it. The recorded runs are made on the self-hosted bench runner `cv-bench-01` by the
dispatch-only workflow `.github/workflows/perf-ws-load.yml`, which must be on `main` before that runner can run
it; the follow-up that carries their numbers writes the W5 answer and the §16.3 column below. The W5 and §16.3
rows are ready to fill.

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
job `perf-pack-full`, the same runner) is queued or running: its first step refuses, rather than sharing a
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

## Budgets: the §16.3 column the Results PR writes (a recorded run fills it)

| Row                              | Source          | Target / hard fail      | Q03, flag on | Q03, flag off | Verdict |
| -------------------------------- | --------------- | ----------------------- | ------------ | ------------- | ------- |
| Fan-out add-on p95               | 06 #6, 23 §16.3 | <= 20 ms                | pending      | pending       | pending |
| Tick to decode p95 / p99, trades | 06 #3           | < 100 ms / < 250 ms     | pending      | pending       | pending |
| Tick to pixel, local, p95        | 23 §16.3        | < 40 ms / > 120 ms      | pending      | pending       | pending |
| Bandwidth, reference workspace   | 23 §16.3        | < 350 KiB/s / > 1 MiB/s | pending      | pending       | pending |
| Full re-snapshot, bytes and time | 23 §16.3        | < 700 KiB, < 400 ms     | pending      | pending       | pending |
| `upstream_desync` per topic-hour | 23 §16.3        | < 1 / > 5               | pending      | pending       | pending |
| Resyncs from backpressure, gaps  | ticket          | 0                       | pending      | pending       | pending |
| Event-loop lag p95 / p99         | C-14.2          | < 50 ms / < 100 ms      | pending      | pending       | pending |

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

**Recommendation: pending.** (keep the fixed x2 and x4, or per-family multipliers; the reasons the rule gave.)

| Family | Share of healthy bytes | Relief at x4 | Staleness cost | Efficiency | Merged updates per frame | Proposed (lagging, saturated) |
| ------ | ---------------------- | ------------ | -------------- | ---------- | ------------------------ | ----------------------------- |
| book   | pending                | pending      | pending        | pending    | pending                  | pending                       |
| trades | pending                | pending      | pending        | pending    | pending                  | pending                       |
| bars   | pending                | pending      | pending        | pending    | pending                  | pending                       |

| Backend CPU, core-seconds per second above the idle baseline | healthy | saturated |
| ------------------------------------------------------------ | ------- | --------- |
| book                                                         | pending | pending   |
| trades                                                       | pending | pending   |
| bars                                                         | pending | pending   |

Multipliers that adapt at run time, per topic, need a signal from the product (a separate design, not built
here). The recommendation and its numbers are handed to E17-T07 and written into 23 §16.6 W5 by the Results
PR after the recorded runs.

## Acceptance criteria

| AC  | How it is verified                                                                                                                   | State   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| 1   | Profile A, 1 h, flag on: rows #6 and #3 above                                                                                        | pending |
| 2   | Profile B, 1 h: every row above and zero backpressure resyncs                                                                        | pending |
| 3   | A bandwidth over 1 MiB/s fails the run with the metric named: `test_bandwidth_over_one_mib_a_second_fails_the_run_naming_the_metric` | pass    |
| 4   | W5 answered from data                                                                                                                | pending |
| 5   | A second same-profile run within 15 %, or a named variance source: `runner repro`                                                    | pending |

The self-check (an ASGI send delay inside the fan-out span must fail budget #6 by name) is
`runner selfcheck`; its offline twin is `test_an_inflated_fanout_fails_budget_6_which_is_the_self_check`.

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
