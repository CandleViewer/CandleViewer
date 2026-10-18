# CI/CD Runbook

> Owner: `area/infra-devops`. Source of truth for pipeline _operation_ — the
> pipeline's _shape_ is `docs/plan/27-adrs/ADR-0013-ci-pipeline.md` (binding
> rules 1–10); if this runbook and the ADR disagree, the ADR wins and this
> file is a bug — fix it in the same PR. Required check names are owned by
> `CONSTITUTION.md` C-9.1; this runbook does not restate that list.

## 1. Purpose

This is the document a person who did **not** write the pipeline uses to:
operate it day to day, understand what a red check means and how to fix it,
rebuild a dev environment from nothing, respond to a leaked secret, and
recover from a bad deploy. It exists because a pipeline only its author can
operate is a bus-factor risk (`docs/plan/32-risk-register.md` R10), and
because ADR-0013's own Validation section commits the team to running it,
measuring it and periodically breaking it on purpose.

## 2. Pipeline job map

```
PR opened/updated (.github/workflows/pr.yml)
├─ changed-paths            → path filters feeding every conditional lane
├─ gates          (one job, #3076)   → one step per gate below; each reports under its own lane
│  ├─ always:       spike-containment (CI-SPIKE-001/002), changelog-fragment (CI-REL-001),
│  │                licence-header, docs-link-check (GOV-002); last, as their installs run PR
│  │                scripts: commitlint, then gen (generated-code freshness, CI-GEN-001..004)
│  ├─ infra filter: pin-check (SR-132)                               (CI-GATE-003, CI-IMG-002)
│  └─ py filter:    statechart-lint, event-coverage, xstate-pin-attestation, machine-hash-lock,
│                   xstate-contract (tools/statechart/run_xstate_contract.sh, also run nightly)
├─ _job-js.yml    (js filter)        → node-version, lint, typecheck, unit, build (CI-JS-001, CI-BUILD-001)
├─ _job-py.yml    (py filter)        → ruff, mypy --strict, architecture contract; pytest in parallel
│                                      lanes (tools/ci/py-test-lanes.json), coverage combined
├─ architecture   (py filter)        → mirrors the py lane's result, beside coverage-thresholds
├─ _job-contract.yml (protocol filter) → OpenAPI/WS conformance         (CI-CON-001)
├─ _job-integration.yml (py filter)  → fixture-driven + DB integration  (CI-INT-001/002)
├─ _job-e2e.yml   (e2e filter)       → Playwright web (4 shards), e2e-staging (@demo-rest-only),
│                                      a11y-axe smoke, e2e-electron on release/* heads
│                                      (CI-E2E-001/002, CI-A11Y-001, CI-BUILD-001)
├─ _job-a11y.yml  (e2e filter)       → the a11y lane: tools/a11y/gates.py over axe, keyboard, trees,
│                                      flash and Lighthouse, plus the contrast-token gate (A11Y-*)
├─ _job-security.yml (js/py/infra/semgrep filters) → codeql, gitleaks, trivy (image filter) and two
│                                      folded jobs, one step per scan (#3104): semgrep-bandit;
│                                      read-only-scans (security-auth, pip-audit, npm-audit,
│                                      license-scan)                    (CI-SEC-001..005)
├─ _job-coverage.yml (js/py filters) → per-package threshold + ratchet  (CI-COV-001..003)
├─ _job-engine-bench.yml (engine/protocol filters) → GPU benchmark vs baseline
│                                      (CI-BEN-001, stub pending E03-T14)
└─ ci-required resolver (always)     → final merge gate                 (CI-GATE-001/002)

merge to main (.github/workflows/main.yml)
├─ dockerfile-pins        → digest-pin check                            (CI-IMG-001)
├─ build-scan-sign        → non-root hardening, Trivy, SBOM, cosign      (CI-IMG-002..006)
└─ deploy-dev.yml (workflow_run, self-hosted dev-host) → verify+deploy+smoke (CI-DEP-001..004, see §8)

merge to main / PRs touching CHANGELOG.md or the changelog tooling (.github/workflows/changelog.yml)
└─ changelog-preview → tools/ci/update_changelog.py --preview (job summary; never commits)

on demand / release branch (.github/workflows/deploy-staging.yml)
└─ deploy-staging (Environment "staging", required reviewers)          → CI-DEP-001..004, see §8

scheduled (.github/workflows/governance*.yml, coverage-ratchet.yml, cold-cache.yml, a11y-nightly.yml)
├─ governance             → bypass-register check                        (CI-PROT-004)
├─ governance-drift       → break-glass / register staleness detection   (CI-PROT-004)
├─ coverage-ratchet       → baseline-raise PR from merged coverage runs
├─ cold-cache             → py and web suites with no caches, non-required (CI-BUILD-001)
└─ a11y-nightly           → a11y sweep of every manifest route, non-required (see below)

release tag (.github/workflows/release.yml)
└─ compute-version → finalize-and-release → build-sign-installer         (CI-REL-001..004)
```

**Dependency-only PRs (#3182).** A PR that changes only `pnpm-lock.yaml`, the root `package.json`
or `pnpm-workspace.yaml` (a transitive `axe-core` or Playwright bump, say) starts `js`, `security`
and `coverage-thresholds` but not `e2e` or `a11y`. The manifests stay out of the `e2e` filter on
purpose: they would put seven more jobs (four `e2e-web` shards, `e2e-staging`, `a11y-axe`, `a11y`)
on every bump. The accepted control is the nightly `a11y-nightly.yml` sweep on `main`, a named
artefact of the release checklist (`docs/plan/07-release-and-prr.md` §4.1). The Playwright suite
has no scheduled run yet (C-9.2 asks for a nightly full matrix), so a bump that breaks it shows on
the next PR the `e2e` filter starts. The decision covers those three files only: a backend manifest
(`services/api/uv.lock`, `pyproject.toml`) skips `migrations`, `contract` and `rule-roundtrip` and
no nightly covers them, an open gap with no decision recorded, not an accepted control.

## 3. Reading the `ci-required` resolver summary

`pr.yml`'s `ci-required` job is the only job branch protection actually
requires; every lane above feeds it. Read its job summary top to bottom:

- A lane with filter `false` and result `skipped` is **fine** — not
  applicable to this diff.
- A lane with filter `true` and result anything other than `success` is
  **CI-GATE-001** — the PR is genuinely red on an applicable lane; go to
  that lane's own log.
- A lane with filter `true` and result `skipped` is **CI-GATE-002** —
  "gate misconfiguration": the workflow itself is broken (a lane that
  should have run did not). This is a pipeline bug, not a PR bug — do not
  try to work around it; open an `infra-devops` issue.
- A gate inside `gates` reports under its own lane name: read the `gates` step named after it
  (its job summary lists every gate's outcome). `gates` red while every gate lane is green
  means a setup step or the verdict step failed; read the `gates` log. A lane showing `cancelled`
  or an empty result means the 45-minute job cap or a run cancellation stopped `gates` first.
- `xstate-contract` is the `gates` step of that name (#3104). It runs
  `tools/statechart/run_xstate_contract.sh`: `uv sync`, the contract suite, event-name coverage,
  then the 60 s suite budget, stopping at the first failing command, so the end of the step log
  names the red check. `xstate-contract-nightly.yml` runs the same script; to reproduce, run
  `bash tools/statechart/run_xstate_contract.sh` in a checkout.
- `gen` is the last `gates` step (#3104): a full `pnpm install`, then
  `tools/ci/check_gen_freshness.py` in a fresh venv holding only PyYAML (Python 3.13). A red `gen`
  writes the reproduce steps to the job summary; its step log holds the CI-GEN code and diff.
- `security` is one lane over every job in `_job-security.yml`. In the folded jobs
  (`security / read-only-scans`, `security / semgrep-bandit`) each scan is a step that starts with
  the scan's name; the job summary's verdict table gives each scan's outcome, and the red scan's
  step holds its log. A red folded job with every scan green means a setup step failed. Re-running
  it re-runs every scan in that job (#3104).
- `CI-GATE-003` on `pin-check` means an action reference in `.github/workflows/**`
  is not pinned to a full commit SHA, or a workflow uses `pull_request_target`
  unsafely. Fix the reference; do not add an exception.

## 4. Triage recipes by error-code family

Each subsection below is the canonical target of the runbook-completeness
check (`scripts/check_runbook_completeness.py`, `CI-DOC-001`): every code
any workflow or `tools/ci`/`scripts` source can emit must have a heading
here, or the check fails the `governance` lane.

### CI-GATE-* — required-check resolver

- **CI-GATE-001** (applicable lane not successful): open the failing lane's
  log linked from the job summary; fix the underlying failure, do not touch
  the resolver.
- **CI-GATE-002** (gate misconfiguration): a required lane was skipped while
  its path filter said it applied. Compare `changed-paths` outputs against
  the lane's `if:` condition in `pr.yml` (a step's `if:` for a gate inside `gates`);
  this is almost always a filter/if mismatch introduced by an edit to `pr.yml` itself.
- **CI-GATE-003** (unpinned action / unsafe trigger): `tools/ci/check_action_pins.py`
  names the offending `uses:` line; replace the tag with the commit SHA
  GitHub shows for that release and keep the `# vX.Y.Z` comment.

### CI-JS-* — JS/TS lane

- **CI-JS-001** (`.nvmrc` vs `package.json#engines.node` mismatch): update
  whichever one is stale so both name the same Node major/minor; re-run
  `node tools/ci/check-node-version.mjs` locally.

### CI-GEN-* — generated-code freshness (`packages/protocol`)

The gate is the `gen` step of `pr.yml`'s `gates` job (§3); `make gen-check` runs it locally.

- **CI-GEN-001** (drift): the working tree does not match `make gen`'s
  output. Run codegen locally, commit the regenerated files — never hand-edit
  `packages/protocol/src/generated`.
- **CI-GEN-002** (untracked generated output): codegen produced files `git
diff` cannot see because they were never tracked. `git add` them in the
  same commit as the schema change that introduced them.
- **CI-GEN-003** (non-deterministic generation): running the generator twice
  produced two different hashes. This is a generator bug (usually an
  unordered map/set iteration or a timestamp leaking into output) — file it
  against the generator, do not silence the check.
- **CI-GEN-004** (generator toolchain failure): the generator itself crashed
  (missing dependency, schema syntax error). Fix the schema or toolchain;
  the gate cannot pass on a generator that did not run.

### CI-CON-* — contract conformance

- **CI-CON-001** (OpenAPI structural validity / server-route drift): a route,
  field or schema in `docs/plan/22-api-openapi.yaml` no longer matches the
  implementation the contract test exercises. Fix the contract-first: update
  the YAML, regenerate, then adjust the handler — never patch the generated
  client to paper over a real drift.

### CI-INT-* — integration lane fixtures

- **CI-INT-001** (fixture unavailable): a fixture referenced by
  `services/api/tests/fixtures/bybit/**` (or its manifest) is missing on
  disk. Confirm it was committed (fixtures are never fetched over the
  network in CI) and that `tools/ci/verify_fixture_manifest.py`'s manifest
  entry path matches.
- **CI-INT-002** (checksum mismatch): the fixture bytes on disk do not match
  the manifest's recorded checksum — either a fixture was edited without
  regenerating its checksum, or it was silently corrupted. Recompute and
  commit the checksum only if the edit was deliberate and reviewed; otherwise
  restore the original fixture.

### CI-E2E-* / CI-A11Y-* — Playwright + accessibility

- **CI-E2E-001** (Playwright suite failed after retry): a spec failed twice
  (not a single flake). Open the uploaded JSON reporter artifact for the
  failing shard; reproduce locally with `pnpm --filter @candleviewer/web e2e`.
  If it fails intermittently across three runs in a week, quarantine per
  §9 (flaky-test process) rather than re-running indefinitely.
- **CI-E2E-002** (demo-REST-only tag matched zero specs): the
  `@demo-rest-only` Playwright tag used to assert demo-environment orders
  never go over WS matched no specs — either the tag was renamed/removed by
  accident or the harness itself regressed. This must never silently pass;
  restore the tag or the specs it should match.
- **CI-A11Y-001** (new serious/critical axe-core violation): open the axe
  report artifact, find the new violation's rule id and selector, fix the
  markup (see `docs/plan/05-accessibility-standard.md`) — never suppress a
  rule repo-wide to unblock one PR.

### CI-BUILD-* — workspace build prerequisites (`tools/ci/check_built_exports.mjs`)

- **CI-BUILD-001** (a workspace package's built exports are missing): a lane that
  builds or tests `apps/web` with pnpm, vitest, vite or Playwright directly must build
  the packages `apps/web` imports first, because turbo's `^build` does not apply there
  (#3244, #3272). Those lanes are `_job-e2e.yml`'s `e2e-web`, `e2e-staging` and
  `a11y-axe`, `_job-a11y.yml`'s `a11y`, `a11y-nightly.yml`, `_job-js.yml`'s `build`
  (before its Electron-hardening step) and `cold-cache.yml`;
  `scripts/tests/test_web_tests_build_deps.py` finds every such job and fails when one
  lacks the build and guard steps. Check that the lane's
  `pnpm --filter "@candleviewer/web^..." run build` step ran and succeeded, and that
  every `exports` target in the package's `package.json` is a file its `build`
  produces (a pattern target must match at least one file).

### CI-SEC-* — security scanning (`tools/ci/security_gate.py`)

- **CI-SEC-001** (blocking finding): a CodeQL/Semgrep/Bandit/pip-audit/
  npm-audit/gitleaks finding has no accepted-risk entry. Fix the finding.
  Gitleaks findings never get an accepted-risk exception (see the gate's own
  comment) — rotate the secret per `SECURITY.md` / IR-02 (§6 below) instead.
- **CI-SEC-002** (licence violation): a new dependency's licence is not on
  `tools/ci/licenses-allowlist.json`. Either drop the dependency, find an
  allowlisted alternative, or add the licence to the allowlist in its own
  reviewed PR with a justification comment — never in the PR that needs it.
- **CI-SEC-003** (LGPL needs approval): an LGPL-licensed dependency needs an
  explicit CODEOWNER approval recorded in the PR description before the
  gate will pass; tag the relevant CODEOWNER and wait for their review.
- **CI-SEC-004** (accepted-risk expired): a previously accepted finding's
  expiry date (C-12.3) has passed. Re-triage: either fix it now or renew the
  acceptance with a fresh, shorter expiry and a note on why it is still
  acceptable.
- **CI-SEC-005** (scanner infrastructure failure): a scanner produced no
  output at all (crashed, mis-configured, or a > 1 non-finding exit code),
  or a SARIF report that records no scan: no `runs`, or a run without a
  named `tool.driver` (the message names the file and the run). CodeQL,
  Semgrep, Bandit and Trivy each write a run on a clean scan too (#3337).
  This never passes by default — check the scanner's own step log for a
  setup problem before assuming the codebase is clean (in a folded job the
  scan's step installs its own tools, so a failed install shows there).
  For `codeql` it also fires per language: each one in the job's
  `CV_CODEQL_LANGUAGES` needs a SARIF that this run's analyze wrote under the
  runner's temp directory, and the message names the language without one.
  The codeql job installs the gate's PyYAML after analyze, by hash, from
  `tools/ci/requirements-security-gate.txt`; if that step fails on a hash,
  refresh it with the command in that file (it tracks the PyYAML pin in
  `scripts/requirements-ci.txt` and the workflow's `PYTHON_VERSION`).
- **CI-SEC-006** (unjustified or expired in-source Semgrep suppression): a
  `# nosemgrep` marker does not clear the gate unless the comment reads
  `nosemgrep: <rule-id>[,<rule-id>] reason=<r> owner=@<handle> review=YYYY-MM-DD`
  with a review date between today and today + 180 days (farther is
  `CI-SEC-006 expiry too far`). Fix the comment or fix the code; see
  `docs/plan/04-security-program.md` 12.2.

### CI-COV-* — coverage gate (`tools/ci/coverage_gate.py`)

- **CI-COV-001** (below floor): measured coverage for a package is below its
  floor in `tools/ci/coverage-baselines.json` (services/api ≥85%/75% branch,
  chart-engine ≥85%, apps/web & packages/ui ≥80% — CONSTITUTION §9 #3). Add
  tests; floors are never lowered to pass (C-9.4).
- **CI-COV-002** (baseline regression): coverage dropped below the recorded
  baseline minus tolerance even though it is still above the hard floor.
  Add tests to recover the baseline, or — only when the drop is a deliberate,
  reviewed removal of dead/duplicated tests — let the nightly
  `coverage-ratchet` job open a baseline-raise PR reviewing the new number.
- **CI-COV-003** (missing coverage artifact): a lane that should have
  produced a coverage report for an applicable package left none. Check
  that lane's upload step; a silently-missing report must never pass.
  In `py` it names a test lane whose raw data (`py-lane-cov-<lane>`, kept
  5 days) is missing: the lane died before writing it, or a "Re-run failed
  jobs" came after the green lanes' data expired; then use "Re-run all jobs".

### CI-MIG-* — Alembic migration gate (`.github/workflows/_job-migrations.yml`,

`tools/ci/migration_lint.py`, C-5.1–C-5.6)

- **CI-MIG-000** (versions directory not found): the migration lint tool
  could not locate the Alembic `versions/` directory at the expected path.
  Check that the migration you added lives under the versions directory
  named in `docs/plan/21-database-schema.md`, and that the path was not
  moved without updating the lint tool's config.
- **CI-MIG-001** (multiple Alembic heads): `alembic heads` returned more
  than one head, meaning two migrations were parented off the same
  revision. Rebase onto `main`, re-`down_revision` your migration onto the
  new head so there is a single linear history (C-5.3), and re-run
  `alembic heads` locally to confirm exactly one head remains.
- **CI-MIG-002** (schema drift): `alembic check` found a mismatch between
  the SQLAlchemy models and the migration chain's resulting schema. Either
  a model changed without a matching migration, or a migration does not
  fully capture the model change. Autogenerate a diff (`alembic revision
--autogenerate`) and reconcile it into your migration by hand — never
  hand-edit an already-applied migration (C-5.4).
- **CI-MIG-003** (destructive operation without a `# cv:contract-phase:`
  annotation): the expand/contract linter found a drop/rename/narrowing
  operation with no phase annotation. Split the change into
  expand → migrate → contract across separate releases (C-5.1), and
  annotate the destructive statement with the phase comment the linter
  expects once you are genuinely in the contract phase.
- **CI-MIG-004** (upgrade-path failure): running the migration chain up
  from the previous release tag's schema failed. Reproduce locally
  (`alembic upgrade head` from a DB seeded at the previous tag) and fix the
  migration; this is separate from the round-trip check in CI-COV/CI-INT
  and exists specifically to catch assumptions about pre-existing data.
- **CI-MIG-005** (`IF NOT EXISTS` used in a migration): a migration file
  uses `IF NOT EXISTS`/`IF EXISTS` guards, which mask a wrong `down_revision`
  or a genuinely missing prior migration instead of failing loudly. Remove
  the guard and fix the actual ordering problem.
- **CI-MIG-006** (informational, non-blocking): a migration touches a table
  named in the audit-table list (C-5.7). This never fails the gate by
  itself — it is a flag for the reviewer to confirm no `UPDATE`/`DELETE`
  grant was added to an audit table.

### CI-IMG-* — container image supply chain (merge-to-main, `main.yml`)

- **CI-IMG-001** (unpinned base image): a `FROM` line in a Dockerfile is not
  pinned by digest. Pin it (`docker pull`, then `docker inspect --format
'{{index .RepoDigests 0}}'`) and commit the `@sha256:...` reference.
- **CI-IMG-002** (root user): the built image runs as root. Add a non-root
  `USER` directive; verify locally with `docker run --rm <image> id`.
- **CI-IMG-003** (Trivy High/Critical): a High/Critical CVE was found in the
  built image. Update the affected package/base image; if genuinely
  unfixable short-term, this needs the same accepted-risk process as
  CI-SEC-004, not a bypass.
- **CI-IMG-004** (cosign verification failed): the pushed image's signature
  did not verify against the expected keyless-OIDC identity. Treat as a
  supply-chain incident — do not deploy the image; re-run the build from a
  clean checkout and re-verify before investigating further.
- **CI-IMG-005** (SBOM generation/validation failed): `syft`'s CycloneDX
  output failed structural validation. Check the `syft` step log for a
  parse/tool error; the gate refuses to sign an image with no valid SBOM.
- **CI-IMG-006** (dev-only package in the image, #2893): the built image can
  import `cvdev`, or a boot with `CV_ACCOUNT_FIXTURE=compliant` did not stop
  with the package-absent refusal (`tools/ci/check_image_no_dev_modules.py`,
  also run by the PR `trivy` job). Check `infra/images/Dockerfile.api`: no
  `COPY` may name `services/api/cvdev` or a directory above it. A `Settings`
  refusal means the boot never reached the fence: check the image's `ENV`
  (a `CV_BYBIT_API_*` or `CV_TEST_CLOCK`) and the gate in `settings.py`. The
  step log shows the last lines of the boot.

### CI-SPIKE-* — spike containment (`tools/ci/check_spike_containment.py`)

- **CI-SPIKE-001** (throwaway prototype code reaching `main`): a path under
  a spike directory is present on a non-spike branch. Per C-4.5, spikes end
  in a written finding and are deleted — remove the prototype path from this
  branch; if code from the spike is genuinely being promoted, move it
  through a normal ticket, not by leaving the spike directory in place.
- **CI-SPIKE-002** (promoted benchmark harness imports from a spike path):
  a "real" benchmark still imports from the throwaway spike location.
  Copy the needed code into its permanent home and update the import.

### CI-PROT-* — branch-protection governance (`scripts/check_bypass_register.py`)

- **CI-PROT-004** (bypass register stale/empty/malformed): `.github/rulesets/bypass-register.md`
  has a row with a passed or too-far-future review date, is missing rows
  entirely, or is malformed. Add/update the row with a review date no more
  than one quarter (91 days) out, or remove a bypass actor that is no
  longer needed. See §5 for the break-glass procedure this register backs.

### CI-REL-* — release automation

- **CI-REL-001** (unparseable changelog fragment / non-conventional PR
  title): the PR has neither a conventional-commit title nor a parseable
  `Changelog:` footer. Fix the title, or add a footer line matching the
  format documented in `tools/ci/changelog_lib.py`'s docstring.
- **CI-REL-002** (1.0.0-explicit-declaration guard): the computed next
  version would cross into `1.0.0` without an explicit, reviewed
  declaration commit. This is deliberate friction — open the declaration PR
  named in the gate's error message first.
- **CI-REL-003** (release-binary signing parity): the Electron installer
  signing step did not produce a signature matching the image-signing
  parity requirement. Check the cosign keyless step log for an OIDC/identity
  mismatch.
- **CI-REL-004** (PRR gate unchecked): the draft release stays a draft while
  the PRR checklist item on the release-checklist issue is unchecked. This
  is not a bug — do not publish manually; complete the PRR checklist
  (`docs/plan/07-release-and-prr.md` §5) and let the checklist gate lift it.

### CI-DEP-* — dev/staging deploy (`tools/ci/deploy_dev.py`, §8)

- **CI-DEP-001** (signature verification failed): `cosign verify` did not
  accept the target digest against the expected OIDC identity/issuer.
  Deployment aborts before any container is replaced; the ledger records
  `signature-verification-failed`. Never re-run with `--no-...` to bypass
  this — investigate why `main.yml`'s own sign step produced (or the
  registry served) an unverifiable digest.
- **CI-DEP-002** (smoke test failed / timed out): `/healthz` or `/readyz`
  never returned `status: "ok"` within the timeout. On dev this triggers
  automatic redeploy of the last known-good digest (`rolled-back` ledger
  entry); on staging it stops and alerts — roll back manually (§8). Check
  the container logs for a stuck boot-time migration (advisory lock,
  E03-T10) first; a long CI-DEP-002 wait is often a CI-DEP-004 in disguise.
- **CI-DEP-003** (sha mismatch after deploy): the container came up healthy
  but `/healthz`'s `git_sha` never matched the digest we just deployed —
  "deploy succeeded, old image still running". Check that the compose
  service actually pulled the new digest (`docker compose images`) rather
  than reusing a cached local tag.
- **CI-DEP-004** (migration lock timeout): the boot-time Alembic advisory
  lock (E03-T10) did not release within its own timeout, so the container
  never reaches `/readyz`. Surfaces here as a CI-DEP-002 smoke timeout;
  check the API container's boot logs for the lock-wait message.

### CI-DOC-* — documentation drift (this runbook's own gate)

- **CI-DOC-001** (undocumented error code): `scripts/check_runbook_completeness.py`
  found a `CI-<FAMILY>-<NNN>` code emitted by a workflow or `tools/ci`/
  `scripts` source with no matching heading in this file. Add a subsection
  under §4 for the new code (copy the pattern above: what it means, how to
  fix it) in the **same PR** that introduced the emitting code — this is
  the mechanical enforcement of "a pipeline change ships with its own docs".

## 5. Secret-exposure response

A secret (API key, token, credential, signature) found in a commit, log,
artifact or screenshot is an incident, not a cleanup task:

1. **Rotate first, always** — per `SECURITY.md` / IR-02 (SR-143), rotating
   the credential at the source (Bybit key management, the secrets store)
   comes before any git-history surgery. A secret that was ever pushed is
   assumed compromised even after a force-push or history rewrite.
2. Follow `SECURITY.md`'s reporting path — never open a public issue
   (C-12.13).
3. If CI itself surfaced the leak (gitleaks, `CI-SEC-001`), the finding
   never gets an accepted-risk exception (§4 CI-SEC-*) — the PR cannot merge
   until the secret is gone from every commit in the branch and rotated.
4. After rotation, `git filter-repo` (or equivalent) removal from history is
   a follow-up hygiene step, not the fix — do it only after rotation is
   confirmed, coordinating with `@basiltt` since it rewrites shared history.

## 6. Quarterly action-pin and workflow-permission review (SR-132)

A recurring review with no scheduled owner does not happen, so it is a
GitHub issue template, not a calendar reminder someone might miss:

- Template: `.github/ISSUE_TEMPLATE/quarterly-ci-review.yml` (added by this
  ticket). Filing cadence: first business day of Jan/Apr/Jul/Oct.
- Checklist covers: every `uses:` action reference is still pinned to a SHA
  matching its documented tag (cross-check `.github/actions-pins.md`); every
  workflow's `permissions:` block is least-privilege for what that workflow
  actually does; the self-hosted GPU runner's isolation/ephemeral-workspace
  posture (ADR-0013 risk note) is still correct; the bypass register (§4
  CI-PROT-004) has no stale rows.
- The **first occurrence is scheduled** for **2026-10-01** (a
  `quarterly-ci-review`-labelled issue filed against `@CandleViewer/devsecops`,
  tracked in the same GitHub Project as regular tickets).

## 7. Dev environment rebuild from scratch (PRR-lite)

For an engineer with repository access and no prior context. If a step
below is found to be missing or wrong while actually following it, fix this
section in the same sprint — do not just work around it and move on.

1. Clone the repo; install the pinned toolchain: Node version from
   `.nvmrc`, `pnpm` via `corepack enable`, Python 3.12/3.13 via `uv`
   (`curl -LsSf https://astral.sh/uv/install.sh | sh` or the platform
   equivalent), Docker (for Postgres/QuestDB/testcontainers-backed suites).
2. `pnpm install --frozen-lockfile` at the repo root.
3. `uv sync --project services/api` (installs the pinned Python deps from
   `services/api/uv.lock`).
4. Copy `.env.example` to `.env`; never fill in real exchange credentials —
   local/dev defaults use fixture data and demo-only stubs, never a live key.
5. Bring up the local stack: `docker compose -f infra/docker-compose.dev.yml up -d`
   (Postgres, QuestDB — once `infra/` ships its compose file per its owning
   epic; until then this step is N/A and the smoke test in step 6 is
   frontend/backend-unit-only).
6. Smoke test: `pnpm verify` (JS/TS lint+typecheck+unit) and, from
   `services/api`, `uv run pytest -m "not exchange_smoke"`. Both must exit 0
   on a fresh clone before the rebuild counts as done.
7. Start the app locally per `AGENTS.md` §4's command table (owned there;
   not restated here) once the relevant app-runner ticket has landed.

## 8. Rollback of a bad dev/staging deploy

- Dev auto-deploys via `.github/workflows/deploy-dev.yml` on every green
  `main.yml` run (`workflow_run` trigger); staging deploys via
  `.github/workflows/deploy-staging.yml`, `workflow_dispatch` or a
  `release/*` push, gated on the `staging` GitHub Environment (required
  reviewers + a deployment branch policy restricting it to `main`/
  `release/*`, SR-141). Both call `tools/ci/deploy_dev.py`, which
  `cosign verify`s the digest immediately before applying it, renders
  `infra/compose/.env` from `infra/compose/.env.example`, runs
  `docker compose ... up -d --wait`, smoke-tests `/healthz` + `/readyz` and
  asserts the deployed `git_sha` matches, then appends a record to
  `deployments/ledger.jsonl` (sha, digest, environment, actor, timestamp,
  outcome, duration) — committed by the workflow for auditability until
  E04's observability lands.
- **Dev** auto-rolls-back on a failed smoke test: the previous `success`
  ledger entry's digest is looked up and redeployed automatically. Both
  outcomes (`smoke-failed` then `rolled-back`) land in the ledger.
- **Staging never auto-rolls-back** (a half-rolled-back staging environment
  mid-soak is harder to reason about than a stopped one) — a failed smoke
  test stops the job; roll back manually by dispatching
  `deploy-staging.yml` with `rollback_to_digest` set to the previous
  digest (find it via `grep '"environment":"staging"' deployments/ledger.jsonl | tail -5`
  or the digest recorded in `main.yml`'s `image-supply-chain-evidence`
  artifact / SBOM-diff job summary).
- Rollback never runs a down-migration (ADR-0013 rule 9): migrations are
  additive expand/contract, so redeploying an older image against the
  current schema is always safe; the deploy script does not invoke
  `alembic downgrade`.
- Never roll back by editing the running container in place — always
  redeploy a previously-built, previously-scanned image by digest.
- Production is a deliberate, checklisted action (ADR-0013 rule 8) and is
  out of scope here; see `docs/plan/07-release-and-prr.md` §4 for the
  release checklist and rollback procedure at that stage.

## 9. Flaky-test quarantine process

- ADR-0013 binding rule 10: a job that fails then passes on retry is
  recorded; three occurrences in a week auto-open a quarantine issue.
- On a quarantine issue: mark the test `@flaky` (Python) or `.fixme`/skip
  annotation with a linked issue (TypeScript/Playwright) within 24 hours
  (C-9.3) — never silently delete a flaky test to make CI green.
- The quarantine issue is `priority/p1-high`, assigned to the area owner of
  the flaky test's package, and stays open until the root cause is fixed and
  the test is un-quarantined in the same PR that fixes it.

## 10. Weekly PR-feedback-time report

- Job: `.github/workflows/ci-metrics-report.yml` (added by this ticket),
  scheduled weekly (Monday 06:00 UTC) and runnable on demand
  (`workflow_dispatch`).
- Reads the `ci-metrics` artifacts (per-run wall-clock time from
  PR-opened/updated to the `ci-required` resolver's conclusion, emitted by
  `pr.yml` since `E03-T01`) for the trailing 7 days and publishes p50/p90 as
  a job summary table.
- **Rebalance trigger**: if p90 > 15 minutes (ADR-0013's target), the report
  emits a `::warning::` annotation naming the rebalance instruction —
  "review the job matrix's path filters and the slowest lane in this run;
  either narrow that lane's trigger conditions or split it" — and opens (or
  comments on) a standing `priority/p2-medium` `area/infra-devops` issue
  tracking the rebalance so it is not lost.
- Budget: the report job itself must complete in ≤60s (this ticket's own
  Performance note); it fails loudly (not silently) if the `ci-metrics`
  artifact for a given week is entirely absent, since a missing metric is
  itself worth flagging, not treating as "zero incidents".

## 11. ADR-0013 validation log

Dated record of the two validation exercises the ADR's own Validation
section requires. Append a new dated entry here every time either exercise
is re-run (e.g. after a significant pipeline change) — never overwrite a
previous entry.

| Date       | Exercise                                                                                              | Result                                                                  | Evidence                                                                    |
| ---------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 2026-09-29 | Break-the-protocol (schema edit, no protocol regen)                                                   | Freshness gate failed with `CI-GEN-001` as expected; PR closed unmerged | See `docs/plan/backlog/E03-T15-validation/exercise-1-break-the-protocol.md` |
| 2026-09-29 | Gate sweep (synthetic secret, prohibited licence, coverage drop, second Alembic head, unsigned image) | Each planted defect independently proven to block its owning gate       | See `docs/plan/backlog/E03-T15-validation/exercise-2-gate-sweep.md`         |

## 12. Benchmark manual-override procedure

- The GPU benchmark lane (`_job-engine-bench.yml`, filled in by `E03-T14`)
  compares against a pinned baseline on a pinned self-hosted runner
  (ADR-0013 rule 4). If that runner is genuinely unavailable (hardware
  failure, maintenance window):
  1. The Architect records an explicit manual-override approval as a PR
     comment naming the reason and expected restoration date.
  2. The PR's benchmark check is treated as non-blocking only for that one
     PR, never repo-wide and never by editing the workflow's `if:` condition.
  3. The override is itself logged in this runbook's validation log (§11)
     as a dated entry so overrides are visible history, not silent bypasses.
- Baseline updates (as opposed to overrides) always need CODEOWNER approval
  and a written justification per ADR-0013 rule 4 — never conflate "the
  runner was down" with "the baseline should move".

## Credential hygiene and full-history sweep (E43-T06)

- `python scripts/check_secrets_hygiene.py all` (CI `gitleaks` job): fixtures carry the `DUMMYKEY_`
  prefix (SR-145), `.env` ignored and `.env.example` non-secret (SR-144), no `set -x`/env dumps in
  workflows, in the repository shell scripts their `run:` steps invoke or in the scripts those run
  (which forms count: `workflow_scripts` in the script; SR-146). `inventory <names.json>` and
  `logs <paths>` back the secret-inventory (SR-140/141) and log/artefact scans.
- Full-history sweep (run by the owner/DevSecOps before the pen-test; gitleaks is not installed on
  agent hosts): `gitleaks detect --source . --log-opts="--all" --config .gitleaks.toml --redact -r sweep.json`
  then `gitleaks detect --no-git ...`; record ruleset version, result and per-hit disposition in
  `docs/plan/spikes`-style note. Any real hit: **rotate first** (IR-02, SR-143), then investigate.

### Sweep record (executed 2026-10-03, gitleaks 8.30.1, ruleset = repo `.gitleaks.toml` on top of defaults)

- Full history (`--log-opts="--all"`, 1037 commits): 16 findings, **0 real credentials**. Dispositions:
  3x `generic-api-key` in `pr1611.diff` (commit 59f75058) = deliberate `CANARY*`/`hunter2-CANARY` test canaries;
  2x `generic-api-key` `docs/plan/threat-models/E05-design-system.md:190` = prose false positive;
  2x `aws-access-token` `.semgrep/tests/cv-secret-shaped-literal.py:7` = an AWS-shaped Semgrep rule-test
  literal (intentionally secret-shaped); 1x `rest_models.py:2143` = generated `max_length=36` description text;
  8x `docs/plan/{14,22,23}-*` = documentation examples (truncated JWT `eyJ...`, `mfa_`/`arm_` sample ids).
  No rotation required (IR-02 not triggered). The `gitleaks` CI job now also runs a full-history gitleaks sweep,
  `trufflehog filesystem` and `trufflehog git` (image pinned by digest; output is detector, file:line, commit,
  verified only). First CI run triage ([run 37080326323](https://github.com/basiltt/CandleViewer/actions/runs/37080326323)),
  all `verified=false`, no rotation:

  | Detector         | Location (mode)                                                   | Hits | Disposition                                                  |
  | ---------------- | ----------------------------------------------------------------- | ---- | ------------------------------------------------------------ |
  | Postgres         | `test_boot_advisory_lock_unit.py:121,126,141` (fs + git 8e8443cc) | 6    | test vector (dummy `u`/`h`/`d` DSN)                          |
  | Postgres         | `test_health_probes.py:67` (fs + git edabeaa2)                    | 2    | test vector (redaction test DSN)                             |
  | Postgres         | `test_health_report_router.py:71` (fs + git edabeaa2)             | 2    | test vector (redaction test DSN)                             |
  | Github           | `.git/config:12` (fs)                                             | 1    | false positive: checkout's ephemeral job token, runner state |
  | Github, Postgres | `trufflehog-fs.log:1-2` (fs)                                      | 2    | false positive: scanner self-scan of its own output          |

  Counts by class: test vector 10, false positive 3 (incl. the Postgres self-scan line), REAL 0. Path-specific excludes with
  reasons live in `.trufflehog-exclude`; raw output moved to `$RUNNER_TEMP` so it is never self-scanned.

- A committed secret fails `security_gate.py --tool gitleaks` (CI-SEC-001), whose output and a `::error` annotation cite IR-02.
- GitHub inventory (`gh api repos/.../actions/secrets|variables|environments`): 0 repository secrets, 0
  variables, 0 environments. CI therefore holds **no production credential** (SR-140). `TURBO_TOKEN`, `PROJECTS_PAT` and
  `GH_BRANCH_PROTECTION_TOKEN` are referenced by workflows but not provisioned (owner to scope them to an environment when added). When release secrets are introduced they MUST live in a protected
  `release` environment with required reviewers and use OIDC (no long-lived cloud keys); `check_inventory`
  fails any prod-credential or repo-scoped release secret name.
  Re-run 2026-10-03 (`gh api .../actions/secrets`, `/variables`, `/environments`; names only): still 0/0/0. No long-lived
  cloud credentials present; OIDC conversion (SR-141) n/a, evidenced by the empty inventory.
- SR-146: the `gitleaks` job runs `check_secrets_hygiene.py all` and scans its own log/artefact outputs
  (`logs`), covered by a leaky-job test. Scope: it scans the job's report/log files in the workspace
  (`*.json`, `*.log`, `*.sarif`), not the hosted Actions log stream itself.
