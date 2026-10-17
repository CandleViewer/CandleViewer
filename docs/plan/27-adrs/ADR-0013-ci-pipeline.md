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
- Quarterly review of action pins and workflow permissions as part of the security programme.
- A deliberate "break the protocol" PR must fail the freshness gate (tested once during Sprint 01).

## Amendment 1 (2026-10-17, #3076)

- **Pipeline shape (refined, not reversed).** The `[always]` gates and the other sub-minute gates run as steps of one `gates` job in `pr.yml`, each step keeping its path filter; the `architecture` mirror runs beside `coverage-thresholds` instead of after the last `py` job; PR runs skip the informational sync-parity job, which runs nightly.
- **Rule 2.** A resolver lane may be a step outcome that `gates` exports under the lane's name. It is judged exactly like a job result: an applicable lane passes only on `success`, and a lane that is not applicable passes. `gates` is a lane too, so a failed setup or verdict step fails the resolver.
- **Validation (2026-10-17, 30 completed `pr.yml` runs, GitHub API).** A median run executed 32 jobs against a 20-job runner cap, 23 of them under a minute (27 % of billed minutes), and queueing was about 75 % of the time to `ci-required`. By the workflow graph a `py` PR now executes 22 jobs (31 before). Re-measure on the next 30 runs with the same method, and report how many runs were created in that window, since queue time depends on load.
