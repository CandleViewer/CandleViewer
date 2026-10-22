# E17 client WS chaos report (E17-Q02, #410)

Status: **all seven scenarios run green; QA sign-off is pending.** The suite is `services/api/tests/chaos/ws/`,
catalogued in its `SCENARIOS.md`. It runs in the PR `py` lane, and every night in `chaos-ws-nightly.yml`. Every
figure under **Measured values** is quoted as the test printed it, in one of the three recorded runs named there, and
nothing there is estimated. Merging moves #410 to In Test, not Done (C-10.4): QA signs off after five consecutive
green nightlies (ruling R7), and the five run ids go in one #410 comment. The QA lens signs off there with a
`QA sign-off: pass` comment from a write-access account other than the closer, the form `qa-guard` accepts. A
nightly is the scheduled run on `main` (cron `29 3 * * *`), and green means all 21 tests passed. A night that
deselects a quarantined test does not count, and a red night restarts the count. No scheduled run has happened yet:
the three runs below were dispatched. So the first nightly is 2026-10-23 at 03:29Z, and the earliest fifth is
2026-10-27. Scenarios 1 and 7 run their gateway half only (see Deviations).

Plans live under `qa/plans/` and results under `docs/qa/perf/`, as for E09 and E17-Q03 (#568). The ticket names
`docs/qa/test-plans/e17-ws-protocol.md`, which does not exist. This file is linked from `qa/plans/e17-ws-conformance.md`
§4.

## How it runs

- **The PR lane.** The `py` lane's `db-chaos-5` job runs the `tests/chaos` path with the lane's marker expression,
  which deselects `harness`. That drops three tests: the 60 s burst, the 60 s isolation run and the budget #6 run. The
  negative control runs there. The job runs whenever `pr.yml`'s `py` filter matches.
- **The nightly.** `.github/workflows/chaos-ws-nightly.yml` runs at 03:29 UTC on `main`, on `ubuntu-latest`, and can
  be dispatched on any branch (`workflow_dispatch`). It adds the three `harness` tests.
  - It is one pytest call, the workflow's `pytest` step, with `-m "chaos and not flaky"`.
  - It has no retries.
  - Its `-rA` output carries the records quoted below, under PASSES in the job log: `grep -E "#410|D8 "` finds them.
  - The `chaos-ws-junit` artifact keeps the JUnit report for 14 days.
- **A red night.** It comments on, or opens, the `chaos-ws` signal's bot-owned issue through `_nightly-issue.yml`, with
  the labels `qa`, `area/backend-platform` and `priority/p1`, titled `chaos: ws gateway nightly failed (YYYY-MM-DD)`.
  A red night blocks the next release (C-9.2, C-13.6). `docs/ci-runbook.md` §2, **Nightly WS chaos**, says how to
  triage one.
  - It pages no one: CI has no path into Alertmanager.
  - The orchestrator accepted the issue as the interim for E04's "page the on-call channel" (ruling R5).
  - The page needs an owner action, the CI-to-Alertmanager webhook secret, which is recorded on #2701.
- **A flaky test.** It is quarantined within 24 hours per C-9.3: `@pytest.mark.flaky` and a P1 ticket
  (`docs/ci-runbook.md` §2 and §9). The nightly's `not flaky` keeps the quarantine.
- **Locally:** `cd services/api && uv run pytest tests/chaos/ws -m chaos --no-cov`. On a loaded host the
  `harness` budget #6 run can fail from CPU contention alone (Deviation 7).

**The recorded runs**, each dispatched on `ubuntu-latest`:

| Run         | Ref, head                                                  | Result    |
| ----------- | ---------------------------------------------------------- | --------- |
| 39723269576 | `main` at `3dadb3d9` (#4088's merge), before #4104's tests | 17 passed |
| 39723275319 | #4104's branch at `f9c90eb8`                               | 21 passed |
| 39727981409 | #4104's branch at `9551bd6f`                               | 21 passed |

From run 39727981409's head (`9551bd6f`) to #4104's last head, `65cf1df2`, only `SCENARIOS.md`'s text changed; #4104
merged as `ea40712c`, and no run exists at `main`'s tip yet. From 39723275319's head to
39727981409's, the review folds changed the tests, among them the negative control's median check and the per-symbol
frame asserts, and a rebase moved the base onto `main`. #4104's own commits change only `tests/chaos/ws`.
`candleviewer/ws` is the same in runs 39723269576 and 39727981409; between the two branch runs, the generated
`error_codes.py` is its only difference.

## Scenario status

| #   | Scenario                                  | C-13.6                                    | Tests                                     | Result                 |
| --- | ----------------------------------------- | ----------------------------------------- | ----------------------------------------- | ---------------------- |
| 1   | Upstream kill (G3), gateway half          | #1 (and the gateway's reaction to #3)     | `test_s1_upstream_kill.py`, 4 cases       | pass, all three runs   |
| 2   | Slow consumer, 60 s (G4, P6)              | #11                                       | `test_s2_slow_consumer.py`, 2 cases       | pass, all three runs   |
| 3   | Burst, 5 000 msg/s                        | none (23 §16.4's row; the nearest is #11) | `test_s3_burst.py`, 4 cases (#4009)       | pass, all three runs   |
| 3   | The other nine symbols and budget #6      | none (06 §9's isolation clause)           | `test_s3_burst.py`, 4 more (#4104)        | pass, both branch runs |
| 4   | Restart, `shutdown_notice` (§9.4)         | none (23 §16.4's row)                     | `test_s4_restart_shutdown_notice.py`, 1   | pass, all three runs   |
| 5   | Token expiry during an outage             | none (§4.3, §9.2)                         | `test_s5_token_expiry_outage.py`, 2       | pass, all three runs   |
| 6   | Grant revoked mid-reconnect (E17-X02)     | none                                      | `test_s6_revocation_reconnect_race.py`, 2 | pass, all three runs   |
| 7   | Kill switch on every socket, gateway half | none (WS-E04, AC-26)                      | `test_s7_kill_switch_propagation.py`, 2   | pass, all three runs   |

Scenario 1 reads C-13.6 #1's "mid-snapshot" as a subscription attached during the outage, and does not cover repeated
kill and restore cycles, the storm; `SCENARIOS.md` says so. No scenario is xfailed, and none found a gateway defect
(DoD item 5: nothing to file).

## Measured values

**Scenario 1, the upstream kill.**

- In all three runs, the upstream was down 10.000 s virtual, 20 stray deltas were refused, and the 3 re-snapshots took
  0 s of virtual time.
- They landed this long after the recovery (loop time, printed, not asserted):

| Run         | Flag off | Flag on  |
| ----------- | -------- | -------- |
| 39723269576 | 1.66 ms  | 42.23 ms |
| 39723275319 | 1.68 ms  | 42.17 ms |
| 39727981409 | 1.62 ms  | 42.16 ms |

The flag-on figure is the harness's Nagle and delayed-ACK stall on its accepted sockets, as `SCENARIOS.md` says.

**Scenario 2, the D8 record** (a 60 s pause, in virtual time):

| Run         | tracemalloc peak | Accounted peak | Ratio | Healthy loop p50 / p95, with the sleeper (traced) | Without (untraced) |
| ----------- | ---------------- | -------------- | ----- | ------------------------------------------------- | ------------------ |
| 39723269576 | 10160258 B       | 8415626 B      | 1.207 | 22.42 / 60.27 ms                                  | 3.17 / 43.03 ms    |
| 39723275319 | 10159542 B       | 8415626 B      | 1.207 | 24.08 / 62.12 ms                                  | 3.22 / 43.15 ms    |
| 39727981409 | 10158887 B       | 8415626 B      | 1.207 | 22.04 / 59.88 ms                                  | 3.04 / 42.97 ms    |

- **The accounted peak** is queued 8355823 B + pending 59803 B, in 212 frames, in every run.
- **Step 1** fired at 39.875 s virtual, with the class `saturated`, and the stream ran at 235 KiB/s.
- **The peak is over 8 MiB (8 388 608 B) by design.** The pause takes the connection over the budget, and step 1
  answers it. At most one frame is pushed between two checks, the bounded overshoot of 23 §8.4 and §8.6. The test
  asserts all of this.
- **The healthy clients.** Their 10 % allowance is met on the virtual clock: 0 ms added, the same frames byte for byte,
  no gap; that allowance is evidenced on the virtual clock only. The loop times above are wall time: the with-sleeper
  column has tracemalloc on for the pause and the other is untraced. tracemalloc slows the traced run, but how much of
  the gap that explains is not measured. They are printed, not asserted.
- **`s2b`, a sleeper holding orders it cannot shed:** step 3 came after 17.500 s virtual asleep (17.625 s in
  39727981409). The harness healed the lane 0.21, 0.23 and 0.22 ms (loop time) after the close, in run order; this is
  printed, not asserted, and times the harness's heal, not the sleeper's recovery.

**Scenario 3, the burst on one symbol.** Every run gave the same counts, and wall time varied from run to run:

| Length | Updates | Frames | Updates a frame | Windows     | Class notices | Wall time (µs an update)                      |
| ------ | ------- | ------ | --------------- | ----------- | ------------- | --------------------------------------------- |
| 10 s   | 50000   | 41     | x1220           | 40 of 1250  | 0             | 1.88 s (20.7), 1.93 s (22.0), 1.65 s (18.2)   |
| 60 s   | 300000  | 241    | x1245           | 240 of 1250 | 0             | 11.10 s (20.9), 11.42 s (22.2), 9.96 s (18.4) |

The wall times are in run order: 39723269576, 39723275319, 39727981409.

**Scenario 3, the other nine symbols** (the two branch runs, in run order: 39723275319, 39727981409):

- **10 s:** 9 symbols x 80 updates, each update its own frame at its publish, and byte for byte the control run's. They
  ran beside 50000 burst updates in 81 frames, with 93 RTT probes and no class notice. The test's burst run and its
  control run together took 5.41 s and 4.69 s of wall time.
- **60 s:** 9 x 480 beside 300000 burst updates in 481 frames, with 594 and 593 probes, in 30.37 s and 25.67 s.

**Budget #6** (p95 ≤ 20 ms, 06 §2): wall-clock latencies over 60 s of virtual stream per kind, as two 30 s runs each in
ABBA order, nightly only. Each runs from the publish to the client's arrival through the proxy, an upper bound on 06 §2's
backend span. The test's five checks and their bounds are in `SCENARIOS.md` (budget #6 in wall time):

| Run         | The nine beside the burst, p50 / p95 / max | Without it            | The burst's window from its release | Over 100 ms | Failed |
| ----------- | ------------------------------------------ | --------------------- | ----------------------------------- | ----------- | ------ |
| 39723275319 | 1.95 / **3.24** / 4.36 ms                  | 1.05 / 1.91 / 3.08 ms | 2.25 / **6.77** / 7.09 ms           | 0           | none   |
| 39727981409 | 1.47 / **2.29** / 4.00 ms                  | 0.83 / 1.52 / 2.70 ms | 2.81 / **6.45** / 6.89 ms           | 0           | none   |

**The negative control** holds the loop 25 ms in each slice of the nine and before each move. In run order
(39723275319, 39727981409):

- **Asserted:** it fails the nine's p95 (154.38 and 153.02 ms), the window's p95 (33.94 and 32.74 ms) and the median the
  burst adds. The median is asserted from `9551bd6f`; at `f9c90eb8` only the two p95s were.
- **Printed, not asserted:** it also trips the stall count, 48 updates over 100 ms in each run, and stays under the 1 s
  ceiling (the nine's max was 154.66 and 153.18 ms).

**Scenarios 4 to 7** print no figure. Each passed its assertions in all three runs.

## Deviations

None is hidden. R2 to R10 are the rulings on #410's plan, which the orchestrator made in its coordination thread. It
ruled on items 1 to 7, 9 and 10: R2 (as approved: recorded, not filed), R5, R6 and R9 on 2026-10-21 at 02:51Z, and
budget #6 on 2026-10-22 at 00:48Z. Items 8, 11 and 12 are risks or limits the plan and `SCENARIOS.md` recorded. Item 13
lists limits against the ticket's own text that no ruling covers. The follow-ups are recorded on #410, not filed (the
filing freeze; issuecomment-6337715027): items 1, 4, 8 and 11 below, the `type/test` kind map (until it lands,
`qa-guard` reopens #410 when this PR closes it), the `chaos` marker's wording, and #4088's two gaps.

1. **No ingestion-side proxy** (R2, R9 a). The ticket's second proxy, between ingestion and a recorded upstream, is not
   built: nothing feeds the hub until the book publisher, #604.
   - Scenario 1 therefore plays the publisher, with production APIs only and nothing patched, and is labelled
     "gateway half".
   - It encodes 23 §7.4's table as the publisher's contract. If #604 does otherwise, this stays the gateway half and
     is no proof of G3 end to end.
   - The end-to-end run, over #604 and the E08 Rig, is recorded on #410 (issuecomment-6337715027) and in
     `SCENARIOS.md`, and not filed, under the filing freeze.
2. **No RSS cross-check** (R9 b). D8's accounting is asserted at every budget check, and the tracemalloc peak and its
   ratio are printed, as ruling D8 (23-ws-protocol.md) asks.
3. **Scenario 2's partial workspace** (R9 c). It has no `bars` or `footprint` panes, because no bar builder is wired
   into the harness. Step 3's redrop trigger is pinned by unit tests (`test_pipeline_ladder.py`), not end to end.
4. **"All six scenarios" means the ticket's 1 to 6** (R9 d). Scenario 7, the E17-X01 hand-off, is the gateway half:
   its producer half waits on #956.
5. **No C-13.6 row for the burst or the restart** (R9 e). Scenarios 3 and 4 cite 23 §16.4, and scenario 3's nearest
   row is #11. No amendment is sought: that is the owner's.
6. **The backpressure flag stays off** (R9 f). Scenarios 2 and 3 passing meet only #410's item of the flag gate. #568's run,
   #571's flag-on overhead re-measure, #413 and #2900 stay open.
7. **Budget #6 is measured on `ubuntu-latest`, not on the shared VPS.** There, three workers share the CPU at a load of
   7 to 12. In local runs reported in #4104's body, the nine's p95 measured 28 ms at a load of about 10, and 42 ms run
   alone at 7.5 to 11.6, against 20 ms. The orchestrator ruled on 2026-10-22 at 00:48Z that the dispatched nightly is
   the measurement.
8. **The pre-6.6-kernel portability run is not done.** It is #3468's follow-up: scenario 2 once on an older kernel,
   for the lane's `SO_RCVBUF` floor. The nightly's runner image is the PR lane's, so this is a portability check,
   not a nightly blocker.
9. **The nightly opens an issue rather than paging** (R5), as **How it runs** says.
10. **The results location** is `docs/qa/perf/` (R6), as above.
11. **Per-lane isolation on one socket is not covered.** Each of the nine symbols has its own connection
    (`SCENARIOS.md`), so the isolation deltas above are between connections, not between symbols sharing a socket.
12. **`SCENARIOS.md`'s scenario 2 paragraph still cites #3100 as a limitation,** though its fix (#3465) landed.
    Whether a sleeper without pings now closes at 45 s of virtual time during the pause is not re-verified, so that
    paragraph is left as it is (a risk #410's plan recorded).
13. **Limits against the ticket's own text:**
    - Scenario 3's burst arrives in lumps: 1 250 updates at one virtual instant per 250 ms tick. So a steady
      interleaving of updates and window closes is not exercised (`SCENARIOS.md`).
    - Scenario 2's 10 % p95 allowance is met on the virtual clock only, where added lateness is 0 by construction.
    - Scenario 4's "order entry off" is the harness client's own flag. The UI, and its screen-reader announcement,
      belong to E17-Q04.
    - The ticket asks each scenario to assert that its `cv_ws_*` series moved. Scenarios 5, 6 and 7 assert none.
    - Scenario 1's `trades` re-snapshot carries `upstream_reconnect`, which is not one of the incident reasons
      (`INCIDENT_REASONS` in `ws/sequencing.py`) that the Gherkin's "incident reason" names.
    - Recovery times are recorded for scenario 1 only. `s2b`'s figure times the harness's heal; the sleeper's resync
      is not timed.

## Definition of Done

| DoD item                                                                | State                                 | Evidence                                                                                         |
| ----------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------ |
| All six scenarios implemented, deterministic and green                  | met                                   | the status table; the three runs above; `SCENARIOS.md`                                           |
| Peak memory, recovery times and isolation deltas recorded on the ticket | met (recovery times: scenario 1 only) | Measured values, above; #410 issuecomment-6337714613 (R6)                                        |
| Nightly CI job wired with alert routing                                 | partial                               | `chaos-ws-nightly.yml` (added by #4088) and its `chaos-ws` issue; a page waits on the owner (R5) |
| Results appended to the E17 test plan                                   | met                                   | this file, linked from `qa/plans/e17-ws-conformance.md` §4 (R6)                                  |
| Any defect found filed, triaged and P0/P1 fixed before R1 exit          | met                                   | none found                                                                                       |
| QA lead sign-off                                                        | pending                               | the orchestrator's QA lens, after five consecutive green nightlies posted on #410 (R7)           |
