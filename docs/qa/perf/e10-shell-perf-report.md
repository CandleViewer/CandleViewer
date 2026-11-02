# E10 shell perf report (E10-Q04, #303)

Status: **skeleton, recording only (R0, `30` §4.4). No CI run of `perf-shell.yml` exists yet, and
the attended reference run is owed (BQ-Q04-11).** PR-5 adds the first green `main` numbers and
commits the baselines. No figure below is a reference-class verdict; none is invented, and every
run that exists is listed.

## What was run, and what was not (PR-1 to PR-4, 2026-11-01)

| Item                                                    | Ran where                                                            | Result                                                                                            |
| ------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Unit tests: marks, report maths, stub backend, set fold | dev VPS (vitest)                                                     | pass                                                                                              |
| Electron cold start (`cold-start.perf.ts`, electron)    | **never ran on the dev host** (no display, no Chromium deps)         | first run: `perf-shell.yml` nightly or dispatch                                                   |
| Browser cold start (`cold-start.perf.ts`, browser)      | dev VPS, PR-2 smoke, 1 set × 10 cold launches, host below-class      | p95 1 996.7 ms; recorded only, not a verdict (one set, below-class host, not the 3 × 10 protocol) |
| Route, rail and chip benches                            | not run on the dev host (no Chromium in the PR-3 and PR-4 worktrees) | first run: `perf-shell.yml` on its own PR                                                         |
| `cv-bench-01` dispatch job                              | never ran (dispatch from `main` only, after merge)                   | unverified: needs `xvfb-run` and a usable Electron sandbox on that host                           |
| Palette filter (`packages/ui` `test:perf`, AC5)         | dev VPS, loaded (load average about 29 on 8 cores)                   | **over budget**: p50 79-92 ms, p95 154-248 ms vs `budget(16)` = 23.3 ms, all three attempts       |
| Reference-class run (Windows Electron build, #220 rule) | not run                                                              | **owed** (BQ-Q04-11 A): needs the owner's laptop; AC6 and the DoD reference line stay open        |

## How CI records

- `.github/workflows/perf-shell.yml`: per PR on the shell paths, headless Chromium (browser cold
  start, then the route, rail and chip benches); nightly and on dispatch, Electron under `xvfb-run`
  and the palette budget. Not a required check.
- Cold start: 3 sets of 10 cold launches, one discarded priming launch per set ("app-cold,
  OS-warm"). `apps/desktop/scripts/perf-sets.mjs` records the median of the three p95s (06 §7.4)
  and, as the trend, the median of the three p50s, with each set's spread (max / min) and
  calibration. A trend 15 % or more above the baseline is flagged, never failed. A missing report
  or a harness error turns the job red.
- CI numbers are never compared with the budgets (Electron 3 000 ms, browser 4 000 ms): the
  verdict is a reference-class run's, read with the #220 evidence rule.
- Reports: the JSON and markdown of each set, the set fold and the chrome benches, uploaded as
  artefacts (7-day retention).

## Budgets

| Budget                       | Source          | Gated | Measured p50 / p95 | n           |
| ---------------------------- | --------------- | ----- | ------------------ | ----------- |
| Electron shell cold start    | `06` §2 row 10  | no    | owed (PR-5)        | 3 × 10      |
| Browser shell cold start     | `20` (4 000 ms) | no    | owed (PR-5)        | 3 × 10      |
| Route change (seven routes)  | SCR-010         | no    | owed (PR-5)        | 20 a route  |
| Rail transition (≤ 120 ms)   | SCR-011, D04    | no    | owed (PR-5)        | per mode    |
| Palette filter (≤ 16 ms p95) | SCR-012, AC5    | no    | dev VPS: see above | 100 strokes |

## Findings and deviations

- **Palette filter over budget (AC5, component level).** CMP-059's `fuzzyRank` over 2 000
  synthetic labels misses `budget(16)` by 6-10 times on the loaded dev VPS. The nightly run on
  `ubuntu-latest` is the evidence; if it confirms, a defect is filed against CMP-059's owner (AC6:
  a manual step). Q04 measures and does not optimise (ticket Out of scope). SCR-012 itself is
  descoped to E15, which re-measures on its precomputed index.
- Multi-window GPU warning: out of scope (SCR-027 descoped to E15; E10-T03 owns windows).
- `session.account_scope_changed` and `workspace.opened` (#304 carry): out of scope, no perf
  meaning; their producers are E27 and E15.

## Follow-up (note only)

- **Grafana:** emitting `shell_cold_start_ms`, `shell_bootstrap_ms`, `shell_route_change_ms` and
  `palette_filter_ms` to the E04 pipeline is an OpenAPI change (`FrontendTelemetry` is closed) plus
  server histograms. A follow-up Task against E04-T06 (the telemetry owner) is to be filed; the
  marks already use the metric names verbatim, so that contract maps 1:1.
