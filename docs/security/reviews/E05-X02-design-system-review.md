# E05 security review — design-system dependencies, CSP impact and Storybook (E05-X02)

- Ticket: E05-X02 (#272), epic E05 (#30). Threat model: `docs/plan/threat-models/E05-design-system.md`
  (E05-X01, here `TM`). Blockers: E05-X01 (#215), E05-T03 (#269) and E05-S04 (#267) all Done.
- Audited sha: `main` `8addd87a73` (2026-10-31), the pre-stage; **re-run at S04's closing sha
  `2ea37eca034b0c1ddb95bb40e08321b3c0ef0ac9` (#5237, 2026-11-01) in §14.** Counts and versions in §1–§13
  are read at the pre-stage sha and §14 diffs them; paths are repo-relative.
- Method: the pipeline's own tools, run locally where they can be (`pnpm audit`, `pnpm licenses`, Semgrep at
  the pinned version), cited from the PR head's CI job where they cannot (CodeQL, the gitleaks binary).
  Agent review only; this is not the human security engineer's review the ticket's DoD names (§15).
- Disclosure: advisories are named by package@version, severity and the entry or tracker that decides them;
  no advisory id, CVE id or exploit detail appears here (C-12.13, `SECURITY.md`).

> **Status: READY.** §1–§13 were pre-staged while E05-S04 (#267) was In Progress, with named slices
> unbuilt (CMP-062, CMP-063, CMP-228, the RbacGate `tooltip` / `notice` forms). S04 closed with #5237 at
> `2ea37eca` (2026-11-01); every tree-dependent result (§2–§9, §11, §12 G5) was re-run there and diffed
> in §14. Verdict after the re-run: no Critical or High finding; the one open finding (the RbacGate
> statement, §12) is closed; no new finding. The orchestrator approved the accepted-risk entries by
> comment 6547596929 (2026-10-31) and re-confirmed them in its security read of record 6555686879
> (2026-11-01, §13). What stays outside this file: the agent security review on #30 (§15), posted at
> merge.

## 0. Ruling

The BQ list on #272 was ruled on 2026-10-31 (17:39Z) by the orchestrator under the owner's 2026-10-29
delegation (#2701): every BQ as proposed, with these decisions.

| BQ  | Ruled                                                                                                                                  | Where    |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 01  | Pre-stage on a draft; the re-run at S04's closing sha (#267 slice H) is one commit before READY                                        | §14      |
| 03  | Fix High; fix or allowlist each Medium with `expires`; the orchestrator approves the entries by comment under the delegation           | §3, §13  |
| 05  | C-12.3's 12-month rule on existing direct and first-level dependencies gives Info rows, not fails (the rule binds new dependencies)    | §5       |
| 08  | G2 reads "not weakened, hash pending #304"; with one comment on #304 that meets the DoD, without waiting                               | §10, §16 |
| 09  | `style-src 'unsafe-inline'` facts go to E43-T12 (#1239); no CSP change                                                                 | §10      |
| 10  | "No publish target exists; the dev and VR servers bind loopback"; A4 re-anchored in RSK-029, dated under the delegation; no new ticket | §11      |
| 14  | The missing RbacGate statement is a finding routed to #267 slice H; no catalogue edit here                                             | §12      |
| 18  | Accepted risks signed by the orchestrator under the delegation, with its wording; the owner ratifies                                   | §13, §15 |
| 20  | One PR; while a draft, `Refs #272` and a `Partial:` line, no closing verb. At READY the body says `Closes #272` (ruling 6546879910)    | PR body  |
| 23  | Licences over prod and dev; a dev-only off-allowlist licence is an Info finding; CI's `--prod` scope gap routed by comment             | §6       |

## 1. What the ticket assumes vs what shipped

| Ticket says                                       | At the audited sha                                                                                        |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| "Storybook 8"                                     | Storybook 10 with the docs, a11y and Vitest addons (`packages/ui/package.json`)                           |
| icon tooling dependencies                         | none: a vendored glyph registry; `scripts/build-icons.mjs` imports only `node:` modules                   |
| VR tooling                                        | Playwright with in-repo baselines (ADR-0019); no VR SaaS, so `TM` residual B4 does not materialise        |
| Style Dictionary                                  | 5.x                                                                                                       |
| pre-paint script allowlisted by hash              | exported with its hash pinned (`packages/ui/src/theme/prepaint.ts`, its test); embedded nowhere yet (§10) |
| Storybook "published"                             | no publish step exists (§11)                                                                              |
| a gitleaks path rule over `packages/ui/tokens/**` | no path rule; the tokens are covered by the full-tree scan and allowlisted nowhere (§9)                   |
| `dangerouslySetInnerHTML` "becomes a lint rule"   | Semgrep rule in CI already; this PR adds `react/no-danger` (§12)                                          |

The review verifies what shipped. A gap is a row routed to its owner, not built here.

## 2. Dependency inventory

Resolved from `pnpm-lock.yaml` (lockfile versions, not manifest ranges): the `packages/ui` importer's
dependencies, devDependencies and optional dependencies, the importers its `link:` entries name, and
every `dependencies` / `optionalDependencies` edge of each snapshot, walked to a fixed point, with
peer-resolution suffixes folded so each package@version counts once. (`pnpm list --depth Infinity`
shows only installed packages and folds repeats, so it is not the counting method.)

| Measure                                             | Count                                                                                      |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Direct dependencies                                 | 1 runtime (`@floating-ui/dom` 1.8.0, exact) + 25 dev (3 workspace, 1 exact, 21 `^` ranges) |
| Closure, package@version (workspace links excluded) | **788** (681 distinct names, 76 with more than one version)                                |
| On the runtime path                                 | **3**: `@floating-ui/dom` 1.8.0, `@floating-ui/core` 1.8.0, `@floating-ui/utils` 0.2.12    |
| Dev or build only                                   | 785                                                                                        |
| Storybook subtree (`storybook`, `@storybook/*`)     | 399 reached from them; **182** reached only through them                                   |

The closure includes the dev closures of the three workspace packages `packages/ui` links
(`@candleviewer/config`, `protocol`, `chart-engine`). Every later table is filtered to this inventory, and
§14's diff is computed on it. Count correction (2026-11-01): the pre-stage recorded 787 entries, 683
names and a Storybook subtree of 233 without the method that produced them; the walk above, re-run at
the PR head (lockfile byte-identical to both audited shas), gives 788 and 681. The Storybook row is the
same walk started only from the direct `storybook` / `@storybook/*` devDependencies (399 entries), and
the share of those no other direct dependency reaches (182).

**Pinning.** The runtime dependency and `esbuild` are exact; 21 devDependencies are `^` ranges despite
`saveExact: true`. Installs are lockfile-pinned (`frozenLockfile: true`), and every lockfile resolution is
a registry tarball with an integrity hash (none git-hosted). Of the workspace `overrides`, one lands
inside this closure: the `source-map-js` floor (resolved 1.2.2); `tar`, `http-cache-semantics` and
`undici` are not in it. No change proposed; bumps follow `docs/plan/35-dependency-freeze-policy.md`.

## 3. SCA: `pnpm audit` and Dependabot alerts

`pnpm audit --json` at the audited sha (workspace-wide, as CI runs it): 0 Critical, 0 High, 6 Medium,
4 Low. Kept: every advisory whose package@version is in the §2 inventory (membership, not audit
paths: `pnpm audit` caps `paths` at 100 per finding, so a path filter drops `minimatch@3.1.5`, which
resolves through `eslint`, a direct devDependency). At this sha every workspace finding is in the
closure: 7 Medium package@version rows (6 distinct advisories) and 4 Low advisory rows.

| Package@version  | Severity          | Path class (via)                                                             | Decided by                                                        |
| ---------------- | ----------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| vite@6.4.4       | Medium            | dev: test runner (`vitest`); workspace: `apps/web` dev server, e2e preview   | fix preferred (patch release 6.4.5); entry meanwhile, 2026-11-20  |
| qs@6.16.0        | Medium            | build: token build (`style-dictionary`)                                      | fix preferred (patch-level override); entry meanwhile, 2026-11-20 |
| minimatch@10.2.6 | Medium            | dev: lint (`typescript-eslint`), Storybook docgen; build: `style-dictionary` | accepted-risk entry, #272, expires 2026-11-20; fix is a major     |
| glob@13.0.6      | Medium            | build: `style-dictionary`; dev: Storybook docgen                             | accepted-risk entry, #272, expires 2026-11-20; fix is a major     |
| minimatch@3.1.5  | Medium            | dev: lint (`eslint` and its plugins); OpenAPI codegen via `protocol`         | the minimatch entry above (one advisory)                          |
| minimatch@5.1.9  | Medium            | dev: OpenAPI codegen (`protocol` > `openapi-typescript`)                     | the minimatch entry above (one advisory)                          |
| fast-uri@3.1.8   | Medium ×2, Low ×2 | dev: commit-message tooling of the shared config package (`ajv`)             | fix preferred (patch-level override); 2 entries meanwhile         |
| esbuild@0.27.7   | Low               | build: `tsup`                                                                | existing accepted-risk entry, tracker #3639, expires 2026-11-20   |
| deepmerge@4.3.1  | Low               | build: `style-dictionary`                                                    | listed (Low); no patched release reported                         |

- None is on the runtime path (§2): `packages/ui` ships its `dist/` bundle, and `@floating-ui/*` has no
  advisory.
- **Reconciliation with `security/accepted-risks.yaml`:** of its six `npm-audit` / `dependabot` entries,
  one covered this closure (the esbuild Low above). Its 2026-11-20 expiry could have fallen before the S04
  re-run; it did not (the re-run is dated 2026-11-01, §14). This PR adds six `npm-audit` entries, one per Medium
  advisory (the seven rows), ticket #272, expiring 2026-11-20 (inside C-12.3's 30 days, with the #3639
  batch). The orchestrator approved them by comment 6547596929 (2026-10-31), re-confirmed 6555686879
  (2026-11-01), with three conditions (§13).
- **Dependabot:** 6 open alerts at the audit time, all outside `packages/ui` (CI's Semgrep venv and the
  chart-engine Tauri bench harness); none has an npm manifest path. Three of the Semgrep-venv alerts carry
  no accepted-risk entry; that is noted for #3672 by comment, outside this review's scope.

## 4. Install scripts

`ignoreScripts: true`; only `electron` and `esbuild` may build (`pnpm-workspace.yaml` `allowBuilds`,
`tools/ci/allowed-postinstall.json`). Enumerated from the installed `package.json` of every inventory
entry on disk: **642** manifests read; 146 entries are optional platform binaries not installed on this
platform and were not enumerated.

| Hook                    | Packages                                                | Disposition                                                                                            |
| ----------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `postinstall`           | esbuild@0.25.12, @0.27.7, @0.28.2                       | retained: allowlist entry `esbuild`                                                                    |
| `preinstall`, `install` | none                                                    | —                                                                                                      |
| `prepare` only          | 39 (e.g. `style-dictionary`, `rollup`, `glob`, `jsdom`) | never runs: pnpm runs `prepare` only for git-hosted or local installs, and none of the closure is (§2) |

No allowlist change.

## 5. Maintenance (C-12.3's 12 months)

Public registry metadata for the 23 non-workspace direct dependencies and 51 further first-level
dependencies (74 unique packages; a first-level dependency that is also direct is counted once). Flagged when deprecated or when the latest release is more than 12 months old.

| Package@version                                                                                     | Level       | Flag                                                                                                             |
| --------------------------------------------------------------------------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------- |
| eslint@9.39.5                                                                                       | direct      | the registry marks this line unsupported (deprecated); 10.x is current. Workspace-wide (every package pins `^9`) |
| eslint-plugin-react@7.37.5                                                                          | direct      | latest release 2025-04-03 (> 12 months)                                                                          |
| 20 first-level packages (e.g. `prop-types`, `doctrine`, `json5`, `tinycolor2`, `@storybook/global`) | first level | latest release > 12 months; none deprecated                                                                      |

**Info rows** (BQ-05): C-12.3's 12-month rule binds new dependencies, so on existing ones these rows
are Info, not fails. The two direct flags are recorded for the frontend-platform lane's next dependency
pass. Staleness past the first level: not assessed.

## 6. Licences (C-12.3, §9 #14)

CI's licence step runs `pnpm licenses list --json --prod`, so for `packages/ui` it sees only the 3
runtime packages. This run reads the licence of all **788** inventory entries (642 from the installed
manifest, 146 from the registry for platform binaries not on disk) against
`tools/ci/licenses-allowlist.json`.

| Licence                                                                                      | Count | Disposition                                                                                               |
| -------------------------------------------------------------------------------------------- | ----- | --------------------------------------------------------------------------------------------------------- |
| MIT, Apache-2.0, ISC, BSD-2/3-Clause, MPL-2.0, Python-2.0, CC0-1.0, dual MIT/Apache, MIT/CC0 | 780   | allowed                                                                                                   |
| BlueOak-1.0.0 (5), MIT-0 (1), 0BSD (1)                                                       | 7     | allowed by the allowlist file; not in §9 #14's prose list (noted for the gate's owner)                    |
| CC-BY-4.0: caniuse-lite@1.0.30001812                                                         | 1     | **Info finding, dev-only** (browserslist data, Storybook's Babel path); off the allowlist, not denylisted |
| GPL / AGPL / SSPL / BUSL / unknown                                                           | 0     | —                                                                                                         |

The runtime path is MIT only. CI's `license-check` scans the shipped (prod) tree, which is C-9.1 #14's
object, so the dev-only off-allowlist licence is an **Info finding**, not a fail (BQ-23). It never ships;
the `--prod` scope gap is routed to the `license-check` gate's owner by comment (no workflow change, no new
issue).

## 7. Pinning

See §2. No finding.

## 8. SAST

- **Semgrep 1.181.0** (the pin in `tools/ci/requirements-semgrep.txt`), CI's 11 registry packs plus every
  `.semgrep/cv-*.yml`, over `packages/ui`: **308 rules, 600 files, 0 findings, 0 errors**.
- `cv-shell-dangerously-set-inner-html` over `apps` and `packages` (its own path scope): 433 files,
  0 findings.
- **CodeQL** (`javascript-typescript`) is not run locally: cited from the PR head's `codeql` job, with the
  count of open code-scanning alerts under `packages/ui/**` by rule id, in the PR's ready line.

## 9. Secrets

- "The gitleaks rule over the tokens is active" means: `.gitleaks.toml` extends the default ruleset, CI
  scans the whole tree and its history, and no allowlist path, global or per rule, matches a file under
  `packages/ui/tokens/`. `scripts/tests/test_e05_x02_design_system_review.py` pins it. No config edit.
- The gitleaks binary could not be run locally. The repo's approximation helpers (the default
  generic-key rule and every custom rule) over every tracked file in `packages/ui`: **0 hits**. The PR
  head's `gitleaks` job (pinned binary, full tree) is the authority and is cited in the ready line.

## 10. CSP (C-12.10)

| Check                                                    | Result                                                              |
| -------------------------------------------------------- | ------------------------------------------------------------------- |
| Inline scripts in `apps/web/index.html`                  | none; the meta CSP's `script-src` is `'self'` (C-12.10)             |
| Desktop CSP (`apps/desktop/src/main/csp.ts`)             | `script-src 'self'`; the hardening gate pins it exactly             |
| `'unsafe-inline'` or `'unsafe-eval'` in any `script-src` | none                                                                |
| Pre-paint script                                         | exported with its SHA-256 pinned by its unit test; embedded nowhere |

**G2 verdict: not weakened, hash pending #304** (E10-S01). The hash requirement is already
written on #304 (2026-10-17) and the script has not changed since. One dated confirmation goes on #304,
naming a second consequence without quoting the digest: the hardening gate's exact `script-src` pin must
accept the hash source when the script lands (also to E43-T01, #1230). The new pytest fails if an inline
script ever appears without its hash in the web `script-src`, or if either `script-src` gains a source
other than `'self'` or a hash. Open PR #5262 (E43) removes the meta from `index.html` in favour of one
the build injects (`apps/web/plugins/cspMetaPlugin.ts`, from the shared policy builder that
`packages/config/src/csp-policy.golden.json` pins). When the source page carries no meta, the pytest
reads that injected policy instead (and checks the plugin is wired, build-only, refuses a hand-written
meta and uses the meta surface), so it passes before and after #5262 merges; #5262's `script-src` is
still `'self'`.

`style-src 'unsafe-inline'` is in both policies. SR-112 allows it only if the design system needs it:
`packages/ui` ships CSS files and has 16 `style={…}` props in 12 non-story sources. These facts are routed
to the style-nonce decision, E43-T12 (#1239), by comment (BQ-09); no CSP change here. G2 is about the
script, so this does not fail the review.

## 11. Storybook hosting and fixture data

- **Verdict: no publish target exists; the dev and VR servers bind loopback.** Storybook is built in the
  `storybook` and `vr` jobs, but no workflow uploads `storybook-static` or runs a pages or
  hosted-Storybook step; the dev server binds `127.0.0.1` with telemetry off, and the VR capture serves
  the static build on `127.0.0.1` only. The new pytest pins all four.
- The story sources and 4,374 VR baselines are committed to a public repo, so a private host would hide
  nothing the repo does not already show. The control that matters is synthetic data.
- **A4 re-anchor.** `TM`'s A4 residual is re-reviewed "at E05-T09 Done", and no E05-T09 exists. RSK-029
  now carries it as "no publish target exists; re-review when one is planned", dated 2026-10-31 under the
  owner's 2026-10-29 delegation (#2701); the owner ratifies. No new ticket: E05-T09's absence is noted on
  #272, and whether a hosted Storybook is ever wanted is the owner's call.
- **Fixtures** (84 story, MDX and `.storybook` sources): a scripted pass for e-mail-, host-, IP-, hex-,
  key- and UID-shaped literals and comma-grouped amounts, every hit read. All synthetic: e-mails on
  `example.com` / `example.invalid`, secrets spelled `demo-…-not-a-secret` or `demo-secret-…`, one
  documentation URL, a placeholder UUID padded with zeros, BTC/ETH prices at public market levels, position rows on accounts
  "Main" / "Hedge" with round PnL. Gitleaks: §9.
- **VR baselines:** not opened one by one. A seeded (seed 272) sample of 20 from the 2,562 baselines whose
  story names match the table, matrix, toast, key-value, masked-value, info-panel, confirm, callout and
  copy stories was viewed: no account id, key, real balance or personal data. This is a sample, not every
  image.

## 12. Component checks

**G3, CMP-034 MaskedValue** (`packages/ui/test/MaskedValue.test.tsx`):

| Leg           | Test                                                                                                                                                            |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DOM           | "Scenario: Masked value never leaks by default"; "N1: … exactly one text node and in no attribute, name or title"                                               |
| Console       | "S5: nothing is logged over the whole lifecycle, a refused copy included"                                                                                       |
| Clipboard     | the `copyable` block (disabled while masked, copies only while revealed, re-mask mid-copy)                                                                      |
| Analytics     | **new**: the host callback only ever receives one boolean across the whole lifecycle; **new**: no `packages/ui` source imports a telemetry or analytics module  |
| Screen reader | accessibility-tree proxy: the mask is `aria-hidden` and the hidden text reads "<label>, hidden" (`expectMasked`). A real screen-reader pass is E05-Q02's (#262) |

**G4, CMP-044 hold gate:** `packages/ui/test/ConfirmDialogHold.test.tsx` ("a synthetic click(), a
pointerdown/pointerup pair and two clicks never confirm nor arm") and Q01's C63; E05-Q03 (#263) makes them
permanent pack tests. Scope: the gate stops a single stray or synthetic activation; it is intent friction,
not a defence against script already running in the page (that is the CSP's and SR-127's job).

**CMP-079 RbacGate (finding):** "a UI affordance, not an authorisation control" is present in the
component (`RbacGate.tsx`) and the Molecules docs, and **absent** from the catalogue entry
(`15-component-catalogue.md` CMP-079), which `TM` row L7 requires, and from `RbacGate.stories.tsx`, which
S04's Security notes require. Routed to #267 slice H by comment (BQ-14): the statement goes into S04's
"As built" lines and the catalogue entry there; no catalogue edit here. **Closed at the re-run** (§14): slice H
put it in the catalogue's "As built (E05-S04)" line and in the stories' docs description.

**G5, no HTML injection:** zero uses in `packages/ui` and `apps/web/src` (JSX attribute or `createElement`
prop). The one textual hit is a type-level ban (`IconSvg.tsx` omits the prop from its props). Enforced by
the Semgrep rule in CI and, from this PR, `react/no-danger: "error"` over `packages/ui`'s `src/` and
`.storybook/`, pinned by `test/eslint-rules/eslint-config.test.ts`.

## 13. Triage

| Finding                                                                                         | Severity | Disposition                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| minimatch@10.2.6 / 5.1.9 / 3.1.5, glob@13.0.6 on dev/build paths (§3)                           | Medium   | Accepted-risk entries in `security/accepted-risks.yaml` (ticket #272, expires 2026-11-20): the fix is a major the parents do not take. Accepted under the owner's 2026-10-29 delegation, #2701 6490317249; the owner ratifies. Approved by the orchestrator's comment 6547596929, re-confirmed 6555686879 |
| vite@6.4.4, qs@6.16.0, fast-uri@3.1.8 on dev/build paths (§3)                                   | Medium   | **Fix preferred**: a patch-level bump (vite 6.4.5, on the registry since 2026-10-21 and accepted by every range that pulls vite; qs 6.16.1, fast-uri 3.1.9), a lockfile change outside this PR's write set. Until it lands, entries on the same terms as the row above; the fix PR removes them           |
| The entries match on the advisory, so each covers it workspace-wide, not only for `packages/ui` | Info     | recorded; every path it covers is dev or build (§3). The vite entry also covers the `apps/web` dev server and the e2e preview, both loopback only                                                                                                                                                         |
| The vite / qs / fast-uri patch-level fix has no open design-system-lane ticket                  | Low      | carried as a row on epic #30 at merge (the E05-X02 security-review comment); the 2026-11-20 expiry gate is the backstop, and the entries' `ticket:` field stays #272                                                                                                                                      |
| esbuild accepted-risk entry may expire before the S04 re-run (§3)                               | Low      | #3639, by comment, if it does. Closed: it did not (§14)                                                                                                                                                                                                                                                   |
| eslint 9 unsupported; eslint-plugin-react stale (§5)                                            | Info     | frontend-platform lane's next dependency pass                                                                                                                                                                                                                                                             |
| caniuse-lite CC-BY-4.0, dev-only; CI's `--prod` licence scope (§6)                              | Info     | the `license-check` gate's owner, by comment                                                                                                                                                                                                                                                              |
| RbacGate statement missing from the catalogue and the stories (§12)                             | finding  | #267 slice H, by comment. Closed at `2ea37eca` (§14)                                                                                                                                                                                                                                                      |
| `style-src 'unsafe-inline'` (§10)                                                               | input    | E43-T12 (#1239), by comment                                                                                                                                                                                                                                                                               |
| A4 re-review trigger names a ticket that does not exist (§11)                                   | residual | RSK-029 re-anchored, dated under the delegation; the owner ratifies                                                                                                                                                                                                                                       |

No Critical or High finding exists at the audited sha, nor at the re-run sha (§14). G1's "each Medium has a
dated accepted-risk entry" is met: the orchestrator approved the six entries by comment 6547596929
(2026-10-31) and re-confirmed them in its security read of record 6555686879 (2026-11-01), with vite
re-classified as "fix preferred, entry meanwhile" and the expiry unchanged. Its three conditions: (1) the
entries match on id and tool, and no advisory id appears outside the YAML; (2) the patch-level fix is
preferred and the PR that lands it removes those entries; (3) at expiry an entry is fixed or
re-approved, never silently renewed.

## 14. Re-run at S04's closing sha

E05-S04 (#267) closed with #5237, merged to `main` as `2ea37eca034b0c1ddb95bb40e08321b3c0ef0ac9` on
2026-11-01. Everything below was re-run at that sha on 2026-11-01 and diffed against §2–§13; the PR's own
base (`40e63d45`) changes none of the paths this review reads after `2ea37eca`.

**What changed in the window** (`8addd87a73..2ea37eca`, 55 commits). `pnpm-lock.yaml`, `pnpm-workspace.yaml`
and every `package.json` are byte-identical, as are `apps/web/index.html`, `apps/desktop/src/main/csp.ts`,
`packages/ui/src/theme/prepaint.ts`, `.gitleaks.toml`, `tools/ci/licenses-allowlist.json`,
`tools/ci/allowed-postinstall.json`, the Semgrep pin and `packages/ui/.storybook/main.ts`. In `packages/ui`,
100 non-image files changed (55 added, 45 modified) and 678 VR baselines were added (14 story families:
WatchlistRow, PreviewTile, DensityToggle, ThemeSwitcher, FileDrop, WatchlistGroupTabs, ColumnPicker,
FreshnessMarker, Table, RbacGate, the E05-S04 theming matrix, the theming perf story, Checkbox, Button).
`.storybook/` gained `idlePointer.ts` and `eventually.ts` and a `preview.ts` `beforeEach`; `theme-bundles.ts`
re-ordered its CSS imports and added the new components' files; one token alias changed
(`semantic-light` `color.surface.hover`). `CONSTITUTION.md` §9 #14 was amended (v2.1.1, #5272) to admit
OFL-1.1 for the two vendored typefaces; that is not an npm dependency and is outside the §2 inventory.

| §   | Pre-staged result                                                              | At `2ea37eca`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Status    |
| --- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| 2   | 788 closure, 3 runtime, 399 / 182 Storybook (§2); exact runtime pin            | identical lockfile and manifests, so the inventory, the runtime path and the pinning facts are the same; no new dependency, no new version                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | confirmed |
| 3   | 0 Critical, 0 High, 6 Medium, 4 Low; 7 Medium + 4 Low rows                     | `pnpm audit --json` on 2026-11-01: 0 / 0 / 6 / 4, the same ten advisory rows (same package@version set, same patched ranges; `pnpm audit` lists no patched version for vite or deepmerge, but the registry has carried vite 6.4.5, outside the affected range, since 2026-10-21, so vite is "fix preferred", §13). The esbuild entry (expires 2026-11-20) is in force. Dependabot: 6 open alerts, all outside `packages/ui` (5 on CI's Semgrep venv, 1 on the chart-engine Tauri bench harness), as before. The six entries stand as written                                                                                                                                                                                                                                                                                                                                                                                                                           | confirmed |
| 4   | `postinstall`: esbuild only; no `preinstall` / `install`                       | a workspace-wide enumeration from a fresh lockfile install (3,064 manifests, a superset of the closure) finds the same three esbuild `postinstall` hooks and one `install` hook outside the inventory (`electron-winstaller`, the desktop packager's), none of which runs under `ignoreScripts: true`; the allowlist file is unchanged                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | confirmed |
| 5   | eslint 9 line deprecated; eslint-plugin-react stale; 20 first-level            | registry re-read 2026-11-01: eslint 9.39.5 still marked unsupported (10.x current); eslint-plugin-react's latest is still 7.37.5 (2025-04-03); no other direct dependency is deprecated at its resolved or latest version; the stale first-level set is unchanged (the only first-level releases in the window were `rollup` and `ws`, neither stale). Info rows as before                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | confirmed |
| 6   | 780 allowed, 7 allowlisted-only, 1 CC-BY-4.0 dev-only                          | identical closure and allowlist file, so the licence table is the same; the §9 #14 amendment adds OFL-1.1 for vendored fonts and does not touch the npm closure. Info finding as before                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | confirmed |
| 8   | Semgrep 1.181.0: 308 rules, 600 files, 0 findings; injection rule 433 files, 0 | the same 11 registry packs plus every `.semgrep/cv-*.yml` over `packages/ui`: **308 rules, 655 files, 0 findings, 0 errors**; `cv-shell-dangerously-set-inner-html` over `apps` and `packages`: 467 files, 0 findings; CI's `security/semgrep/auth` pack over its three targets: 13 rules, 1,608 files, 0 findings                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | confirmed |
| 9   | gitleaks not run locally; approximation helpers 0 hits                         | **the pinned gitleaks binary (8.30.1, CI's) was run this time**: `detect --no-git` over the whole tree at `2ea37eca` (200 MB), no leaks; over `packages/ui` at the PR head, no leaks; the PR's own commits (`git` mode), no leaks. The one token change is covered. The pytest pin (no allowlisted path under `tokens/`) is green                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | confirmed |
| 10  | `script-src 'self'` both sites; no inline script; 16 `style=` in 12            | both CSP sites and the pre-paint script unchanged; the pytest pins are green. `style={…}` props in non-story sources: **19 in 14 files** (new: `PreviewTile.tsx`, `Table.tsx`), still the E43-T12 (#1239) input, not a CSP change. G2 stays "not weakened, hash pending #304"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | confirmed |
| 11  | no publish target; loopback servers; 84 story sources; 4,374 baselines         | no workflow publishes (`test_no_workflow_publishes_a_storybook_build` green on the window's workflow changes; the dev server and the VR server flags are unchanged). Story, MDX and `.storybook` sources: **96** (24 added or changed); the scripted literal pass over those 24 found only synthetic data: `manager@example.com`, `example.com` URLs, `ALTnnnUSDT` / `BTCUSDT` / `ETHUSDT` / `SOLUSDT` / `FOOUSDT` symbols, public-level prices (64,012.50; 3,144.21), round turnover and byte counts, and one deliberate `<script>alert(1)</script>` text fixture whose story asserts it renders as text. VR baselines: **5,052** (+678); a seeded (272) sample of 12 of the 552 new baselines in the grid, tile, picker, switcher and notice stories was viewed: synthetic rows, no account id, key, balance or personal data (a sample, not every image). The new `.storybook` modules are tester-only (gated on Vitest's browser flag), with no network or storage | confirmed |
| 12  | RbacGate statement absent from the catalogue and the stories                   | present in both: the catalogue's "As built (E05-S04)" line for CMP-079 ("a UI affordance, not an authorisation control (the server enforces, C-12.4)") and `RbacGate.stories.tsx`'s docs description. G3 and G4 sources are unchanged in the window; `MaskedValue.test.tsx` and `eslint-rules/eslint-config.test.ts` re-run green (46 tests)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | closed    |
| 12  | G5: zero `dangerouslySetInnerHTML` uses                                        | zero uses in `packages/ui` and `apps/web/src` (grep and the Semgrep rule); the only textual hits are the `IconSvg.tsx` type-level ban and `innerHTML` reads in tests and story assertions that check a value is absent. `react/no-danger` is pinned by the lint test                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | confirmed |

**New surface checked, no finding.** CMP-067 FileDrop (new in the window) is the design system's first
file input: it refuses a file over `maxBytes` (64 KB) before reading it, holds a drop to the native
`accept` list, decodes UTF-8 and refuses other bytes, never interprets the text itself (the host parses and
previews), and the preview renders the host's content as text nodes only; its tests pin each of those
(`test/FileDrop.test.tsx`). T2 (RbacGate) is an affordance on it, not the control, as §12 says.

**New findings: none.** Per-finding status: every §13 row is confirmed as written except the two closed
above (the esbuild expiry row and the RbacGate statement). The accepted-risk entries and their expiries
need no change; the vite entry was re-classified "fix preferred" after the re-run (§13), and RSK-029
says so.

## 15. Sign-off

- Agent security review of this record at the PR head, posted on epic #30 and labelled "agent security
  review, not a human security engineer", with the carried row for the vite / qs / fast-uri
  patch-level fix (§13). Posted at merge.
- Accepted risks (the six Medium entries, §13) and the A4 re-anchor (§11): signed by the orchestrator
  under the owner's 2026-10-29 delegation (#2701) by comment 6547596929 (2026-10-31), re-confirmed
  6555686879 (2026-11-01) with its three conditions (§13); the owner ratifies.
- The human security engineer's comment the ticket's DoD names is not given by this record.

## 16. Gherkin and DoD map

| Item                                                              | State                                                                         |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| G1 zero Critical / High; each Medium dated                        | zero Critical / High at both shas (§14); Mediums entered, approved 6547596929 |
| G2 CSP not weakened                                               | not weakened, hash pending #304; both policies unchanged at the re-run (§14)  |
| G3 MaskedValue                                                    | automated and green (screen reader by proxy; the real pass is #262)           |
| G4 hold gate                                                      | automated and green                                                           |
| G5 no HTML injection                                              | zero uses at both shas; lint rule and Semgrep rule (§14)                      |
| DoD: hash requirement on E10                                      | on #304; the one confirmation comment meets it (BQ-08)                        |
| DoD: Storybook private, fixtures synthetic                        | no publish target; dev and VR servers loopback; fixtures synthetic            |
| DoD: security engineer comment on #30                             | agent review pending; human comment not given here                            |
| DoD: accepted risks dated, Owner-signed, in `32-risk-register.md` | RSK-029 updated; signed under the delegation, the owner ratifies              |
