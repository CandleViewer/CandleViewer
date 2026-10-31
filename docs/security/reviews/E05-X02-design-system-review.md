# E05 security review — design-system dependencies, CSP impact and Storybook (E05-X02)

- Ticket: E05-X02 (#272), epic E05 (#30). Threat model: `docs/plan/threat-models/E05-design-system.md`
  (E05-X01, here `TM`). Blockers: E05-X01 (#215) and E05-T03 (#269) closed; **E05-S04 (#267) open**.
- Audited sha: `main` `8addd87a73` (2026-10-31). Counts and versions below are read there; paths are
  repo-relative.
- Method: the pipeline's own tools, run locally where they can be (`pnpm audit`, `pnpm licenses`, Semgrep at
  the pinned version), cited from the PR head's CI job where they cannot (CodeQL, the gitleaks binary).
  Agent review only; this is not the human security engineer's review the ticket's DoD names (§15).
- Disclosure: advisories are named by package@version, severity and the entry or tracker that decides them;
  no advisory id, CVE id or exploit detail appears here (C-12.13, `SECURITY.md`).

> **Status: pre-staged, not final.** E05-S04 (#267) was In Progress when these results were taken, with
> named slices unbuilt (CMP-062, CMP-063, CMP-228, the RbacGate `tooltip` / `notice` forms). Every
> tree-dependent result (§2–§9, §11, §12 G5) is re-run at S04's closing sha and diffed in §14 before this
> record is READY. Open for READY: that re-run, the Owner's decision on the Mediums (§13), the Owner's
> dated sign-off on the A4 re-anchor (§11) and the agent security review on #30 (§15).

## 0. Assumed pending ruling

The BQ list on #272 is not yet ruled. This record builds on each BQ's proposed answer; a ruling that flips
one changes only the rows named.

| BQ  | Assumed                                                                                                                                      | Flip changes     |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 01  | Pre-stage on a draft PR covers a blocker In Progress; READY only after the S04 re-run                                                        | §14, status line |
| 05  | A stale or deprecated existing dependency is an advisory finding, not a C-12.3 exception due now                                             | §5               |
| 08  | The written handoff on E10-S01 (#304) satisfies "recorded on the E10 ticket"; G2 reads "not weakened; hash allowlisting pending #304"        | §10, §16         |
| 14  | The missing RbacGate statements are routed to S04 (#267), not added here                                                                     | §12              |
| 18  | An agent security lens on #30, labelled as such; Owner signs any accepted risk                                                               | §15              |
| 20  | Draft with `Refs #272`; `Closes` only when every DoD row is met                                                                              | PR body          |
| 23  | Licences scanned with dev included; a dev-only non-allowlisted licence is a finding routed to the licence gate's owner, not a review failure | §6               |

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

Resolved from `pnpm list --filter @candleviewer/ui --depth Infinity --json` (lockfile versions, not
manifest ranges):

| Measure                                             | Count                                                                                      |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Direct dependencies                                 | 1 runtime (`@floating-ui/dom` 1.8.0, exact) + 25 dev (3 workspace, 1 exact, 21 `^` ranges) |
| Closure, package@version (workspace links excluded) | **787** (683 distinct names, 76 with more than one version)                                |
| On the runtime path                                 | **3**: `@floating-ui/dom` 1.8.0, `@floating-ui/core` 1.8.0, `@floating-ui/utils` 0.2.12    |
| Dev or build only                                   | 784                                                                                        |
| Storybook subtree (`storybook`, `@storybook/*`)     | 233                                                                                        |

The closure includes the dev closures of the three workspace packages `packages/ui` links
(`@candleviewer/config`, `protocol`, `chart-engine`). Every later table is filtered to this inventory, and
§14's diff is computed on it.

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

| Package@version  | Severity          | Path class (via)                                                             | Decided by                                                      |
| ---------------- | ----------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------- |
| vite@6.4.4       | Medium            | dev: test runner (`vitest`)                                                  | **open: Owner (§13)**; no patched release reported              |
| qs@6.16.0        | Medium            | build: token build (`style-dictionary`)                                      | **open: Owner (§13)**; a patch release fixes it                 |
| minimatch@10.2.6 | Medium            | dev: lint (`typescript-eslint`), Storybook docgen; build: `style-dictionary` | **open: Owner (§13)**; fixed only in a later major              |
| glob@13.0.6      | Medium            | build: `style-dictionary`; dev: Storybook docgen                             | **open: Owner (§13)**; fixed only in a later major              |
| minimatch@3.1.5  | Medium            | dev: lint (`eslint` and its plugins); OpenAPI codegen via `protocol`         | **open: Owner (§13)**; fixed only in a later major              |
| minimatch@5.1.9  | Medium            | dev: OpenAPI codegen (`protocol` > `openapi-typescript`)                     | **open: Owner (§13)**; fixed only in a later major              |
| fast-uri@3.1.8   | Medium ×2, Low ×2 | dev: commit-message tooling of the shared config package (`ajv`)             | **open: Owner (§13)**; a patch release fixes it                 |
| esbuild@0.27.7   | Low               | build: `tsup`                                                                | existing accepted-risk entry, tracker #3639, expires 2026-11-20 |
| deepmerge@4.3.1  | Low               | build: `style-dictionary`                                                    | listed (Low); no patched release reported                       |

- None is on the runtime path (§2): `packages/ui` ships its `dist/` bundle, and `@floating-ui/*` has no
  advisory.
- **Reconciliation with `security/accepted-risks.yaml`:** of its six `npm-audit` / `dependabot` entries,
  one covers this closure (the esbuild Low above). Its 2026-11-20 expiry may fall before the S04 re-run;
  if it does, that is a finding for #3639, by comment. No entry covers the seven Medium rows.
- **Dependabot:** 6 open alerts at the audit time, all outside `packages/ui` (CI's Semgrep venv and the
  chart-engine Tauri bench harness); none has an npm manifest path. Three of the Semgrep-venv alerts carry
  no accepted-risk entry; that is noted for #3672 by comment, outside this review's scope.

## 4. Install scripts

`ignoreScripts: true`; only `electron` and `esbuild` may build (`pnpm-workspace.yaml` `allowBuilds`,
`tools/ci/allowed-postinstall.json`). Enumerated from the installed `package.json` of every inventory
entry on disk: **641** manifests read; 146 entries are optional platform binaries not installed on this
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

Advisory under the assumed ruling (§0, BQ-05): none blocks; the two direct flags are recorded for the
frontend-platform lane's next dependency pass. Staleness past the first level: not assessed.

## 6. Licences (C-12.3, §9 #14)

CI's licence step runs `pnpm licenses list --json --prod`, so for `packages/ui` it sees only the 3
runtime packages. This run reads the licence of all **787** inventory entries (641 from the installed
manifest, 146 from the registry for platform binaries not on disk) against
`tools/ci/licenses-allowlist.json`.

| Licence                                                                                      | Count | Disposition                                                                                                  |
| -------------------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------ |
| MIT, Apache-2.0, ISC, BSD-2/3-Clause, MPL-2.0, Python-2.0, CC0-1.0, dual MIT/Apache, MIT/CC0 | 779   | allowed                                                                                                      |
| BlueOak-1.0.0 (5), MIT-0 (1), 0BSD (1)                                                       | 7     | allowed by the allowlist file; not in §9 #14's prose list (noted for the gate's owner)                       |
| CC-BY-4.0: caniuse-lite@1.0.30001812                                                         | 1     | **finding, dev-only** (browserslist data under Storybook's Babel path); not on the allowlist, not denylisted |
| GPL / AGPL / SSPL / BUSL / unknown                                                           | 0     | —                                                                                                            |

The runtime path is MIT only. The one finding never ships; it is routed, with the `--prod` scope question,
to the `license-check` gate's owner by comment (no workflow change, no new issue).

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

## 10. CSP

| Check                                                    | Result                                                              |
| -------------------------------------------------------- | ------------------------------------------------------------------- |
| Inline scripts in `apps/web/index.html`                  | none; the meta CSP's `script-src` is `'self'`                       |
| Desktop CSP (`apps/desktop/src/main/csp.ts`)             | `script-src 'self'`; the hardening gate pins it exactly             |
| `'unsafe-inline'` or `'unsafe-eval'` in any `script-src` | none                                                                |
| Pre-paint script                                         | exported with its SHA-256 pinned by its unit test; embedded nowhere |

**G2 verdict: not weakened; hash allowlisting pending E10-S01 (#304).** The hash requirement is already
written on #304 (2026-10-17) and the script has not changed since. One dated confirmation goes on #304,
naming a second consequence without quoting the digest: the hardening gate's exact `script-src` pin must
accept the hash source when the script lands (also to E43-T01, #1230). The new pytest fails if an inline
script ever appears without its hash in the web `script-src`, or if either `script-src` gains a source
other than `'self'` or a hash.

`style-src 'unsafe-inline'` is in both policies. SR-112 allows it only if the design system needs it:
`packages/ui` ships CSS files and has 16 `style={…}` props in 12 non-story sources. Recorded as input to the
style-nonce decision, E43-T12 (#1239); G2 is about the script, so this does not fail the review.

## 11. Storybook hosting and fixture data

- **No publish target exists.** Storybook is built in the `storybook` and `vr` jobs, but no workflow
  uploads `storybook-static` or runs a pages or hosted-Storybook step; the dev server binds `127.0.0.1`
  and runs with telemetry off. The new pytest pins all three.
- The story sources and 4,374 VR baselines are committed to a public repo, so a private host would hide
  nothing the repo does not already show. The control that matters is synthetic data.
- **A4 re-anchor.** `TM`'s A4 residual is re-reviewed "at E05-T09 Done", and no E05-T09 exists. RSK-029
  now carries it as "no publish job exists; re-review when one is planned". Needs the Owner's dated
  sign-off on #272 (§15).
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

**CMP-079 RbacGate:** "a UI affordance, not an authorisation control" is present in the component
(`RbacGate.tsx`) and the Molecules docs, and **absent** from the catalogue entry
(`15-component-catalogue.md` CMP-079), which `TM` row L7 requires, and from `RbacGate.stories.tsx`, which
S04's Security notes require. Routed to S04 (#267) by comment.

**G5, no HTML injection:** zero uses in `packages/ui` and `apps/web/src` (JSX attribute or `createElement`
prop). The one textual hit is a type-level ban (`IconSvg.tsx` omits the prop from its props). Enforced by
the Semgrep rule in CI and, from this PR, `react/no-danger: "error"` over `packages/ui`'s `src/` and
`.storybook/`, pinned by `test/eslint-rules/eslint-config.test.ts`.

## 13. Triage

| Finding                                                                                                      | Severity | Disposition                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| vite@6.4.4, qs@6.16.0, minimatch@10.2.6 / 5.1.9 / 3.1.5, glob@13.0.6, fast-uri@3.1.8 on dev/build paths (§3) | Medium   | **Owner decides**: fix (qs and fast-uri by a patch-level override; the others need a major or have no fix) or a dated accepted-risk entry each. An entry matches on the advisory, so it silences that advisory workspace-wide, not only for `packages/ui`. The register's schema keys an entry on the tool's own advisory id, so the accepted-risk route names each advisory by id in that public file by design. Either way the PR takes `security-review`; a fix also regenerates the freeze manifest |
| esbuild accepted-risk entry may expire before the S04 re-run (§3)                                            | Low      | #3639, by comment, if it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| eslint 9 unsupported; eslint-plugin-react stale (§5)                                                         | advisory | frontend-platform lane's next dependency pass                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| caniuse-lite CC-BY-4.0, dev-only; CI's `--prod` licence scope (§6)                                           | finding  | the `license-check` gate's owner, by comment                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| RbacGate statement missing from the catalogue and the stories (§12)                                          | finding  | S04 (#267), by comment                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `style-src 'unsafe-inline'` (§10)                                                                            | input    | E43-T12 (#1239), by comment                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| A4 re-review trigger names a ticket that does not exist (§11)                                                | residual | RSK-029 re-anchored; Owner's dated sign-off                                                                                                                                                                                                                                                                                                                                                                                                                                                             |

No Critical or High finding exists at the audited sha. G1's "each Medium has a dated accepted-risk entry"
is not met until the Owner decides the seven Medium rows (6 advisories).

## 14. Re-run at S04's closing sha

Pending. At S04's close: re-run §2 (inventory diff), §3 (same inventory-membership rule), §4, §5, §6, §9 and §11's fixture pass and G5 at
that sha, and record the diff here against the pre-staged results above.

## 15. Sign-off

- Agent security review of this record at the PR head, posted on epic #30 and labelled "agent security
  review, not a human security engineer". Pending.
- Owner: the seven Medium rows (§13) and the A4 re-anchor (§11), each with a dated comment on #272. Pending.
- The human security engineer's comment the ticket's DoD names is not given by this record.

## 16. Gherkin and DoD map

| Item                                                              | State                                                                  |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------- |
| G1 zero Critical / High; each Medium dated                        | zero Critical / High; Mediums await the Owner; final at the S04 re-run |
| G2 CSP not weakened                                               | not weakened; hash allowlisting pending #304                           |
| G3 MaskedValue                                                    | automated and green (screen reader by proxy; the real pass is #262)    |
| G4 hold gate                                                      | automated and green                                                    |
| G5 no HTML injection                                              | zero uses; lint rule and Semgrep rule; final at the S04 re-run         |
| DoD: hash requirement on E10                                      | on #304; confirmation comment pending                                  |
| DoD: Storybook private, fixtures synthetic                        | no publish target; fixtures synthetic (sampled images)                 |
| DoD: security engineer comment on #30                             | agent review pending; human comment not given here                     |
| DoD: accepted risks dated, Owner-signed, in `32-risk-register.md` | RSK-029 updated; Owner sign-off pending                                |
