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
