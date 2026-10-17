# Contributing to CandleViewer

CandleViewer is a private, self-hosted trading terminal (React + custom WebGL chart engine + Electron
shell, Python FastAPI monolith, Bybit v5 USDT linear perpetuals). It places real orders with real capital,
so the bar for changes is high and the rules are explicit.

## Read these first

| Document                                                                         | What it is                                                                                                                                                                                                                                                                                         |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **[`CONSTITUTION.md`](CONSTITUTION.md)**                                         | **The binding rules.** Scope guardrails, architecture invariants, branching, quality gates, review rules, DoR/DoD, security, testing, a11y/performance budgets, release and amendment process. It outranks every other document in this repo.                                                      |
| **[`AGENTS.md`](AGENTS.md)**                                                     | The practical operating manual — repo map, how to pick up a ticket, ticket anatomy (§3a), board protocol (§3b), commands per package, coding standards, test-writing rules, PR checklist, prohibitions. Written for AI coding agents (tool-agnostic: Copilot, Codex, Cursor, Claude Code, humans). |
| **[`CLAUDE.md`](CLAUDE.md)**                                                     | Claude Code's entry point specifically — a thin pointer into `CONSTITUTION.md` and `AGENTS.md`, not a second rulebook. If you use a different agent, read `AGENTS.md` directly instead.                                                                                                            |
| **[`SECURITY.md`](SECURITY.md)**                                                 | Vulnerability reporting, supported versions, secrets policy, incident process.                                                                                                                                                                                                                     |
| `docs/plan/`                                                                     | Planning source of truth: SDLC, DoR/DoD, testing, security, a11y, performance, release/PRR, UX, architecture, API/WS contract, schema, roadmap, backlog.                                                                                                                                           |
| `docs/adr/`                                                                      | Accepted architecture decisions (MADR). Do not relitigate them silently.                                                                                                                                                                                                                           |
| `.github/PULL_REQUEST_TEMPLATE.md`                                               | The checklist your PR must satisfy.                                                                                                                                                                                                                                                                |
| `.github/CODEOWNERS`                                                             | Who must review what.                                                                                                                                                                                                                                                                              |
| **[`docs/ci-runbook.md`](docs/ci-runbook.md)**                                   | Operating manual for the CI/CD pipeline: job map, `ci-required` resolver, per-error-code triage recipes, dev-environment rebuild, secret-exposure and bad-deploy response, flaky-test quarantine, weekly PR-feedback-time metrics.                                                                 |
| **[`docs/plan/observability-contract.md`](docs/plan/observability-contract.md)** | One-page contract for module authors: registering metrics, permitted labels, probes and getting an alert approved.                                                                                                                                                                                 |

If anything below appears to conflict with the Constitution, **the Constitution wins** and the conflict is
a bug to report.

## The short version

1. **Start from a Ready issue.** Check it against the Definition of Ready (Constitution §11.1). If
   acceptance criteria, design sign-off, dependencies or estimate are missing, comment on the issue and
   stop — do not guess.
2. **One ticket = one branch = one PR.** Branch as `<type>/<epic-key>-<short-slug>` using `feat/`, `fix/`,
   `chore/`, `design/`, `spike/` or `docs/` (Constitution §4.2).
3. **Contract first.** If the REST/WS surface changes, edit `docs/plan/22-api-openapi.yaml` or
   `docs/plan/23-ws-protocol.md` and regenerate `packages/protocol` before writing implementation code
   (§6).
4. **Tests first, at the right level.** Unit for pure logic, integration for boundaries (with recorded
   Bybit fixtures — no live-exchange calls in CI), E2E only for user-visible critical paths (§13).
   Exchange payloads come from the shared corpus `packages/fixtures/bybit/` (via
   `services/api/tests/_corpus.py`). The only suite that reaches Bybit is the opt-in, demo-only,
   credential-free `exchange_smoke` suite. Its fail-closed environment guard is explained in
   `services/api/tests/exchange_smoke/README.md`.
5. **[Conventional Commits](https://www.conventionalcommits.org/)** with an allowed scope; `commitlint`
   enforces it (§4.4). This also feeds the changelog: your PR title must be a conventional-commit header,
   or the PR body must include a `Changelog: <one-line user-facing summary>` footer — the
   `changelog-fragment` check (`tools/ci/check_changelog_fragment.py`, CI-REL-001) fails otherwise, except
   for PRs whose title is `chore:`/`ci:`/`docs:` (docs/plan/07-release-and-prr.md §3). A usable fragment
   becomes a `CHANGELOG.md` `Unreleased` entry at the next changelog sync PR; every merge shows a preview
   (docs/plan/07-release-and-prr.md §3). For a security fix, write the impact-only `Security` line
   yourself, ending with your PR number `(#N)`.
6. **Rebase, never merge** (`git pull --rebase origin main`). PRs land on `main` as a squash. `main` is
   protected: no direct pushes, no force-pushes (§4.5).
7. **Keep it small.** ≤400 changed LOC preferred; >800 needs a `large-pr-approved` label with a written
   justification (C-4.8).
8. **Open a PR with `Closes #N`** and the template fully completed, with evidence attached (test output,
   screenshots for UI, benchmark deltas for engine work, migration up/down output for schema work).
9. **Get 2 approvals including 1 CODEOWNER.** Security-sensitive paths need `@CandleViewer/security`; UI
   changes need `design-approved` and a Done design ticket (§10).
10. **Merging means In Test, not Done.** Only QA or the owner moves a ticket to Done (§10, §11.2).

## Quality gates

Every PR must pass **all** required CI checks. **The single source of truth for the list of check names,
and for what each one enforces, is [`CONSTITUTION.md` §9 (Quality gates)](CONSTITUTION.md#9-quality-gates-required-ci-checks).**
It is deliberately **not** duplicated here, in `AGENTS.md`, or in the PR template — a renamed check must
require exactly one edit, in one file. If you find a check list copied into any other document, delete it
and link to §9 instead.

Rules that always hold, wherever the list lives:

- A red required check is never merged. There is no admin merge and no "re-run until green".
- Checks are never disabled, skipped, marked `continue-on-error`, or removed from branch protection in a
  feature PR. Changing the required-check set is an amendment (Constitution §16).
- Coverage floors are floors and may never be lowered in the PR that fails them (C-9.4). Per-package floors,
  ratchet baselines and tolerance live in `tools/ci/coverage-baselines.json` (CODEOWNER-gated by the QA
  lead — see `.github/CODEOWNERS`); the `coverage-thresholds` check (`tools/ci/coverage_gate.py`) reads it
  and fails a PR with a specific `CI-COV-00x` code and reason rather than a bare red X.
- Run the same gates locally before pushing — see [`AGENTS.md` §4 (Commands)](AGENTS.md#4-commands), which
  is the single source of truth for task/script names.

## Hard boundaries

Out of scope, and rejected on sight (Constitution §1.3): Android/iOS or any mobile client; a separate admin
application (admin lives as RBAC-gated screens inside the web app); any exchange other than Bybit or any
category other than USDT linear perpetuals; options/GEX; withdrawal, transfer or funding code; public
internet exposure (Tailscale only); multi-tenant/SaaS productisation; a third-party chart library as the
production renderer.

Safety invariants that no flag, environment or "advanced mode" may weaken: every position-opening order
carries a **native exchange-side stop-loss**; API keys **never leave** the secrets module; **withdrawal
permission is never enabled**; **every order action is audited** append-only; **RBAC and risk caps are
enforced server-side**.

## Local commands

**Single source of truth: [`AGENTS.md` §4 (Commands)](AGENTS.md#4-commands).** Task names are not
duplicated here. The monorepo scaffold (`pnpm-workspace.yaml`, `turbo.json`, `package.json`,
`services/api/pyproject.toml`) shipped with `E02-T11`, so `AGENTS.md` §4 mirrors the real, runnable
task graph. The generated-code required check fails the build if `AGENTS.md` §4 and the real scripts
disagree.

**Reproducing any CI gate locally, and what a red check means:** see
[`docs/ci-runbook.md`](docs/ci-runbook.md) §4 for the full per-error-code
(`CI-<FAMILY>-<NNN>`) triage table — this file does not duplicate it. The
runbook also covers the dev-environment rebuild procedure (§7), secret-exposure
response (§5), bad-deploy rollback (§8) and the flaky-test quarantine process
(§9); this section stays limited to the JS/generated-code local-reproduction
commands already documented below.

See `AGENTS.md` §4 for the root install/verify command and the backend lint/format/typecheck/test loop.

After `pnpm install --frozen-lockfile`, run `pnpm prepare` once to install the local git hooks
(`.husky/`: `commit-msg` commitlint, `pre-commit` lint-staged, `pre-push` branch-name + affected-project
typecheck). This is a deliberate, code-owned exception to the repo's `ignore-scripts=true` posture — see
the comment in `.npmrc` — so it is not run implicitly by `pnpm install`. Hooks are a convenience; the same
rules are enforced server-side by CI and cannot be weakened by `--no-verify`.

### Generated-code freshness (`packages/protocol`)

`packages/protocol` is regenerated from `docs/plan/22-api-openapi.yaml` and the WS schema in
`docs/plan/23-ws-protocol.md` (ADR-0013 binding rule 3, ADR-0005). If you touch either source, run
`make gen` and commit the resulting diff under `packages/protocol` — never hand-edit
`packages/protocol/src/generated/**`.

The `gen` job (`.github/workflows/_job-gen.yml`) is an always-on required check. If it fails:

1. **`CI-GEN-003` (codegen is not deterministic)** — the generator itself is flaky; this is a bug in
   `packages/protocol/scripts/*`, not something you can fix by regenerating again. Reproduce locally
   with `make gen && make gen` and diff the tree; file it against the protocol package before retrying.
2. **`CI-GEN-001` (drift)** — run `make gen` locally, review the diff under `packages/protocol`, and
   commit it in the same PR as the schema change.
3. **`CI-GEN-002` (untracked output)** — `make gen` produced a new file CI can see via `git status` but
   `git diff` couldn't. Check `.gitignore` hasn't accidentally swallowed a new generated path, then `git
add` and commit it.
4. **`CI-GEN-004` (generator toolchain failure)** — the generator command itself errored (missing
   dependency, syntax error in the schema, pinned tool version mismatch); the job summary and step log
   carry the underlying stdout/stderr.

Run the same check locally before pushing: `make gen-check` (wraps
`tools/ci/check_gen_freshness.py`).

**Reproducing the JS CI lane locally** (E03-T02, `.github/workflows/_job-js.yml`): the lane is exactly
`pnpm turbo run <task> --filter='...[origin/main]'` for `lint`, `typecheck`, `test:cov` (split into
`unit-frontend`: `ui`/`web`/`desktop`, and `unit-engine`: `chart-engine`/`protocol`), then `build` — same
task names as `pnpm verify`, just scoped to what changed since `origin/main` the way CI scopes it. Run
the whole thing exactly as CI does with:

```sh
pnpm install --frozen-lockfile --ignore-scripts
node tools/ci/run-allowed-postinstall.mjs   # SR-138 exception list (electron, esbuild)
pnpm turbo run lint typecheck test:cov build --filter='...[origin/main]'
```

CI reads `TURBO_API`/`TURBO_TEAM` (repository variables) and, on `main`-branch runs only, a write-scoped
`TURBO_TOKEN` secret for the Turborepo remote cache (ADR-0013 rule 6); PR runs and local runs without
those variables set simply fall back to Turborepo's local cache.

### Governance regression pack (`GOV-00n` codes)

The `governance` required check (`.github/workflows/governance.yml`, E01-Q02) runs a fixed pack of
checkers, each emitting a stable `GOV-00n` code so CI history stays greppable. Reproduce any of them
locally with `python scripts/<checker>.py` (or `python docs/plan/backlog/_tools/validate.py` for the
backlog report tool); fix instructions live in the tool's own `--help` and its emitted message.

| Code      | Checker                                                                                               | What it means                                                                                                                                                                                                                                 |
| --------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GOV-001` | `scripts/check_codeowners_coverage.py`                                                                | A tracked path resolves only to the CODEOWNERS catch-all `*`, a rule matches no tracked path, or a rule names an undeclared owner.                                                                                                            |
| `GOV-002` | `scripts/check_rule_refs.py`                                                                          | A `C-x.y` rule reference doesn't resolve to a declaration in `CONSTITUTION.md`. Run with `--fix-suggest` for nearest-id suggestions.                                                                                                          |
| `GOV-003` | `scripts/check_sot_duplication.py`                                                                    | A `C-16.5`-owned list has been restated outside its owner file/section (`scripts/sot-registry.json`). Delete the copy and link to the owner, or add an isolated-mention entry to `scripts/sot-allowlist.txt`.                                 |
| `GOV-004` | `scripts/check_issue_forms.py`, `scripts/validate-backlog.py`, `docs/plan/backlog/_tools/validate.py` | An issue form is structurally broken, or a backlog ticket JSON fails schema/cross-file validation (dependency cycles, parent chains, sprint ordering, secret-pattern scan).                                                                   |
| `GOV-005` | `scripts/check_required_check_reconciliation.py`                                                      | `.github/branch-protection.json` and `CONSTITUTION.md` §9 (and, once populated, the workflow job names) disagree on required-check names.                                                                                                     |
| `GOV-006` | `scripts/check_markdown_governance_docs.py`                                                           | A governance document (`CONTRIBUTING.md`, the E01 test plans, the E01-X02 security findings doc) has a broken relative link or a lint issue (hard tab, trailing whitespace, a heading level jump, a bare autolink, missing trailing newline). |

The job also runs a **canary self-test** (`python scripts/gov_self_test.py --self-test`) that replays
every checker above against a deliberately-broken fixture tree under
`scripts/tests/fixtures/self_test/` and asserts each one fails — the guard against a green `governance`
check that has silently stopped checking anything — and a **coverage gate** (`pytest --cov=scripts
--cov-fail-under=85`) over all of `scripts/**`. Job duration is measured against a 60s budget and
recorded as a `::notice` annotation on every run; exceeding the budget fails the job (`::error`
annotation). Per-run artefacts (CODEOWNERS ownership report, backlog per-epic summary) are uploaded
as the `governance-reports` artefact for diffable history across runs.

Sprints are **1 week** (Fri→Thu; Sprint 01 = 2026-09-25; calendar in `docs/plan/backlog/_tools/calendar_cv.py`). Design runs at least two sprints ahead of engineering; no frontend screen work starts before its design
ticket is Done. Architectural decisions are recorded as MADR ADRs in `docs/adr/` and must be proposed
before implementation (Constitution §15.1).

## Governance map — which document owns what

Every list in this repo has exactly one owner (`CONSTITUTION.md` C-16.5); everything else links to it
instead of restating it. See the [C-16.5 single-source-of-truth registry](CONSTITUTION.md#16-amendment-process)
for the authoritative table (rules, CI check names, budgets, commands, repo layout, ownership, security
policy, ticket schema, statechart contracts). If you find the same list copied into a second file, that
copy is a bug — delete it and link to the owner instead.

## Branch protection break-glass runbook

`main` protection (`.github/branch-protection.json`, applied by
`scripts/apply_branch_protection.py`, `enforce_admins: true`) has no built-in
bypass — that is the point (C-9.1). If protection must be lifted in a genuine
emergency (e.g. to land a hotfix while CI infrastructure itself is down):

1. Only `@basiltt` or a person they explicitly delegate in writing on the
   tracking issue may perform the bypass.
2. Before changing anything, open (or comment on) the dedicated break-glass
   tracking issue, stating: what is broken, why waiting for a normal PR is not
   possible, and the exact setting(s) about to change.
3. Use the repository-administration-scoped credential only via the GitHub UI
   or `gh api`, never the automated apply script (which never runs from a
   PR-triggered workflow, by design).
4. Restore `.github/branch-protection.json` settings immediately after the
   emergency merge — do not leave protection weakened.
5. The weekly `governance-drift` workflow (GOV-005, `.github/workflows/governance-drift.yml`)
   will detect any settings left un-restored and open a `priority/p1-high`
   `security`-labelled issue regardless of step 4 — this is deliberate, not a
   bug: break-glass usage is always independently recorded.
6. The tracking issue is reviewed at the R4 live-enablement gate
   (`docs/plan/28-statechart-catalogue.md` B-series live gate; see
   `docs/plan/30-release-roadmap.md`).

Break-glass is for repository infrastructure emergencies only — it is never a
substitute for getting a second review on a normal change.

## Reporting security issues

Never open a public issue for a vulnerability. Follow [`SECURITY.md`](SECURITY.md).

## Changing the rules

The Constitution changes only through its [amendment process](CONSTITUTION.md#16-amendment-process):
a `constitution`-labelled issue, an amendment PR updating every affected artefact, a 3-working-day
discussion period, and approval from the architect, the security engineer, affected CODEOWNERS and
`@basiltt`. Local exceptions, temporary bypasses and undocumented practices are not permitted.

## Code of Conduct

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
