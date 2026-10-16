#!/usr/bin/env python
# -----------------------------------------------------------------------------
# run_gate.py -- CandleViewer adoption gate runner for `xstate-statemachine`
# -----------------------------------------------------------------------------
"""Run every check, probe and benchmark against an installed library version and
print a single pass/fail table.

Usage
-----
    <venv>/Scripts/python gate/run_gate.py                 # primary + secondary + probes
    <venv>/Scripts/python gate/run_gate.py --no-secondary  # primary + probes only
    <venv>/Scripts/python gate/run_gate.py --with-bench    # + benchmarks (slow)
    <venv>/Scripts/python gate/run_gate.py --only LC-01,LC-03
    <venv>/Scripts/python gate/run_gate.py --json out.json

Exit code
---------
    0  -- every BLOCKING check PASSED (primary set + probes + benches).
    1  -- at least one blocking check FAILED, or any check ERRORed.
    2  -- harness error (library not importable, paths missing, ...).

The two check sets -- read this before interpreting the table
-------------------------------------------------------------
From 0.8.0 the library fixes defects as **per-machine policies or additive APIs
whose default preserves the previous semantics**. One check set is therefore not
enough, and the exit code of a single script is not a verdict.

* **`verify` rows -- PRIMARY, BLOCKING.** `issues/verify-0.8.0/LC-xx_*.py`.
  These construct machines with the CandleViewer **mandated configuration**
  (`actionErrorPolicy`, `onUnhandled`, `guardErrorPolicy`, `strictTargets`,
  `strict`, a bounded inbox, an injected clock -- see
  `17-reeval-0.8.0-verdict.md` s.4) and answer the gate's real question: *with the
  configuration we are required to ship, is the defect gone?* A FAIL here is a
  genuine failure.

* **`verifyM` rows -- PRIMARY, BLOCKING.** `issues/verify-main-5327ba6/*.py`.
  The same contract, added by the `main` @ `5327ba6` verification pass
  (`22-verify-main-verdict.md`). These cover the issues re-verified in that
  window -- the `[Unreleased]`/0.8.1 fix wave (#27, #31, #37, #39/#75, #43,
  #44, #50/#76, #51, #52, #77, #78, #79, #80) -- and are kept as a separate,
  named set so a per-set regression is visible without diffing totals. Two
  scripts share the `LC-37` prefix; both run, disambiguated by file stem.

* **`verifyM2` rows -- PRIMARY, BLOCKING.** `issues/verify-main-3c527b0/*.py`.
  Added by the `main` @ `3c527b0` verification pass
  (`26-verify-3c527b0-verdict.md`), covering the three issues PR #83 closed
  (#43 one task per invoked child, #79 provenance-based system events, #80
  dedicated `ErrorEvent`). Same contract; kept as its own named, commit-keyed
  set per `20-adoption-gate.md` s.9.6 amendment 8, so a per-wave regression is
  visible without diffing totals. Baseline: 3/3 PASS -- ANY failure here is a
  regression.

* **`verifyM3` rows -- PRIMARY, BLOCKING.** `issues/verify-main-cec108b/*.py`.
  Added by the round-6 pass (`39-r6-final-readiness-verdict.md`), covering the
  26 issues verified on `main` @ `cec108b` -- the round-5 fix set #142-#162 plus
  the five narrow reopens #118/#122/#125/#133/#134. Same contract; own named,
  commit-keyed set. Baseline at cec108b: 24/26 PASS with exactly two expected
  FAILs (#122 PARTIAL -- documented rather than fixed; #157 NOT-FIXED as filed,
  reopened on narrower grounds). Any FAIL outside that pair is a regression.
  Round 7 (H-1) added `150` and `probe` to the expected set: both are pre-existing
  deterministic FAILs that appear in NO cec108b baseline JSON because the script
  directory gained those files after the allow-list was written. Confirmed 5/5
  deterministic and confirmed absent from `result-main-cec108b.json` by a direct
  check-by-check diff -- new rows, not PASS->FAIL transitions.

* **`verifyM4` rows -- PRIMARY, BLOCKING.** `issues/verify-main-221ce7c/*.py`.
  Added by the round-7 pass (`44-r7-final-readiness-verdict.md`), covering the
  12 issues verified on `main` @ `221ce7c` -- the round-6 fix set #166-#175 plus
  #157 and #122-as-designed. Own named, commit-keyed set. Baseline at 221ce7c:
  10/11 PASS with exactly one expected FAIL (#167 -- PARTIAL: bounded for plain
  `def` services, completely unbounded for `async def`; the coroutine half is
  R7-01). Any FAIL outside that is a regression.

  NOTE (round-7 standing amendment 12): a row that exercises an `invoke` and is
  NOT parametrised over service kind (`def` / `async def`) is not evidence. Our
  own round-6 confirmations declared `def` services and therefore confirmed a fix
  that does not hold on the lane our mandatory configuration requires.

* **`verifyM5` rows -- PRIMARY, BLOCKING.** `issues/verify-main-6db65d8/*.py`.
  Added by the round-8 pass (`49-r8-final-readiness-verdict.md`), covering the
  16 issues verified on `main` @ `6db65d8` -- the round-7 fix set #179-#190 plus
  the reopened #167/#168/#174/#175. Own named, commit-keyed set. Baseline at
  6db65d8: 15/16 PASS with exactly one expected FAIL (#174 -- DOCUMENTED-ONLY,
  no code changed, so the script correctly still reports the behaviour the
  documentation describes). Any FAIL outside that is a regression. Note that
  #167 PASSES in this set while it is allow-listed in the older `verifyM4` set:
  the sets are keyed on different commits on purpose and their allow-lists must
  not be merged.

  NOTE (round-8 standing amendment 13): a row that exercises a `send` and is NOT
  parametrised over issuer provenance (external vs issued from an action) AND
  chain state (untripped vs already tripped) is not evidence. R8-01 survived an
  upstream fix, a pinned upstream test and a full battle round because every
  existing test sent externally into an untripped chain. The general form of
  amendments 12 and 13: when a fix distinguishes two cases, the test must
  exercise both sides of the distinction -- and the arm expected to fail must be
  given work that can actually fail. A parametrised row whose arms are not
  equally capable of failing is not parametrised.

* **`verifyM7` rows -- PRIMARY, BLOCKING.** `issues/verify-main-19cb1f1/*.py`.
  Added by the round-10 pass (`59-r10-final-readiness-verdict.md`), covering the
  8 issues verified on `main` @ `19cb1f1` (merge of PR #211, commit `4dbf86e`)
  -- the round-9 fix set #203-#210. Own named, commit-keyed set. Baseline at
  19cb1f1: **8/8 PASS, NO expected failures.** Any FAIL is a regression.

  `203_*` and `204_*` are the load-bearing rows: they close round-9's two Highs
  (R9-02 `after` provenance, R9-04 SCXML s.6.1 `statesToInvoke`) on BOTH engines
  and BOTH service kinds, and their closure is what retires CV-C46 and CV-C45's
  send-side clause and what unblocks Phase-3 shim retirement. If either flips,
  reinstate both constraints before the order path runs.

  RETIRED FROM THIS SET (round 11): `206_delayed_selfsend_charged.py`. It
  asserts the #206 rule -- that a re-armed delayed self-send is charged per lap
  -- which **#212 deliberately reverses**. It was the SINGLE stable PASS->FAIL
  delta across the 163-check gate and the 527-script sweep at `c78ce99`, and it
  is category SUPERSEDED-BY-#212, not a regression. Left in place it becomes one
  permanent, meaningless blocking FAIL, which is how a reader is trained to
  ignore red. See `60-r11-regression.md` s.2 and `64-r11-final-readiness-verdict.md`
  s.2(b). The #212 rule is now asserted POSITIVELY by `verifyM8`'s `212_*` row.

* **`verifyM8` rows -- PRIMARY, BLOCKING.** `issues/verify-main-c78ce99/*.py`.
  Added by the round-11 pass (`64-r11-final-readiness-verdict.md`), covering the
  5 issues verified on `main` @ `c78ce99` (merge of PR #217, `fix/0.8.1-round10`)
  -- the round-10 fix set #212-#216. Own named, commit-keyed set. Baseline at
  c78ce99: **6/6 PASS, NO expected failures.** Any FAIL is a regression.

  Two SEMANTIC REVERSALS are pinned here, and both invert an earlier assertion:
  `212_*` pins that a `raise(delay=)` self-send is a TIMER (arming ends the
  step's chain; a self ping-pong of any period is legal periodic work), which
  SUPERSEDES #206; `213_*`/`214_*` pin snapshot layout **v3** with
  `scheduled_sends`, strict-on-restore, v2 upcast and `lane`. A future round
  that finds these rows failing must check whether the rule changed again before
  calling it a regression -- that is the whole lesson of the retired 206 row.

  NOTE (round-11 standing amendment 20): when a fix closes a constraint's
  ground, re-ground the constraint or retire it -- never carry it on the old
  justification. This set closed CV-C47's R10-03 ground (#212) and CV-C49's
  R10-04 ground (#213) in one release; CV-C47 was re-grounded on R11-04 and
  CV-C49 rewritten on R11-08, while CV-C48 retired outright.

  NOTE (round-10 standing amendment 16): a row asserting a SECURITY property
  must state the minimum capability it presumes and carry a CONTROL showing what
  that capability achieves WITHOUT the finding. Round 10 filed three
  Blocker/High candidates and all three fell to their own controls.

  NOTE (round-10 standing amendment 17): a row must demonstrate its own
  DISCRIMINATING POWER -- show the metric moving with the parameter it claims to
  bound. `209_*`'s paired `nested_invoke` shape never exits its initial state,
  so it agrees across all three lanes because a constant agrees with itself.

* **`verifyM6` rows -- PRIMARY, BLOCKING.** `issues/verify-main-f28719c/*.py`.
  Added by the round-9 pass (`54-r9-final-readiness-verdict.md`), covering the
  12 issues verified on `main` @ `f28719c` -- the round-8 fix set #192-#201 plus
  the reopened #181/#186. Own named, commit-keyed set. Baseline at f28719c:
  11/12 PASS with exactly one expected FAIL (#197 -- genuinely PARTIAL, the
  R9-08 residual). Any FAIL outside that is a regression.

  NOTE (round-9 standing amendment 14): where a row exercises a TRUST MECHANISM
  it must enumerate every call site the mechanism is meant to govern, not sample
  one. R9-02 exists because #195 minted three private engine event classes and
  wired two of them into transition selection -- a row checking only
  `done`/`error` reports the fix complete. A restore-path row must additionally
  exercise the RAW SERIALISED RECORD, not only the deserialised class: R9-02's
  decisive vector carries no "engine" flag and never meets a `send()`-time check
  at all.

  NOTE (round-9 standing amendment 15): a row must cite the doc sentence or spec
  clause it enforces, and a row whose citation and assertion disagree is a defect
  IN THE ROW. Upstream shipped both failure modes in one release --
  `test_always_rollforward_matches_sync` pins the behaviour its own docs say
  cannot happen, and `TestAsyncRollbackRearmCycleBounded` fails ~80% of runs on
  CORRECT behaviour by reading a counter at 0.6s when the `def` lane converges
  at ~1.0s. Corollary, binding on our scripts: assert convergence by POLLING to
  convergence, never by sleeping a guessed interval.

* **`repro` rows -- SECONDARY, INFORMATIONAL.** `issues/repro/LC-xx_*.py`, the
  original 0.7.0 scripts, which exercise the library **defaults**. They answer a
  different and still-useful question: *what does an unconfigured caller get?*
  A FAIL here is expected and is NOT counted in the exit code. Triage each one
  into `unfixed` / `fixed-but-opt-in` / `stale repro` in writing before citing it
  (`20-adoption-gate.md` s.9.2).

Both sets use the same convention: **exit 1 == the defect is still present**,
**exit 0 == the defect is gone**. The gate reports `PASS` only on exit 0.

* **probes/p0x** always exit 0; they self-report `N/M PASS` on the last line
  and write `probes/results/*.json`. The gate parses that JSON and compares the
  set of non-PASS probe ids against the recorded baseline
  (`PROBE_BASELINE_FAILURES`, currently the 0.8.0 baseline). A probe that newly
  regresses is a FAIL; a probe that newly passes is reported as IMPROVED.
* **bench/** scripts print `=== name ===` + a JSON blob. The gate extracts the
  metrics named in THRESHOLDS below and applies the documented pass rule.

A standing caveat on BENCH-1: it must be read **with the mandated policy block
armed**, where `actionErrorPolicy="rollback"` costs ~22% throughput. See
`20-adoption-gate.md` s.9.1.

Baselines are the measurements recorded in `04-performance-concurrency.md`,
`05-semantics-probes.md` (0.7.0) and `13-reeval-0.8.0-bench.md`,
`14-reeval-0.8.0-probes.md` (0.8.0) on the study machine. Benchmark thresholds
are hardware-sensitive: re-baseline on the target host before trusting a
marginal bench verdict (see `20-adoption-gate.md` s.6).

The baseline is keyed on a COMMIT, not a version string
-------------------------------------------------------
`20-adoption-gate.md` s.9.4 amendment 6. The current baseline build,
`main` @ `5327ba6`, reports `__version__ == "0.8.0"` while its CHANGELOG targets
0.8.1 -- so the version string cannot distinguish it from the release it
supersedes. This harness therefore resolves the git commit of the installed
clone (`library_commit()`), prints it, records it in the JSON, and compares it
against `BASELINE_COMMIT`. The version string is still reported, but it is
never the identity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

from _paths import SKIP_ENV_EXIT

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
GATE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(GATE_DIR)  # docs/research/xstate
REPRO_DIR = os.path.join(ROOT, "issues", "repro")
VERIFY_DIR = os.path.join(ROOT, "issues", "verify-0.8.0")
VERIFY_MAIN_DIR = os.path.join(ROOT, "issues", "verify-main-5327ba6")
VERIFY_MAIN2_DIR = os.path.join(ROOT, "issues", "verify-main-3c527b0")
# Round-6 set. Added 2026-09-20 by `39-r6-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log for cec108b. Covers the 26 issues verified
# against `main` @ `cec108b` (round-5 fixes #142-#162 plus the five narrow
# reopens #118/#122/#125/#133/#134).
VERIFY_MAIN3_DIR = os.path.join(ROOT, "issues", "verify-main-cec108b")
# Round-7 set. Added 2026-09-20 by `44-r7-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log for 221ce7c. Covers the 12 issues verified
# against `main` @ `221ce7c` (round-6 fixes #166-#175 plus #157 and
# #122-as-designed).
VERIFY_MAIN4_DIR = os.path.join(ROOT, "issues", "verify-main-221ce7c")
# Round-8 set. Added 2026-09-21 by `49-r8-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log for 6db65d8. Covers the 16 issues verified
# against `main` @ `6db65d8` (round-7 fix set #179-#190 plus the reopened
# #167/#168/#174/#175).
VERIFY_MAIN5_DIR = os.path.join(ROOT, "issues", "verify-main-6db65d8")
# Round-9 set. Added 2026-09-22 by `54-r9-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log 9.14 for f28719c. Covers the 12 issues
# verified against `main` @ `f28719c` (round-8 fix set #192-#201 plus the
# reopened #181/#186).
VERIFY_MAIN6_DIR = os.path.join(ROOT, "issues", "verify-main-f28719c")
# Round-10 set. Added 2026-09-22 by `59-r10-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log 9.15 for 19cb1f1 (merge of PR #211, commit
# 4dbf86e). Covers the 8 issues verified against `main` @ `19cb1f1` -- the
# round-9 fix set #203-#210.
VERIFY_MAIN7_DIR = os.path.join(ROOT, "issues", "verify-main-19cb1f1")
# Round-11 set. Added 2026-09-22 by `64-r11-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log for c78ce99 (merge of PR #217,
# `fix/0.8.1-round10`). Covers the 5 issues verified against `main` @ `c78ce99`
# -- the round-10 fix set #212-#216, including TWO semantic reversals.
VERIFY_MAIN8_DIR = os.path.join(ROOT, "issues", "verify-main-c78ce99")
# Round-12 set. Added 2026-09-23 by `69-r12-final-readiness-verdict.md` s.10 /
# `20-adoption-gate.md` gate-run log for de2da4e (merge of PR #223,
# `fix/0.8.1-round11`). Covers the 5 issues verified against `main` @ `de2da4e`
# -- the round-11 fix set #218-#222.
#
# ONE BEHAVIOUR CHANGE lives in this set. #219 makes an in-step
# send(..., wait=True) on an action's own interpreter raise ReentrantWaitError
# instead of deadlocking, on BOTH engines. That is a BREAKING CHANGE for user
# actions. It broke NOTHING in this corpus -- 0 of 573 sweep scripts and 0 of
# 20 contract charts contain the shape -- but that is a property of CV-C25
# (no external send() from inside an action), not of the change. Before any
# future round adds a script here, lint it for the shape.
VERIFY_MAIN9_DIR = os.path.join(ROOT, "issues", "verify-main-de2da4e")

# Round 13: the v0.9.0 verification set. Keyed on the TAG, not a branch commit,
# because `v0.9.0` = 91bd979 is the released artefact and `main` @ e3a1f22
# differs from it only in `.github/workflows/publish.yml` (verified). These are
# the #225-#235 re-verification probes; all exit 0 on the tag.
VERIFY_V090_DIR = os.path.join(ROOT, "issues", "verify-v0.9.0")

# Round 14: the v0.9.1 verification set (#239-#248), keyed on tag v0.9.1 = 45bb7f3.
# `main` @ 801eacd is an empty merge over the tag (git diff v0.9.1..HEAD empty).
VERIFY_V091_DIR = os.path.join(ROOT, "issues", "verify-v0.9.1")
PROBE_DIR = os.path.join(ROOT, "probes")
BENCH_DIR = os.path.join(ROOT, "bench")

# -----------------------------------------------------------------------------
# Baseline identity -- COMMIT, not version string.
#
# `20-adoption-gate.md` s.9.4 amendment 6. The baseline build reports
# `__version__ == "0.8.0"` while its CHANGELOG targets 0.8.1, so the version
# string is not an identity. Everything below keys on the commit.
# -----------------------------------------------------------------------------
BASELINE_COMMIT = "3c527b0d04c0d2d0ebb565af7e9e905f7178f620"
BASELINE_COMMIT_SHORT = BASELINE_COMMIT[:7]
BASELINE_LABEL = "main @ 3c527b0 (unreleased 0.8.1, merge of PR #83)"
BASELINE_REPORTED_VERSION = "0.8.0"  # what __version__ STILL says on that commit

# Recorded `verifyM` outcome on BASELINE_COMMIT (3c527b0): 12/15 PASS. Three
# expected FAILs, all triaged in writing in `26-verify-3c527b0-verdict.md` s.1.
# LC-28 and LC-52 PASSED on this commit (#43 and #80 landed) and were removed
# from the expected set -- a FAIL on either is now a regression. A verifyM FAIL
# on any id OUTSIDE this set is a regression and must be triaged in writing.
VERIFYM_BASELINE_FAILURES: list[str] = [
    "LC-07",  # #31 engine parity under strict_targets=False -- REOPEN
    "N-3",  # #77 runaway overflow still silent (drops+logs, does not raise)
    "N-8",  # #79 namespace-visibility sub-check; the reported defect is fixed,
    #         the residual is the ENGINE_EVENT_SHAPES name exemption (G-7)
]

# Recorded `verifyM2` outcome on BASELINE_COMMIT: 3/3 PASS. There is no expected
# failure in this set -- any FAIL is a regression against the commit that
# introduced these fixes.
VERIFYM2_BASELINE_FAILURES: list[str] = []

# Recorded `verifyM3` outcome on `cec108b` (round 6, 2026-09-20). This set is
# the 26 round-5 issue verifications. One id is an expected FAIL and is triaged
# in writing in `39-r6-final-readiness-verdict.md` s.1 -- a FAIL on any id
# OUTSIDE this set is a regression and must be triaged before deciding.
#
#   #157 -- NOT FIXED as filed, reopened on NARROWER grounds. The headline claim
#           (inbox bound bypassed, events accepted then lost) was refuted by our
#           own corrected repro: `_enqueue()` on the loop is authoritative and
#           refuses correctly. What survives is that a loop-side RAISE refusal
#           lands on a future fire-and-forget producers never read, with no log
#           and no `on_event_dropped` -- a hidden shed rate. Tracked as R6-05.
#
# NOT in this list, deliberately: **#122**. Its script here checks the criterion
# that actually landed (the documented `tick()` contract plus zero-delay and
# SimulatedClock ladder drains) and PASSES. The unmet criterion is the original
# RealClock real-delay-ladder repro, which lives in the repro set, not here. The
# issue is PARTIAL upstream; this row is green and a FAIL on it IS a regression.
# H-1 (round 7): `150` and `probe` added. Both are pre-existing deterministic
# FAILs (5/5) that appear in NO `result-main-cec108b.json` row -- the script
# directory gained `150_send_threadsafe_budgeted.py` and `probe_144_async*.py`
# after this allow-list was written, so they were new rows being misreported as
# regressions. `150` is the CHANGELOG's own documented residual (a
# default-argument `send_threadsafe()` from a plain `threading.Thread` is still
# unbudgeted); `probe` is `AssertionError: no RunawayChainError recorded`, named
# in `39-r6-final-readiness-verdict.md` s.2 as a pre-existing cec108b FAIL.
VERIFYM3_BASELINE_FAILURES: list[str] = ["157", "150", "probe"]

# Recorded `verifyM4` outcome on `221ce7c` (round 7, 2026-09-20). This set is
# the 12 round-6 issue verifications. One id is an expected FAIL, triaged in
# writing in `44-r7-final-readiness-verdict.md` s.1:
#
#   #167 -- PARTIAL. The plain-`def` invoked service is bounded (chain-budget
#           trip, ~1000 calls); the `async def` (coroutine) service is still
#           completely unbounded (~10-21k calls in 1-2 s, no charge) because its
#           completion is published on the public inbox lane
#           (`interpreter.py:2414`) and never reaches the charging site
#           (`:2287-2288`). Tracked as R7-01 (Blocker).
#
# NOT in this list, deliberately: **#175**. Its script here reports the
# NOT-FIXED Case D as a FAIL correctly, and that row is expected to stay FAIL
# until `stop()` resolves duplicate-`Event`-instance receipts -- but it is
# recorded as a defect row, not a baseline allowance, so it stays visible.
VERIFYM4_BASELINE_FAILURES: list[str] = ["167"]

# Recorded `verifyM5` outcome on `6db65d8` (round 8, 2026-09-21). This set is the
# 16 round-7 issues re-verified on that commit: #179-#190 plus the reopened
# #167/#168/#174/#175. Recorded baseline: 15 of 16 scripts exit 0.
#
# The single expected FAIL is **#174**, and it is expected BY DESIGN, not by
# concession: #174 was closed DOCUMENTED-ONLY -- no code changed -- so its script
# correctly still reports the behaviour it was written to detect (a plain-`def`
# service blocking its own machine's `after` timers, ~514 ms against a 100 ms
# budget). The documentation at `docs/_guide/production-characteristics.md:93`
# is the closure; the script is the evidence that the documentation is accurate.
# If this row ever flips to PASS, the behaviour changed and the docs are now
# stale -- triage it as a behaviour change, not as good news.
#
# NOT in this list, deliberately: nothing else. #167 PASSES here (it was the
# expected FAIL of the round-7 `verifyM4` set and is genuinely fixed at this
# commit, bounded at maxIterations+2 on both service kinds), so a FAIL on 167 in
# THIS set is a regression even though the same number is allow-listed in
# `VERIFYM4_BASELINE_FAILURES` for the older commit-keyed set. The sets are
# keyed on different commits on purpose; do not merge the allow-lists.
VERIFYM5_BASELINE_FAILURES: list[str] = ["174"]

# Recorded `verifyM6` outcome on `f28719c` (round 9, 2026-09-22). This set is the
# 12 round-8 issues re-verified on that commit: #192-#201 plus the reopened
# #181/#186. Recorded baseline: 11 of 12 scripts exit 0.
#
# The single expected FAIL is **#197**, and it is expected because the issue is
# genuinely PARTIAL, not because the script is stale. The library's own pinned
# property test passes, but the reporter's original `always` + nested-final +
# `after` chart still returns a success-shaped `send(wait=True)` receipt over an
# empty configuration (`ok: true` while `get_persisted_snapshot()` REFUSES with
# SnapshotMidStepError at the same instant). That residual is carried as R9-08
# (Medium). If this row flips to PASS, R9-08 is fixed -- verify against
# `issues/post-f28719c/new/repro/R9-08_*.py` before closing it.
#
# NOTE, deliberately: this script is STRICTER than the gate's own `verifyM5`
# cell for the same issue number, which PASSes. The round-9 regression sweep
# (`50-r9-regression.md` s.2) flagged the disagreement; triage resolved it in
# favour of THIS script -- it carries an assertion the older cell lacks, and the
# assertion is the genuine defect signal. Do not "fix" the disagreement by
# weakening this one.
VERIFYM6_BASELINE_FAILURES: list[str] = ["197"]

# Recorded `verifyM7` outcome on `19cb1f1` (round 10, 2026-09-22). This set is
# the 8 round-9 issues re-verified on that commit: #203-#210.
#
# Recorded baseline: **8 of 8 scripts exit 0 -- NO expected failures.** This is
# the first verification set in the study with a clean baseline, and that is a
# deliberate property, not an accident of scope: round 10 found every claimed
# fix landing on every axis it claimed (both engines, both service spellings).
# ANY FAIL in this set is a regression and must be triaged in writing.
#
# Two footnotes recorded so a later reader does not mistake them for slack:
#  - `209_*` sweeps two shapes and the paired `nested_invoke` one is INERT (it
#    never exits state `a`, fires exactly 2 calls at every limit 1-25 and can
#    never trip RunawayChainError). The discriminating `rollback_ondone` shape
#    carries the row. Standing amendment 17 -- do not read the second shape as
#    coverage, here or in the library's own tests/test_round9_findings.py.
#  - `207_*`'s reporter-side "failure" in the original report was under-waiting
#    after an async send(), not a regression. Poll to convergence.
VERIFYM7_BASELINE_FAILURES: list[str] = []

# Recorded `verifyM8` outcome on `c78ce99` (round 11, 2026-09-22). This set is
# the 5 round-10 issues re-verified on that commit: #212-#216, across 6 scripts.
#
# Recorded baseline: **6 of 6 scripts exit 0 -- NO expected failures.** Second
# consecutive verification set with a clean baseline, and as at round 10 that is
# a deliberate property: every claimed fix landed on every axis it claimed, both
# engines and both service spellings. ANY FAIL in this set is a regression and
# must be triaged in writing.
#
# Footnotes recorded so a later reader does not mistake them for slack:
#  - `212_*` pins the REVERSAL of #206. If a future round sees it fail, check
#    the CHANGELOG for another rule change BEFORE calling it a regression. The
#    retired `206_delayed_selfsend_charged.py` is the cautionary example.
#  - The five fixes are clean, but four carry SCOPE residuals that these rows do
#    NOT cover, because each is a defect in an ADJACENT surface rather than in
#    the fix: R11-06 (#215's descent gate hangs start() on a self-receipt
#    await), R11-07 (#216 checks the ROOT DICT ONLY -- 0/120 nested typos
#    caught), R11-08 (#213's records are dropped by restore->re-persist without
#    start()), R11-02/R11-10 (#214's strict check and its reporting do not reach
#    `scheduled_sends` / any plugin). A green verifyM8 is NOT evidence against
#    any of them; they are tracked in `63-r11-findings-register.md`.
VERIFYM8_BASELINE_FAILURES: list[str] = []

# Recorded `verifyM9` outcome on `de2da4e` (round 12, 2026-09-23). This set is
# the 5 round-11 issues re-verified on that commit: #218-#222, across 7 scripts
# (218 carries two, 221 carries two).
#
# Recorded baseline: **7 of 7 scripts exit 0 -- NO expected failures.** THIRD
# consecutive verification set with a clean baseline. ANY FAIL here is a
# regression and must be triaged in writing.
#
# Footnotes recorded so a later reader does not mistake them for slack:
#  - `219_*` pins a BREAKING CHANGE, not a bug fix. An in-step self-wait now
#    raises ReentrantWaitError on BOTH engines. If a future round sees this row
#    fail, check whether the guard's PREDICATE was narrowed (which is what
#    DE-L1 asks for) before calling it a regression -- a narrower predicate is
#    the requested outcome, and this row must then be rewritten, not reported.
#  - `222_*` pins the NEW sticky API (chain_trips / last_chain_error /
#    clear_chain_error / on_chain_budget_exceeded). `last_error` remains the
#    PER-STEP read it always was, BY DESIGN. Our own R11-09 repro tests the
#    oracle #222 retired and has been rewritten -- see RETIRED_OR_REWRITTEN.
#  - Only TWO residuals are not covered by these rows, and both are in an
#    ADJACENT surface rather than in the fix: DE-L1/Q-1 (#219's guard rides an
#    INHERITABLE ContextVar, so the documented ensure_future escape hatch is
#    refused whenever the spawning action yields again) and Q-5 (#220 does not
#    recurse into an inline-machine invoke.src). A green verifyM9 is NOT
#    evidence against either; both are tracked in
#    `69-r12-final-readiness-verdict.md` s.5.
VERIFYM9_BASELINE_FAILURES: list[str] = []

# -----------------------------------------------------------------------------
# OUR scripts RETIRED or REWRITTEN because an upstream rule change superseded
# the oracle they assert. Maintained as an explicit list, because the failure
# mode this guards against is a superseded test becoming a permanent,
# meaningless blocking FAIL that trains the reader to ignore red.
#
# The round-11 precedent worked: `206_delayed_selfsend_charged.py` was renamed
# with a `_RETIRED_` prefix, and round 12 spent ZERO triage on it.
# -----------------------------------------------------------------------------
RETIRED_OR_REWRITTEN: list[tuple[str, ...]] = [
    (
        "issues/verify-main-19cb1f1/_RETIRED_206_delayed_selfsend_charged.py",
        "RETIRED (round 11)",
        "SUPERSEDED-BY-#212. Asserts that a re-armed delayed self-send is "
        "charged per lap; #212 deliberately reverses that rule -- a "
        "raise(delay=) self-send is a TIMER. Excluded from all counts.",
    ),
    (
        "issues/post-c78ce99/new/repro/R11-09_chain_trip_erased_by_next_event.py",
        "REWRITE (round 12)",
        "SUPERSEDED-BY-#222. Asserts last_error still names RunawayChainError "
        "after one benign event; it still reports REPRODUCED: True on all "
        "three lanes, and that is now BY DESIGN -- #222 documents last_error "
        "as the per-step read it always was and moves stickiness to "
        "chain_trips / last_chain_error / on_chain_budget_exceeded. Rewrite "
        "against the LATCH; do not count the current FAIL.",
    ),
    (
        "issues/post-c78ce99/new/repro/R11-07_nested_config_typos_silent.py",
        "REWRITE (round 12)",
        "STALE REPRO, FIX CONFIRMED (#220). Builds {'states': {'a': "
        "{'entyr': ..., 'onn': ...}}} expecting SILENCE; de2da4e raises "
        "InvalidConfigError naming the path. It exits non-zero PRECISELY "
        "BECAUSE THE DEFECT IS GONE. Rewrite as a positive pin.",
    ),
]


def report_retired_scripts() -> None:
    """Print the retired/rewritten list so a red row is never miscounted."""
    print()
    print("[gate] --- OUR scripts retired or rewritten (superseded oracles) ---")
    for path, action, why in RETIRED_OR_REWRITTEN:
        print(f"  {action:<20} {path}")
        print(f"  {'':<20} {why}")


# Per-script timeout overrides (seconds), keyed by filename prefix.
#
# Added round 9. Two scripts in the f28719c set contain several 30-second sleep
# cells by construction (they must outlive a service that does not yield), so at
# the default timeout they report a spurious TIMEOUT/143. Both exit 0 cleanly
# when given enough wall time -- `50-r9-regression.md` s.2 recorded these as
# harness artefacts, not defects. `196_*` is additionally noisy by design (it
# logs expected RunawayChainError / microstep-exceeded lines); noise is not
# failure.
SCRIPT_TIMEOUT_OVERRIDES: dict[str, int] = {
    "195_provenance": 150,
    "196_always_vs_named_event": 150,
    "197_empty_config_wait": 150,
    # Round 10. `209_*` sweeps maxIterations 1-25 across three lanes and `210_*`
    # re-runs a pytest node five times to prove the convergence fix is not
    # flaky; both are wide by construction, not slow by accident.
    "209_lap_parity_sweep": 200,
    "210_test_converges_not_flaky": 200,
}


def timeout_for(path: str, default: int) -> int:
    """Return the per-script timeout, honouring overrides.

    Never shortens a caller-supplied timeout: an override only ever raises the
    bound, so `--timeout` on slow hardware still wins.
    """
    name = os.path.basename(path)
    for prefix, secs in SCRIPT_TIMEOUT_OVERRIDES.items():
        if name.startswith(prefix):
            return max(default, secs)
    return default


# H-2 (round 7): the `verify` set had no baseline-failure allow-list at all, so
# five unchanged pre-existing FAILs flagged on every run. All five were already
# FAIL at cec108b (confirmed by direct check-by-check JSON diff); LC-01 is the
# documented-superseded row (#145 deliberately changed the behaviour the script
# asserts). A `verify` FAIL outside this list is a regression.
VERIFY_BASELINE_FAILURES: list[str] = [
    "LC-01",  # asserts the pre-#145 status == "error"; the docstring is stale
    "LC-12",  # spawn blocking on the async engine
    "LC-26",  # after-timer starvation under load (BENCH-6 class)
    "LC-48",  # no error-observability hooks (its companion `repro` row passes)
    "LC-57",  # two engines duplicate the core algorithm
]

# Previous baselines, for history and for re-running against an older install.
PREVIOUS_BASELINES = {
    "5327ba6": "main @ 5327ba6 (unreleased, pre-0.8.1)",
    "9bf6065": "0.8.0 (released)",
    "42612cf": "0.7.0 (released)",
}

# -----------------------------------------------------------------------------
# Recorded 0.7.0 baseline: probe ids that do NOT pass. Kept for history / for
# re-running the gate against a 0.7.0 install. See PROBE_BASELINE_FAILURES
# below for the baseline actually used to evaluate the currently installed
# library version.
# -----------------------------------------------------------------------------
PROBE_BASELINE_FAILURES_0_7_0: dict[str, list[str]] = {
    "01_core_transitions": ["A3", "A5", "A6", "A10"],
    "02_invoke_timers_history": [],
    "03_context_snapshot_determinism": [
        "C6",
        "C7",
        "C10",
        "C15",
        "C16",
        "C17",
    ],
}

# -----------------------------------------------------------------------------
# Recorded 0.8.0 baseline: probe ids that do NOT pass.
# A regression = a probe id outside this set that stops passing.
#
# Reconciled against 0.7.0 in docs/research/xstate/14-reeval-0.8.0-probes.md:
#   - A5, C10, C16 newly PASS on 0.8.0 (legitimate fixes -- #36 internal event
#     queue for C10/raise ordering, #31 `.child` resolution fix + strict
#     targets for A5, #40 sendTo-by-id/systemId for C16) -- removed from the
#     baseline.
#   - A18 newly fails on 0.8.0: it encoded the OLD (silently-ignored)
#     behaviour for an unresolvable `.child` target. `strict_targets`
#     defaults to True in 0.8.0 (#29, #30), so the same config now raises
#     `InvalidConfigError` at create_machine time -- a deliberate `Changed`
#     behaviour, not a regression. Added to the baseline.
#   - A3, A6, A10, C6, C7, C15, C17 are unchanged, still-open defects.
# -----------------------------------------------------------------------------
PROBE_BASELINE_FAILURES: dict[str, list[str]] = {
    "01_core_transitions": ["A3", "A6", "A10", "A18"],
    "02_invoke_timers_history": [],
    "03_context_snapshot_determinism": [
        "C6",
        "C7",
        "C15",
        "C17",
    ],
}

# Verified UNCHANGED on main @ 5327ba6 (2026-09-18): the same eight ids, no
# regression and no improvement, so no baseline edit was warranted. Aliased
# explicitly so the current baseline is named by commit rather than inherited
# silently from the 0.8.0 run. See `20-adoption-gate.md` s.9.3.
PROBE_BASELINE_FAILURES_0_8_0 = PROBE_BASELINE_FAILURES
PROBE_BASELINE_FAILURES_5327BA6 = PROBE_BASELINE_FAILURES

# -----------------------------------------------------------------------------
# Benchmark pass thresholds (see `20-adoption-gate.md` s.5 for the rationale)
# -----------------------------------------------------------------------------
# Each entry: (bench script, human label, extractor key path, rule, threshold)
#   rule "ge" -> metric must be >= threshold
#   rule "le" -> metric must be <= threshold
THRESHOLDS: list[dict[str, Any]] = [
    {
        "bench": "bench_h_candleviewer_budgets.py",
        "id": "BENCH-1",
        "label": "Order path p95 headroom (submit->open, 500 bg machines)",
        "path": [
            "h_candleviewer_budgets",
            "budget1_submit_ack_latency",
            "budget_headroom_x",
        ],
        "rule": "ge",
        "threshold": 3.0,
        "unit": "x",
        "baseline_0_7_0": 1.81,
        "why": (
            "300 ms budget must be met with >=3x headroom so that a real Bybit "
            "round trip (50-150 ms) plus a burst still fits. 0.7.0 gives 1.81x "
            "-- engine-only, before any network I/O."
        ),
    },
    {
        "bench": "bench_h_candleviewer_budgets.py",
        "id": "BENCH-2",
        "label": "Rule-lifecycle event rate (market events/s, async)",
        "path": [
            "h_candleviewer_budgets",
            "budget2_rules_async_1000x10",
            "market_events_per_sec",
        ],
        "rule": "ge",
        "threshold": 2000.0,
        "unit": "ev/s",
        "baseline_0_7_0": 288.0,
        "why": (
            "100 rules x 10 symbols at 2,000 market ev/s == 200k rule evals/s. "
            "0.7.0 delivers ~30k evals/s => 288 market ev/s, 6.9x short. "
            "PASS here would remove the mandatory >=99% pre-filter (LC-40)."
        ),
    },
    {
        "bench": "bench_h_candleviewer_budgets.py",
        "id": "BENCH-3",
        "label": "500 open order machines -- memory per order",
        "path": [
            "h_candleviewer_budgets",
            "budget3_500_open_orders",
            "kb_per_open_order",
        ],
        "rule": "le",
        "threshold": 8.0,
        "unit": "KB",
        "baseline_0_7_0": 1.08,
        "why": "Quiescent order machines must stay cheap. 0.7.0 passes at 1.08 KB.",
    },
    {
        "bench": "bench_b_many_interpreters.py",
        "id": "BENCH-4",
        "label": "10k interpreters -- RSS ceiling",
        "path": ["b_10000_interpreters_notrace", "rss_peak_mb"],
        "rule": "le",
        "threshold": 1200.0,
        "unit": "MB",
        "baseline_0_7_0": 1055.0,
        "why": (
            "10k live interpreters must fit inside a 1.2 GB working set so a "
            "single trading process can hold a full day's order population."
        ),
    },
    {
        "bench": "bench_c_timers.py",
        "id": "BENCH-5",
        "label": "Timer drift -- 100 ms `after`, idle loop (p95 error)",
        "path": ["c_timer_precision", "idle", "after_100ms_error_ms", "p95"],
        "rule": "le",
        "threshold": 25.0,
        "unit": "ms",
        "baseline_0_7_0": 15.1,
        "why": (
            "Idle drift must stay inside the Windows ~15.6 ms timer floor plus "
            "margin. 0.7.0 passes at +15.1 ms."
        ),
    },
    {
        "bench": "bench_c_timers_v2.py",
        "id": "BENCH-6",
        "label": "Timer lateness -- 10 ms `after`, 500 busy machines (p99, upstream scenario)",
        "path": ["summary_by_busy_level", "500", "p99"],
        "rule": "le",
        "threshold": 100.0,
        "unit": "ms",
        "baseline_0_7_0": 2530.0,
        "why": (
            "This is LC-26, the headline timing risk. ROUND-13 CORRECTION: this "
            "row used to read bench_c_timers.py, which does NOT reproduce the "
            "'N busy machines' loaded-timer scenario -- so five rounds of "
            "'174.4 ms, still missed' measured the wrong thing. It now wraps "
            "the library's own benchmarks/production_characteristics.py --quick "
            "section 2. At v0.9.0, n=10: min 52.1 / p50 53.4 / p99 55.8 ms. "
            "PASS here retires the external MonotonicScheduler requirement for "
            "COARSE timers (CV-C12 -> CV-C12'); hard sub-100 ms deadlines stay "
            "on the external scheduler regardless, and this must be re-measured "
            "on TARGET hardware before the relaxation applies in production."
        ),
    },
    {
        "bench": "bench_a_throughput.py",
        "id": "BENCH-7",
        "label": "Single-interpreter throughput (burst 50k)",
        "path": ["a_single_interpreter_throughput", "burst_50000", "events_per_sec"],
        "rule": "ge",
        "threshold": 30000.0,
        "unit": "ev/s",
        "baseline_0_7_0": 30000.0,
        "why": (
            "Regression guard, not an aspiration. 0.7.0 sits at ~30k ev/s; a "
            "drop below this means a hot-path regression landed upstream."
        ),
    },
]

BENCH_SCRIPTS = [
    "bench_a_throughput.py",
    "bench_b_many_interpreters.py",
    "bench_c_timers.py",
    # Round 13: BENCH-6 moved here. Wraps upstream production_characteristics.py
    # --quick section 2; bench_c_timers.py is retained for BENCH-5 (idle drift),
    # which it does measure correctly.
    "bench_c_timers_v2.py",
    "bench_h_candleviewer_budgets.py",
]

# -----------------------------------------------------------------------------
# Result record
# -----------------------------------------------------------------------------
PASS, FAIL, SKIP, ERROR, IMPROVED = "PASS", "FAIL", "SKIP", "ERROR", "IMPROVED"
# "skipped (environment)": the script needs an upstream dev venv / checkout that
# this host does not have (#1928). Neither a pass nor a failure; never blocking.
SKIP_ENV = "SKIP-ENV"


class Check:
    def __init__(self, cid: str, kind: str, label: str) -> None:
        self.id = cid
        self.kind = kind  # repro | probe | bench
        self.label = label
        self.status = SKIP
        self.detail = ""
        self.seconds = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "seconds": round(self.seconds, 2),
        }


# -----------------------------------------------------------------------------
# Subprocess helper
# -----------------------------------------------------------------------------
def run_script(path: str, cwd: str, timeout: int) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(  # noqa: S603  # runs the gate's own research scripts via sys.executable
            [sys.executable, path],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"


# -----------------------------------------------------------------------------
# 1. Check sets -- every LC-xx script must exit 0
#
# PRIMARY (blocking): `issues/verify-0.8.0/*.py`. These exercise the CandleViewer
#   *mandated configuration* (17-reeval-0.8.0-verdict.md s.4) -- actionErrorPolicy,
#   onUnhandled, guardErrorPolicy, strictTargets, strict, bounded inbox, injected
#   clock. They answer the gate's actual question: "with the configuration we are
#   required to ship, is the defect gone?"
#
# SECONDARY (informational, never blocking): `issues/repro/*.py`. These are the
#   original 0.7.0 scripts and exercise the library *defaults*. From 0.8.0 the
#   library fixes defects as per-machine policies whose default preserves the old
#   semantics, so a secondary FAIL usually means "fixed but opt-in" or "stale
#   repro" rather than "unfixed" -- see 20-adoption-gate.md s.9.2. Reported for
#   contrast, excluded from the exit code.
# -----------------------------------------------------------------------------
def classify_exit(rc: int, out: str, fail_detail: str) -> tuple[str, str]:
    """Map a check script's exit code to ``(status, detail)``.

    0 == defect gone (PASS); 1 == defect present (FAIL); ``SKIP_ENV_EXIT`` (77)
    == the script cannot run on this host (SKIP-ENV, see gate/_paths.py);
    anything else is a harness ERROR.
    """
    if rc == 0:
        return PASS, "defect NOT reproduced -- fixed"
    if rc == 1:
        return FAIL, fail_detail
    if rc == SKIP_ENV_EXIT:
        reason = next(
            (
                ln.strip()
                for ln in reversed(out.splitlines())
                if ln.strip().startswith("skipped (environment)")
            ),
            "skipped (environment): " + _last_line(out),
        )
        return SKIP_ENV, reason[:200]
    return ERROR, f"exit {rc}: {_last_line(out)}"


def _run_lc_dir(
    directory: str,
    kind: str,
    only: list[str] | None,
    timeout: int,
    fail_detail: str,
) -> list[Check]:
    """Run every LC-xx script in `directory`; exit 0 == defect gone."""
    checks: list[Check] = []
    if not os.path.isdir(directory):
        raise SystemExit(f"[gate] missing {kind} dir: {directory}")
    seen: dict[str, int] = {}
    for fn in sorted(os.listdir(directory)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        lc = fn.split("_", 1)[0]  # "LC-01"
        if only and lc not in only:
            continue
        # Two scripts can share one LC prefix (verify-main-5327ba6 has two for
        # LC-37). Ids must stay unique or the JSON and the table collapse them.
        # In verify-main-3c527b0 the prefix is the GitHub issue number.
        seen[lc] = seen.get(lc, 0) + 1
        row_id = lc if seen[lc] == 1 else f"{lc}#{seen[lc]}"
        chk = Check(row_id, kind, fn.split("_", 1)[1][:-3].replace("-", " "))
        t0 = time.perf_counter()
        script = os.path.join(directory, fn)
        rc, out = run_script(script, directory, timeout_for(script, timeout))
        chk.seconds = time.perf_counter() - t0
        chk.status, chk.detail = classify_exit(rc, out, fail_detail)
        checks.append(chk)
    return checks


def run_verify(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the mandated configuration. Blocking."""
    return _run_lc_dir(
        VERIFY_DIR,
        "verify",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ 5327ba6 verification scripts. Blocking.

    Added by the `main` @ `5327ba6` pass (`22-verify-main-verdict.md`). Same
    contract as `run_verify`: exit 0 == defect gone.
    """
    return _run_lc_dir(
        VERIFY_MAIN_DIR,
        "verifyM",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main2(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ 3c527b0 verification scripts. Blocking.

    Added by the `main` @ `3c527b0` pass (`26-verify-3c527b0-verdict.md`),
    covering #43 / #79 / #80. Same contract as `run_verify`: exit 0 == defect
    gone. Baseline is 3/3 PASS, so any FAIL is a regression.

    These scripts are named `<GH#>_<slug>.py` rather than `LC-xx_<slug>.py`, so
    the row id is the issue number.
    """
    return _run_lc_dir(
        VERIFY_MAIN2_DIR,
        "verifyM2",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main3(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ cec108b verification scripts. Blocking.

    Added by the round-6 pass (`39-r6-final-readiness-verdict.md`), covering the
    26 issues verified on that commit (#142-#162 plus the reopens
    #118/#122/#125/#133/#134). Same contract as `run_verify`: exit 0 == defect
    gone.

    Two expected FAILs at the recorded baseline (#122 PARTIAL, #157 NOT-FIXED);
    see `VERIFYM3_BASELINE_FAILURES`. Any FAIL outside that pair is a regression.

    Like `verifyM2`, these scripts are named `<GH#>_<slug>.py`, so the row id is
    the issue number rather than an `LC-xx` prefix.
    """
    return _run_lc_dir(
        VERIFY_MAIN3_DIR,
        "verifyM3",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main4(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ 221ce7c verification scripts. Blocking.

    Added by the round-7 pass (`44-r7-final-readiness-verdict.md`), covering the
    12 issues verified on that commit (#166-#175 plus #157 and #122-as-designed).
    Same contract as `run_verify`: exit 0 == defect gone.

    One expected FAIL at the recorded baseline (#167 PARTIAL -- fixed for plain
    `def` services only); see `VERIFYM4_BASELINE_FAILURES`. Any FAIL outside it
    is a regression.

    Standing amendment 12: a row here that exercises an `invoke` MUST be
    parametrised over service kind. `def` and `async def` take different
    publication lanes for their completions, so a single-kind row silently
    confirms a fix that does not hold on the other lane.
    """
    return _run_lc_dir(
        VERIFY_MAIN4_DIR,
        "verifyM4",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main5(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ 6db65d8 verification scripts. Blocking.

    Added by the round-8 pass (`49-r8-final-readiness-verdict.md`), covering the
    16 issues verified on that commit: the round-7 fix set #179-#190 plus the
    reopened #167/#168/#174/#175. Same contract as `run_verify`: exit 0 ==
    defect gone.

    One expected FAIL at the recorded baseline (#174 -- DOCUMENTED-ONLY, no code
    changed); see `VERIFYM5_BASELINE_FAILURES`. Any FAIL outside it is a
    regression.

    Standing amendment 12 (round 7): a row exercising an `invoke` MUST be
    parametrised over service kind.

    Standing amendment 13 (round 8): a row exercising a `send` MUST be
    parametrised over issuer provenance (external vs issued from an action) AND
    chain state (untripped vs already tripped). R8-01 survived an upstream fix,
    a pinned upstream test and a full battle round because every existing test
    sent externally into an untripped chain. Related: a parametrised row whose
    arms are not equally capable of failing is not parametrised -- give the arm
    expected to fail work that can actually exceed the bound.
    """
    return _run_lc_dir(
        VERIFY_MAIN5_DIR,
        "verifyM5",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main6(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ f28719c verification scripts. Blocking.

    Added by the round-9 pass (`54-r9-final-readiness-verdict.md`), covering the
    12 issues verified on `main` @ `f28719c` -- the round-8 fix set #192-#201
    plus the reopened #181/#186. Own named, commit-keyed set. Same contract as
    `run_verify`: exit 0 == defect gone.

    One expected FAIL at the recorded baseline (#197 -- genuinely PARTIAL, the
    R9-08 residual); see `VERIFYM6_BASELINE_FAILURES`. Any FAIL outside it is a
    regression.

    Standing amendments 12 and 13 apply (service kind; issuer provenance and
    chain state).

    Standing amendment 14 (round 9): where a row exercises a TRUST MECHANISM, it
    must enumerate every call site the mechanism is meant to govern rather than
    sampling one. R9-02 exists because #195 minted three private engine event
    classes and wired two of them into transition selection; a row that checked
    only `done`/`error` would have reported the fix complete. Related: a restore
    -path row must exercise the RAW SERIALISED RECORD, not only the deserialised
    class -- R9-02's decisive vector never passes a `send()`-time check at all.

    Standing amendment 15 (round 9): a row must cite the doc sentence or spec
    clause it enforces, and a row whose citation and assertion disagree is a
    defect in the row. Corollary: assert convergence by POLLING to convergence,
    never by sleeping a guessed interval -- see `t_r6_plateau.py`, where a
    0.6 s read reports a correct `maxIterations + 2` plateau as a spin.
    """
    return _run_lc_dir(
        VERIFY_MAIN6_DIR,
        "verifyM6",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main7(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- the main @ 19cb1f1 verification scripts. Blocking.

    Added by the round-10 pass (`59-r10-final-readiness-verdict.md`), covering
    the 8 issues verified on `main` @ `19cb1f1` (merge of PR #211, commit
    4dbf86e) -- the round-9 fix set #203-#210. Own named, commit-keyed set.
    Same contract as `run_verify`: exit 0 == defect gone.

    **NO expected failures at the recorded baseline** (`VERIFYM7_BASELINE_FAILURES`
    is empty). Every FAIL here is a regression. This set closes both round-9
    Highs: `203_*` pins the `after` provenance gate (R9-02) and `204_*` pins the
    SCXML s.6.1 `statesToInvoke` deferral (R9-04) on BOTH engines and BOTH
    service kinds -- if either flips to FAIL, CV-C45's send-side clause and
    CV-C46 must be reinstated before the order path runs.

    Standing amendments 12-15 apply (service kind; issuer provenance and chain
    state; exhaustive trust-mechanism call sites; cite the clause you enforce
    and poll to convergence).

    Standing amendment 16 (round 10): a row asserting a SECURITY property must
    state the minimum capability it presumes and carry a CONTROL showing what
    that capability achieves WITHOUT the finding. Round 10 filed three
    Blocker/High candidates and all three fell to their own controls -- a plain
    registered action writes context arbitrarily, and a hand-edited snapshot
    relocates the machine, both without any event forgery at all. If the control
    achieves as much as the exploit, the row is hardening, not a defect.

    Standing amendment 17 (round 10): a row must demonstrate its own
    DISCRIMINATING POWER -- show the metric moving with the parameter it claims
    to bound. `209_*`'s paired `nested_invoke` shape agrees across all three
    lanes because it is a constant, and a constant agrees with itself.
    """
    return _run_lc_dir(
        VERIFY_MAIN7_DIR,
        "verifyM7",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main8(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- `main` @ c78ce99 (round 11). Blocking.

    The round-10 fix set #212-#216, pinned on the commit. Baseline 6/6 PASS.

    TWO SEMANTIC REVERSALS live here. `212_*` pins that a `raise(delay=)`
    self-send is a TIMER, which SUPERSEDES #206 -- the row it replaces
    (`206_delayed_selfsend_charged.py`) was RETIRED from verifyM7 this round
    precisely because it asserted the old rule. `213_*`/`214_*` pin snapshot
    layout v3. Before calling any failure here a regression, check the CHANGELOG
    for a further rule change.

    Standing amendment 18 (round 11): test every blob-write finding against the
    `state_ids`-only control BEFORE triage. Three rounds, three Blockers filed
    against engine-event provenance, three refuted on the same control -- if the
    same writer reaches the same place with `state_ids`/`context` alone, the row
    is hardening, not a defect. `from_snapshot` is a documented trusted-input
    boundary and `machine_hash` is explicitly not a MAC; the boundary is the
    HMAC tag on the blob (CV-C53).

    Standing amendment 20 (round 11): when a fix closes a constraint's ground,
    re-ground the constraint or retire it. This set closed the grounds of
    CV-C47, CV-C48 and CV-C49 in a single release, with three different
    outcomes -- re-grounded, retired, rewritten.
    """
    return _run_lc_dir(
        VERIFY_MAIN8_DIR,
        "verifyM8",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )


def run_verify_main9(only: list[str] | None, timeout: int) -> list[Check]:
    """PRIMARY check set -- `main` @ de2da4e (round 12). Blocking.

    The round-11 fix set #218-#222, pinned on the commit. Baseline 7/7 PASS.

    ONE BEHAVIOUR CHANGE lives here. `219_*` pins that an in-step
    send(..., wait=True) on an action's own interpreter RAISES
    ReentrantWaitError on BOTH engines, where it previously deadlocked. That is
    a BREAKING CHANGE for user actions, not a bug fix, and it is the reason
    this set needs its own note: a FAIL on that row may mean the guard's
    predicate was NARROWED (the outcome DE-L1 requests), in which case the row
    is rewritten, not reported.

    Standing amendment 20 (round 11) fired hard this round and is restated:
    WHEN A FIX CLOSES A CONSTRAINT'S GROUND, RE-GROUND THE CONSTRAINT OR RETIRE
    IT. #218 closed the second and last ground of CV-C47 (R11-04, the unbounded
    _timer_handles leak) after #212 had closed its first (R10-03), so CV-C47
    and CV-C61 BOTH RETIRE -- the first retirement in this study driven by a
    defect being fixed at the mechanism rather than by a constraint being
    superseded. The handle-count gauge is kept as TELEMETRY, because it is what
    would detect a recurrence.

    Standing amendment 21 (round 12, NEW): A SUPERSEDED ORACLE IS NOT A
    REGRESSION, AND IT MUST BE RENAMED OR REWRITTEN IN THE ROUND THAT NOTICES
    IT. Round 11 retired the 206 row by renaming the file; round 12 spent zero
    triage on it, which is the whole argument. Two more of OUR scripts are
    superseded at this commit (R11-09 by #222, R11-07 by #220's fix landing) --
    see RETIRED_OR_REWRITTEN. Leave them and they become permanent meaningless
    reds.

    Standing amendment 22 (round 12, NEW): A ROW ASSERTING A BENCHMARK
    THRESHOLD MAY NOT BE SATISFIED BY ABSENCE OF EVIDENCE. BENCH-6 has been
    UNMEASURED for five consecutive rounds while CV-C12 stands on its stale
    number. `unmeasured` is not `met`; decision-table row 9 is refused on that
    basis, and `bench_c_timers` gets a DEDICATED time slice, first, before
    anything else in round 13.

    Standing amendment 23 (round 13, NEW): amendment 22 IS DISCHARGED, and the
    way it was discharged is the lesson. BENCH-6 was not merely unmeasured --
    it was being measured with THE WRONG TOOL. `bench_c_timers.py` does not
    reproduce upstream's "N busy machines" loaded-timer scenario at all, so
    five rounds of "still missed, 174.4 ms" were five rounds of a number that
    never addressed the question. BENCH-6 now runs `bench_c_timers_v2.py`,
    a thin wrapper over the library's OWN `benchmarks/production_characteristics.py
    --quick` section 2. Ten runs at v0.9.0: min 52.1 / p50 53.4 / p99 55.8 ms
    against a 100 ms bar -- MET, with ~44 ms headroom, every run under.
    CV-C12 (the `after` ban) retires to CV-C12' on the strength of it.
    The rule this leaves behind: when a threshold sits unmet for several
    rounds with no mechanism story, SUSPECT THE INSTRUMENT BEFORE THE LIBRARY.

    Standing amendment 24 (round 13, NEW): VERIFY_V090_DIR joins the primary
    set. Round 13 keys on the TAG (`v0.9.0` = 91bd979) rather than a branch
    commit, having first verified that `main` @ e3a1f22 differs from the tag
    only in CI config -- and, separately, that the PyPI wheel matches the tag
    across all 42 modules. A gate that decides on a tree which is not the
    artefact anyone installs is deciding on the wrong thing.
    """
    checks = _run_lc_dir(
        VERIFY_MAIN9_DIR,
        "verifyM9",
        only,
        timeout,
        "defect still present UNDER THE MANDATED CONFIG -- this is a real FAIL",
    )
    checks += _run_lc_dir(
        VERIFY_V090_DIR,
        "verifyV090",
        only,
        timeout,
        "round-12 fix (#225-#235) NOT holding at tag v0.9.0 -- this is a real FAIL",
    )
    checks += _run_lc_dir(
        VERIFY_V091_DIR,
        "verifyV091",
        only,
        timeout,
        "round-13 fix (#239-#248) NOT holding at tag v0.9.1 -- this is a real FAIL",
    )
    return checks


def run_repros(only: list[str] | None, timeout: int) -> list[Check]:
    """SECONDARY check set -- library defaults. Informational only."""
    return _run_lc_dir(
        REPRO_DIR,
        "repro",
        only,
        timeout,
        "reproduces at DEFAULTS -- triage: unfixed / fixed-but-opt-in / stale repro",
    )


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1][:160] if lines else "(no output)"


# -----------------------------------------------------------------------------
# 2. Probes -- compare non-PASS set against the 0.7.0 baseline
# -----------------------------------------------------------------------------
def run_probes(timeout: int) -> list[Check]:
    checks: list[Check] = []
    if not os.path.isdir(PROBE_DIR):
        raise SystemExit(f"[gate] missing probe dir: {PROBE_DIR}")
    for fn in sorted(os.listdir(PROBE_DIR)):
        if not (fn.startswith("p0") and fn.endswith(".py")):
            continue
        # p01_core_transitions.py -> results/01_core_transitions.json
        result_name = fn[1:-3]
        chk = Check(f"PROBE-{result_name.split('_')[0]}", "probe", result_name)
        t0 = time.perf_counter()
        rc, out = run_script(os.path.join(PROBE_DIR, fn), PROBE_DIR, timeout)
        chk.seconds = time.perf_counter() - t0
        if rc != 0:
            chk.status = ERROR
            chk.detail = f"exit {rc}: {_last_line(out)}"
            checks.append(chk)
            continue

        rpath = os.path.join(PROBE_DIR, "results", f"{result_name}.json")
        try:
            with open(rpath, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            chk.status = ERROR
            chk.detail = f"cannot read {rpath}: {exc}"
            checks.append(chk)
            continue

        nonpass = sorted(r["id"] for r in data if r.get("status") != "PASS")
        base = sorted(PROBE_BASELINE_FAILURES.get(result_name, []))
        regressed = sorted(set(nonpass) - set(base))
        improved = sorted(set(base) - set(nonpass))
        n_pass = sum(1 for r in data if r.get("status") == "PASS")

        if regressed:
            chk.status = FAIL
            chk.detail = f"{n_pass}/{len(data)} PASS; REGRESSED: {','.join(regressed)}"
        elif improved:
            chk.status = IMPROVED
            chk.detail = f"{n_pass}/{len(data)} PASS; newly passing: {','.join(improved)}"
        elif nonpass:
            chk.status = FAIL
            chk.detail = (
                f"{n_pass}/{len(data)} PASS; still failing at baseline: {','.join(nonpass)}"
            )
        else:
            chk.status = PASS
            chk.detail = f"{n_pass}/{len(data)} PASS"
        checks.append(chk)
    return checks


# -----------------------------------------------------------------------------
# 3. Benchmarks -- parse the printed JSON blocks, apply thresholds
# -----------------------------------------------------------------------------
_BLOCK = re.compile(r"^=== (?P<name>[^=]+?) ===\s*$", re.M)


def parse_bench_blocks(text: str) -> dict[str, Any]:
    """Extract every `=== name ===\\n<json>` block printed by common.report()."""
    blocks: dict[str, Any] = {}
    marks = list(_BLOCK.finditer(text))
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        chunk = text[start:end].strip()
        # the JSON object starts at the first '{' and is indent=2 pretty-printed
        brace = chunk.find("{")
        if brace < 0:
            continue
        depth, endpos = 0, None
        in_str, esc = False, False
        for pos, ch in enumerate(chunk[brace:], start=brace):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    endpos = pos + 1
                    break
        if endpos is None:
            continue
        try:
            blocks[m.group("name").strip()] = json.loads(chunk[brace:endpos])
        except json.JSONDecodeError:
            continue
    return blocks


def parse_bare_json(text: str) -> dict[str, Any]:
    """The first top-level JSON object in ``text``, or ``{}`` (#579).

    `bench_c_timers_v2.py` (BENCH-6) prints one bare JSON document rather than
    `=== name ===` blocks, so its THRESHOLDS path starts at that object's top
    level. Without this fallback the row could never find its metric and was an
    ERROR on every `--with-bench` run.
    """
    start = text.find("{")
    if start < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def dig(blocks: dict[str, Any], path: list[str]) -> float | None:
    node: Any = blocks
    for key in path:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    if isinstance(node, bool):
        return 1.0 if node else 0.0
    if isinstance(node, (int, float)):
        return float(node)
    return None


def run_benches(timeout: int) -> list[Check]:
    checks: list[Check] = []
    outputs: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    for script in BENCH_SCRIPTS:
        path = os.path.join(BENCH_DIR, script)
        if not os.path.isfile(path):
            errors[script] = "script missing"
            continue
        print(f"[gate] running {script} (this is slow) ...", flush=True)
        rc, out = run_script(path, BENCH_DIR, timeout)
        if rc != 0:
            errors[script] = f"exit {rc}: {_last_line(out)}"
        outputs[script] = parse_bench_blocks(out) or parse_bare_json(out)

    for spec in THRESHOLDS:
        chk = Check(spec["id"], "bench", spec["label"])
        script = spec["bench"]
        if script in errors and not outputs.get(script):
            chk.status = ERROR
            chk.detail = errors[script]
            checks.append(chk)
            continue
        value = dig(outputs.get(script, {}), spec["path"])
        if value is None:
            chk.status = ERROR
            chk.detail = f"metric {'.'.join(spec['path'])} not found in {script} output"
            checks.append(chk)
            continue
        thr, unit = spec["threshold"], spec["unit"]
        ok = value >= thr if spec["rule"] == "ge" else value <= thr
        chk.status = PASS if ok else FAIL
        op = ">=" if spec["rule"] == "ge" else "<="
        chk.detail = (
            f"{value:,.2f} {unit} (need {op} {thr:,.2f}; "
            f"0.7.0 baseline {spec['baseline_0_7_0']:,.2f})"
        )
        checks.append(chk)
    return checks


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------
def library_version() -> str:
    try:
        import xstate_statemachine as lib

        return getattr(lib, "__version__", "unknown")
    except Exception as exc:
        raise SystemExit(f"[gate] cannot import xstate_statemachine: {exc}") from exc


def library_commit() -> str:
    """Resolve the git commit of the installed library clone.

    The version string is not an identity (`BASELINE_COMMIT` docstring), so the
    commit is what the gate records and compares. Returns "unknown" for a
    non-editable install with no reachable git checkout -- in which case the
    run log MUST record how the build was obtained.
    """
    try:
        import xstate_statemachine as lib

        pkg = os.path.dirname(os.path.abspath(lib.__file__))
    except Exception:
        return "unknown"

    # src/xstate_statemachine -> src -> repo root
    for repo in (
        os.path.dirname(os.path.dirname(pkg)),
        os.path.dirname(pkg),
        pkg,
    ):
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            out = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
                ["git", "-C", repo, "rev-parse", "HEAD"],  # noqa: S607  # git from PATH, matches CI usage
                capture_output=True,
                text=True,
                timeout=30,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            return "unknown"
    return "unknown"


def describe_build(version: str, commit: str) -> str:
    """One line naming the build under test, keyed on the commit."""
    short = commit[:7] if commit != "unknown" else "unknown"
    if commit == BASELINE_COMMIT:
        return f"{BASELINE_LABEL} -- matches BASELINE_COMMIT {BASELINE_COMMIT_SHORT}"
    if short in PREVIOUS_BASELINES:
        return f"{PREVIOUS_BASELINES[short]} @ {short} -- an EARLIER baseline"
    if commit == "unknown":
        return (
            f"commit UNKNOWN (reports __version__ {version}) -- "
            "record provenance in the run log by hand"
        )
    return (
        f"commit {short} -- NOT a recorded baseline "
        f"(reports __version__ {version}); triage every delta in writing"
    )


def print_table(checks: list[Check]) -> None:
    w_id = max([len(c.id) for c in checks] + [6])
    w_lb = min(56, max([len(c.label) for c in checks] + [10]))
    print()
    print(f"{'ID':<{w_id}}  {'KIND':<6}  {'STATUS':<8}  {'CHECK':<{w_lb}}  DETAIL")
    print("-" * (w_id + w_lb + 60))
    for c in checks:
        print(f"{c.id:<{w_id}}  {c.kind:<6}  {c.status:<8}  {c.label[:w_lb]:<{w_lb}}  {c.detail}")


def summarize(checks: list[Check], version: str, commit: str) -> int:
    counts: dict[str, int] = {}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    short = commit[:7] if commit != "unknown" else "unknown"
    print()
    print("=" * 78)
    print(f"  xstate-statemachine @ {short}  --  CandleViewer adoption gate")
    print(f"  {describe_build(version, commit)}")
    print("=" * 78)
    for kind, note in (
        ("verify", "PRIMARY -- mandated config, blocking"),
        ("verifyM", "PRIMARY -- main@5327ba6 verification set, blocking"),
        ("verifyM2", "PRIMARY -- main@3c527b0 verification set, blocking"),
        ("verifyM3", "PRIMARY -- main@cec108b verification set (round 6), blocking"),
        ("verifyM4", "PRIMARY -- main@221ce7c verification set (round 7), blocking"),
        ("verifyM5", "PRIMARY -- main@6db65d8 verification set (round 8), blocking"),
        ("verifyM6", "PRIMARY -- main@f28719c verification set (round 9), blocking"),
        ("verifyM7", "PRIMARY -- main@19cb1f1 verification set (round 10), blocking"),
        ("verifyM8", "PRIMARY -- main@c78ce99 verification set (round 11), blocking"),
        ("verifyM9", "PRIMARY -- main@de2da4e verification set (round 12), blocking"),
        ("repro", "SECONDARY -- defaults, informational"),
        ("probe", ""),
        ("bench", ""),
    ):
        subset = [c for c in checks if c.kind == kind]
        if not subset:
            continue
        p = sum(1 for c in subset if c.status in (PASS, IMPROVED))
        sk = sum(1 for c in subset if c.status == SKIP_ENV)
        skipped = f", {sk} skipped (environment)" if sk else ""
        suffix = f"   ({note})" if note else ""
        print(f"  {kind:<6}: {p}/{len(subset) - sk} pass{skipped}{suffix}")
    print("  totals: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    # Only the primary set, probes and benches gate the exit code. A FAIL in the
    # secondary (defaults) set is expected from 0.8.0 onward -- see
    # 20-adoption-gate.md s.9.2 -- and must be triaged in writing, not treated as
    # a gate failure. An ERROR anywhere is always blocking: it invalidates the row.
    blocking = [c for c in checks if c.status == ERROR or (c.status == FAIL and c.kind != "repro")]
    informational = [c for c in checks if c.kind == "repro" and c.status == FAIL]

    # Separate carried-forward `verifyM` partials from genuine regressions.
    # `20-adoption-gate.md` s.9.4 amendment 7: every delta is classified.
    vm_fails = [c for c in checks if c.kind == "verifyM" and c.status == FAIL]
    vm_expected = [c for c in vm_fails if c.id.split("#")[0] in VERIFYM_BASELINE_FAILURES]
    vm_regressed = [c for c in vm_fails if c not in vm_expected]
    if vm_fails:
        print()
        print(
            f"  verifyM: {len(vm_expected)} FAIL(s) at the recorded "
            f"{BASELINE_COMMIT_SHORT} baseline (expected, already triaged as"
        )
        print(
            "           'keep open' in 22-verify-main-verdict.md s.1): "
            + ", ".join(sorted(c.id for c in vm_expected))
        )
        if vm_regressed:
            print(
                "           REGRESSION -- outside the baseline, triage in "
                "writing: " + ", ".join(sorted(c.id for c in vm_regressed))
            )

    # `verifyM2` has no expected failures at the baseline commit.
    vm2_fails = [c for c in checks if c.kind == "verifyM2" and c.status == FAIL]
    if vm2_fails:
        print()
        print(
            "  verifyM2: REGRESSION -- this set is 3/3 PASS at "
            f"{BASELINE_COMMIT_SHORT} and has no expected failures."
        )
        print(
            "            Triage in writing before deciding: "
            + ", ".join(sorted(c.id for c in vm2_fails))
        )

    # `verifyM3` (round 6) has exactly two expected failures at cec108b.
    vm3_fails = [c for c in checks if c.kind == "verifyM3" and c.status == FAIL]
    vm3_expected = [c for c in vm3_fails if c.id.split("#")[0] in VERIFYM3_BASELINE_FAILURES]
    vm3_regressed = [c for c in vm3_fails if c not in vm3_expected]
    if vm3_fails:
        print()
        print(
            f"  verifyM3: {len(vm3_expected)} FAIL(s) expected at the recorded "
            "cec108b baseline (#157 NOT-FIXED as filed, reopened narrower --"
        )
        print(
            "            triaged in 39-r6-final-readiness-verdict.md s.1): "
            + ", ".join(sorted(c.id for c in vm3_expected))
        )
        if vm3_regressed:
            print(
                "            REGRESSION -- outside the baseline, triage in "
                "writing: " + ", ".join(sorted(c.id for c in vm3_regressed))
            )

    # `verifyM4` (round 7) has exactly one expected failure at 221ce7c.
    vm4_fails = [c for c in checks if c.kind == "verifyM4" and c.status == FAIL]
    vm4_expected = [c for c in vm4_fails if c.id.split("#")[0] in VERIFYM4_BASELINE_FAILURES]
    vm4_regressed = [c for c in vm4_fails if c not in vm4_expected]
    if vm4_fails:
        print()
        print(
            f"  verifyM4: {len(vm4_expected)} FAIL(s) expected at the recorded "
            "221ce7c baseline (#167 PARTIAL -- bounded for plain `def`"
        )
        print(
            "            services only; the coroutine half is R7-01, triaged "
            "in 44-r7-final-readiness-verdict.md s.1): "
            + ", ".join(sorted(c.id for c in vm4_expected))
        )
        if vm4_regressed:
            print(
                "            REGRESSION -- outside the baseline, triage in "
                "writing: " + ", ".join(sorted(c.id for c in vm4_regressed))
            )

    # `verifyM5` (round 8) has exactly one expected failure at 6db65d8: #174,
    # which was closed DOCUMENTED-ONLY, so its script correctly still reports the
    # behaviour the documentation describes.
    vm5_fails = [c for c in checks if c.kind == "verifyM5" and c.status == FAIL]
    vm5_expected = [c for c in vm5_fails if c.id.split("#")[0] in VERIFYM5_BASELINE_FAILURES]
    vm5_regressed = [c for c in vm5_fails if c not in vm5_expected]
    if vm5_fails:
        print()
        print(
            f"  verifyM5: {len(vm5_expected)} FAIL(s) expected at the recorded "
            "6db65d8 baseline (#174 DOCUMENTED-ONLY -- no code changed, so the"
        )
        print(
            "            script still reports the documented behaviour; see "
            "49-r8-final-readiness-verdict.md s.1): "
            + ", ".join(sorted(c.id for c in vm5_expected))
        )
        if vm5_regressed:
            print(
                "            REGRESSION -- outside the baseline, triage in "
                "writing: " + ", ".join(sorted(c.id for c in vm5_regressed))
            )

    # `verifyM6` (round 9) has exactly one expected failure at f28719c: #197,
    # which is genuinely PARTIAL -- the success-shaped send(wait=True) receipt
    # over an empty configuration, carried as R9-08 (Medium).
    vm6_fails = [c for c in checks if c.kind == "verifyM6" and c.status == FAIL]
    vm6_expected = [c for c in vm6_fails if c.id.split("#")[0] in VERIFYM6_BASELINE_FAILURES]
    vm6_regressed = [c for c in vm6_fails if c not in vm6_expected]
    if vm6_fails:
        print()
        print(
            f"  verifyM6: {len(vm6_expected)} FAIL(s) expected at the recorded "
            "f28719c baseline (#197 PARTIAL -- the library's own pinned test"
        )
        print(
            "            passes but the original chart still yields a "
            "success-shaped receipt over an empty configuration; carried as "
            "R9-08, see 54-r9-final-readiness-verdict.md s.1): "
            + ", ".join(sorted(c.id for c in vm6_expected))
        )
        if vm6_regressed:
            print(
                "            REGRESSION -- outside the baseline, triage in "
                "writing: " + ", ".join(sorted(c.id for c in vm6_regressed))
            )

    # `verifyM7` (round 10) has NO expected failures at 19cb1f1. All 8 scripts
    # (#203-#210) exit 0 at the recorded baseline -- the first clean
    # verification set in the study. Every FAIL here is a regression.
    vm7_fails = [c for c in checks if c.kind == "verifyM7" and c.status == FAIL]
    if vm7_fails:
        print()
        print(
            "  verifyM7: REGRESSION -- this set has NO expected failures at the "
            "recorded 19cb1f1 baseline. Triage in writing: "
            + ", ".join(sorted(c.id for c in vm7_fails))
        )
        if any(c.id.split("#")[0] in ("203", "204") for c in vm7_fails):
            print(
                "            #203 and/or #204 FAILED -- these close round-9's "
                "two Highs (R9-02, R9-04). Reinstate CV-C45's send-side clause "
                "and CV-C46 before the order path runs, and re-gate Phase-3 "
                "shim retirement (59-r10-final-readiness-verdict.md s.10)."
            )

    # `verifyM8` (round 11) has NO expected failures at c78ce99. All 6 scripts
    # (#212-#216) exit 0 at the recorded baseline. Every FAIL here is a
    # regression -- UNLESS the CHANGELOG reversed a rule again, which is exactly
    # what happened to the retired 206 row this round. Check before triaging.
    vm8_fails = [c for c in checks if c.kind == "verifyM8" and c.status == FAIL]
    if vm8_fails:
        print()
        print(
            "  verifyM8: REGRESSION -- this set has NO expected failures at the "
            "recorded c78ce99 baseline. Triage in writing: "
            + ", ".join(sorted(c.id for c in vm8_fails))
        )
        if any(c.id.split("#")[0] == "212" for c in vm8_fails):
            print(
                "            #212 FAILED -- this row pins a SEMANTIC REVERSAL "
                "(a raise(delay=) self-send is a TIMER, superseding #206). "
                "Check CHANGELOG for a further rule change BEFORE calling it a "
                "regression; the retired 206_delayed_selfsend_charged.py is the "
                "cautionary example (64-r11-final-readiness-verdict.md s.2b)."
            )
        if any(c.id.split("#")[0] == "213" for c in vm8_fails):
            print(
                "            #213 FAILED -- snapshot layout v3 scheduled_sends "
                "round-trip. This is the only restart-safe in-chart deadline "
                "primitive we have; if it flips, no catalogue deadline may move "
                "into a chart (K11) and CV-C49' must harden."
            )

    # `verifyM9` (round 12) has NO expected failures at de2da4e. All 7 scripts
    # (#218-#222) exit 0 at the recorded baseline. Every FAIL here is a
    # regression -- UNLESS the CHANGELOG changed a rule again. Check first.
    vm9_fails = [c for c in checks if c.kind == "verifyM9" and c.status == FAIL]
    if vm9_fails:
        print()
        print(
            "  verifyM9: REGRESSION -- this set has NO expected failures at the "
            "recorded de2da4e baseline. Triage in writing: "
            + ", ".join(sorted(c.id for c in vm9_fails))
        )
        if any(c.id.split("#")[0] == "218" for c in vm9_fails):
            print(
                "            #218 FAILED -- the timer-handle release. THIS IS "
                "THE GROUND ON WHICH CV-C47 AND CV-C61 WERE RETIRED "
                "(69-r12-final-readiness-verdict.md s.7). If it flips, BOTH "
                "constraints UN-RETIRE, R11-04 reopens at High, and the gate "
                "falls from row 8 to row 6. Cross-check the _timer_handles "
                "gauge kept as telemetry under CV-C28'."
            )
        if any(c.id.split("#")[0] == "219" for c in vm9_fails):
            print(
                "            #219 FAILED -- this row pins a BREAKING CHANGE "
                "(in-step self-wait RAISES ReentrantWaitError), not a bug fix. "
                "A failure may mean the guard's PREDICATE WAS NARROWED, which "
                "is the outcome DE-L1 requests. If so, REWRITE this row; do "
                "not report it as a regression."
            )
        if any(c.id.split("#")[0] == "220" for c in vm9_fails):
            print(
                "            #220 FAILED -- the recursive unknown-key check. "
                "Our wrapper's own recursive check (CV-C57) is the fallback "
                "and must NOT be retired while this row is red."
            )
        if any(c.id.split("#")[0] == "222" for c in vm9_fails):
            print(
                "            #222 FAILED -- the chain-trip latch. CV-C59 "
                "(supervisors must not poll last_error) reverts from 'agrees "
                "with the runtime' to 'substitutes for it'. Note last_error "
                "staying per-step is BY DESIGN and is NOT this row."
            )

    # `verify` (H-2, round 7): five unchanged pre-existing FAILs, allow-listed.
    v_fails = [c for c in checks if c.kind == "verify" and c.status == FAIL]
    v_regressed = [c for c in v_fails if c.id.split("#")[0] not in VERIFY_BASELINE_FAILURES]
    if v_regressed:
        print()
        print(
            "  verify  : REGRESSION -- FAIL outside VERIFY_BASELINE_FAILURES, "
            "triage in writing: " + ", ".join(sorted(c.id for c in v_regressed))
        )

    if informational:
        print()
        print(
            f"  NOTE: {len(informational)} secondary repro(s) FAIL at library "
            "defaults. This is informational -- from 0.8.0"
        )
        print(
            "        onward these are usually 'fixed but opt-in' or a stale "
            "repro. Triage each one in writing"
        )
        print("        (17-reeval-0.8.0-verdict.md s.0) before citing it.")

    print()
    if not blocking:
        print("  VERDICT: all blocking checks green -> proceed to the decision table in")
        print("           20-adoption-gate.md s.7.")
        print("           REMINDER: a FIXED-OPT-IN Blocker (LC-01, LC-03) counts as")
        print("           closed ONLY while CV-LINT-XS1/XS2 enforce the mandated")
        print("           config. Confirm the linter is green before deciding ADOPT.")
    else:
        print(f"  VERDICT: {len(blocking)} blocking check(s) not green -> NOT a clean gate.")
        print("           Map each FAIL to its register row and apply the")
        print("           decision table in 20-adoption-gate.md s.7:")
        print("           Blocker FAIL -> DEFER; High FAIL -> ADOPT with constraints;")
        print("           Medium/Low or bench-only FAIL -> ADOPT with constraints.")
        for c in blocking[:12]:
            print(f"             - {c.id:<9} {c.kind:<6} {c.status:<5} {c.detail[:70]}")
        if len(blocking) > 12:
            print(f"             ... and {len(blocking) - 12} more")
    print("=" * 78)
    return 1 if blocking else 0


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--with-bench",
        action="store_true",
        help="also run the benchmark suite (slow: 20-40 min)",
    )
    ap.add_argument("--bench-only", action="store_true", help="run only the benchmarks")
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated LC ids to run, e.g. LC-01,LC-03",
    )
    ap.add_argument("--json", default="", help="write the full result set here")
    ap.add_argument(
        "--no-secondary",
        action="store_true",
        help=(
            "skip the informational issues/repro set (library defaults) and run "
            "only the primary issues/verify-0.8.0 set"
        ),
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="per-script timeout in seconds (default 900)",
    )
    args = ap.parse_args()

    version = library_version()
    commit = library_commit()
    only = [s.strip() for s in args.only.split(",") if s.strip()] or None

    print(f"[gate] python              : {sys.version.split()[0]}")
    print(f"[gate] xstate-statemachine : {version} (reported; NOT the identity)")
    print(f"[gate] commit              : {commit}")
    print(f"[gate] build               : {describe_build(version, commit)}")
    print(f"[gate] root                : {ROOT}")

    checks: list[Check] = []
    t0 = time.perf_counter()
    try:
        if not args.bench_only:
            print("\n[gate] --- verify (PRIMARY: mandated configuration) ---")
            checks += run_verify(only, args.timeout)
            print("\n[gate] --- verifyM (PRIMARY: main@5327ba6 verification set) ---")
            checks += run_verify_main(only, args.timeout)
            print("\n[gate] --- verifyM2 (PRIMARY: main@3c527b0 verification set) ---")
            checks += run_verify_main2(only, args.timeout)
            print("\n[gate] --- verifyM3 (PRIMARY: main@cec108b verification set, round 6) ---")
            checks += run_verify_main3(only, args.timeout)
            print("\n[gate] --- verifyM4 (PRIMARY: main@221ce7c verification set, round 7) ---")
            checks += run_verify_main4(only, args.timeout)
            print("\n[gate] --- verifyM5 (PRIMARY: main@6db65d8 verification set, round 8) ---")
            checks += run_verify_main5(only, args.timeout)
            print("\n[gate] --- verifyM6 (PRIMARY: main@f28719c verification set, round 9) ---")
            checks += run_verify_main6(only, args.timeout)
            print("\n[gate] --- verifyM7 (PRIMARY: main@19cb1f1 verification set, round 10) ---")
            checks += run_verify_main7(only, args.timeout)
            print("\n[gate] --- verifyM8 (PRIMARY: main@c78ce99 verification set, round 11) ---")
            checks += run_verify_main8(only, args.timeout)
            print("\n[gate] --- verifyM9 (PRIMARY: main@de2da4e verification set, round 12) ---")
            checks += run_verify_main9(only, args.timeout)
            report_retired_scripts()
            if not args.no_secondary:
                print("\n[gate] --- repros (SECONDARY: library defaults, informational) ---")
                checks += run_repros(only, args.timeout)
            else:
                print("\n[gate] secondary repro set skipped (--no-secondary)")
            print("\n[gate] --- probes ---")
            checks += run_probes(args.timeout)
        if args.with_bench or args.bench_only:
            print("\n[gate] --- benchmarks ---")
            checks += run_benches(args.timeout)
        else:
            print("\n[gate] benchmarks skipped (pass --with-bench to include)")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[gate] harness error: {type(exc).__name__}: {exc}")
        return 2

    print_table(checks)
    rc = summarize(checks, version, commit)
    print(f"\n[gate] elapsed {time.perf_counter() - t0:,.1f}s")

    if args.json:
        payload = {
            "library_version": version,
            "library_commit": commit,
            "baseline_commit": BASELINE_COMMIT,
            "matches_baseline": commit == BASELINE_COMMIT,
            "build": describe_build(version, commit),
            "python": sys.version.split()[0],
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "benchmarks_run": bool(args.with_bench or args.bench_only),
            "checks": [c.as_dict() for c in checks],
            "exit_code": rc,
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"[gate] wrote {args.json}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
