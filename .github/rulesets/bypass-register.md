# Branch-protection bypass register (E03-T13, CI-PROT-004)

Every actor permitted to bypass `main` branch protection (`.github/branch-protection.json`,
`enforce_admins: true`) must be named here with a justification and a review date
(CONSTITUTION.md C-9.1, C-10.1; `docs/plan/01-sdlc-and-branching.md` §7–§8). An actor that can
bypass protection but is **not** listed here is a `CI-PROT-004` finding — treat it as an incident,
not a config nit.

There is deliberately **no standing bypass** for ordinary merges: `enforce_admins: true` means even
repository admins go through the same 2-review + required-checks gate. The only registered bypass
is the release-automation identity below, scoped to creating one release tag per verified
candidate — and it is **not** a bypass of `main`'s protection at all, since it pushes no commit and
no branch (see Scope).

| Actor                                                                                                                 | Scope of bypass                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Justification                                                                                                                                                                                                                                                                                                                                      | Review date                                    |
| --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `github-actions[bot]` (release workflow, `.github/workflows/release.yml` `tag-draft` job, #3099)                      | Create one annotated tag `refs/tags/vX.Y.Z` per release, through the REST git database, at a candidate commit on `main` only after `verify` (`tools/ci/prepare_release.py --verify`, GitHub-verified commit) the e2e gate and the SBOM validation at that commit pass; a no-op when the tag already points there, a failure when it points elsewhere. It **never** pushes a commit or a branch, and never moves or deletes a tag. Not a `main`-protection bypass (`main` is untouched); listed because it is the repo's one non-human identity that creates release refs, and no `v*` tag ruleset exists yet (an owner item: such a ruleset would name this identity as its only bypass) | Releases roll forward from `main` (`docs/plan/07-release-and-prr.md` §4): the reviewed release-prep PR carries the finalised `CHANGELOG.md` and `version.txt`, so the tag is the run's only write to git, and tagging only a verified, smoke-tested candidate keeps every release tag on `main`'s history (C-15.6, C-15.7)                         | 2027-01-29 (quarterly review)                  |
| `@basiltt` (break-glass only)                                                                                         | Manually disable/relax protection settings via the GitHub UI or `gh api` in a genuine repository-infrastructure emergency (CI itself down)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | `CONTRIBUTING.md` § "Branch protection break-glass runbook" — no automated tooling ever performs this; `governance-drift` (GOV-005) independently detects and flags any settings left un-restored                                                                                                                                                  | 2026-12-25 (quarterly review, next: Sprint 13) |
| `candleviewer-ci[bot]` (`deploy-dev.yml` / `deploy-staging.yml` "Commit the updated deployment ledger" step, E03-T09) | Push `deployments/ledger.jsonl` + `deployments/README.md` commits to `refs/heads/ops/deploy-ledger` only, **never `main`** — same non-bypass shape as the release-automation row above (the ref is not `main`, so nothing here touches `main`'s protection). Listed for completeness as the repo's second non-human commit identity with a standing push grant                                                                                                                                                                                                                                                                                                       | Every dev/staging deploy attempt must append an audit row (ticket "Deployment records", C-2.9-style append-only trail) without waiting on a PR review round-trip per deploy; routing it through `main` would violate C-4.1, so it lands on a dedicated ref the deploy workflows are the sole writer of (serialised by their `concurrency:` groups) | 2026-12-25 (quarterly review, next: Sprint 13) |

## Rules for this table

1. Adding a row requires a PR touching this file, reviewed like any other change to `.github/`
   (CODEOWNERS: `@CandleViewer/devsecops @CandleViewer/security`).
2. Every row must have a review date no more than one quarter (13 sprints) out. Staleness is
   enforced two ways so a passed date is never caught only by luck of a PR being open:
   `scripts/check_bypass_register.py` runs both in `governance.yml` (every PR touching this file
   or the checked paths) **and** in the scheduled `governance-drift.yml` (weekly, independent of any
   open PR) — see the "Register staleness (CI-PROT-004)" step there.
3. Removing a bypass (e.g. the release-automation identity is retired) removes its row in the same PR
   that removes the capability — an orphaned row for a bypass that no longer exists is also a finding.
4. This table is the single source of truth for "who can bypass `main`'s protection" (C-16.5); do not
   duplicate it elsewhere — link here instead.
5. `scripts/check_bypass_register.py` only validates internal consistency of this file (rows parse,
   dates unexpired, dates not more than one quarter out); it does **not** reconcile the table against
   the live actors that currently hold push/bypass access to `main`, and — despite an earlier version
   of this note — `scripts/check_branch_protection_drift.py` does **not** do that reconciliation
   either: it diffs `.github/branch-protection.json`'s known keys (`enforce_admins`,
   `required_pull_request_reviews`, etc.) against the live classic branch-protection API response, and
   the classic protection API has no per-actor bypass-allowance field to diff against in the first
   place. So a passed `enforce_admins: true` check tells you admin bypass is off in general; it does
   **not** tell you whether every actor with some other route to `main` (a repo collaborator with
   direct push rights, a ruleset bypass list, an app installation) is named in this table. **There is
   currently no automated check that catches an unregistered live bypass actor by identity** — that
   reconciliation is a manual review step (repo Settings → Collaborators/Rulesets, cross-checked
   against this table) until a script is written against the GitHub rulesets/collaborators APIs to do
   it (tracked as a follow-up; not yet a ticket). Treat any discrepancy you find manually as an
   incident per this file's intro, the same as a `CI-PROT-004` finding.
