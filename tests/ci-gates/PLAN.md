# E03 CI gate black-box test plan

Ticket: E03-Q01 (issue #208). Owner: QA. Status: **Draft — pending dry-run execution and second
QA/SDET peer review** (Definition of Done item 1).

This plan is the black-box verification that every required check named in `CONSTITUTION.md` C-9.1
actually fails on the input it claims to catch, and passes cleanly on a no-op change — because a gate
that fails everything is as useless as one that fails nothing. It has no knowledge of the pipeline's
internals beyond the public error-code contract each job publishes (`docs/ci-runbook.md` §2, §4) and the
tool source under `tools/ci/` and `scripts/`.

## 0. How to use this plan

- **Audience:** a QA/SDET with a clone of the repo and no author context.
- **Row scope:** one row per required check name from `CONSTITUTION.md` C-9.1 (columns "Check name" /
  "#"), reproduced here **by reference only** (name + gate number) — the gate _definition_ is never
  restated (C-16.5); see `docs/ci-runbook.md` §2 for the job map.
- **Case id scheme:** `E03-GT-<NN>`, one positive + one negative id per row where both are proven
  end-to-end (unit level, in-process); some rows are proven by an existing scripted unit test already
  shipped by the owning task ticket (E03-T05/T06/T07/T09/T13) — those are marked `existing` in the
  Automation column and re-run, not re-implemented, to avoid duplicating another ticket's coverage.
- **Fixtures:** `tests/ci-gates/fixtures/*` (scripted, not long-lived branches — `make ci-gate-fixture
<name>` regenerates a fixture's inputs on demand so cases stay valid as the codebase evolves).
- **Runner:** `python tests/ci-gates/run_fixtures.py [--case <id>]` drives every fixture against the
  real gate script it targets and asserts the _expected_ PASS/FAIL, printing "expected FAIL, observed
  FAIL" (or the mismatch) so a reader never misreads a red run as a problem (Technical notes).
- **Synthetic-only rule (SR-145):** the planted-secret fixture uses an obviously fake, dummy-prefixed
  string (`CV_TEST_DUMMY_SECRET_...`) asserted by its own test to never match a real key shape. No case
  in this plan ever uses or requires a real credential.

## 1. Required-check matrix

| #          | Check (C-9.1)                           | Positive case                                                                                                   | Negative case                                                                             | Error code                              | Automation                                                                                                                                                                               |
| ---------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1          | `lint`                                  | `E03-GT-01a` clean file                                                                                         | `E03-GT-01b` Ruff `E501`/ESLint error injected                                            | n/a (tool exit 1)                       | manual dry-run (tool invocation, no wrapper script)                                                                                                                                      |
| 2          | `typecheck`                             | `E03-GT-02a` clean types                                                                                        | `E03-GT-02b` `mypy --strict` type error injected                                          | n/a                                     | manual dry-run                                                                                                                                                                           |
| 3          | `unit-backend`                          | `E03-GT-03a` passing pytest module                                                                              | `E03-GT-03b` one assertion flipped to fail                                                | n/a                                     | manual dry-run                                                                                                                                                                           |
| 3,4,5      | coverage thresholds (`CI-COV-001..003`) | `E03-GT-04a` `coverage_gate.py` at/above floor                                                                  | `E03-GT-04b` below floor, `E03-GT-04c` baseline regression, `E03-GT-04d` missing artifact | `CI-COV-001/002/003`                    | existing (`scripts/tests/test_coverage_gate.py`), re-run                                                                                                                                 |
| 6          | `contract`                              | `E03-GT-05a` route matches OpenAPI op                                                                           | `E03-GT-05b` route with no matching operation                                             | `CI-CON-001`                            | existing (`services/api/tests/contract/test_openapi_conformance.py`), re-run                                                                                                             |
| 7          | `integration`                           | `E03-GT-06a` fixture manifest checksum matches                                                                  | `E03-GT-06b` corrupted checksum                                                           | `CI-INT-002`                            | existing (`scripts/tests/test_verify_fixture_manifest.py`), re-run                                                                                                                       |
| 8          | `e2e-smoke`                             | n/a — deferred to E03-Q02 harness (out of scope here)                                                           | n/a                                                                                       | `CI-E2E-001/002`                        | out of scope (E03-Q02)                                                                                                                                                                   |
| 9          | `a11y`                                  | `E03-GT-07a` axe-core run with zero serious/critical                                                            | `E03-GT-07b` a planted `serious` violation (missing `aria-label` on an icon-only button)  | `CI-A11Y-001`                           | `tests/ci-gates/fixtures/a11y/` (new, this ticket)                                                                                                                                       |
| 10         | `sast`                                  | `E03-GT-08a` clean SARIF                                                                                        | `E03-GT-08b` `cv-unpinned-action` Semgrep finding                                         | `CI-SEC-001`                            | existing (`scripts/tests/test_security_gate.py::*unpinned_action*`), re-run                                                                                                              |
| 10         | `sast` (secrets)                        | `E03-GT-09a` clean diff                                                                                         | `E03-GT-09b` synthetic dummy-prefixed secret (SR-145)                                     | `CI-SEC-001`                            | `tests/ci-gates/fixtures/secrets/` (new, this ticket)                                                                                                                                    |
| 11         | `sca`                                   | n/a (dep-audit clean lockfile)                                                                                  | `E03-GT-10b` expired accepted-risk entry                                                  | `CI-SEC-004`                            | existing (`scripts/tests/test_security_gate.py::*expired*`), re-run                                                                                                                      |
| 12         | `secrets-scan`                          | see `E03-GT-09a`                                                                                                | see `E03-GT-09b`                                                                          | `CI-SEC-001`                            | shared with row above                                                                                                                                                                    |
| 14         | `license-check`                         | `E03-GT-11a` allowlisted licence                                                                                | `E03-GT-11b` AGPL dependency                                                              | `CI-SEC-002`                            | existing (`scripts/tests/test_security_gate.py::*license*`), re-run                                                                                                                      |
| 16         | `engine-bench`                          | `E03-GT-18a` non-engine diff reported not applicable; `E03-GT-19a` no GPU runner registered, fallback, no alert | `E03-GT-18b` applicable lane failed; `E03-GT-19b` runner offline, fallback and alert      | `CI-GATE-001`, `CI-BEN-003/004`         | `tests/ci-gates/fixtures/engine_bench.py` (E03-T14); the GPU run itself (`CI-BEN-001`) needs a registered runner and is proven by the harness tests (`ci-compare.test.ts`, 5 % boundary) |
| 17         | `migrations`                            | `E03-GT-12a` single head                                                                                        | `E03-GT-12b` two heads, `E03-GT-12c` undecorated `op.drop_table`                          | `CI-MIG-001/003`                        | existing (`scripts/tests/test_migration_lint.py`), re-run                                                                                                                                |
| 18         | `architecture`                          | `E03-GT-13a` acyclic module graph                                                                               | `E03-GT-13b` a forbidden import edge                                                      | import-linter/dependency-cruiser exit 1 | manual dry-run                                                                                                                                                                           |
| 19         | `generated-code-check`                  | `E03-GT-14a` regenerated tree matches committed                                                                 | `E03-GT-14b` drifted `packages/protocol`, `E03-GT-14c` untracked generated file           | `CI-GEN-001/002`                        | existing (`scripts/tests/test_check_gen_freshness.py`), re-run                                                                                                                           |
| 20         | `pr-metadata`                           | `E03-GT-15a` conventional title + `Closes #N`                                                                   | `E03-GT-15b` non-conventional title                                                       | pr-metadata exit 1                      | manual dry-run                                                                                                                                                                           |
| governance | branch-protection reconciliation        | `E03-GT-16a` desired-state matches C-9.1                                                                        | `E03-GT-16b` a required-check job renamed without updating `branch-protection.json`       | `CI-PROT-002`                           | `tests/ci-gates/fixtures/protection/` (new, this ticket — Scenario 4 of the ticket AC)                                                                                                   |
| governance | bypass register                         | `E03-GT-17a` fresh review date                                                                                  | `E03-GT-17b` expired review date                                                          | `CI-PROT-004`                           | existing (`scripts/tests/test_check_bypass_register.py`), re-run                                                                                                                         |

Rows without a fixture id in the Automation column and marked "manual dry-run" are proven by directly
invoking the underlying, already-shipped CI tool (Ruff/ESLint/mypy/pytest/import-linter/pr-metadata
resolver) against a one-line deliberately broken scratch file inside the QA session, observing the
non-zero exit, then discarding the scratch file — no fixture directory is needed because the tool
itself _is_ the fixture target and already has its own unit tests upstream; re-implementing a second
harness around a generic linter would duplicate, not add, coverage.

## 2. New fixtures this ticket adds

`CI-PROT-002` (renamed required check silently dropped from branch protection) had **no existing
proof** anywhere in the repo — `scripts/check_required_check_reconciliation.py` implements the
reconciliation logic (job names vs. `CONSTITUTION.md` §9 vs. `branch-protection.json`) but ships with
no test asserting the drift path actually raises. `tests/ci-gates/fixtures/protection/` closes that gap:
a scratch `branch-protection.json` + scratch `.github/workflows/*.yml` where `coverage-thresholds` is
renamed to `coverage-check`, asserting the reconciliation script's exit code is non-zero and its output
names the missing job — matching AC Scenario 4 verbatim.

`a11y` (row 9) and `secrets` (row 9/12) had partial coverage (the underlying tools are real and used in
CI) but no scripted, offline negative fixture proving the _gate's own_ threshold behaviour without a
live browser/QuestDB stack; both are added as small, deterministic Python fixtures under
`tests/ci-gates/fixtures/` driven by `run_fixtures.py`.

## 3. Positive control

`E03-GT-00`: a one-line comment-only diff to this file's own header touches no code path. Expected: every
applicable check above passes; none fail. This is the "gates are not indiscriminately red" proof
required by the ticket's second Gherkin scenario. Recorded in `tests/ci-gates/records/`.

## 4. Exploratory charter

See `tests/ci-gates/EXPLORATORY-CHARTER.md` for the 4-hour timeboxed session write-up (Scenario 3 of the
ticket AC).

## 5. Execution record

See `tests/ci-gates/records/2026-09-30.md`.

## 6. Sign-off

- [ ] Plan peer-reviewed by a second QA/SDET (Definition of Done item 1).
- [ ] QA sign-off comment posted on issue #208 with pass/fail per Gherkin scenario, `qa` label.
- [ ] Any bypass found by the exploratory charter filed as a `priority/p0-critical` Bug against the
      owning task before `E03` closes.
