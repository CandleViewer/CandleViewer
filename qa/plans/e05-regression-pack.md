# E05 regression pack (design system)

Ticket: E05-Q03 (#263) for epic E05 (#30, design system). Inputs: the E05-Q01 plan and defect log
(`docs/qa/test-plans/e05-components.md`, #261) and the E05-Q02 report (`docs/qa/a11y/e05-q02-design-system-v1.md`,
#262). The epic run and the proposed sign-off are in `docs/qa/e05-signoff.md`. Base: `main` at `67fe8b526`.

Rulings: the coordinator's BQ list for #263 (BQ-0 to BQ-15) is posted as comment 6576081782. This pack is built on its
ORCH-defaults; **defaults built; ruling pending (comment 6576081782)**. A ruling replaces a default in place.

The pack adds no story, no tag and no baseline, and changes no tolerance, `EXCLUDED_TAGS` entry or shard budget
(BQ-0, BQ-6). It selects by name. Editing this document? Run its guard: `python3 -I qa/plans/_tools/e05_q03_pack_audit.py
--check` (`--fill` regenerates section G; `--self-test` proves each gate trips on its own mutation).

## How to run

All commands from the repo root, after `pnpm install`.

| Leg                                          | Command                                                                                                                                     | Where it runs                                                     |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| (a) VR, every story x 3 themes x 2 densities | `pnpm --filter @candleviewer/ui build:tokens`, `storybook:build`, then `pnpm --filter @candleviewer/ui vr` over `packages/ui/vr/baselines/` | CI only for a verdict: the `vr` job of `_job-a11y.yml`, 14 shards |
| (b) interaction + axe, default cell          | `pnpm --filter @candleviewer/ui storybook:test` (every story's play function; axe serious / critical fail the story)                        | CI `storybook` job; local is authoritative too                    |
| (c) unit, incl. the named regression tests   | `pnpm --filter @candleviewer/ui test` (sections C and D name the tests)                                                                     | CI `unit-frontend`; local is authoritative too                    |
| (d) full a11y sweep (manual run)             | the E05-Q02 axe driver + `e05-q02-merge.mjs --strict`, and the E05-Q02 manual driver (keyboard, zoom, motion): Q02 report §7 steps 1 to 3   | local, by hand (FU-5 carries the wiring)                          |
| (e) excluded                                 | the five `perf`-tagged stories (section H): no VR cell, no sweep cell                                                                       | E05-T02 frame-budget check                                        |

VR captures motion at `reduce` only (README, Visual regression). Local VR is for debugging: the token fonts draw only where
installed, and baselines come from the CI image only, never from a laptop. **A local VR run is not authoritative and
this pack never records one as a result.**

## A. Per-PR lane (BQ-4, part one)

The ticket proposed a per-PR subset (touched components plus a smoke set: Button, Table, Dialog, ThemeSwitcher) and a
nightly full sweep. On `main` the per-PR lane is already the full matrix: every PR that `pr.yml`'s `e2e` filter selects
(`packages/ui/**`, `apps/web/**`, the tokens, `_job-a11y.yml`) runs the `a11y` lane, whose `storybook` job runs (b) and whose
`vr` job runs (a) in 14 shards. The smoke set (Button 17 stories, Table 18, Dialog 13, ThemeSwitcher 12) is a subset of it.
**Per-PR = the existing lane, unchanged.**

Measured on `main`'s lane (run 41349402849, #5351's head, 2026-11-01): the 14 `vr` shards took 166 s to 234 s of job wall
each (2,699 s runner time in all; the budget is 360 s per shard, CI-A11Y-007), the `storybook` job 165 s (budget 600 s),
and the lane 666 s of wall clock from the first job's start to the last's end. That is within the ~15 min PR budget
(ADR-0019 decision drivers). This PR's own lane run is recorded in the sign-off record when CI has run it.

## B. Nightly sweep (BQ-4, part two): PENDING, not built

> **Pending a ruling (BQ-4) and a `security-review` (C-10.2: a workflow file).** Nothing in this section is built.

Fact at the base: `storybook-nightly.yml` calls `_job-a11y.yml` with `storybook_only: true`, so the nightly runs (b) only.
VR has no nightly run, and the E05-Q02 drivers (d) run nowhere (Q02 FU-5).

- **Default (proposed, not built):** `storybook-nightly.yml` also runs the `vr` compare shards (one input to
  `_job-a11y.yml`), its pin test (`scripts/tests/test_storybook_nightly.py`) updated, in this PR or a follow-up with the
  `security-review` label. The nightly's existing `report` job carries a red VR nightly to the tracker issue that
  `CV_STORYBOOK_NIGHTLY_TRACKER_ISSUE` names, or opens a P1 (BQ-14); no new channel.
- **Alternative B:** no workflow change; nightly VR is a carry, and the PR body says `Partial:` (BQ-2).
- **Either way:** the E05-Q02 drivers stay a manual run (d); FU-5 is carried to its owner (the E05-T03 harness owner).

The ticket's "failures route via the E04 alerting path" is not wired for this lane: the nightly's own `report` job is the
route (one Deviation line, carried to the E04 owner).

## C. Fixed defect to test, with the revert test (BQ-5)

Every defect fixed from the E05-Q01 log (D1 to D3) and the E05-Q02 log (F-1 to F-3) maps to a named test that fails on the
pre-fix code. The revert test was run for all six on 2026-11-02 on `67fe8b526` plus this PR's F-3 test: in a scratch
worktree, the fix's `packages/ui/src` change was reverted, the named tests run with
`pnpm exec vitest run --project unit <files>` from `packages/ui`, the result recorded, the tree restored, and the same tests
run again green.

| Id  | Defect (log)                                                                 | Fix               | Test (file, title)                                                                                                                                                                                                                                                                                                  | Reverted                                                                  | Red on revert                 | Green restored |
| --- | ---------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------- | -------------- |
| D1  | A gated control announces nothing on a refused activation (Q01, #5131)       | #5135 `55a9e5daa` | `packages/ui/test/RbacGate.test.tsx`:112 "denied: Enter, click and a dispatched click each announce the reason once, never call the handler"; and the gated-announce tests of the eight atoms (`Button`, `Checkbox`, `ColorSwatch`, `IconButton`, `RadioGroup`, `SegmentedControl`, `Slider`, `Toggle` `.test.tsx`) | the eight atoms' announce call neutralised (see note 1)                   | 9 of 9 files, 18 of 342 tests | 342 of 342     |
| D2  | The Dialog card overflows at 200 % zoom, its body cannot scroll (Q01, #5143) | #5149 `c61092c7f` | `packages/ui/test/dialog-css.test.ts`:79 "in the narrow query the layer has a definite row, so the card's max-height: 100% resolves (#5143)"                                                                                                                                                                        | `dialog.css` hunk reversed                                                | 1 of 12 tests                 | 12 of 12       |
| D3  | A non-modal Drawer over the page at 720 px or less is not modal (Q01, #5144) | #5155 `b148ca470` | `packages/ui/test/Drawer.test.tsx`:576 "narrow: aria-modal, the scrim, the page inert and not scrolling" (and three more narrow tests); `packages/ui/test/InfoPanel.test.tsx`:318 "narrow: aria-modal, Tab stays inside, Esc closes and focus returns to the trigger"                                               | `Drawer.tsx`, `layers.tsx` hunks reversed, `useNarrowViewport.ts` removed | 2 of 2 files, 5 of 68 tests   | 68 of 68       |
| F-1 | The focused SkipLink pill overlays the first header control, 2.5.8 (Q02)     | #5243 `b2126268d` | `packages/ui/test/skiplink-css.test.ts`:29 "focused: the primary pill at the control height with the CMP-039 ring"                                                                                                                                                                                                  | `skiplink.css`, `SkipLink.tsx` hunks reversed                             | 1 of 6 tests                  | 6 of 6         |
| F-2 | ErrorState summary links under 24 px, 2.5.8 (Q02)                            | #5243 `b2126268d` | `packages/ui/test/errorstate-css.test.ts`:77 "each summary link is at least size.target.min tall (WCAG 2.5.8, list items)"                                                                                                                                                                                          | `errorstate.css` hunk reversed                                            | 1 of 12 tests                 | 12 of 12       |
| F-3 | Typography `HeadingLevelVsStyle` jumps h1 to h4, heading-order (Q02)         | #5243 `b2126268d` | `packages/ui/test/Typography.test.tsx`:163 "never skips a heading level" (added by this PR, note 2); and the story's VR row (CI)                                                                                                                                                                                    | `Typography.stories.tsx` hunk reversed                                    | 1 of 35 tests                 | 35 of 35       |

Notes:

1. D1: the #5135 `src` hunks no longer apply verbatim (later PRs edited five of the files). The revert is functional: in
   each of the eight atoms #5135 changed, `useGatedAnnounce()` was replaced by a no-op, so a refused activation announces
   nothing, as before the fix. The failing tests include the RbacGate abuse check (section D) and every atom's
   gated-announce test.
2. F-3 had no test that fails on the pre-fix story: axe rates `heading-order` moderate, which neither the `storybook` job
   nor `merge --strict` fails on, and the fix sits in the story itself, so the story's play function moves with it. This
   PR adds one assertion over every Typography story (no heading skips a level). The VR row also catches it in CI (the
   label text changes); a local VR run is not evidence (fonts).

Not "fixed" and so not in the map: D4 (Checkbox `Indeterminate` shows no visible word "Mixed") and D5 (the stacked Table at
`high-contrast` · `compact`, row fills about 1.07 : 1) are open rows of the Q01 plan, not filed (coordinator ruling
2026-10-31); they are carries in the sign-off record. E05-D05's (#260) light hover tint finding, fixed by #5232, is outside the
two logs this AC names.

## D. The two abuse checks as permanent tests (BQ-7)

Both run in (c) on every PR; nothing is added.

| Plan case | Property                                                                   | Test                                                                                                                                       |
| --------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| C63       | The hold-to-confirm gate cannot be satisfied by a synthetic event          | `packages/ui/test/ConfirmDialogHold.test.tsx`:237 "a synthetic click(), a pointerdown/pointerup pair and two clicks never confirm nor arm" |
| C64       | A dispatched click on an RbacGate-disabled control never calls the handler | `packages/ui/test/RbacGate.test.tsx`:112 (the D1 row), and :282 / :346 for the `tooltip` and `notice` forms                                |

## E. Composition stories (BQ-6)

No composition defect was found and fixed: D1 to D3 are component defects, each pinned by a unit test above, so DoD row 2
("a regression story for every fixed defect") is met by the named tests plus the revert test (one Deviation line). The two
composition surfaces with no story, Combobox-in-Dialog and Menu-in-Drawer (Q01 OQ-5, C53, C55), are gaps, not defects: they
stay named with an owner row in the sign-off record. A story PR that adds them runs the `vr_update` dispatch and gets a
`vr/baselines` CODEOWNER review and design approval (README, Visual regression).

Stories the Q01 plan named for the pack exist and run in every leg: Toast `RegionUnderModal`, Table `Reflow`, Dialog
`EscTopmost` and `Reflow`, ConfirmDialog `HoldKeyboard` and `HoldReducedMotion`, Tooltip `EchoReason`.

## F. Triage of a VR diff, a flake or a sweep finding (BQ-8)

The workflow is `packages/ui/README.md`, Visual regression, "Reviewing a diff" (inspect, accept through the `vr_update`
dispatch, approve by a `vr/baselines` CODEOWNER plus `design-approved`), with this PR's addendum there: what counts as
intentional, the flake route (C-9.3) and the sweep-finding route.

## G. VR matrix per component (generated)

Derived from `git ls-tree -r --name-only HEAD packages/ui/vr/baselines/` (`{story}--{theme}--{density}.png`); the guard
regenerates it with `--fill`. Each story has six cells (3 themes x 2 densities, motion `reduce`).

<!-- e05-vr-matrix:begin -->

By tier: atoms 42 (444 stories, 2664 cells); molecules 34 (428 stories, 2568 cells); organisms 4 (21 stories, 126 cells); foundations 3 (6 stories, 36 cells); trading 1 (6 stories, 36 cells).

| Component                               | Tier        | Stories |    Cells |
| --------------------------------------- | ----------- | ------: | -------: |
| `atoms-all-atoms-matrix`                | atoms       |       6 |       36 |
| `atoms-avatar`                          | atoms       |       6 |       36 |
| `atoms-avatargroup`                     | atoms       |       5 |       30 |
| `atoms-badge`                           | atoms       |       7 |       42 |
| `atoms-button`                          | atoms       |      17 |      102 |
| `atoms-callout`                         | atoms       |      13 |       78 |
| `atoms-checkbox`                        | atoms       |      13 |       78 |
| `atoms-colorswatch`                     | atoms       |      16 |       96 |
| `atoms-confidencedots`                  | atoms       |       8 |       48 |
| `atoms-copybutton`                      | atoms       |       9 |       54 |
| `atoms-countdown`                       | atoms       |      10 |       60 |
| `atoms-divider`                         | atoms       |       6 |       36 |
| `atoms-emptystate`                      | atoms       |      15 |       90 |
| `atoms-errorstate`                      | atoms       |      14 |       84 |
| `atoms-focusring`                       | atoms       |       4 |       24 |
| `atoms-freshnessmarker`                 | atoms       |       7 |       42 |
| `atoms-fundingcountdown`                | atoms       |      13 |       78 |
| `atoms-icon`                            | atoms       |       3 |       18 |
| `atoms-iconbutton`                      | atoms       |      17 |      102 |
| `atoms-inlinespinnertext`               | atoms       |       7 |       42 |
| `atoms-kbd`                             | atoms       |       9 |       54 |
| `atoms-keyvaluerow`                     | atoms       |       8 |       48 |
| `atoms-link`                            | atoms       |      11 |       66 |
| `atoms-maskedvalue`                     | atoms       |      12 |       72 |
| `atoms-numericstepperinput`             | atoms       |      17 |      102 |
| `atoms-popover`                         | atoms       |      10 |       60 |
| `atoms-progressbar`                     | atoms       |      13 |       78 |
| `atoms-radiogroup`                      | atoms       |      14 |       84 |
| `atoms-segmentedcontrol`                | atoms       |      16 |       96 |
| `atoms-select`                          | atoms       |      17 |      102 |
| `atoms-skeleton`                        | atoms       |      10 |       60 |
| `atoms-skeletonchart`                   | atoms       |       5 |       30 |
| `atoms-skiplink`                        | atoms       |       5 |       30 |
| `atoms-slider`                          | atoms       |      13 |       78 |
| `atoms-sparkline`                       | atoms       |      12 |       72 |
| `atoms-spinner`                         | atoms       |       7 |       42 |
| `atoms-swatchlegenditem`                | atoms       |       5 |       30 |
| `atoms-tag`                             | atoms       |      16 |       96 |
| `atoms-textinput`                       | atoms       |      13 |       78 |
| `atoms-toggle`                          | atoms       |      14 |       84 |
| `atoms-tooltip`                         | atoms       |      12 |       72 |
| `atoms-typography`                      | atoms       |       9 |       54 |
| `foundations-motion-recipes`            | foundations |       3 |       18 |
| `foundations-placeholder`               | foundations |       1 |        6 |
| `foundations-theme-runtime`             | foundations |       2 |       12 |
| `molecules-all-molecules-matrix`        | molecules   |      30 |      180 |
| `molecules-auditrow`                    | molecules   |       9 |       54 |
| `molecules-card`                        | molecules   |       9 |       54 |
| `molecules-columnpicker`                | molecules   |       9 |       54 |
| `molecules-combobox`                    | molecules   |      15 |       90 |
| `molecules-commandpalette`              | molecules   |       6 |       36 |
| `molecules-confirmdialog`               | molecules   |      19 |      114 |
| `molecules-datepicker`                  | molecules   |      16 |       96 |
| `molecules-daterangepicker`             | molecules   |      16 |       96 |
| `molecules-densitytoggle`               | molecules   |      13 |       78 |
| `molecules-dialog`                      | molecules   |      13 |       78 |
| `molecules-drawer`                      | molecules   |      11 |       66 |
| `molecules-e05-s04-theming-matrix`      | molecules   |       2 |       12 |
| `molecules-filedrop`                    | molecules   |      12 |       72 |
| `molecules-formfield`                   | molecules   |      15 |       90 |
| `molecules-formsection`                 | molecules   |      11 |       66 |
| `molecules-fuzzylist`                   | molecules   |      13 |       78 |
| `molecules-infopanel`                   | molecules   |       8 |       48 |
| `molecules-menu`                        | molecules   |      20 |      120 |
| `molecules-pageheader`                  | molecules   |       8 |       48 |
| `molecules-previewtile`                 | molecules   |      17 |      102 |
| `molecules-rbacgate`                    | molecules   |      14 |       84 |
| `molecules-searchbox`                   | molecules   |       8 |       48 |
| `molecules-symbolinfopopover`           | molecules   |       8 |       48 |
| `molecules-symbolpicker`                | molecules   |      13 |       78 |
| `molecules-symbolsearchinput`           | molecules   |       8 |       48 |
| `molecules-systemhealthtile`            | molecules   |      15 |       90 |
| `molecules-table`                       | molecules   |      18 |      108 |
| `molecules-tabs`                        | molecules   |      12 |       72 |
| `molecules-themeswitcher`               | molecules   |      12 |       72 |
| `molecules-theming-and-density-perf`    | molecules   |       1 |        6 |
| `molecules-toast`                       | molecules   |      14 |       84 |
| `molecules-watchlistgrouptabs`          | molecules   |      10 |       60 |
| `molecules-watchlistrow`                | molecules   |      23 |      138 |
| `organisms-adminlayout`                 | organisms   |       7 |       42 |
| `organisms-forbiddenstate`              | organisms   |       4 |       24 |
| `organisms-globalerrorboundaryfallback` | organisms   |       7 |       42 |
| `organisms-notfoundstate`               | organisms   |       3 |       18 |
| `trading-colorconventionlegend`         | trading     |       6 |       36 |
| **total: 84 components**                |             | **905** | **5430** |

<!-- e05-vr-matrix:end -->

## H. Excluded stories (`EXCLUDED_TAGS`: `perf`)

The five stories tagged `perf` have no VR cell and no sweep cell (`vr/matrix.ts`; the Q02 driver excludes them the same
way). Their frame budget is E05-T02's check.

- `foundations-theme-runtime--style-recalc-benchmark`
- `atoms-sparkline--perf-200-points`
- `molecules-fuzzylist--perf-1000-items`
- `molecules-table--perf-200-rows`
- `molecules-theming-and-density-perf--frame-budget`
