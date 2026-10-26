# E01 governance exploratory charter

Format per `docs/plan/03-testing-strategy.md` §11.2. Executed 2026-09-26, timebox 90 minutes, by the
E01-Q01 QA session (sprint01-r3 implementer).

## Mission

Probe the governance controls shipped by E01 for bypasses: can a determined, non-malicious engineer
in a hurry get non-compliant work onto `main`, or close a ticket without its gates, without deliberately
attacking the system?

## Areas probed

1. Rule-reference and duplication checkers (GOV-002/GOV-003) — can a citation or restated list slip
   through if worded slightly differently than the checker expects?
2. CODEOWNERS coverage (GOV-001) — can a genuinely new top-level path go unreviewed?
3. Backlog ticket schema (`validate.py`) — can a ticket with a real scheduling/dependency defect still
   merge into `all-tickets.json`?
4. Board close guards (kind-sync, qa-guard, security-guard, a11y-guard) — can a Story/Bug/security/a11y
   ticket be closed without its evidence, via a forged marker, a self-approval, or a missing-field
   dodge?
5. Branch-protection desired state — can a weakened setting pass the validator that applies it?
6. Rollout posture — is anything silently already-enforcing when the ticket says it should be
   observe-only, or vice versa (a guard that stayed silent when it should have fired, or fired when it
   shouldn't)?

## Oracles (what "looks wrong")

- A merge that should not have happened.
- A closed ticket missing its evidence.
- A guard that stayed silent.
- A confusing error that would drive someone to route around the process instead of fixing the cause.
- A checker that passes on a technicality (right shape, wrong content) rather than the actual intent.

## Session log (selected findings, chronological)

1. **GOV-002 wording sensitivity** — tried citing a rule id with trailing punctuation
   (`C-4.13,` and `C-4.13.`) instead of a clean word boundary, to see if the regex's `\b` boundary was
   too permissive and would silently treat a slightly-different-looking citation as satisfied when it
   should still resolve fine (this is the _good_ case — a real, still-valid citation with punctuation
   should still resolve). Confirmed: `RULE_ID_RE = re.compile(r"C-\d+\.\d+")` correctly extracts the id
   regardless of trailing punctuation, and the declaration check is independent of it. No bypass — the
   checker's scope (verify the id is _declared_, not verify formatting) is well-matched to its stated
   purpose.
2. **GOV-003 threshold gaming** — the registry uses a token-count threshold (e.g. 3 of N tokens). Tried
   restating exactly `threshold - 1` tokens (2, one below the 3-token bar for `required-check-names`) in
   a scratch addition to `AGENTS.md`, expecting it to _not_ fire (by design — this is meant to allow
   incidental overlap, not wholesale copies). Confirmed it did not fire at 2 tokens, and did fire at 3+.
   This is working as designed, but it is a soft spot worth naming: an engineer who wants to "reference"
   a list without triggering GOV-003 can do so by restating N-1 tokens plus paraphrasing the rest — the
   check catches verbatim copies, not paraphrased duplication. Filed as an observation, not a bug (the
   ticket that owns GOV-003, E01-T01, explicitly scoped it as fingerprint-based, not fuzzy).
3. **qa-guard self-signoff via a second account impersonating write access** — the guard trusts
   `gh_adapter.has_write_access` (a real collaborator-permission API call) rather than any
   self-reported field. Traced the code path: there is no way for the _closing_ actor to also be the
   accepted sign-off commenter (`comment.author_login == closer_login` is explicitly excluded). The
   only remaining route to bypass would be a second GitHub account that itself holds real write access
   on the repo — at which point this is no longer "an engineer in a hurry" but "a second legitimate
   collaborator", which is exactly what separation-of-duties is meant to permit. No bypass found within
   the charter's threat model (excludes adversarial privilege per the ticket's own Out-of-scope note).
4. **a11y-guard foreign-link check** — read `guard_a11y.py`'s link-validation regex/logic (not just its
   tests) to check whether a same-repo link to an _unrelated_ Actions run (e.g. a run from a totally
   different, unrelated PR) would be accepted just because it's repo-scoped. Confirmed the guard checks
   repo-scope only, not run-relevance-to-this-issue. This is a genuine, if narrow, bypass: a hurried
   engineer could satisfy the guard by pasting _any_ real Actions run URL from the same repo, not
   necessarily the one that actually ran the a11y sweep for their change. **Filed as QA-BUG-E01-004,
   P2** (workaround exists — a human reviewer reading the linked run would notice; not a P1 because it
   requires the closer to also fabricate a plausible-looking but wrong link, which is a deliberate act
   past "in a hurry", but still worth tightening in E01-Q02).
5. **validate.py's silent `all-tickets.json` rewrite** — already filed as QA-BUG-E01-003 in the test
   plan; re-confirmed during the charter as a "confusing (non-)error": running the validator in what a
   newcomer would read as "check only" mode leaves a dirty working tree, which is exactly the kind of
   friction that drives someone to `git checkout -- .` and lose real backlog edits, or to stop running
   the validator locally at all.
6. **Branch-protection validator vs. partial-object PUT risk** — re-read the `$comment` in
   `.github/branch-protection.json` warning that "a full PUT... replaces the whole object... this file
   must stay complete." Confirmed `apply_branch_protection.py`'s `validate_desired_state` checks for the
   presence of every required top-level key before allowing an apply — an engineer who edits only one
   key and leaves the rest of the file untouched (the realistic "in a hurry" scenario, not a from-scratch
   partial object) cannot accidentally trigger the destructive-partial-PUT failure mode the comment
   warns about, because the file is never partial to begin with. No bypass.

## Debrief

- **Time spent**: ~90 minutes (code reading + 6 targeted probes, 2 of them mutating scratch state and
  reverting, per §0 of the test plan).
- **Did a merge that should not have happened, happen?** No — not reachable from this session (no live
  admin/rulesets access on GitHub Free; separately verified as a real capability gap, not a control gap,
  in the test plan §1).
- **Did a closed ticket miss its evidence?** No new instance found; one narrow bypass in the a11y-guard's
  link-relevance check (finding 4) that a hurried-but-not-adversarial engineer could exploit by accident
  (pasting the wrong-but-real run link) more easily than on purpose.
- **Did a guard stay silent when it should have fired?** No silent guard found.
- **Was any error message confusing enough to drive someone around the process?** Yes — the
  `validate.py` silent-rewrite behaviour (finding 5 / QA-BUG-E01-003) is exactly this failure mode,
  though for backlog hygiene rather than a safety-relevant control.
- **New bugs from this charter**: QA-BUG-E01-004 (P2, a11y-guard link-relevance). QA-BUG-E01-003
  reconfirmed from the test plan.
- **Bypass found during exploration is filed, not absorbed**: per the ticket's negative acceptance
  scenario, QA-BUG-E01-004 is filed as a standalone Bug ticket (see §9 of the test plan and the tracked
  P0/P1 gate in Done means), not silently patched by this QA ticket, and not folded into E01-T07's
  already-merged scope.

## Follow-up

- File QA-BUG-E01-004 on the board with `security`-adjacent but not `security`-labelled (it's an a11y
  evidence-integrity gap, not a security bypass) — P2, referencing this charter.
- Hand §10 of the test plan (automatable cases) to E01-Q02 alongside this charter.

## E01-Q02 governance job duration budget (measured)

- Before (6 PR runs): 61.4-66 s wall; the 60 s budget failed on pure runner variance.
- Profile: unit tests ~40 s (3 slow tests: licence-headers 25 s, event-coverage 15 s, error-registry 12 s), pip install 3-6 s, checkout ~5 s, every GOV script <=1 s.
- Optimisations: pip cache, `pytest -n auto` (xdist). Full-depth checkout is kept because `tools/ci/verify_migration_lockfile.py` needs `git merge-base`.
- After: ~60 s on the PR run (xdist gains are limited on 2-vCPU runners), so the optimised median is not <40 s.
- Budget set to 90 s (measured max ~66 s + ~35% margin). The duration step prints a timing table to the step summary so drift is visible.

### Follow-up: faster job, same budget (#2557)

- Before (26 PR runs, 2026-10-15): 45-92 s as measured by the budget step, median 77 s; 3 of the 26 failed on the budget alone. The unit-test step took 26-62 s, and most of that was a tail: on the slowest run the last test finished 38 s after 95% of the suite. The CODEOWNERS scan also ran twice (the check, then the report artefact), about 4 s each on slow runners.
- Profile (local, `-n 4`): the tail is two real-repo tests, `test_event_coverage` (8.6 s) and the four `test_error_registry` real-document tests (1.5-3 s each). Most of their time was coverage overhead in code that is not measured: the default `ctrace` core makes a trace call for every frame of the `ast` and PyYAML work, although only `scripts/**` is measured. Without coverage they take 3.1 s and 3.5 s.
- Changes: `COVERAGE_CORE=sysmon` on the unit-test step (line coverage only, so `sys.monitoring` works on Python 3.13; the per-file coverage report is byte-identical), `--dist worksteal`, and GOV-001 writes the ownership report in the same run (`--report-file`) with one matching pass per path. The old report step now runs only when GOV-001 did not run.
- After (local, `-n 4`, median of 3): unit-test step 17.45 s to 7.81 s; GOV-001 check plus report 2.57 s to 0.68 s. The CI timings are in the fix PR for #2557.
- Unchanged: `BUDGET_MS=90000`, the budget step stays blocking and last, the 85% coverage gate on `scripts/**`, and the canary self-test.

### Follow-up: three parallel jobs, same budget (#3789)

- Before (18 PR runs, 2026-10-19): job wall median 83.5 s, p95 97 s, max 99 s. With every test green, the budget step failed on 20 of the day's 158 attempts before the fix (13%), and on 8 of the last 23 attempts (5 of the last 18 runs). The unit-test step took a median 55.5 s (max 69 s); checkout 6 s, the pip install 3 s, setup-python 2 s, GOV-001 2 s, every other check or report step 0-1 s. The suite is CPU-bound: locally on 4 CPUs, without semgrep as in CI, `-n 4` took 25.4 s and `-n 8` 31.6 s; coverage costs about 10%.
- Changes: `governance.yml` runs its three job definitions in parallel. `governance-checks` keeps every GOV check, the canary and the reports. Four `governance-tests` shards (#4365; two before) split the files `pytest scripts/tests scripts/gh/tests` collects by measured duration (`tools/ci/governance_shards.py`, greedy, heaviest first) and write raw coverage data. `governance` needs all of them, combines the data, applies the 85% gate on `scripts/**` and fails unless every other job passed, so the `governance` check still means the whole set. `test_real_repo_wiring_is_resolved_and_clean` scans the tree once instead of twice (7.4 s to 3.8 s locally). Each job keeps the blocking budget step, last.
- After (local, 4 CPUs, CI-like): shard 1 12.2 s, shard 2 13.6 s, against 27.7 s for the whole suite in one run; the combined coverage is identical (16446 statements, 534 missed, 97%). The CI timings are in the fix PR for #3789; the 20-run table follows in its QA record.
- Unchanged: `BUDGET_MS=90000` (now per job), the 85% coverage gate (on the combined data), the canary self-test and every GOV check.

### Follow-up: infra suites in the shards, same budget (#4361)

- Before: `infra/scripts/tests`, `infra/alertmanager/tests` and `infra/grafana/tests` held 146 tests that pin the infra scripts, alert rules and dashboards CI and the deploy path rely on. No workflow ran 128 of them, so one assertion (`test_page_alert_payload_carries_no_ids_or_key_material`) had been red since `ingestion.yml` landed, and nothing said so. The other 18 are `test_live_render.py`, which needs a running Grafana and runs only in the integration lane, on the merge queue.
- Changes: `tools/ci/governance_shards.py` adds the three directories to `SUITES`, weights the two new files that cost 0.5 s or more, and keeps `test_live_render.py` out through a new `EXCLUDED` map, because under `CI=true` without `GRAFANA_URL` it fails by design. The wired suites need only PyYAML and pytest (`scripts/requirements-ci.txt`), and `governance.yml` is unchanged: it already runs on every pull request. `scripts/tests/test_no_orphaned_test_dirs.py` fails on any `test_*.py`, `*_test.py` or promtool `*.test.yml` under `infra/`, `tools/` and `scripts/` that no workflow runs, and pins that governance still starts on every pull request.
- After, on #4365's four shards: the eight infra modules and the pin test add 2.56 table-seconds to the 176.40 s split. Shard 1 stays at 48.98 s (`test_e12_security_gates.py` alone), and shards 2 to 4 go from 42.46-42.49 s to 43.32-43.34 s, so the spread narrows from 6.52 s to 5.66 s and no shard sits more than 10% over an even split. `WEIGHTS` gains `test_alerting_config.py` (1.33 s) and `test_no_orphaned_test_dirs.py` (0.53 s): each was measured the table's way, in two runs beside six files of the table on a loaded shared VPS, and scaled to those six; every other new file is under the 0.5 s floor. The combined coverage of `scripts/**` is unchanged by the wired suites (97%; `--cov=scripts` never measured `infra/`). The CI timings are in the fix PR for #4361.
- Unchanged: `BUDGET_MS=90000` per job, the 85% coverage gate, the canary self-test and every GOV check. A shard that mixes `scripts/` and `infra/` files reads the root `pytest.ini`, and one of `scripts/` files only reads `scripts/pytest.ini`; `test_governance_shards.py` pins that the two configure pytest alike.

### Follow-up: the budget measures the suite, not the runner (#4666)

- Before: each job's budget step judged the job wall time, checkout, installs and artifact transfers included. Under runner contention on 2026-10-26 (three merge-group builds and several PR runs at once) the shards' pytest wall time stayed at about 55-65 s while provisioning stretched the jobs past 90 s, and green pull requests went red on the budget alone three times, each needing a "Re-run failed jobs": #4651 at ~19:00Z, #4650 at ~21:00Z (`governance-tests (1/6)` at 1m41s and `(3/6)` at 1m39s of job wall time) and a `governance` combine job at 94 s earlier in the day.
- Rule: the budget measures the suite. Each `governance-tests` shard budgets its pytest wall time (`pytest_ms`, taken around the pytest call alone) and `governance` its combine step (`combine_ms`: the coverage combine and the 85% report). The job wall time stays in each job summary as an informational row and fails nothing. A run that recorded no time (its step failed or never ran) fails the budget instead of passing unmeasured. `governance-checks` is unchanged: its checks are the job's own work, and it still budgets the job wall time.
- After: judged by the rule, the same runs pass: about 55-65 s of pytest wall time is under 90 s, and the 94-101 s job wall times are reported, not judged. A shard whose pytest wall time passes 90 s still fails with the E01-Q02 error. `scripts/tests/test_governance_yml_budget.py` runs the budget steps' own scripts: a 60 s run in a 150 s job passes, a 90.001 s run fails, and a run with no recorded time fails.
- Unchanged: `BUDGET_MS=90000`, the budget step blocking (`continue-on-error: false`) and last in every job, the 85% coverage gate on `scripts/**`, the canary self-test and every GOV check.
