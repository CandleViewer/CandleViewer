# ADR-0013 — CI/CD pipeline on GitHub Actions

- Status: **decided**
- Date: 2026-09-14
- Deciders: DevSecOps, Architect, QA lead, Security engineer
- Consulted: planning brief "SDLC requirements" and "Deliverables", `docs/plan/01-sdlc-and-branching.md`, ADR-0012
- Related: `docs/plan/07-release-and-prr.md`, `docs/plan/03-testing-strategy.md`

## Context and problem statement

Trunk `main` is protected; work happens on `feat/`, `fix/`, `chore/`, `design/` and `spike/` branches with small PRs (≤ 400 LOC preferred), conventional commits, two approvals including one code owner, and required checks. The repository is a polyglot monorepo (TypeScript apps and packages, a Python service, infra, docs) with a generated protocol package, heavyweight GPU benchmarks and a broad security tool set. The pipeline must give fast, trustworthy signal without becoming a 40-minute tax on every PR.

## Decision drivers

- The repository already lives on GitHub with a GitHub Project for planning; adding a second CI system would fragment the workflow.
- Only some checks are affected by any given change — a docs PR must not run GPU benchmarks.
- Generated code (`packages/protocol`) must never drift from its source of truth.
- Benchmarks need a consistent machine or their numbers are noise.
- Security scanning is mandated by the planning brief across SAST, SCA, secrets, DAST and container scanning.

## Considered options

1. **GitHub Actions with path-filtered, parallel jobs; a self-hosted runner for GPU benchmarks; Turborepo/uv caching.**
2. **GitHub Actions running everything on every PR.**
3. **An external CI system** (Buildkite/CircleCI/Jenkins).

## Decision outcome

**Chosen: option 1.**

### Pipeline shape

```
PR opened/updated
├─ changed-paths (dorny/paths-filter) ──> job matrix
├─ [always] commitlint, licence header check, docs link check
├─ [js]  lint (eslint) · typecheck (tsc) · unit (vitest) · build
├─ [py]  lint (ruff) · typecheck (mypy --strict on modules) · unit (pytest) · build
├─ [always] generated-code freshness: `make gen && git diff --exit-code`
├─ [contract] OpenAPI/WS schema conformance + protocol codec round-trip
├─ [integration] fixture-driven pipeline + OMS fake-exchange suite
├─ [e2e] Playwright web (+ Electron on release branches)
├─ [engine] benchmarks B1-B10 on the self-hosted GPU runner (only if chart-engine changed)
├─ [a11y] axe-core suite
├─ [security] CodeQL · Semgrep · Bandit · pip-audit · npm audit · gitleaks · Trivy (images)
└─ [infra] compose config validation · hadolint · terraform-free (n/a)
merge to main
├─ build + push images (GHCR, tagged semver+sha) · SBOM (syft) · sign (cosign)
├─ deploy to the staging compose stack (synthetic feed) · smoke tests
└─ nightly: load (k6/Locust) · 24 h ingestion soak · chaos suite · ZAP DAST · full E2E matrix
release tag
└─ changelog · Electron installers (signed) · release checklist + PRR gate (07-release-and-prr.md)
```

### Binding rules

1. **Required checks for merge**: commitlint, lint, typecheck, unit, generated-code freshness, contract, integration, e2e (web), a11y, security (SAST + secrets + SCA), and — when `packages/chart-engine` changed — the engine benchmarks. Two approvals including one code owner (`.github/CODEOWNERS`).
2. **Path filtering** decides which jobs run, but the _required_ set is computed from the same filter so a skipped-but-required job reports success only when genuinely not applicable (a "required checks resolver" job emits the conclusion).
3. **Generated-code freshness is a hard gate.** `packages/protocol` is regenerated from `22-api-openapi.yaml` and the WS schema; any diff fails the build. Generated files are committed so consumers need no codegen step.
4. **Benchmarks run on a pinned self-hosted runner** (the reference machine class, fixed GPU driver, fixed Chromium). Results are compared to a stored baseline; a > 10 % regression fails. Baseline updates require an explicit reviewer-approved commit that states the cause.
5. **Caching**: Turborepo remote cache for JS, `uv` cache for Python, Playwright browser cache, Docker layer cache. Target: PR feedback ≤ 15 minutes end-to-end.
6. **No secrets in PR workflows from forks.** The repository is private and single-org, but workflows still use least-privilege `permissions:` blocks and pinned action SHAs (not floating tags) to close the supply-chain path.
7. **Concurrency groups** cancel superseded runs per branch to keep the queue short.
8. **Deployment is image-based and immutable**: every merge to `main` produces a tagged image with an SBOM and a signature; the staging stack is redeployed automatically, production (the owner's box or the VPS) is a deliberate, checklisted action.
9. **Migrations are applied on boot under an advisory lock** and must be backward-compatible for one release (expand/contract), so a rollback never requires a down-migration.
10. **Flaky-test policy**: a job that fails and then passes on retry is recorded; three occurrences in a week auto-open a quarantine issue (ADR-0012).

### Consequences

Positive:

- One platform for code, planning, review, CI and releases — no context switching and no second permissions model.
- Path filtering keeps the common case fast while the full matrix still runs nightly.
- The freshness gate makes protocol drift structurally impossible, which is the highest-value guarantee in a polyglot monorepo.

Negative / risks:

- A self-hosted GPU runner is infrastructure we must maintain and secure (isolated, ephemeral workspace, no secrets, restricted to this repository). Documented in `04-security-program.md`.
- GitHub Actions minutes and LFS bandwidth are real costs; mitigated by caching, path filters and concurrency cancellation.
- Benchmark stability depends on that one machine; if it is unavailable, the engine check blocks merges. Mitigated by a documented manual-override procedure requiring the architect's approval, recorded in the PR.

### Why not the alternatives

- **Run everything on every PR**: simple and honest, but a 40-minute pipeline on a docs typo destroys the small-PR culture the SDLC depends on.
- **External CI**: better GPU-runner ergonomics in some cases, but it splits the workflow across two systems, duplicates permissions, and adds a third-party with repository access — a poor trade for a private, security-sensitive project.

## Validation

- Measure PR feedback time weekly; if the p90 exceeds 15 minutes, rebalance the job matrix.
  - **#3751 (2026-10-19): the `py` job's pytest lanes are four.** In three green runs that night, `db-chaos-contract` took 15.5 to 20.5 minutes against 15 to 19.3 for `rest` and 12.2 to 15.8 for `unit-heavy`. In its 19-minute run, `tests/integration` took 10.5 minutes, `tests/contract` 4.8 and `tests/chaos` 1.8. It is now two lanes, `db-chaos` (`tests/integration`, `tests/chaos`) and `contract-security`, which also takes `tests/xstate_contract`, `tests/security` and `tests/rules` (4.5 minutes) from `rest`. On those runners the longest lane then runs about 12 test-minutes instead of 17, at the cost of one more job of setup and collection (about 1.5 minutes) per run. `tools/ci/py-test-lanes.json` holds the lanes.
- Quarterly review of action pins and workflow permissions as part of the security programme.
- A deliberate "break the protocol" PR must fail the freshness gate (tested once during Sprint 01).

## Amendment 1 (2026-10-17, #3076)

- **Pipeline shape (refined, not reversed).** The `[always]` gates and the other sub-minute gates run as steps of one `gates` job in `pr.yml`, each step keeping its path filter; the `architecture` mirror runs beside `coverage-thresholds` instead of after the last `py` job; PR runs skip the informational sync-parity job, which runs nightly.
- **Rule 2.** A resolver lane may be a step outcome that `gates` exports under the lane's name. It is judged exactly like a job result: an applicable lane passes only on `success`, and a lane that is not applicable passes. `gates` is a lane too, so a failed setup or verdict step fails the resolver.
- **Validation (2026-10-17, 30 completed `pr.yml` runs, GitHub API).** A median run executed 32 jobs against a 20-job runner cap, 23 of them under a minute (27 % of billed minutes), and queueing was about 75 % of the time to `ci-required`. By the workflow graph a `py` PR now executes 22 jobs (31 before). Re-measure on the next 30 runs with the same method, and report how many runs were created in that window, since queue time depends on load.

## Amendment 2 (2026-10-17, #3104)

- **Pipeline shape (refined).** Inside the `[security]` lane, jobs that hold the same permissions share one: the `contents: read` scans (pip-audit, npm-audit, the licence scan, the auth rule pack) run as steps of `read-only-scans`, and Bandit runs in Semgrep's job, `semgrep-bandit` (both upload SARIF). CodeQL, gitleaks and Trivy stay separate jobs.
- **Rule 2 unchanged.** `ci-required` judges the whole `security` workflow as one lane. Each folded scan is a `continue-on-error` step with its old job's time budget, and a verdict step fails the job unless every scan succeeded or was skipped, so one scan neither stops nor hides another. The cost: a re-run of a red folded job re-runs every scan in it.
- **Validation.** By the workflow graph a `py` PR now executes 18 jobs (22 before) and a PR matching every filter 37 (41). Re-measure with the method of Amendment 1.
- **PR2 (2026-10-17): `xstate-contract` in `gates`.** The blocking contract gate is a `gates` step on the `py` filter, `continue-on-error`, with its old job's time budget; `gates` exports its outcome under the lane's name, so rule 2 judges it as before. Its run has one definition, `tools/statechart/run_xstate_contract.sh`, which the nightly's `_job-xstate-contract.yml` also runs. By the workflow graph a `py` PR now executes 17 jobs and a PR matching every filter 36.
- **PR3 (2026-10-17): `gen` in `gates`.** Rule 3's freshness gate is the last `gates` step, after the installers, since its full install runs the PR's build scripts: `continue-on-error`, its old job's 5-minute budget, the same checks on the same Python 3.13 with only PyYAML (a venv of its own), and its failure summary written by the step itself. No pnpm or turbo cache is restored, so a cached artifact still cannot mask drift, and `gates` exports its outcome under the `gen` lane, so rule 2 judges it as before. By the workflow graph a docs-only PR now executes 3 jobs, a `py` PR 16 and a PR matching every filter 35.

## Amendment 3 (2026-10-18, #3433)

- **Pipeline shape (extended).** `pr.yml` also runs on `merge_group` for `main`, so GitHub's merge queue can test the exact `main`+PR tree before it merges. `changed-paths` diffs a merge group's head against `main` from their merge base, so the same filters start the lanes for its own change and for every entry ahead of it: the queue's grouping (`HEADGREEN` in `.github/branch-protection.json`) merges a failed entry together with a later one that passed, trusting the later run to have checked the combined change. Selecting more lanes is the safe direction. The trigger is inert until the owner turns on "Require merge queue" for `main`.
- **Rule 2.** On a merge group the PR-metadata gates, commitlint and changelog-fragment, are not applicable: the PR's run checked its title, body and commits, and the queue's squash commit is not those commits. They skip only where `changed-paths` reports a merge group, so a lost output runs them (fail closed). `secret-scan` scans the group's own commit: every entry ahead had its commits scanned on its own PR's run. Every other gate and lane is judged as on a PR. Protection requires only `ci-required`, so the workflows that run on `pull_request` only stay that way.
- **Rule 6.** A merge group's run executes in the base repository, as a push does. It holds only the permissions `pr.yml` declares, as a run for a same-repository PR does, receives no repository secret, and `coverage-ratchet.yml` ignores it. For a PR from a fork that is more than its PR run had (a read-only token): `security-events` in `security` and `pull-requests` in `coverage-thresholds`. Enqueueing is therefore the trust decision: the orchestrator enqueues a PR only once it has its two C-10.1 approvals and every check on the PR is green, `pr-metadata` and `governance` included, since the queue re-runs only `ci-required`.
- **Rule 7.** A push to a PR branch still cancels the branch's last run. Each merge group build runs in a concurrency group of its own, keyed on its head commit, and is never cancelled, since the queue would read the cancelled check as a failure.
- **#2892 (2026-10-18): `security-review-label` on a merge group.** This job, which labels a PR that touches a C-10.2 path, also holds `pull-requests` write on a merge group, because a job's permissions cannot depend on the event. A fork PR's merge-queue run therefore gains it as well as the two that rule 6 names. On a merge group the job checks out only `main` and skips its labelling step.

## Amendment 4 (2026-10-19, #3558)

- **Pipeline shape (extended).** C-9.1 #11's Dependabot alert gate runs as its own job, `dependabot-alerts`, on every PR and merge group. It is the only job that holds `vulnerability-alerts: read`, so by Amendment 2 it shares no job, and it installs nothing but the gate's PyYAML wheel, pinned by hash: no package the PR's manifests name runs while its token can read the alerts. No path filter applies: the alerts describe `main`, not the PR's paths, so a docs-only PR is blocked too while a High or Critical alert stays open (`docs/ci-runbook.md`, CI-SEC-001).
- **Rule 2.** `ci-required` judges it as the `dependabot-alerts` lane, applicable on every run. By the workflow graph a docs-only PR now executes 5 jobs, a `py` PR 18 and a PR matching every filter 37 (4, 17 and 36 before).
