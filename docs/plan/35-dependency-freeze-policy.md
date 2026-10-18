# 35 — Dependency freeze policy and vendored-code register (E43-T05)

Owner: Security engineer + @basiltt. Requirements: SR-130..SR-139, SR-156
(`04-security-program.md` §6.13). Code freeze for the pen-test: **2027-02-11**
(`30-release-roadmap.md` §8.5).

## 1. Freeze artefacts

| Surface | Frozen by                                           | Verified by                                                    |
| ------- | --------------------------------------------------- | -------------------------------------------------------------- |
| Python  | `uv.lock` (hashes)                                  | CI `uv sync --frozen`                                          |
| JS      | `pnpm-lock.yaml`                                    | `pnpm install --frozen-lockfile --ignore-scripts`              |
| Images  | `FROM ...@sha256:` in `infra/images/Dockerfile.api` | `tools/ci/check_dockerfile_pins.py`, `check_image_non_root.py` |
| Actions | full SHAs, ledger `.github/actions-pins.md`         | `tools/ci/check_action_pins.py`, Semgrep `cv-unpinned-action`  |

Tags: `pentest-freeze-<yyyymmdd>` (the build under test) and `pentest-retest-<yyyymmdd>`;
both hashes go in the evidence pack (E43-X07). Create the tag on the commit that
passes every gate in §4 — creating it is a release-manager action after this PR merges.

## 2. Changes allowed inside the freeze window

Only security fixes (a High/Critical advisory, or a pen-test finding). Each needs
**Security + Owner approval**, is recorded as a comment on E43-T05, produces a new
`pentest-freeze-*` tag, and the tester is notified (via E43-X02's channel) of the
new tag and the diff. Everything else waits until after the retest.

### 2.1 Dependency bumps and the freeze manifest (all year, not only in the window)

The `freeze` step of `read-only-scans` compares the installed graph to
`security/freeze-manifest.sha256` (§8.3), so
**every** dependency change is red until the manifest is regenerated in the same PR. That is
intended: the manifest is the reviewer's proof that the graph only changed where the PR says it
did. Dependabot cannot run `--write`, so the flow is **propose-in-CI, commit-by-human**:

1. **Grouped, labelled bumps.** `.github/dependabot.yml` opens at most one PR per ecosystem per
   week (`github-actions`, `pip`, `npm` minor+patch, `docker`), labelled
   `dependencies` plus the area / `sla/*` labels. Ungrouped single-package PRs from before this
   policy are closed in favour of the next grouped run (`@dependabot recreate` is acceptable).
2. **CI proposes, never commits.** `check_freeze_manifest.py --propose` runs in that `freeze`
   step on every PR. On a mismatch it still fails, prints the expected/actual digests, writes the
   regenerated manifest + unified diff to the job **step summary**, and (only for
   `dependabot[bot]` or `dependencies`-labelled PRs) uploads the `freeze-manifest-proposal`
   artifact (14 days). No workflow has write access to the branch; nothing is auto-committed.
3. **Review = diff + bump.** The reviewer (Security for `security-review`-labelled bumps, i.e. all
   `github-actions` ones; otherwise the area CODEOWNER) checks that (a) the other required checks
   are green, (b) the manifest diff touches exactly the components the bump should touch
   (`pnpm-lock.yaml`/`pnpm-graph` for npm, `uv.lock`/`uv-graph` for pip, nothing for
   actions/docker — those PRs must be green without a manifest change), and (c) during the freeze
   window the bump is a §2 security fix with Owner approval.
4. **Human commits the manifest.** Approved: the reviewer checks out the Dependabot branch, runs
   `python tools/ci/check_freeze_manifest.py --write`, commits
   `chore(<area>): regenerate freeze manifest for <bump>` and pushes (Dependabot keeps rebasing
   on top; if it force-pushes, re-run `--write`). Alternatively the orchestrator bundles several
   approved groups into one `chore(deps): weekly dependency bumps <date>` PR with a single
   `--write` — this is the preferred path when more than one ecosystem is red in the same week.
   Only after that commit is `read-only-scans` green and the PR mergeable (no admin merge, C-9.1).
5. **Majors on pinned-runtime-sensitive packages are ignored**, not merely left red: `size-limit`
   / `@size-limit/*` >= 12 need Node 22 while `package.json` `engines` pins Node 20 — ignored
   until the Node 22 upgrade ticket lands, which removes the `ignore` entry in the same PR.
   `xstate-statemachine` (ADR-0016 exact pin) and `pnpm` (corepack `packageManager` pin) are
   never bumped by Dependabot. **All npm semver-major bumps are ignored** (`dependency-name: "*"`) because majors are sequenced manually via #1819 (Node 22 floor first, #1778 F); remove that entry once step 1 of #1819 lands.
   The docker `python` base image (`infra/images`) ignores minor and major updates: the backend
   targets Python 3.12 (`services/api/.python-version`, the mypy/Ruff/Black targets in
   `services/api/pyproject.toml`, the `python:3.12-slim` pin in `infra/images/PINS.md`;
   `AGENTS.md` §5.2 sets 3.12 as the floor; #3314 declined, #3430), so only patch and digest
   updates flow until the runtime-upgrade ticket #3492 and its ADR remove the entry. Any new
   `ignore` entry needs a comment naming the unblocking ticket.

Non-Dependabot dependency changes (a feature PR adding a package) follow §8.3 as before: the
author runs `--write` in the same PR and the reviewer applies step 3(b).

## 3. Advisory SLA (SR-134)

Advisories touching the order path or key handling: triage within **48 h**; all others
**7 days**. Dependabot (`.github/dependabot.yml`) labels PRs `sla/48h` or `sla/7d`.
Unfixable High: §16.2 exception in `04-security-program.md` AND `security/accepted-risks.yaml`
(expiry <= one release cycle; Critical is never exception-able).

## 4. Gates (required checks, names in C-9.1)

`pip-audit`, `npm-audit`, `license-scan` (allowlist `tools/ci/licenses-allowlist.json`),
`trivy`, `semgrep`. Local: `pnpm audit --audit-level=high`.

## 5. postinstall review (SR-138)

CI installs with `--ignore-scripts`. Exceptions are the two in
`tools/ci/allowed-postinstall.json`: `electron` (pinned binary download) and `esbuild`
(pinned platform binary). Any addition needs Security review.

## 6. Container hardening

`Dockerfile.api`: digest-pinned base, multi-stage, `USER 10001:10001`; compose sets
`read_only: true` and drops capabilities; weekly rebuild via Dependabot docker +
scheduled build. Verified by `check_image_non_root.py`.

## 7. Vendored / forked third-party code (SR-139)

| Source               | Version | Reason | Update owner |
| -------------------- | ------- | ------ | ------------ |
| _none at 2026-10-03_ |         |        |              |

Adding any vendored or forked code requires a row here in the same PR.

## 8. SCA sweep triage (2026-10-03, `pnpm audit`, High/Critical)

| Package                               | Advisory                                 | Path                         | Area          | Decision                                                               |
| ------------------------------------- | ---------------------------------------- | ---------------------------- | ------------- | ---------------------------------------------------------------------- |
| tar (<=7.5.20, 1 Critical + 6 High)   | GHSA-23hp-3jrh-7fpw et al.               | transitive, electron-builder | build-time    | **Fixed**: `overrides: tar >=7.5.21`                                   |
| vitest 2.1.8 (Critical) / vite (High) | GHSA-5xrq-8626-4rwp, GHSA-fx2h-pf6j-xcff | dev, test runner             | dev-only      | **Fixed**: vitest + coverage-v8 -> ^3.2.6                              |
| electron 33.4.11 (11 High)            | e.g. GHSA-9qh4-3jw8-366w                 | direct                       | desktop shell | **Fixed**: electron -> ^41.10.7 (hardening gate + desktop tests green) |
| app-builder-lib, builder-util-runtime | GHSA-7g7r-gx96-252g, GHSA-p2f4-r6v6-j797 | direct, electron-builder     | build-time    | **Fixed**: electron-builder -> ^26.15.3                                |
| extract-zip                           | GHSA-jmr9-qjv8-65gv, GHSA-7pqw-9j4j-h8q3 | transitive of electron       | install-time  | **Fixed**: electron 41 no longer depends on `extract-zip`              |

### 8.1 Python and container sweep (2026-10-03)

| Scan               | Command                                                                                                                  | Result                                                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pip-audit (Python) | `uv export --frozen --no-emit-project` (services/api/uv.lock, hashed) then `pip-audit -r <file> --no-deps --disable-pip` | **No known vulnerabilities found**; no Python exceptions needed                                                                                                                                 |
| Trivy (container)  | `trivy` job on `infra/images/Dockerfile.api`                                                                             | **Not run locally: no docker / trivy binary.** Runs in the required CI `trivy` job; base image is digest-pinned. Any High/Critical it reports needs a fix or an exception before the freeze tag |
| Licences           | `license-scan` step of `read-only-scans`, allowlist `tools/ci/licenses-allowlist.json`                                   | CI-only; gate behaviour proven by fixture tests in `scripts/tests/test_dependency_freeze.py`                                                                                                    |

Tests in `scripts/tests/test_dependency_freeze.py`: known-vulnerable finding fails the SCA gate
(CI-SEC-001); prohibited licence fails with a message naming package and licence (CI-SEC-002);
Dockerfile is digest-pinned and non-root (static; runtime probe `check_image_non_root.py` needs
docker, not run locally); lockfiles are integrity-hashed (frozen installs reproduce byte-identically).

### 8.2 Post-fix sweep (2026-10-03)

After the electron / electron-builder bumps, `pnpm audit --audit-level=high` reports
**0 High / 0 Critical** (2 Low, 6 Moderate); `pip-audit` unchanged (none). No High/Critical
exceptions are needed, so EX-02..EX-04 are withdrawn (§16.2 of `04-security-program.md`).

**Correction (E43-T05-B1, #1737):** that sweep later reports 2 High with no upstream patch:
http-cache-semantics (GHSA-ch52-4w7c-c8xp) and braces (GHSA-vfj7-8cjw-p6xm). Both are build/dev-only
transitives; recorded as EX-05/EX-06 (EX-02..EX-04 stay withdrawn) (§16.2) and in `security/accepted-risks.yaml`, expiry 2026-12-31.
**Update (#1857):** EX-05 is cleared by a `pnpm-workspace.yaml` override (`http-cache-semantics >=4.3.0 <5`,
no major bump) and its register entry removed; EX-06 (braces, no upstream patch) remains.
The freeze-manifest `pnpm-graph` hash mismatch (defect 2) is only mitigated here by OS-independent normalisation
(unit-tested); it is NOT verified on Windows+Linux, so #1737 must not be closed on it: track it as a separate bug.

### 8.3 Freeze assertion and tag procedure

- CI (the `freeze` step of `read-only-scans`, `_job-security.yml`) runs `tools/ci/check_freeze_manifest.py` after
  `pnpm install --frozen-lockfile` and `uv sync --frozen`: SHA-256 of `pnpm-lock.yaml`, `uv.lock`,
  the normalised `pnpm ls -r --json --depth Infinity` graph and `uv export --frozen` must equal
  `security/freeze-manifest.sha256`. It does not depend on any tag. Any approved freeze change
  (§2) regenerates the manifest with `--write` in the same PR; Dependabot PRs get the
  regenerated manifest as a CI proposal and a human commits it (§2.1).
- Tag (owner-only): on the merged commit whose CI is green, the owner runs
  `git tag -a pentest-freeze-<yyyymmdd> <sha> -m "pen-test freeze; manifest <sha256 of freeze-manifest.sha256>"`
  and `git push origin pentest-freeze-<yyyymmdd>`; the tag sha + manifest hash go into the
  evidence pack (E43-X07). Retest uses `pentest-retest-<yyyymmdd>` the same way.

### 8.4 npm-audit gate fix and SCA triage (2026-10-18, #3494)

The `npm-audit` step's gate read npm's `vulnerabilities` schema, but the step feeds it
`pnpm audit --json`, which writes `advisories` + `metadata`, so the gate saw no findings. It now
reads pnpm 12.5.1's report and fails closed on anything else (CI-SEC-005). On `main` (d77138f07)
`pnpm audit` reported 2 Critical, 2 High, 6 Moderate and 1 Low; the overrides below (in
`pnpm-workspace.yaml`, each floored at the first patched release) leave 1 High (EX-06),
6 Moderate and 1 Low, which the gate's High threshold passes.

| Package                     | Advisory                                                           | Path                                        | Area            | Decision                                                                                                                                                           |
| --------------------------- | ------------------------------------------------------------------ | ------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| tinypool 1.1.1 (2 Critical) | GHSA-5gmw-xhrv-c9v3, GHSA-85c8-ppgw-ccpr                           | transitive, vitest 3.2.7                    | test-only       | **Fixed**: `overrides: tinypool >=2.1.2 <3` (2.2.0); every vitest suite passes on it. Remove with vitest 4 (#1819)                                                 |
| source-map-js 1.2.1 (High)  | GHSA-68fv-2mgg-jv7q                                                | transitive, postcss and magicast            | build/test-time | **Fixed**: `overrides: source-map-js >=1.2.2 <2` (1.2.2); the ui and web builds pass                                                                               |
| braces 3.0.3 (High)         | GHSA-vfj7-8cjw-p6xm                                                | transitive, lint-staged                     | dev-only        | Unchanged: EX-06 (`security/accepted-risks.yaml`), expires 2026-12-31                                                                                              |
| 6 Moderate, 1 Low           | uuid, react-router ×2, vitest, @vitest/mocker, sprintf-js; esbuild | transitive (react-router ships in apps/web) | mixed           | **Accepted** to 2026-11-20 (pre-R1 cut): one dated entry per advisory in `security/accepted-risks.yaml` (#3558), as R0's gate (`30-release-roadmap.md` §4.4) wants |

#3558: none of the seven pnpm advisories has a patched release in its installed major.
react-router (which ships) and vitest need #1819's majors, uuid needs Storybook 9 or later,
esbuild needs tsup 9, and sprintf-js has no fix. Dependabot also lists vitest on seven manifests,
which the vitest entry's decision covers, and tauri 2.1.1 in the E06-T01 bench harness (patched
in 2.11.1, a pin bump that needs cargo and a harness re-run), accepted to the same date as
`tool: dependabot`. C-12.3 gives a Medium 30 days, which end 2026-10-27 to 2026-11-07 for the six
Medium GHSAs here, tauri's included: running them one release cycle is exception EX-09
(`04-security-program.md` §16.2), for the owner to ratify on #2701. They expire when S09 starts,
so the re-decision comes before the R1 cut and the cut-day PRs stay green.
