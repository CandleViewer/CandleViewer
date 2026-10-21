# E06-X02 — Spike toolchain supply-chain review and containment controls

- Ticket: E06-X02 (issue #165), Task, chart-engine, `blocked_by` E06-K01 (merged, PR #1503),
  E06-X01 (merged, PR #1415).
- Branch: `chore/e06-spike-supply-chain`.

## 1. Dependency pinning and review

### JS/TS

Every dependency the E06 spike introduced is already an **exact-range-then-lockfile-pinned**
`devDependency` of an existing workspace package (`packages/chart-engine` or `apps/desktop`),
resolved to a single exact version in the committed `pnpm-lock.yaml` (lockfile v9). E06-K01/K02/Q01
added **zero new package.json dependency entries** — every PR in the epic's merged history
(#1503, #1509, #1544) reused the harness's existing devDependencies (`vitest`, `@vitest/coverage-v8`,
`tsup`, `typescript`, `typescript-eslint`, `eslint`, `globals`, `@types/node`), which were justified
and reviewed when `packages/chart-engine` was scaffolded (E02-T03, PR #1452):

| Package | Resolved version (pnpm-lock.yaml) | Introduced by | Justification |
|---|---|---|---|
| `vitest` / `@vitest/coverage-v8` | 2.1.9 | E02-T03 | Test runner + V8 coverage; already the repo-wide standard for every TS package (`packages/config`). |
| `tsup` | pinned via range `^8.5.1` -> lockfile-resolved exact version | E02-T03 | `esbuild`-backed bundler for the package's `dist/` output; smallest maintained option that supports dual ESM output + `.d.ts` rollup without a hand-rolled build script. |
| `typescript` / `typescript-eslint` | 5.9.3 / 8.70.1 | E02-T03 | Repo-standard toolchain (`packages/config`). |
| `eslint` / `globals` | 9.39.5 / (lockfile-pinned) | E02-T03 | Repo-standard lint toolchain. |

No new **direct** dependency was added by E06-K01, E06-K02 or E06-Q01 — confirmed by diffing each
PR's `package.json`/`pnpm-lock.yaml` changes (none touched either file; `gh pr view <n> --json files`
shows no `package.json` or `pnpm-lock.yaml` path in #1503, #1509 or #1544). Playwright and Electron
(named in this ticket's "Scope / Deliverables" as things to review) are `apps/desktop`
devDependencies pinned at `electron@33.2.1` / `@playwright/test@1.49.1` / `playwright@1.49.1`
(exact caret ranges resolved to single lockfile entries); they were introduced and justified by
E02-T04 (desktop shell scaffold), not by this Epic's spike work — E06 has not yet driven a real
browser/Electron benchmark (see §4 below), so no new Playwright/Electron surface exists to pin here.
`pnpm-workspace.yaml`'s `allowBuilds` allowlist (`electron`, `esbuild`) and
`tools/ci/allowed-postinstall.json` already document and gate the only two packages in the whole
workspace with a reviewed postinstall/lifecycle script (SR-138); nothing E06 added needs a new entry.

### Rust/Tauri arm

**Does not exist in this repository yet.** `find . -iname Cargo.toml` returns no results outside
`node_modules`; E06-T03 (the Electron-vs-Tauri spike decision, ADR-0011) has not merged. There is
therefore no `Cargo.lock`, no crate set, and no `cargo audit` surface to pin or scan today — this
ticket's "Rust-arm dependencies should be confined to a workspace member that is trivially
deletable" guidance is recorded here for **whoever implements E06-T03** to follow at that time; it is
out of scope to fabricate a Rust workspace member with no code behind it just to exercise this
control. `cargo` is also not installed in this environment (confirmed: `which cargo` — not found),
consistent with the harness instructions' "NOT installed: docker, java" note (Rust/cargo likewise
absent), which is itself evidence no Rust arm has landed — the toolchain to build one was never
provisioned.

### Vendored font (SDF text)

**Does not exist yet either.** `packages/chart-engine/src/text/index.ts` is still the
`E06/E11`-scoped placeholder (`export {};`) — no SDF atlas generator, no font asset, checksummed or
otherwise, has been committed. E06-K03 ("prototype footprint cells + SDF text") has not merged
(confirmed: no merged PR referencing E06-K03). The hash-assertion control this ticket specifies
("record the font's SHA-256 alongside the asset, and have the atlas generator assert the hash at
generation time") is a requirement on **E06-K03's** introducing PR, not retrofittable here without a
font or atlas generator to attach it to. This is recorded as the concrete acceptance bar for that
ticket: the vendored font file ships alongside a `<font>.sha256` (or equivalent manifest entry) and
the atlas generator's first step reads and asserts that hash before generating glyphs, failing loudly
(not silently falling back) on a mismatch.

## 2. CI gates applied to the spike surface

- `packages/chart-engine/**` is already inside the `engine` path filter (`pr.yml` `changed-paths`
  job) and therefore inside `npm-audit`/`pnpm audit` (`_job-security.yml` `npm-audit` job, gates via
  `tools/ci/security_gate.py --tool npm-audit`), `gitleaks` (repo-wide, not path-scoped), and
  `codeql`/`semgrep` (both scan `javascript-typescript` across the whole tree, not path-filtered) —
  see `.github/workflows/_job-security.yml`. No path-filter exclusion hides `packages/chart-engine`
  from any of these; `security` (the `pr.yml` job wrapping `_job-security.yml`) triggers whenever
  `js == 'true' || py == 'true' || infra == 'true'`, and `packages/chart-engine/**` changes set
  `engine == 'true'` which is independent of, and does not suppress, the `js`/`infra` triggers that
  gate `security` — confirmed no `changed-paths` filter maps `engine` paths away from `js`/`infra`
  in a way that would exclude the engine package (Dependabot's own config, `.github/dependabot.yml`,
  is repo-tree-wide for the single pnpm ecosystem entry, so it already covers
  `packages/chart-engine/package.json`).
- `cargo audit` is not yet wired anywhere because there is no Rust code to audit (§1 above); wiring a
  `cargo-audit` job with nothing to scan would be a no-op gate, which this ticket's own "Technical
  notes" warns against ("a policy engine fails silently"). E06-T03's introducing PR must add a
  `cargo-audit` job to `_job-security.yml` (or a new reusable workflow) gated on a `rust`/`tauri`
  `changed-paths` filter, scoped to the trivially-deletable workspace member.
- **New in this PR:** the always-on `spike-containment` job in `.github/workflows/pr.yml` (§3) and
  the `chart-engine-harness-no-spike` `dependency-cruiser` rule plus the ESLint
  `no-restricted-imports` pattern in `packages/chart-engine/eslint.config.mjs` (§3), so the containment
  boundary is enforced by tooling on every PR, not by reviewer vigilance.

## 3. Throwaway-code containment

- `tools/ci/check_spike_containment.py` — the crude, reliable path-existence + import-boundary gate
  this ticket's "Technical notes" calls for. Two checks:
  1. `find_spike_paths` — fails (`CI-SPIKE-001`) if `packages/chart-engine/spike/` exists on the
     branch being checked (the ticket's own suggested directory name).
  2. `find_harness_imports_of_spike` — fails (`CI-SPIKE-002`) if any file under
     `packages/chart-engine/src/**` or `packages/chart-engine/bench/**` imports a path containing a
     `spike` path segment, even if the spike directory has already been removed.
  Wired into `.github/workflows/pr.yml` as the always-on `spike-containment` job (not path-filtered —
  a spike path reaching a PR must fail regardless of which `changed-paths` filter it happens to trip)
  and folded into the `ci-required` resolver.
  `scripts/tests/test_check_spike_containment.py` covers both scenarios plus the "harness file living
  under the spike marker is not double-counted as an importer" edge case and the missing-root error
  path (7 tests, `pytest scripts/tests/test_check_spike_containment.py -q`).
- `packages/chart-engine/eslint.config.mjs` — added a `no-restricted-imports` pattern
  (`**/spike/**`) to both the `src/**/*.ts`/`bench/**/*.ts` block and a new `bench/**/*.mjs` block, so
  `pnpm --filter @candleviewer/chart-engine lint` also fails on a harness-to-spike import locally, not
  only in CI.
- `.dependency-cruiser.js` — added `chart-engine-harness-no-spike` (`from: packages/chart-engine/(src|bench)`,
  `to: packages/chart-engine/spike`), mirroring the existing C-2.16 rules' style (named rule with a
  `comment` citing this ticket).
- **Deviation, disclosed:** the ticket's example path (`packages/chart-engine/spike/`) is what this
  check enforces going forward. E06-K02's prototype (PR #1509, merged **before** this ticket started)
  already landed under `packages/chart-engine/bench/scenes/` instead — a pre-existing gap in that
  ticket's own DoD execution that this ticket cannot retroactively fix by adding
  `bench/scenes/` to the forbidden-marker list without breaking `main` immediately (the opposite of
  what a containment gate is for; see the script's own top-of-file comment). `bench/scenes/README.md`
  already carries the required "THROWAWAY CODE" banner (title, date via the ticket reference, and the
  superseding report `docs/plan/spikes/E06-K02.md`), so the disclosure requirement is met even though
  the path-containment gate does not (yet) cover that specific directory. Recommendation for the Epic
  close checklist (§5): either promote `bench/scenes/` properly (tests, coverage, no "modelled GPU
  cost" caveat) or relocate it under `packages/chart-engine/spike/` before tagging/archiving, so the
  containment check's forbidden-path list can be extended to match without a `main`-breaking surprise.
- **Negative-test evidence** (ticket's own "Test plan" — "a deliberate PR adding a file under the
  spike path to `main` must fail the containment check"): verified locally, not as a separate PR
  (per this ticket's own branch-size guidance, "small, <=200 LOC... the deliberate failing test PRs
  are closed, not merged" — recorded here instead of opening/closing a throwaway PR):
  ```
  $ mkdir -p packages/chart-engine/spike && touch packages/chart-engine/spike/x.ts
  $ python tools/ci/check_spike_containment.py --root .
  CI-SPIKE-001: throwaway prototype code found on this branch under a spike-only path...
  $ echo $?
  1
  ```
  and the import-boundary case is exercised the same way by
  `scripts/tests/test_check_spike_containment.py::test_harness_importing_spike_path_fails_with_ci_spike_002`.

## 4. Secrets hygiene check

- `packages/chart-engine/bench/results.json`, `bench/baseline.json`, `bench/report-*.json/.md` and
  `bench/scenes/report-*.json/.md` are all `.gitignore`d (see `.gitignore` lines 66-72) — generated
  run artefacts are **never committed**, so there is nothing to scan them for; the only committed
  artefact-adjacent files are the `.mjs`/`.ts` source and `README.md`s, which contain no absolute
  paths, hostnames, or credentials (confirmed by `grep -riE "<local-user>|C:\\\\Users|/home/[a-z]+|localhost:[0-9]|127\.0\.0\.1"`
  across `bench/results.json` and `bench/scenes/*.md` — zero matches).
- `gitleaks` (repo-wide, `_job-security.yml`) already covers `packages/chart-engine/**` on every PR
  and on `main`; no path exclusion for this package exists.

## 5. Branch archival procedure (executed at Epic close)

1. Confirm every promoted E06 PR (currently #1503, #1509, #1544, plus whichever
   E06-K03/E06-K04/E06-T01 PRs land before Epic close) is merged to `main`.
2. Tag the throwaway spike branch as it stands at Epic close:
   `git tag -a spike/e06-engine-m0-archived -m "E06 M0 spike, archived unmerged at Epic close — see docs/plan/spikes/E06-K02.md" spike/e06-engine-m0`
   `git push origin spike/e06-engine-m0-archived`
3. Record the tag name and date on the Epic issue and in the M0 report
   (`docs/plan/spikes/E06-K02.md` "Findings"/closing section, or a dedicated `E06-M0-report.md` if one
   exists by then).
4. Delete the live `spike/e06-engine-m0` branch ref once the tag exists (the tag keeps the commits
   reachable and findable without the branch being importable or mergeable).
5. Confirm no commit from that branch has been merged into `main` — `git log main --grep="E06-K0"`
   plus a diff of `git merge-base main spike/e06-engine-m0-archived` against `main`'s tip should show
   the merge-base predates every prototype-only commit.

At the time of writing this ticket's PR, `spike/e06-engine-m0` does not exist as a remote ref
(`git ls-remote --tags origin | grep -i e06` and `git ls-remote origin 'refs/heads/spike/*'` both
return nothing). E06-K02 (PR #1509) was in fact opened from a branch named `spike/e06-engine-m0` —
but it was **squash-merged into `main`** (not left unmerged) and its branch auto-deleted afterward,
which is exactly the outcome §3's Deviation note flags: the prototype scenes under
`bench/scenes/` reached `main` because no containment gate existed yet to stop them, and the branch
that should have been archived unmerged no longer exists to archive. This ticket cannot undo an
already-merged PR; it can only (a) stop it happening again — the `spike-containment` gate added here
— and (b) record the gap so the Epic-close checklist accounts for it: `bench/scenes/` must be
promoted properly or relocated under `packages/chart-engine/spike/` and re-archived through a fresh
spike branch before Epic close, rather than the archival procedure being run against a branch that
no longer exists.
