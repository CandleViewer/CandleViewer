# E05-Q02 (#262): design system v0 accessibility audit, run record

## 0. Honest scope

This is an **agent-run** audit. It is not a human pass: no screen reader was operated by a person, no pointer-free session was driven by a person, and nobody zoomed a browser. Every number below was measured by the committed driver; every item that needs a person is listed as human-owed in §5.

- **Swept sha:** `b6253ac33`, the E05-S04 slice-H head, which carries the complete v0 component set.
- **Fix commits:** `fb7e0f159` (skip link) and `f2b3d0331` (error summary links and the Typography story). The re-sweep of the three components was run before the branch was rebased onto `main`; the fixes were not re-swept at the rebased head.
- **Environment:** the built Storybook, served on loopback, Playwright Chromium, headless. No live exchange, no network beyond loopback. The driver counts off-site requests; there were none.
- **Out of scope** (ticket): application screens and routes (E47), design-contract sign-off (E05-D04), chart canvas a11y.

## 1. Tools

| Tool                                           | Version | Source           |
| ---------------------------------------------- | ------- | ---------------- |
| axe-core                                       | 4.14.0  | `pnpm-lock.yaml` |
| @axe-core/playwright                           | 4.14.0  | `pnpm-lock.yaml` |
| @playwright/test                               | 1.64.1  | `pnpm-lock.yaml` |
| playwright-core / playwright (Chromium driver) | 1.64.1  | `pnpm-lock.yaml` |

Driver: `docs/plan/a11y/_tools/e05-q02-ds.qa.ts` (one Playwright test per story, `--shard` capable), `e05-q02-ds.config.ts`, and `e05-q02-merge.mjs` (merges shard output into one summary).

## 2. Full automated sweep

| Measure             | Value                                                          |
| ------------------- | -------------------------------------------------------------- |
| Stories swept       | 776 (5 perf stories excluded)                                  |
| Cells               | 9,030 (3 themes x 2 densities x motion no-preference / reduce) |
| Errored cells       | 0                                                              |
| Missing story files | 0                                                              |
| Off-site requests   | 0                                                              |
| Critical            | 0                                                              |
| Serious             | 30                                                             |
| Moderate            | 12                                                             |
| Minor               | 0                                                              |

- **Negative control:** a must-trip fixture (an image with no alt text, a button with no name) is run in every sweep. It tripped `image-alt` and `button-name`, so a zero elsewhere is not a silent driver.
- **Three page-level rules disabled, with reason:** `landmark-one-main`, `page-has-heading-one` and `region`. A lone component in the isolated story iframe has no main landmark, no h1 and no region by construction. The E47 screens sweep covers them on real pages.
- **Rule set:** axe-core WCAG 2.0/2.1/2.2 A and AA tags, plus best-practice.
- **pa11y-ci:** the ticket names a complementary pa11y-ci sweep. It was **not run here**. A root `.pa11yci.json` exists (E03-T06) with one URL, the apps/web placeholder route; it is not wired in CI (deferred to E03-T12) and nothing targets Storybook. See §5 and §6.

## 3. Findings and fixes

All three defect classes were caught by axe, so no manual-only defect class was found (the follow-up the ticket asks for on manually caught classes is therefore empty).

| #   | Component                        | Rule          | WCAG SC               | Impact   | Cells | Fix                                                                                                                                                                                                                  | Status |
| --- | -------------------------------- | ------------- | --------------------- | -------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| F-1 | SkipLink (focused)               | target-size   | 2.5.8                 | serious  | 18    | commit `fb7e0f159` (the focused skip link takes space instead of covering a target): the focused pill is in flow and takes space, instead of overlaying the first header control (#262 BQ-4, the lane's default (b)) | fixed  |
| F-2 | ErrorState (summary links)       | target-size   | 2.5.8                 | serious  | 12    | commit `f2b3d0331` (24 px targets for the error summary links): `min-block-size` is `size.target.min` (24 px)                                                                                                        | fixed  |
| F-3 | Typography (heading-level story) | heading-order | 1.3.1 (best practice) | moderate | 12    | commit `f2b3d0331` (same commit): the story renders h1 then h2 (it jumped h1 to h4)                                                                                                                                  | fixed  |

Totals: 18 + 12 = 30 serious cells and 12 moderate cells, which is every violation in §2. No finding is open.

### 3.1 Re-sweep after the fixes

The three components' stories were re-swept before the rebase, with the fixes applied: **28 stories, 330 cells, 0 violations of any impact**, negative control tripped. The full 9,030-cell sweep was **not repeated** after the fixes; the other stories are unchanged by these commits.

## 4. Accessible-name check

`packages/ui/test/a11y-names.test.ts`: 15 tests (14 table rows and one no-leak test) covering 12 components: CMP-001, 002, 003, 004, 005, 008, 010, 013, 023, 025, 033, 034. Each asserts the role and the computed accessible name (testing-library `getByRole(role, { name })`, which reads the accessibility tree) against the `A11y` line of `docs/plan/15-component-catalogue.md`. A name that is present but wrong fails the test.

- **CMP-034 MaskedValue never exposes its value while masked** (the ticket's security note): asserted by the test.
- Components whose `A11y` line names no fixed label, and the overlays reached only by a play function, are listed with a reason at the top of the test file. The overlays' names are pending E05-S04 stories.
- This is a computed-name check in jsdom. It is not a screen-reader announcement.

## 5. Acceptance criteria and Definition of Done

| Item                                                                                | Result                                                                                                      | Evidence and what remains                                                                                                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC 1: zero serious or critical in 3 themes x 2 densities, axe and pa11y-ci          | **partial: axe fixed, pa11y-ci pending**                                                                    | axe: 30 serious found, all fixed, re-sweep clean (§2, §3). pa11y-ci was not run: its config covers one placeholder route only and is not wired (E03-T12).                                                                                                                                                                                                                                                                                |
| AC 2: announced name matches the documented name table                              | **pass** (computed) / **human-owed** (announced)                                                            | §4: 12 components, 15 tests. The announcement under a real screen reader is the manual pass below.                                                                                                                                                                                                                                                                                                                                       |
| AC 3: keyboard-only completion, incl. hold-to-confirm and table row navigation      | **partial: tests pass, human pass owed**                                                                    | Existing component tests drive the keyboard in jsdom: `Table.test.tsx` (arrows by cell, Home / End, Ctrl+Home / Ctrl+End), `ConfirmDialogHold.test.tsx` and `ConfirmDialogGateMatrix.test.tsx` (the hold gate), `Combobox.test.tsx`, `Menu.test.tsx`, `SkipLink.test.tsx` and others. A person operating every documented interaction with no pointer in a real browser was not done.                                                    |
| AC 4: 200% zoom, compact table, reflow without clipping or data loss                | **partial: CSS contracts pass, human pass owed**                                                            | `Table.test.tsx` ("stacked reflow") and `dialog-css.test.ts` (the 200 % reflow breakpoints in rem; the card fills the viewport at 200 % on 1280 x 800) assert the reflow rules. No browser was zoomed to 200 % or 125 % text scale and no clipping was inspected by eye. Human-owed.                                                                                                                                                     |
| AC 5: no information lost under `data-motion="reduce"`                              | **partial: lint and axe reduce cells pass; non-motion-cue check rests on component tests or is human-owed** | The motion CSS lint (`packages/ui/test/theme/motion-css.test.ts` and the `*-css.test.ts` reduced-motion assertions) and the sweep's reduce cells: every story is swept with motion reduced and shows no violation. That a state change keeps a non-motion cue rests on component tests such as `Dialog.test.tsx` ("reduced motion is a cut") and `toast-css.test.ts` (reduce resolves the slide to none); beyond those it is human-owed. |
| AC 6: an unresolved serious finding gates the epic                                  | **pass**                                                                                                    | No serious finding is open (§3).                                                                                                                                                                                                                                                                                                                                                                                                         |
| DoD 1: automated sweep green, zero serious or critical, all themes and densities    | **partial (axe fixed, pa11y-ci pending)**                                                                   | §2, §3.1. pa11y-ci part pending.                                                                                                                                                                                                                                                                                                                                                                                                         |
| DoD 2: manual SR passes per the coverage matrix, versions recorded                  | **human-owed**                                                                                              | `05-accessibility-standard.md` §8.2. Pending the coordinator's decision (BQ-1). No SR was run; no SR or browser version is recorded because none was used.                                                                                                                                                                                                                                                                               |
| DoD 3: keyboard-only, 200% zoom and reduced-motion passes                           | **partial**                                                                                                 | Reduced motion: pass (above). Keyboard-only and zoom: automated coverage only; human-owed.                                                                                                                                                                                                                                                                                                                                               |
| DoD 4: findings logged with WCAG SC, blocking ones fixed                            | **pass**                                                                                                    | §3.                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| DoD 5: report attached; Accessibility role and QA both sign off                     | **pending**                                                                                                 | This record is the report. Sign-off is human-owed.                                                                                                                                                                                                                                                                                                                                                                                       |
| DoD 6: follow-ups to automate any manually caught defect class                      | **pass** (none)                                                                                             | No defect was found by hand, so no class needs automating. The tightening rows are in §6.                                                                                                                                                                                                                                                                                                                                                |
| Performance note: does reduce-motion measurably reduce frame work (SCR-117's claim) | **not measured**                                                                                            | No frame-work measurement was made. The claim is neither confirmed nor refuted here.                                                                                                                                                                                                                                                                                                                                                     |

## 6. Follow-ups

No new issues are filed from this record. Rows for the coordinator to place:

| Row  | Item                                                                                                                                                                                                                                    | Suggested home            |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| FU-1 | The manual SR pass per `05` §8.2, with SR and browser versions recorded (BQ-1)                                                                                                                                                          | #262 itself, human-owed   |
| FU-2 | A person's keyboard-only pass and 200 % zoom / 125 % text-scale pass, compact table first                                                                                                                                               | #262, human-owed          |
| FU-3 | The pa11y-ci complementary sweep: it is named by the ticket and `03-testing-strategy.md` but a root `.pa11yci.json` (E03-T06) lists one URL, the apps/web placeholder, and is unwired; extend it to Storybook when E03-T12 schedules it | E03-T12                   |
| FU-4 | Measure frame work with reduce-motion on and off, for SCR-117's claim                                                                                                                                                                   | the SCR-117 owner         |
| FU-5 | Wire the e05-q02 driver into a CI or nightly job so a regression in the three fixed components, or a new story, is swept                                                                                                                | the E05-T03 harness owner |
| FU-6 | The accessible-name table omits CMP-007, 009, 011, 012, 016, 017, 020, 022, 031, 032 and the play-function overlays; add rows when E05-S04 supplies their open-state stories                                                            | E05-S04 follow-on         |

## Observability

The §2 counts by severity are the R0 baseline. The merged `results.json` and `summary.md` artefact link goes on the PR and the epic.

## 7. Reproduce

1. Build Storybook: `pnpm --filter @candleviewer/ui run storybook:build` (the config serves `storybook-static` on loopback).
2. Run the driver with `docs/plan/a11y/_tools/e05-q02-ds.config.ts` (add `--shard n/m` to split), then merge with `e05-q02-merge.mjs` (`--strict` also fails on any serious or critical violation; one `A11Y_OUT` per shard).
3. `pnpm --filter @candleviewer/ui exec vitest run --project unit test/a11y-names.test.ts` for the name check.
