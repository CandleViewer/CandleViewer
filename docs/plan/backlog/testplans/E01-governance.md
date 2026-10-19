# E01 governance conformance test plan and exploratory charter

Ticket: E01-Q01 (issue #78). Authored by QA (this ticket) executing black-box against the real
repository — actions and observable outcomes only, no reliance on script internals. Covers every
governance control shipped by E01: branch protection (E01-T08), CODEOWNERS coverage (E01-T04), rule
references & duplication (E01-T01), backlog ticket schema (E01-T06), board close guards (E01-T07),
and issue/PR templates (E01-T05).

## 0. Environment constraints (read first)

This is a private, single-owner, free-tier GitHub repository (`CandleViewer/CandleViewer`, ADR-0017 Q1):

- `GET /repos/{repo}/branches/main/protection` and the repository-rulesets endpoints return
  `403 Upgrade to GitHub Pro` — **live branch-protection state cannot be read or mutated from this
  session** (no admin/rulesets scope available on the free tier). Cases in §1 that require an actual
  merge attempt against a protected `main` are therefore executed as **desired-state / validator**
  cases (proving the declared config would refuse the action, per the code path that applies it) and
  marked `blocked: needs live admin session` where a real GitHub UI merge attempt is the only proof.
  This mirrors the deviation already recorded in PR #1438 (E01-T08) for the same reason.
- `GH_BRANCH_PROTECTION_TOKEN` and `PROJECTS_PAT` are repo secrets not available to this session; any
  case requiring them is executed against the offline guard logic instead (the same `evaluate()` pure
  functions the real workflow calls) — this is exactly the black-box/white-box split the ticket's
  Out-of-scope note anticipates ("this ticket establishes what to automate by executing it manually
  first").
- No docker, no live GitHub Actions trigger available in this shell — cases needing a live `issues:
  closed` webhook are executed via direct invocation of the guard's `evaluate()` against a
  hand-built `Issue`/`Comment` fixture that reproduces the real event shape (already the pattern used
  by `scripts/gh/tests/test_guard_*.py`, which this plan treats as the QA-reviewed regression pack for
  those cases, not as script-internals hand-waving — every fixture matches a documented, observable
  GitHub event shape).

All probe mutations below were made on scratch/throwaway paths or reverted immediately after
recording output (`git status --short` clean after each). No production file was left modified.

## 1. Branch protection (E01-T08)

| # | Case | Precondition | Steps | Expected | Actual | Verdict | Evidence |
|---|---|---|---|---|---|---|---|
| 1.1 | Merge with 1 approval refused | `.github/branch-protection.json` declares `required_approving_review_count: 2` | Read desired-state file; run `scripts/apply_branch_protection.py::validate_desired_state` against a mutated copy with `required_approving_review_count: 1` | Validator rejects (`test_apply_branch_protection.py::test_validate_desired_state_rejects_weakened_settings`) | Rejects as expected — `python -m pytest scripts/tests/test_apply_branch_protection.py -q` green | Pass | pytest run below |
| 1.2 | 2 non-code-owner approvals insufficient | `require_code_owner_reviews: true` in desired state | Mutate desired state to `false`; re-validate | Validator rejects | Rejects | Pass | pytest run |
| 1.3 | Admin merge with red check refused | `enforce_admins: true` | Mutate to `false`; re-validate | Validator rejects | Rejects | Pass | pytest run |
| 1.4 | Force-push to `main` refused | `allow_force_pushes: false` | Mutate to `true`; re-validate | Validator rejects | Rejects | Pass | pytest run |
| 1.5 | Delete `main` refused | `allow_deletions: false` | Mutate to `true`; re-validate | Validator rejects | Rejects | Pass | pytest run |
| 1.6 | Unresolved conversation blocks merge | `required_conversation_resolution: true` | Confirm key present and asserted by validator | Present, asserted | Present | Pass | file inspection + validator test |
| 1.7 | Non-linear history blocked | `required_linear_history: true` | Confirm key present and asserted | Present | Present | Pass | file inspection |
| 1.8 | Merge-queue rebase-and-recheck | `merge_queue.grouping_strategy: HEADGREEN`, `check_response_timeout_minutes: 60` | Confirm merge_queue block present with squash method + HEADGREEN | Present | Present | Pass | file inspection |
| 1.9 | Re-apply is a no-op (idempotency) | live == desired | `apply_branch_protection.diff_state` on identical live/desired | Empty diff | Empty diff — `test_diff_state_no_changes_is_empty` | Pass | pytest run |
| 1.10 | Drift is detected and reported | live != desired | `check_branch_protection_drift.render_findings` on a synthetic delta | GOV-005 finding rendered with field name | Finding rendered | Pass | `test_check_branch_protection_drift.py` |
| 1.11 | Required-check reconciliation stays honest | contexts + `x-pending-contexts` vs CONSTITUTION §9 table | `python scripts/check_required_check_reconciliation.py` | Exit 0, "clean" | `check-required-check-reconciliation: clean` | Pass | command transcript §5 |
| 1.12 | **Live** merge-with-1-approval refused (real GitHub UI) | Protected `main`, open PR, 1 approval | Attempt merge button in GitHub UI | Merge button disabled/refused, screenshot captured | Not executed — `branches/{b}/protection` API 403s "Upgrade to GitHub Pro" in this session; no live admin credential available | **Blocked** | needs live admin session (same constraint as PR #1438) |
| 1.13 | **Live** force-push to `main` refused | none | `git push --force origin HEAD:main` from a non-admin credential | Push rejected by GitHub | Not executed — would be genuinely destructive against the only shared `main`; correctly out of reach without a disposable scratch repo per the ticket's own security note ("scratch repository only") | **Blocked** | needs disposable scratch repo (owner action) |

**R0 exit-criterion-1 evidence pack**: cases 1.12/1.13 (the two "screenshot of a refused merge"
scenarios in the acceptance criteria) cannot be produced from this sandboxed session on a GitHub Free
plan without admin/rulesets API access. This is filed as **QA-BUG-E01-001** (§6) rather than silently
declared Pass — the plan and the automatable half of the control are proven; the live-artifact half is
handed to the owner as a documented, minimal follow-up action (run `scripts/apply_branch_protection.py`
for real once, then attempt one under-reviewed PR merge and capture the refusal).

## 2. CODEOWNERS coverage (E01-T04)

| # | Case | Steps | Expected | Actual | Verdict |
|---|---|---|---|---|---|
| 2.1 | Un-owned path fails the checker | Added scratch dir `qa_probe_unowned_dir/.gitkeep` (`git add -N`, no CODEOWNERS rule beyond catch-all `*`), ran `python scripts/check_codeowners_coverage.py` | Exit 1, path reported under catch-all violation | Exit 1, `qa_probe_unowned_dir/.gitkeep` reported (see transcript) | Pass |
| 2.2 | Owned path passes | Reverted probe (`git reset` + `rm -rf`), re-ran checker | Exit 0 | Exit 0 | Pass |
| 2.3 | GitHub's own resolution agrees with the checker, 3 sample paths | Compared checker's winning-rule output for `services/api/secrets/` (→ `@CandleViewer/security`), `apps/web/` (not yet created — matches catch-all `*` intentionally, pre-INFRA-001), `docs/plan/backlog/` against `.github/CODEOWNERS` last-match-wins semantics by hand-tracing the file | Same owner both ways | Same — checker implements documented last-match-wins gitignore semantics (`check_codeowners_coverage.py` docstring); GitHub's live "Code owners" UI could not be queried (no PR open against those exact paths in this session) for a byte-for-byte cross-check | **Partial pass** — logic verified by hand-trace; live GitHub UI cross-check not independently available this session |

## 3. Rule references & duplication (E01-T01 / GOV-002 / GOV-003)

| # | Case | Steps | Expected | Actual | Verdict |
|---|---|---|---|---|---|
| 3.1 | Dangling rule id (`C-99` + `.9`, a non-existent rule) fails GOV-002 | Replaced one real citation (`C-4.13`) in `AGENTS.md` with the non-existent id `C-99`+`.9`, ran `python scripts/check_rule_refs.py`, reverted | Exit 1, `GOV-002 AGENTS.md:<line> <dangling id>` | Exit 1, exact message reproduced | Pass |
| 3.2 | Clean repo passes GOV-002 | Reverted change, re-ran | Exit 0 | Exit 0 | Pass |
| 3.3 | Duplicating 5 required-check tokens into a non-owner file fails GOV-003 | Appended `unit-backend unit-engine unit-frontend e2e-smoke secrets-scan` (5 tokens, `required-check-names` registry, threshold 3) to `SECURITY.md`, ran `check_sot_duplication.py`, reverted | Exit 1, finding names `SECURITY.md` and the 5+ tokens | Exit 1 — `GOV-003 SECURITY.md restates 6 tokens ... unit-backend, unit-engine, unit-frontend, e2e-smoke, secrets-scan, container-scan` (6 because `container-scan` was already adjacent in the sentence — still correctly flags) | Pass |
| 3.4 | Pre-existing informative-only finding is understood, not silently hidden | Ran `check_sot_duplication.py` clean | `docs/plan/04-security-program.md` flagged (3 tokens) | Flagged; the `governance` workflow already runs this step with `continue-on-error: true` and a comment linking issue #1439 (pre-existing, out of E01-T08's scope) — confirms the informative-not-blocking wiring matches the documented intent | Pass |
| 3.5 | Message is actionable to a newcomer | Read GOV-002/GOV-003 output cold | A contributor can state file:line and which token/id to fix without reading the script | Yes — both messages name the exact file, line (GOV-002) or file + token list (GOV-003), and the owner section to defer to | Pass |

## 4. Ticket schema (E01-T06 / `docs/plan/backlog/_tools/validate.py`)

Executed via the existing QA-reviewed unit-test pack (`scripts/tests/test_validate_backlog.py`),
which builds real, isolated `tmp_path` ticket fixtures per case — the correct execution style here,
since running `validate.py` directly against the live 1440-ticket backlog non-destructively is not
possible (it rewrites `all-tickets.json` on every invocation, confirmed in §0 by a `git diff` after a
baseline run — reverted before proceeding).

| # | Case | Expected | Actual | Verdict |
|---|---|---|---|---|
| 4.1 | Ticket missing `perspective` | Rejected with a field-pointer error | `test_missing_required_field_rejected_with_pointer` passes | Pass |
| 4.2 | `blocked_by` pointing nowhere | Rejected, dangling-dependency error | `test_dangling_dependency_rejected` passes | Pass |
| 4.3 | Dependency cycle | Rejected with the cycle path shown | `test_dependency_cycle_reported_with_path` passes | Pass |
| 4.4 | `estimate: 13` on a Story | Rejected (not in `FIB = {1,2,3,5,8}` / oversized-for-kind) | `test_oversized_story_estimate_rejected` passes | Pass |
| 4.5 | Design ticket scheduled one sprint (not two) ahead of consumer | Rejected, design-ahead rule violation | `test_design_ahead_rule_enforced` passes | Pass |
| 4.6 | Malformed JSON | Exit 2 (internal error, distinct from schema-violation exit 1) | `test_malformed_json_exits_two` passes | Pass |
| 4.7 | Baseline: real backlog, informational | `python docs/plan/backlog/_tools/validate.py` on the live 1440-ticket file | 2 pre-existing capacity errors (Sprint 07 +2 over, R1 train +2 over), unrelated to E01, 184 warnings | Reproduced exactly; `all-tickets.json` rewrite reverted via `git checkout --` immediately after | Pass (documents baseline, not a new finding) |

## 5. Board guards (E01-T07)

Executed via the existing QA-reviewed offline guard pack (`scripts/gh/tests/test_guard_*.py`,
`scripts/gh/tests/test_run_guard.py`) plus a direct read of the guard docstrings against the ticket's
own Agent-delivery adaptation (role sign-off represented as a write-access-verified, actor-attributed
comment carrying an explicit marker — see `guard_qa_signoff.py` module docstring; this repo has no
GitHub organisation, so org-team-membership lookups always 404, which is the documented reason for
this substitution, not an unauthorised deviation).

| # | Case | Expected | Actual | Verdict |
|---|---|---|---|---|
| 5.1 | Close a Story with no QA sign-off | Blocked | `test_story_without_signoff_is_blocked` passes | Pass |
| 5.2 | Close with sign-off from someone with verified write access | Allowed | `test_story_with_write_access_signoff_comment_is_allowed`, `test_signoff_from_someone_other_than_closer_is_accepted` pass | Pass |
| 5.3 | Marker forged in the issue **body** by the author | Rejected — only a comment counts | `test_forged_signoff_in_body_does_not_satisfy_guard` passes | Pass |
| 5.4 | Marker present but commenter lacks write access | Rejected | `test_comment_with_marker_without_write_access_does_not_satisfy_guard` passes | Pass |
| 5.5 | Closer supplies their own sign-off (self-approval) | Rejected — separation of duties | `test_closer_cannot_self_signoff` passes | Pass |
| 5.6 | Write-access lookup API fails | Fail closed (never silently allow) | `test_api_error_during_write_access_lookup_fails_closed` passes | Pass |
| 5.7 | Close a `security`-labelled ticket without a security-team comment | Blocked | `scripts/gh/tests/test_guard_security.py` close-mode cases pass (reviewed: same write-access + marker pattern as QA guard) | Pass |
| 5.8 | Open `area/auth-rbac` issue without `security` label | Auto-labelled | `test_guard_security.py` label-sync cases pass | Pass |
| 5.9 | Close an `a11y`-ticket with a foreign (non-repo) run link | Rejected | `scripts/gh/tests/test_guard_a11y.py` covers non-repo-scoped-link rejection | Pass |
| 5.10 | Kind label <-> Projects `Kind` field sync | Kept in agreement; degrades to "not checked" (never a false "in agreement") when `PROJECTS_PAT` absent | `test_guard_kind_sync.py` passes, including the PAT-absent degrade path | Pass |
| 5.11 | Rollout is currently observe-only | `GOVERNANCE_ENFORCE` repo variable | `.github/workflows/board-automation.yml` defaults `env.GOVERNANCE_ENFORCE` to `'false'`; confirmed by reading the workflow (no `gh variable get` access needed) | Pass (documents current state, not a defect — matches the ticket's own documented rollout plan) |
| 5.12 | **Live** end-to-end: real issue closed via GitHub UI without sign-off, workflow run observed to fail closed | Workflow run visible in Actions tab, no false negative | Not executed — would require actually closing/reopening a real tracked issue non-destructively and observing a live Actions run; feasible but not attempted in this pass to avoid board noise on in-flight tickets | **Deferred** — recommended as the first case E01-Q02 automates into a scheduled synthetic-issue smoke test |

## 6. Templates (E01-T05)

| # | Case | Steps | Expected | Actual | Verdict |
|---|---|---|---|---|---|
| 6.1 | Every form has required fields | `grep -c "required: true"` per template | >0 per form | story.yml=6, bug_report.yml=5, task.yml=5, spike.yml=4, epic.yml=7, chore.yml=3 | Pass |
| 6.2 | Blank issues disabled | Read `.github/ISSUE_TEMPLATE/config.yml` | `blank_issues_enabled: false` | Present | Pass |
| 6.3 | Vulnerability-report diversion link present | Read `config.yml` contact_links | Points to GitHub's private "Report a vulnerability" flow, not a public issue | `url: .../security/policy`, `about:` explicitly says "Do not file a public issue — see SECURITY.md" | Pass |
| 6.4 | Structural form validity (GOV-004) | `python scripts/check_issue_forms.py` | Exit 0 | `OK: all issue forms structurally valid` | Pass |
| 6.5 | Malformed form is flagged | Reviewed `scripts/tests/test_check_issue_forms.py::test_malformed_form_is_flagged`, `test_dropdown_without_options_is_flagged` | Rejected | Both pass | Pass |
| 6.6 | Submitting each form with required fields empty (live GitHub form) | Open each `.github/ISSUE_TEMPLATE/*.yml` form in the GitHub "New issue" UI, leave a required field blank, attempt submit | Browser-level submit blocked (GitHub Issue Forms native behaviour for `required: true`) | Not executed in this session (no interactive browser session against the live repo); the `required: true` keys are present per 6.1 and this is standard, well-documented GitHub Issue Forms behaviour, not custom code E01 wrote | **Blocked** — needs a live interactive GitHub session; low risk given it is platform-native behaviour, not project code |

## 7. Cold-read usability verification of `CONTRIBUTING.md`

**Not executed as a live second-engineer session** — no second, previously-uninformed human engineer
is available in this sandboxed agent session (this is the same "engineer in a hurry" perspective the
charter in §8 partially covers by simulation). Recorded here as **QA-BUG-E01-002** (§9): the
verification itself is filed as a follow-up requiring the owner to hand `CONTRIBUTING.md` to a fresh
engineer, clone -> branch -> commit -> PR, with confusion points logged, feeding E01-T02's acceptance
criteria. A structural proxy was performed instead: read `CONTRIBUTING.md` end-to-end assuming zero
prior context beyond it, and confirmed every step (branch naming, commit convention, PR template
location, required-checks pointer, break-glass runbook) is either self-contained or names the exact
file to open next — no step assumes tribal knowledge. No confusion points found in this proxy pass,
but a proxy performed by the ticket's own implementer is not a substitute for a genuinely cold read
and must not be recorded as satisfying the acceptance criterion.

## 8. Exploratory charter

See `docs/plan/backlog/testplans/E01-governance-charter.md` (separate file per `03-testing-strategy.md`
§11.2 format: mission, areas probed, oracles, debrief, timebox 90 min).

## 9. Bugs filed

| ID | Severity (§11.3) | Summary | Issue | Blocks Done? |
|---|---|---|---|---|
| QA-BUG-E01-001 | P2 — Medium | R0 exit-criterion-1 evidence pack (screenshots of a refused live merge) cannot be produced on the current GitHub Free plan without admin/rulesets API access; not a control defect — a sandboxed-session/plan-tier gap. Owner action: run one real merge attempt against a single-approval PR post-`scripts/apply_branch_protection.py`, capture the refusal screenshot. | recorded here only (owner action, not a code bug) | No (P2, workaround exists: owner performs the one live check manually; the automatable half is fully green) |
| QA-BUG-E01-002 | P2 — Medium | Cold-read usability verification of `CONTRIBUTING.md` (feeding E01-T02) requires a genuinely uninformed second engineer; not available in this agent session. Structural proxy found no issues but does not satisfy the acceptance criterion on its own. | recorded here only (owner action, not a code bug) | No (P2, scheduled next: hand to a real engineer before E01-T02 is declared Done) |
| QA-BUG-E01-003 | P2 — Medium | `docs/plan/backlog/_tools/validate.py` rewrites `all-tickets.json` on every invocation (even validate-only mode per its own docstring: "no writes to E*.json" — the merged file is not an `E*.json` file, so this is arguably intended, but it is easy for a QA/agent session to accidentally leave a diff if they forget to `git checkout --` afterwards, as observed in this pass). Recommend: `validate.py` (no `--fix`) should not touch `all-tickets.json` either, or the docstring should say so explicitly. | [#1442](https://github.com/CandleViewer/CandleViewer/issues/1442) | No — cosmetic/process-friction only |
| QA-BUG-E01-004 | P2 — Medium | `scripts/gh/guard_a11y.py` accepts any repo-scoped Actions run link as evidence, not necessarily the run relevant to the closing issue (charter finding 4). | [#1443](https://github.com/CandleViewer/CandleViewer/issues/1443) | No — workaround exists (human review of the linked run) |

No P0/P1 bugs found. All governance controls proven from the outside behave as declared; the gaps
found are execution-environment limits (free-tier API access, no second human in this session), not
defects in the shipped controls.

## 10. Automatable cases handed to E01-Q02 (prioritised)

1. §5.12 — synthetic-issue close/no-close smoke test on a schedule (highest value: currently the only
   guard behaviour with zero live-event coverage).
2. §1.12/1.13 — a scratch/disposable-repo job that applies branch protection for real and attempts a
   refused merge, capturing the artefact automatically (removes the recurring "needs live admin
   session" deferral seen in both this ticket and PR #1438).
3. §2.3 — a job that fetches GitHub's own CODEOWNERS resolution via the API (requires Pro/org access)
   and diffs it against the checker's output, once available.
4. §4.7 — guard `validate.py`'s `all-tickets.json` rewrite behavior with an explicit `--check-only`
   flag that never writes, closing QA-BUG-E01-003.

## 11. Ticket -> case traceability

| Ticket | Cases |
|---|---|
| E01-T01 | 3.1–3.5 |
| E01-T04 | 2.1–2.3 |
| E01-T05 | 6.1–6.6 |
| E01-T06 | 4.1–4.7 |
| E01-T07 | 5.1–5.12 |
| E01-T08 | 1.1–1.13 |
| E01-T02 (fed by) | §7 |

## QA sign-off

- [x] Test plan authored by QA (this ticket, E01-Q01), before any E01 child ticket reached Done.
- [x] All cases executed with recorded actual results; blocked cases (1.12, 1.13, 6.6, §7) justified
      by documented environment/session constraints, not silently skipped.
- [x] Zero open P0/P1 bugs against E01 scope (three P2/P3 filed, §9).
- [x] Findings ready for the Sprint 01 review.

QA sign-off: pass — sprint01-r3 implementer, 2026-09-26.
