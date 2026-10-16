# 81 — Pinned nightly gate triage (E50-C17, #579) — 2026-10-16

**Subject.** `.github/workflows/xstate-nightly.yml`, job `xstate-nightly-pinned`. It was red on all
12 scheduled runs from 2026-10-04 to 2026-10-15, and each run filed a new issue (#1808, #1840, #1928,
#2021, #2073, #2113, #2180, #2220, #2253, #2326, #2364, #2472). The pin did not move:
`xstate-statemachine==0.9.1`, wheel sha256 `d832d4d9…2687162`; `check_pin.py` and `uv sync --frozen`
were green every night.

**Method.** I downloaded the `xstate-gate-pinned` artifact of all 12 runs (`gate-result.json`,
`bench6.json`, the report) and diffed every row against the committed baseline
`gate/result-v0.9.1.json`. I re-ran the comparator, old and new, on each artifact. The disputed rows
were reproduced locally on Linux, Python 3.12.12, with the pinned wheel and an upstream checkout of
tag `v0.9.1` (commit `801eacd`).

## 0. Answer

**Why exit 1.** `tools/statechart/nightly_gate.py --mode pinned` exits 1 in only two cases:

- a blocking row (a non-`repro` FAIL, or any ERROR) is not a blocking failure in `result-v0.9.1.json`;
- the dedicated BENCH-6 step reports p99 > 100 ms at 500 busy machines.

The second never happened: p99 was 19.7–50.9 ms. SKIP-ENV rows, `COVERAGE LOSS` lines and "baseline
failures now passing" never change the exit code. So every red night came from the regression list
alone. That baseline was recorded once, on Windows with Python 3.13.7, **without benchmarks**
(`benchmarks_run: false`). Any bench row that is not PASS is therefore automatically "new".

**What the list held.** Since #1962 (2026-10-07) it has always been `bench:BENCH-2`, `bench:BENCH-6`,
`verifyM4:174` and `verifyM5:174`. On 4 of those 9 nights it also held `bench:BENCH-1`. The runs of
10-04 to 10-06 also carried the 15 hard-coded-path failures that #1962 fixed.

**No item is a 0.9.1 behaviour regression (class e).** The pin did not move, and §2 explains each item
with evidence.

**Result.** With this change the 2026-10-15 artifact comes out **GREEN**. It is excused only by the
three rows with a written justification and by the BENCH-6 double count. Of the 9 post-#1962 nights,
5 come out green. The other 4 stay **red on BENCH-1 alone**, which needs an owner decision (§5).

## 1. Per-night evidence

"Old" and "new" are the comparator on `main` and on this branch, run on the same artifact.

| Night      | Run         | BENCH-1 (≥ 3.0×) | BENCH-2 (≥ 2,000 ev/s) | BENCH-6 step p99 (max) | Old regressions | New regressions | New verdict |
| ---------- | ----------- | ---------------- | ---------------------- | ---------------------- | --------------- | --------------- | ----------- |
| 2026-10-04 | 37193306380 | 2.91             | 571                    | 50.5 (50.9) ms         | 20              | BENCH-1 + 15    | RED         |
| 2026-10-05 | 37296638248 | 4.12             | 785                    | 36.3 (36.6) ms         | 19              | 15 path rows    | RED         |
| 2026-10-06 | 37448864756 | 3.43             | 601                    | 40.3 (40.5) ms         | 19              | 15 path rows    | RED         |
| 2026-10-07 | 37606269663 | 2.80             | 578                    | 50.9 (51.2) ms         | 5               | BENCH-1         | RED         |
| 2026-10-08 | 37764458920 | 3.51             | 610                    | 40.2 (40.3) ms         | 4               | none            | GREEN       |
| 2026-10-09 | 37918393752 | 3.12             | 584                    | 46.5 (47.3) ms         | 4               | none            | GREEN       |
| 2026-10-10 | 38042843878 | 2.75             | 569                    | 50.1 (51.2) ms         | 5               | BENCH-1         | RED         |
| 2026-10-11 | 38130402959 | 3.96             | 771                    | 38.4 (40.0) ms         | 4               | none            | GREEN       |
| 2026-10-12 | 38238787532 | 2.92             | 589                    | 48.9 (49.0) ms         | 5               | BENCH-1         | RED         |
| 2026-10-13 | 38384515742 | 2.95             | 584                    | 48.0 (48.6) ms         | 5               | BENCH-1         | RED         |
| 2026-10-14 | 38537131725 | 7.47             | 1,195                  | 19.7 (19.9) ms         | 4               | none            | GREEN       |
| 2026-10-15 | 38704697721 | 4.19             | 783                    | 28.7 (29.0) ms         | 4               | none            | GREEN       |

The "15 path rows" were `verify:LC-39`, `verify:LC-53`, `verifyM3:142/144/145/146`, `verifyM4:166`,
`verifyM7:210`, `verifyM9:220`, `verifyM:LC-37#2`, `verifyM:LC-52`, `verifyM:N-2`, `verifyM:N-4`,
`verifyV090:229` and `verifyV091:248`: owner-specific paths, removed by #1962 (diagnosis on #1928).

From 10-07, 13 rows are SKIP-ENV every night. 9 of them are `COVERAGE LOSS`: they passed in the
baseline. `run_gate`'s own `bench:BENCH-6` row is ERROR on every night (§2).

BENCH-7 shows the runner itself changing: about 47–64 k ev/s on most nights, but 106 k and 79 k on
10-14 and 10-15.

## 2. Classification

Classes: **(a)** env/harness · **(b)** bench variance on shared runners · **(c)** documented
behaviour that the baseline does not encode · **(d)** stale repro · **(e)** real regression (none
found).

| Row                                                                                       | Class | Evidence                                                                                                                                                                                                                                                                                                                                               | Fix on this branch                                                                                                                                                                                                      |
| ----------------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bench:BENCH-6` (the `run_gate` row)                                                      | (a)   | ERROR every night. From 10-07 it reads `metric summary_by_busy_level.500.p99 not found`; before that, the hard-coded path. `bench_c_timers_v2.py` prints one bare JSON document, but `run_gate.py` only parsed `=== name ===` blocks, so this row could never read its metric. The dedicated step on the same nights: p99 19.7–50.9 ms, within budget. | `run_gate.parse_bare_json` fallback: run locally, the row reads p99 25.3 ms and PASSes. `nightly_gate` judges BENCH-6 once, from `--bench`, and reports the `run_gate` row as superseded.                               |
| 13 SKIP-ENV rows (9 `COVERAGE LOSS`)                                                      | (a)   | The runner had no `_upstream/.venv-main` and no `_upstream/.venv-gate`, so every script needing them exited 77. `XSTATE_SRC` already resolves to the `_upstream` checkout; the venvs were the missing piece.                                                                                                                                           | The workflow builds both venvs: the pinned wheel (sha256 from `services/api/uv.lock`), plus upstream's `test` group from the tag's own `uv.lock`, all with `--require-hashes --no-build`. Locally all 13 rows run (§4). |
| `bench:BENCH-2`                                                                           | (c)   | 569–1,195 ev/s against 2,000. The owner decision of 2026-09-24 (header of `29-statechart-adoption-plan.md`) calls this "permanent". `79-r14-final-readiness-verdict.md` §0 and §9 record it as architectural and as the reason for row 8, not row 9. The study machine read 380.9 ev/s.                                                                | `KNOWN_DELTAS` entry, which excuses FAIL only. The threshold is unchanged and the row is still reported. BENCH-7 stays the hot-path regression guard.                                                                   |
| `verifyM4:174`, `verifyM5:174`                                                            | (d)   | Deterministic: FAIL on all 12 nights and in 2 of 2 local runs. Only criterion [2] fails, as §3 shows. Criterion [2] measures the Windows timer tick, not the library.                                                                                                                                                                                  | `KNOWN_DELTAS` entries, which excuse FAIL only. The proposed rewrite of criterion [2] is in §5.                                                                                                                         |
| `bench:BENCH-1` (FAIL on 10-04, 10-07, 10-10, 10-12, 10-13)                               | (b)   | 2.75–7.47× across nights. The 5 failures sit at 2.75–2.95×, just under 3.0×. `bench1-idle-rerun-p3-g4.md` rules that a BENCH-1 taken on a loaded host is "inconclusive, not a pass". `79-r14` §9 says a sub-3.0× reading leaves the decision at row 8 (CV-C13: the order lane is on a dedicated loop regardless).                                      | **None.** How to gate BENCH-1 on a shared runner is an owner decision (§5).                                                                                                                                             |
| `verify:LC-26` ("baseline failure now passing" on 10-14 and 10-15); `repro:LC-26` flaps   | (b)   | LC-26 asserts timer lateness ≤ 50 ms under 100 busy interpreters. It passes only on the two faster-runner nights (BENCH-7 above). It never gates.                                                                                                                                                                                                      | None.                                                                                                                                                                                                                   |
| Log lines `SUPERSEDED-BY-#222`, `STALE REPRO, FIX CONFIRMED (#220)`, `RETIRED (round 11)` | (d)   | `run_gate.report_retired_scripts()` prints the `RETIRED_OR_REWRITTEN` register. Those scripts live under `issues/post-c78ce99/` or carry a `_` prefix, so the gate never runs or counts them.                                                                                                                                                          | None; already registered (amendment 21).                                                                                                                                                                                |

`verifyM2:79` and `verifyM6:197` ("timing-sensitive" on #1928 and item M) **passed on all 12 nights**.
They differed only in one local re-run on 2026-10-06. Neither they nor 174 is flaky in CI, so C-9.3
quarantine does not apply.

## 3. #174 in detail

Both scripts exit 0 when #174 is still exactly as documented: the docs state it, and the behaviour is
unchanged. They exit 1 when the docs are missing or the behaviour has changed. Local Linux run on the
pinned wheel, 2026-10-16:

| Criterion                                                             | `verifyM4:174` (221ce7c script) | `verifyM5:174` (6db65d8 script) |
| --------------------------------------------------------------------- | ------------------------------- | ------------------------------- |
| [1] `production-characteristics.md` documents #174                    | True                            | True                            |
| [2] busy-loop `after: 50` misses by > 15 ms                           | **False** (1.1 ms late)         | **False** (0.4 ms late)         |
| [3] `after: 100` beside a 500 ms plain-`def` service fires at ~500 ms | True (502 ms)                   | True (503 ms)                   |
| [4] the same beside an `async def` service fires on time              | n/a                             | True (102 ms)                   |

Criterion [2] is the stale part.

- **Upstream says the busy loop is fixed.** The upstream CHANGELOG, 0.9.0 section (line 520 at the
  tag), reads: "#174 re-measured on the fixed tree: `after: 50` under a 100-event busy loop … is 0–1 ms
  late". Only the plain-`def` half stays documented-only.
- **Our own r8 note agrees.** `issues/verify-main-6db65d8/174.result.md` says the same: the busy-loop
  case improved to 0–1 ms.
- **The study machine passes for a platform reason.** It still passed [2] because Windows delivers
  timers on a ~15.6 ms tick. `20-adoption-gate.md` §3 already calls that tick "a platform floor, not
  the library's fault" (BENCH-5). Every recorded Windows result agrees: PASS for `verifyM4:174` from
  `6db65d8` to `801eacd` (7 results) and for `verifyM5:174` from `f28719c` (6 results).
- **Linux shows what upstream documents.** The runner delivers the same timer 0.4–1.1 ms late.

The row's citation and its assertion disagree, which is a defect in the row (standing amendment 15).
It is a superseded oracle, not a regression (amendment 21). The library still behaves as #174's
documentation says: [1], [3] and [4] hold.

Side note: `run_gate.py`'s comment on `VERIFYM5_BASELINE_FAILURES` calls 174 an "expected FAIL". The
script's own convention (exit 0 = documented-only, confirmed) and every recorded result say PASS.
That comment should be corrected when the row is rewritten.

## 4. What this branch changes

- **`.github/workflows/xstate-nightly.yml`.**
  - **New step: upstream dev venvs.** It builds `_upstream/.venv-main` and `_upstream/.venv-gate`.
    Both get the pinned wheel, and `.venv-main` also gets upstream's hash-locked `test` group.
  - **Local proof of the recipe.** I ran the same recipe locally, with the same `--only` set and
    `--no-secondary`. All 13 rows that were SKIP-ENV ran:
    - the 9 `COVERAGE LOSS` rows PASS (`verify:LC-53`, `verifyM3:142/144/145/146`, `verifyM4:166`,
      `verifyM7:210`, `verifyM:LC-52`, `verifyM:N-4`);
    - `verify:LC-57` and `verifyM:N-8` FAIL, as in the baseline;
    - `verifyM4:167` and `verifyM5:167` PASS. The baseline has them as FAIL; `79-r14` §2 calls row
      167 a load-flake. They will show under "baseline failures now passing", which never gates.
  - **Least privilege.** The gate job drops `issues: write`. A new `notify` job holds that permission
    alone, runs no checkout and no third-party code, and comments on the open tracker issue. It files a
    new issue only when none is open.
  - **Credentials.** All checkouts set `persist-credentials: false`.
- **`tools/statechart/nightly_gate.py`.**
  - **`KNOWN_DELTAS`.** Three entries, each excusing exactly one status (FAIL), each with one
    justification line. Any other status of those rows is judged normally. If a row stops showing its
    documented status, the report prints a `DRIFT` line.
  - **BENCH-6 judged once.** When `--bench` is given, BENCH-6 is judged from it alone.
  - **Upstream mode unchanged.**
- **`docs/research/xstate/gate/run_gate.py`.** `parse_bare_json`, so `bench_c_timers_v2.py` output is
  read.
- **Tests.**
  - `scripts/tests/test_nightly_gate.py`: 8 new cases, 17 pass.
  - `services/api/tests/unit/statechart/test_xstate_gate_env_skip.py`: 3 new cases.
- **Docs.** This note and a log row in `80-upstream-liaison-log.md`.
- **Not yet on this branch: the E50-T04 implementation note in `29-statechart-adoption-plan.md` §1.7.**
  The one-line update is drafted, but the file is not prettier-clean on `main`. Committing it through
  the repo's `lint-staged` hook rewrites 278 lines of the binding plan, so it is left for decision 2.

**Unchanged:** the pin, `machine_hashes.lock`, every machine, every research script's assertions,
every threshold, and `result-v0.9.1.json`.

## 5. Decisions needed (owner or orchestrator)

1. **BENCH-1 on a shared runner.** This is item M, point 4 on #1778, never ruled. Options:
   - (i) run the pinned job on `CV_TARGET_HW_RUNNER`, which is the real fix (P3-G4 and P3-G6);
   - (ii) treat BENCH-1 as informational until that runner exists, citing
     `bench1-idle-rerun-p3-g4.md`;
   - (iii) apply `20-adoption-gate.md` §3 "take the better of three" in the harness.

   Until one is chosen, roughly 4 nights in 9 stay red on BENCH-1 alone, and they now comment on one
   tracker instead of filing issues.

2. **Accept the documented-deltas extension of the committed baseline.** It changes the verdict
   wording of `29-statechart-adoption-plan.md` §1.7 (CODEOWNER: architecture), which must change in
   the same PR (C-15.2). Choose how to land that one line: normalise 29 with prettier in its own
   `docs` PR first, or apply the drafted line where the hook does not reformat the file. Item M,
   point 3 (re-record the baseline on Ubuntu) then becomes optional. Re-recording would freeze one
   night's bench noise into the baseline.
3. **Rewrite criterion [2] of both 174 scripts** (amendment 21): report the busy-loop lateness but do
   not gate on it. The `KNOWN_DELTAS` entries can then be removed. Until then, a change in [1], [3] or
   [4] on Linux is hidden behind [2]'s FAIL.
4. **Close the 11 duplicate auto-filed issues** in favour of #2472 as the tracker.

## 6. Follow-ups (not on this branch)

- **#1965: pin `_upstream` by commit.** The tag `v0.9.1` is tag object `45bb7f3c…` and points to
  commit `801eacdeef5bda2ba24b75f537ae04cc3527747e`. The checkout now feeds two venvs and the upstream
  test run, so a moved tag matters more than before.
- **`bench_c_timers_v2.py` "p99".** It takes `sorted(vals)[int(0.99·n) − 1]`, which for n = 5 is the
  second-largest of 5, not the maximum. The nightly margin is ≥ 49 ms, so no verdict changes. Fix it,
  with a justification, before P3-G6 relies on the number.
- **The `upstream` job checks out no upstream tree**, so most env rows SKIP there: 38 SKIP-ENV on the
  0.11.0 run of 2026-10-14.
