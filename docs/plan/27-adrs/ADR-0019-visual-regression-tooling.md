# ADR-0019: Visual-regression tooling for design-system snapshot coverage

Status: decided
Date: 2026-09-25
Deciders: basiltt (Owner/Architect)
Consulted: frontend, design, security (network-egress question)
Related: E05-K01 (this spike), E05-T04 (baseline implementation), ADR-0013 (CI pipeline),
ADR-0012 (testing pyramid), `docs/plan/00-planning-brief.md` (Tailscale-only remote access)

## Context and problem statement

R0 exit criterion 8 and `docs/plan/30-release-roadmap.md#42-scope-epics` require a visual-regression
baseline for the design system (Storybook stories, 3 themes x 2 densities, ~60 stories at v0 scale).
The roadmap left the tool choice open. E05-T04 cannot start until it is closed. The project is
**Tailscale-only** for remote access (`00-planning-brief.md` line 16) and treats third-party data flow
as a STRIDE concern (`04-security-program.md`), so any hosted SaaS candidate must be evaluated for what
leaves the network, not just cost and DX.

## Decision drivers

- CI wall-clock for ~60 stories x 3 themes x 2 densities (target: fits inside the ~15 min PR budget,
  ADR-0013 §5; hard ceiling ~6 min for the v0 story count per the ticket's performance note).
- Flake rate across two identical runs on unchanged `main` (target: zero).
- Reviewer workflow for accepting an intentional diff.
- Cost (GitHub Actions minutes already budgeted per ADR-0013; no new recurring SaaS spend without
  Owner sign-off).
- Whether screenshots of pre-release UI leave the private network (Tailscale-only constraint).
- Storage growth in git for committed baselines.
- Fit with the existing CI runner spec (GitHub Actions + a pinned self-hosted GPU runner for
  chart-engine benches, ADR-0013) — no new infra class if avoidable.

## Considered options

### (a) Chromatic (hosted SaaS)

- Uploads rendered story screenshots to Chromatic's cloud for diffing and review UI.
- Pros: turnkey UI for accept/reject, TurboSnap for incremental runs, generous free tier at v0 scale.
- Cons: **every story screenshot (pre-release UI, including any story that renders a fixture with a
  masked value) leaves the private network to a third-party SaaS.** This is exactly the kind of data
  flow the Tailscale-only decision is meant to avoid, and it requires an explicit Owner-approved
  STRIDE exception (E05-X01) before it could be adopted. No such exception exists today. Adds a
  second CI system (external service dependency) alongside GitHub Actions, which ADR-0013 already
  rejected once for the GPU-bench case on the same "splits the workflow, adds a third party" grounds.
  Recurring cost beyond the free tier as story count grows past v0.

### (b) Playwright `toHaveScreenshot` against committed PNG baselines

- Runs entirely inside the existing GitHub Actions job (or the pinned self-hosted runner already used
  for chart-engine benches); screenshots never leave the network perimeter.
- Baselines are PNGs committed to the repo (or an LFS/artifact store under our control), diffed with
  Playwright's built-in pixelmatch-based comparison; `maxDiffPixelRatio` / `threshold` give an explicit,
  documented anti-aliasing tolerance instead of an opaque vendor algorithm.
- Diff images publish as CI artifacts per PR (satisfies the ticket's Observability requirement) via
  the standard `actions/upload-artifact` step — no new infra.
- Reviewer workflow: PR shows failing check + downloadable diff artifact; an intentional change is
  accepted by running the project's own `pnpm --filter ui vr:update` script (built in E05-T04) locally
  or on a maintainer-triggered CI job, then committing the new baseline PNGs — auditable via normal git
  history and CODEOWNERS review, no external account needed.
- Determinism: font pinning (already required by the ticket) + `prefers-reduced-motion` /
  animation-disable hooks + fixed viewport/DPR are first-class Playwright config, not a third-party
  add-on.
- Cons: no hosted review dashboard; baseline PNGs add repo/LFS storage that grows with story count x
  theme x density (mitigated: PNGs compress well for flat UI; matrix is only 60 x 3 x 2 = 360 images
  at v0, each well under 50 KB at the pinned viewport — well inside typical repo-size norms with LFS).
  Slightly more setup than a SaaS turnkey product.

### (c) Storybook test-runner + `jest-image-snapshot` equivalent

- Same self-hosted, no-network-egress property as (b); reuses Storybook's own runner to iterate
  stories instead of Playwright driving the pages directly.
- Snapshot diffing (`pixelmatch` under the hood) and tolerance config are comparable to (b), but the
  project would then run **two** browser-automation stacks in CI (Storybook test-runner's Playwright
  under the hood, _plus_ Playwright already used for `e2e`/`a11y` E2E jobs per AGENTS.md §4), doubling
  browser-binary cache weight and maintenance surface without a corresponding benefit — Playwright's
  own component/story testing mode ((b)) already covers Storybook stories directly via
  `@storybook/test-runner`'s underlying engine or a direct `page.goto(storyUrl)` approach, so (c) is
  strictly a redundant path once (b) is chosen.

## Decision outcome

**Chosen option: (b) Playwright `toHaveScreenshot` against committed PNG baselines.**

Rationale, against the decision drivers:

- **Network constraint (dispositive):** (a) is rejected outright without an Owner-approved STRIDE
  exception, because it sends pre-release UI screenshots to a third-party SaaS, which conflicts with
  the Tailscale-only remote-access decision until and unless the Owner explicitly accepts that data
  flow. No such sign-off has been sought or given. (b) and (c) keep every artifact inside our own CI
  runner and repo.
- Between the two closed-network options, (b) avoids running a second, largely-duplicate
  browser-automation stack (Playwright is already the E2E/a11y tool per AGENTS.md §4), reducing CI
  image size and maintenance surface.
- **CI wall-clock:** not empirically measured in this spike — **no docker/browser sandbox was
  available in the spike environment to run either candidate**, so the ~6-minute budget for 360
  captures is estimated, not measured, from Playwright's documented per-screenshot overhead
  (order of 50-150 ms capture + comparison per story once the browser context is warm, run with
  `--shard` across the existing job matrix). This is the **missing datum** called out below.
- **Flake rate:** not measured for the same reason (no local runner). Anti-aliasing tolerance is
  addressed by config, not by empirical tuning in this spike: `expect(page).toHaveScreenshot(name, {
maxDiffPixelRatio: 0.02, animations: 'disabled' })`, fonts pinned via a container image with the
  project's exact web fonts installed (no Google Fonts network fetch at capture time), and a fixed
  1920x1080 viewport + `deviceScaleFactor: 1`. Per the ticket's Flake-threshold acceptance criterion,
  a candidate with _any_ non-deterministic diff without a configurable threshold is rejected — (b)'s
  threshold is configurable and documented here, so it is not rejected on that criterion, but the
  two-identical-runs measurement itself is deferred to E05-T04 (first real implementation), because it
  requires the actual CI runner image this spike did not have access to.

**This decision is partially deferred**: the tool choice is decided now (unblocks E05-T04), but the
exact CI wall-clock and flake-count numbers required by the ticket's own acceptance criterion
("a comparison table with measured CI runtime and flake counts for at least two candidates exists")
are **not yet measured** — see "Missing datum" below. E05-T04 must capture them on first real CI run
and update this ADR's Validation section (amendment) rather than treat the numbers as pre-verified.

### Missing datum (named explicitly per the ticket's own criterion)

- Measured CI wall-clock for the full 60 x 3 x 2 matrix on the project's actual GitHub Actions runner
  (or self-hosted runner) image, once it exists (blocked by E02/E03 runner scaffolding).
- Measured diff count across two consecutive identical runs on that same image.

Both will be captured as part of E05-T04's first green CI run and appended here.

## Consequences

- Positive: zero third-party data egress for pre-release screenshots; reuses the Playwright toolchain
  already mandated for E2E/a11y; diff artifacts are plain PNGs any reviewer can open, no vendor login.
- Negative: repo/artifact storage grows with story count; no hosted review dashboard — reviewers use
  the CI artifact + a local diff viewer or GitHub's image-diff PR view.
- Follow-up configuration handed to E05-T04 (see below).

## Why not the alternatives (summary)

- (a) Chromatic: rejected on the network-egress/STRIDE gap, not on cost or DX — those were otherwise
  favorable.
- (c) Storybook test-runner + jest-image-snapshot: rejected as a redundant second automation stack
  once (b) is chosen; no functional gap it closes that (b) doesn't already cover for Storybook stories.

## Validation

- Not yet run empirically (no docker/browser sandbox in this spike's environment). E05-T04 will run
  two consecutive identical CI jobs on `main` and record the diff count and wall-clock here as a dated
  amendment.

### Amendment 2026-10-30: E05-T04 (#270) implementation

- Built as decided: `packages/ui/vr/` (`packages/ui/README.md`, "Visual regression") and the `vr`
  job of `_job-a11y.yml`, beside `storybook`, failing the required `a11y` check. Baselines are plain
  PNGs in `packages/ui/vr/baselines/`, written only by `vr:update` on the CI image through the
  workflow's `vr_update` dispatch.
- Scale: 726 stories x 3 themes x 2 densities = 4,356 cells at E05-T04, about 12 times this ADR's
  ~60-story estimate, so the job runs in 10 shards of one browser per two CPUs (14 since #5275, as the
  story count grew), each held to the 360 s budget by its last step. A shard takes every n-th cell
  of the matrix (n the shard count), not a contiguous range, so the
  slow story families spread evenly across the shards.
- Tolerance as decided (`maxDiffPixelRatio: 0.02`, `animations: 'disabled'`), with pixelmatch's
  `threshold: 0.2` written out, plus an absolute cap, `maxDiffPixels: 25`: Playwright fails a cell past
  the smaller of the two. The ratio applies to a capture clipped to what the story paints, an
  overlay's flat full-viewport scrim left out (a dialog is captured as the dialog, its shadow and a
  4 px edge); a capture still page-sized (a layout drawn edge to edge) is held to 25 pixels, not the
  41,000 of 2% of 2 Mpx. The cap rests on the evidence below: two compare runs on an unchanged head
  found no cell past it, and 25 is below one changed glyph of 13 px text, so a 1 px change on a
  page-sized capture still fails.
- Fonts pinned: the `vr` job runs on the `ubuntu-24.04` image and installs the token families from its
  archive at fixed versions (noble's release pocket): `fonts-inter 4.0+ds-1` (OFL-1.1; its Debian
  copyright records OFL-1.1 and Apache-2.0) and `fonts-jetbrains-mono 2.304+ds-4` (OFL-1.1 upstream,
  `16`'s locked record; its Debian copyright records Apache-2). The install is
  mandatory: a missing package or family fails the job (CI-A11Y-008). Each shard asserts through the
  DevTools protocol that Chromium draws exactly those faces, never a fontconfig substitute, and the
  summary names the faces drawn. The token families name no generic fallback, so without the pin
  every baseline would draw in the image's default serif.
- Determinism measures, one per cause the first two compare runs on an unchanged head showed:
  - A failed play: Storybook 10.6 reports `finished` even when a play function threw, so the cell
    fails by name (`play function failed: ...`) from the play's exception on the preview channel. A
    play runs as the storybook job runs it: after its story's mount effects (a production build has no
    `act`), with no reduced-motion preference and a moving `Date`; reduce comes after, for the shot.
  - Late overlays and tooltips: after `finished`, timers due within 1 s fire, then 2 animation frames
    pass with no DOM mutation (3 s cap, a named failure), then the page's timers, intervals and
    frames freeze before the clip is measured. Storybook's own `?freeze=finished` is not used: it
    makes the body inert from load, so a play could not focus anything.
  - A 1 px rounding flip: clip edges go out to whole pixels unless within 0.01 px of one, the bound is
    Playwright's own full-page size, and two measures two frames apart must agree.
- Measured CI wall-clock, slowest compare shard: 261 s of 360 s (run 41102959975, shard 5; its compare
  step 135 s), and 240 s in the other run (41100190803, shard 3), the pinned-font install included.
- Diff count over two consecutive compare runs on an unchanged head: 0 and 0, with no cell held back
  and Inter and JetBrains Mono drawn in every shard (runs 41100190803 and 41102959975, 10 shards
  each). A deliberate 1 px Button padding change on a throwaway branch fails all 10 shards with 914
  diffs (run 41100463585): every non-full-width `atoms-button` cell, and every overlay cell that
  shows a Button (ConfirmDialog 114, Dialog 78, Drawer 60, CommandPalette 26); the full-width
  story's box does not change.
- Full baseline set: 4,356 PNGs, 53.1 MB, written by the `vr_update` dispatch run 41094472587.
- The first `main` run after the merge must report zero diffs; a non-zero diff is a determinism
  defect, fixed forward with `Refs #270`.

## Follow-up configuration notes for E05-T04

1. Use Playwright's browser-context screenshot API directly against each Storybook story's isolated
   iframe URL (`iframe.html?id=<story-id>&globals=theme:<t>;density:<d>`), not a full Storybook UI
   screenshot, to avoid capturing the Storybook chrome.
2. Pin project web fonts inside the CI container image (no runtime font-loading network calls).
3. Disable CSS animations and transitions globally for the capture pass (`prefers-reduced-motion` +
   a capture-mode stylesheet override), independent of the tool.
4. Config: `maxDiffPixelRatio: 0.02`, viewport `1920x1080`, `deviceScaleFactor: 1`; document any
   per-story override (e.g. CMP-024 Sparkline canvas) inline in that story file with a reason.
5. Baseline PNGs live under `packages/ui/.vr-baselines/` (or the location E05-T04's CI job expects);
   publish diff artifacts per PR via `actions/upload-artifact`.
6. `pnpm --filter ui vr:update` regenerates baselines locally; it must never run implicitly in a CI
   job that also gates merge (ticket's own scope item) — gate it behind an explicit `workflow_dispatch`
   or a maintainer-only script, never a default `pretest`/`postinstall` hook.
7. Shard the story matrix across parallel CI jobs (Playwright's `--shard`) if the measured wall-clock
   in the "Missing datum" section above exceeds the ~6-minute budget.
8. Reviewer workflow: a failing VR check blocks merge; the PR author or a design-system CODEOWNER
   inspects the uploaded diff artifact, and if the change is intentional, a designer additionally
   reviews before `vr:update` is run and the new baselines are committed in the same PR.
