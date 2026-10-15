# Upstream liaison log — `basiltt/xstate-statemachine`

Standing log for chore E50-C17 (one entry per upstream release or status change). Owner of the
rules: ADR-0016 (`docs/plan/27-adrs/ADR-0016-statechart-runtime.md`, "Upstream liaison" and the pin
discipline). This file records **observations only**; it never moves the pin.

## Current state (observed 2026-10-14, read-only via `gh`)

| Item                                      | State                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Pin in use                                | `xstate-statemachine==0.9.1` (tag `v0.9.1` = `45bb7f3`)                                                                                                                                                                                                                                                |
| Meta issue #26                            | **CLOSED**, last comment 2026-09-17, last update 2026-09-23. Its body is the round-13 report (0.9.0). The round-14 report is still a **draft, not posted** (`issues/post-v0.9.1/meta-26.md`, manifest `"posted": false`).                                                                              |
| R14-01 (`re_mint` `type=`/`src=` forgery) | Draft only (`issues/post-v0.9.1/new/R14-01-*.md`); **no upstream issue found** by search. In `v0.11.0` source, `events.re_mint(original, **fields)` still forwards every override to `_replace`, so by reading the code it looks **unfixed**. Not confirmed with our repro. `CV-C68` therefore stands. |
| Upstream issue list                       | Newest open issue is #364 "Battle-test programme (0.11.0)". Nothing there is a CandleViewer-filed defect.                                                                                                                                                                                              |

### Releases after 0.9.1

| Release                         | Date               | Re-verification needed?                                                                                                                                                                          |
| ------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| v0.10.0 – v0.10.5               | 2026-09-24 → 09-25 | Informational. Release notes cover the CLI toolkit (`xsm simulate` etc.); no core-engine claim seen. Superseded by 0.11.0.                                                                       |
| **v0.11.0** (`1b21501`, Latest) | 2026-10-13         | **Yes.** Snapshot layout **v4** (0.10.x cannot read v4), durable deadlines, new plugin-discovery opt-in, idempotency scope escaping, large integration surface. Notes say core is still pre-1.0. |

Release notes say new snapshots add `machine_version` and `deadlines`, which touches
`persistence.py` and the HMAC'd snapshot envelope (`machine_hash`, `minimum_version=3`). That is a
"snapshot-format change", which ADR-0016 (line 307) lists as failing the bump outright; any bump to
0.11.0 therefore needs an ADR-0016 amendment that addresses the v4 layout explicitly.

## Re-verification status

- **Not yet run against 0.11.0.** This PR does not run the gate (no network installs, no pin move).
  The next `xstate-nightly` `upstream` job (informational, latest PyPI) will be the first automated
  data point; the E50-C17 occurrence is not complete until its report and the steps below are attached.
- Acceptance criterion: gate + contract suite run against a new release **within one sprint** (1-week
  sprints) of publication, so for 0.11.0 by **2026-10-20**.

## Standing procedure (per upstream release)

1. **Detect.** `gh release list -R basiltt/xstate-statemachine`; also read the `upstream` job note of
   `.github/workflows/xstate-nightly.yml` (E50-T04, `tools/statechart/nightly_gate.py --mode upstream`).
2. **Gate.** Run `docs/research/xstate/gate/run_gate.py` against the candidate; compare with the
   committed baseline `docs/research/xstate/gate/result-v0.9.1.json`.
3. **Contract suite.** `pytest tests/xstate_contract -W error::RuntimeWarning` on both engines and
   both service spellings (E50-T31), against the candidate in a scratch environment.
4. **BENCH-6.** `docs/research/xstate/bench/bench_c_timers_v2.py`; p99 ≤ 100 ms at 500 busy machines
   (P3-G6, target hardware).
5. **Constraint check.** Re-run our repro for each open constraint (now: R14-01 / `CV-C68`). A
   constraint retires only when the fix is verified on both engines.
6. **Record.** Add a dated entry below with results, even if red.
7. **Decide.** Any new Blocker, suite/coverage regression, BENCH-6 breach or snapshot-format change
   fails the bump. Only when gate **and** contract suite are green is an ADR-0016 amendment proposed.

## Pin-bump path (never inside the liaison PR)

A separate PR, owned by its own ticket, containing: the ADR-0016 amendment with the dated gate,
contract and BENCH-6 output; the new `==` pin with sha256 lock and PEP 740 attestation verify
(`pypi_attestations verify pypi`); a `machine_hash` bump plus version bump or registered upcaster
with a golden-snapshot test if semantics change; `machine_hashes.lock` regenerated. Security-review
applies (dependency manifest). For 0.11.0 specifically, the snapshot v4 rolling-deploy constraint
(old readers cannot read v4) must be addressed in that amendment.

## Open items for the owner

1. Post (or decide not to post) the round-14 comment on upstream #26, which is closed; consider
   reopening it or filing R14-01 as its own issue. Nothing has been posted from this repo.
2. Authorise the 0.11.0 re-verification run (needs installing the candidate; target-hardware runner
   `CV_TARGET_HW_RUNNER` for BENCH-6).
3. Confirm that the E50-C17 DoD item "docs in `29-statechart-adoption-plan.md` still accurate" is
   reviewed against 0.11.0 once the run exists.

## Log

| Date       | Entry                                                                                                            |
| ---------- | ---------------------------------------------------------------------------------------------------------------- |
| 2026-10-14 | Initial entry: state above. 0.11.0 flagged as needing re-verification; R14-01 appears unfixed by source reading. |
