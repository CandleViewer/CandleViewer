# E12-Q07 (#530): bar-mode, series and interval surfaces accessibility audit, run record v1 (PR 1, the built set)

PR 1 audits the E12 surfaces that are built at the pin, per the ruling of record (comment 6637510765) on the BQ list (comment 6634721156): the 2026-10-30 hold is lifted for the built set only. Six of the stories the ticket now waits on are open with their code unmerged (#533, #535, #451, #521, #336, #387); every row they own reads "not yet built — <story>". This PR is `Refs #530` and Partial: the closing slice follows the last of those six and re-runs the whole set.

## 0. Honest scope

This is an **agent-run, offline** audit. No screen reader was operated, nobody tabbed a mounted chart, and nothing was zoomed by hand (the layout criteria are listed as not run in §3.7). Every verdict below is agent-run and marked (heuristic); every item that needs a person is an owner-run row (§6).

- **Pin:** `main` at `aa0a02b8c54c877c39718f101abf69467cb4a2d6` (tree `apps` `b8fbf0c2df34`); every cite below is read there.
- **Reachability is cited, not re-derived:** E47-T01's rows (T01:178–185) put every E12 surface out of reach of a route: SCR-041 and SCR-048 built but not mounted, the rest not built. No route hosts `Chart`, `QuickSwitcher`, `PriceScaleMenu`, `ChartTablePanel` or `ChartErrorSurface`, so no Playwright collector can visit them.
- **AC 1's axe sweep is not run: not mounted** (ruling BQ-2). It joins the required `a11y` check's screen set (`05`:304) when E15 mounts the chart and the collectors take the E12 states as E10-Q03's driver took the shell's. No new check name is added (BQ-3).
- **Offline legs (BQ-2):** vitest with React Testing Library on jsdom in `apps/web`; the `packages/ui` Storybook project in Chromium headless (axe through the a11y addon); the repo's contrast gate. No new dependency, no new route, no live feed (C-2.11): the synthetic fixture `apps/web/test/chart/a11y/fixture.ts` only.
- **Not here:** journeys in `apps/web/e2e/specs/e12-bars/chart-probe.ts` (edited by Draft #5829; no journey until it lands and a route mounts the panes, BQ-9); any `fixme` or skipped test (BQ-7).

## 1. Tools

| Tool                     | Version                                   | Source                                            |
| ------------------------ | ----------------------------------------- | ------------------------------------------------- |
| vitest                   | 4.1.12                                    | `pnpm-lock.yaml`                                  |
| jsdom                    | 25.0.1                                    | `pnpm-lock.yaml`                                  |
| axe-core                 | 4.14.0                                    | `pnpm-lock.yaml` (through `@axe-core/playwright`) |
| Chromium (Storybook leg) | 156.0.8078.4                              | the installed Playwright build                    |
| Contrast gate            | `tools/contrast` (`contrast:gate` script) | `packages/ui/package.json`                        |

## 2. What is built at the pin (BQ-1)

| Surface                               | At the pin                                                                          | This PR                     |
| ------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------- |
| SCR-041 quick-switcher                | built (`QuickSwitcher.tsx`), not mounted                                            | offline legs, §3.1          |
| SCR-042 interval and bar-mode menu    | not yet built — #535                                                                | none                        |
| SCR-043 scale context menu            | built (`PriceScaleMenu.tsx`), not mounted                                           | offline legs, §3.1          |
| SCR-044 go-to-date                    | not yet built — E26-S06 #811 (T01:181)                                              | none                        |
| SCR-045 data-table alternative        | the shell and the polite writer are built (E47-S01); the per-mode rows are #521's   | offline legs, §3.1 and §3.2 |
| SCR-047 empty state                   | the engine's `dataState` edge is built; no app surface consumes it — #487           | none (§4, N-3)              |
| SCR-048 error state                   | built (`ChartErrorSurface.tsx`), not mounted                                        | offline legs, §3.1          |
| CMP-199 legend                        | not yet built — #336                                                                | none                        |
| CMP-220 IntervalPicker                | not yet built — #535 (QuickSwitcher holds its slot only)                            | none                        |
| CMP-221 ChartToolbar                  | not yet built — #451                                                                | none                        |
| CMP-222 ChartTypeToggle               | not yet built — #533 (its oracle is the ruled #419 BQ-4 radiogroup)                 | none                        |
| CMP-029 skeleton                      | built (`packages/ui` `Skeleton`, `SkeletonChart`)                                   | Storybook leg, §3.3         |
| Candle, OHLC, hollow and Heikin-Ashi  | built in the engine (E12-S06, E12-S07 PR A); their accessible text needs the mirror | contrast leg, §3.4          |
| Rebuild strip, cancel, history marker | not yet built — #535                                                                | none                        |

## 3. Offline legs and results

### 3.1 The suites already at the pin

`pnpm --filter @candleviewer/web exec vitest run test/chart/a11y test/features/chart-price-scale test/features/chart-errors test/features/symbol-search/QuickSwitcher.test.tsx`: **16 files, 307 tests, all pass** at the pin. They are the keyboard journeys of the built surfaces (RTL, real key events on jsdom), cited here and not duplicated:

- SCR-041: Esc, the trigger and an outside press close without commit and return focus to the trigger; Tab out closes; the commit returns focus to its trigger and is said once (`QuickSwitcher.test.tsx`, "closes on the open trigger's press, Esc or a press outside, without commit, focus back on the trigger"). This is D04E47:122 (R-7).
- SCR-043: arrows wrap, Home and End, Enter and Space activate, a gated item is T2 with its reason said again, and every close returns focus to the chart container (`PriceScaleMenu.test.tsx`, "keyboard: arrows wrap and reach the gated items, Home / End, Enter activates"). This is D04E47:119 (R-4).
- SCR-045: the grid keys, `Esc` back to the chart, Alt+T both ways, focus on the chart surface or the Table button and never the page (`ChartDataTable.test.tsx`, `ChartTablePanel.test.tsx`).
- SCR-048: the card keeps focus, moves focus from the panes to its first stop and returns it on close (`ChartErrorSurface.test.tsx`, "focus in the panes moves to the card's first stop and returns to it on close").

Four of those files already run axe-core on jsdom (colour contrast off): SCR-041, SCR-043, SCR-045 and SCR-048, each with 0 serious or critical. That is supplementary, layout-free evidence (jsdom has no layout, so contrast and target size cannot run there) and **not** AC 1 (N-4). These runs evidence no layout-dependent criterion: target size, reflow, text spacing, focus appearance and forced colours are §3.7's rows, not covered by them.

### 3.2 This PR's tests (`apps/web/test/chart/a11y/e12Q07Audit.test.tsx`, 5 tests, all pass)

| Test                                       | Oracle                                 | Measured (heuristic)                                                                                                                                                                                                            |
| ------------------------------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windowing at 100 000 bars, open and travel | D11:96 (60 rows, cap 200, 1,800 nodes) | at open 61 bar rows and 882 grid nodes; after 40 × ↓ and an expanded bar, 59 bar rows plus 3 level rows and 908 nodes; never above 200 rows or 1,800 nodes                                                                      |
| A forming-bar update at 100 000 bars       | the ticket's Performance notes         | one mutation record, 0 nodes added; the grid keeps its 459 nodes (the cursor on the latest bar)                                                                                                                                 |
| BG-09: a held ↓ in the table               | D11:537                                | 60 presses (2 s at 30 Hz): 0 polite writes; the reader follows focus                                                                                                                                                            |
| BG-13: a forming value at 20 Hz for 60 s   | D11:541, `05`:185                      | 31 writes in 60 s through the polite writer, at most 1 in any 1 s window (the ceiling is 2); the last write is the latest value. The writer alone: the combined cursor-plus-panel worst case (D11:552) is not built, so not run |
| Parity: no footprint, delta and CVD absent | D07:238                                | every row's delta and CVD cell reads "—", never a digit                                                                                                                                                                         |

The test asserts the caps and the 61 rows at open; the other node and row counts above were read from a one-off instrumented run of the same test and are reported, not asserted. The node count and the update cost are counted, not timed: a wall-clock budget belongs in a perf project, not in the unit run.

### 3.3 CMP-029 in Storybook

`pnpm --filter @candleviewer/ui exec vitest run --project storybook src/components/Skeleton.stories.tsx src/components/SkeletonChart.stories.tsx` (after `build:tokens`): **2 files, 15 stories, all pass**; the a11y addon fails a story on any serious or critical violation (`packages/ui/.storybook/preview.ts`). The reduced-motion stories render the static two-tone from the first frame.

### 3.4 Contrast and non-colour cues

`pnpm --filter @candleviewer/ui contrast:gate`: 516 pair checks, 81 CVD checks, 0 findings. Series marks against `color.surface.canvas` (3:1 floor), read from the gate's `pairs` entries in its output `build/reports/contrast-matrix.json` under `packages/ui` (regenerated by reproduce step 3; the per-token rows are copied into the results file):

| Token               | Dark | Light | High contrast |
| ------------------- | ---- | ----- | ------------- |
| `color.candle.up`   | 7.45 | 5.03  | 7.45          |
| `color.candle.down` | 4.68 | 4.85  | 4.68          |
| `color.candle.wick` | 5.96 | 6.36  | 5.96          |

Buy against sell under simulation (ΔE76, floor 5.0): deuteranopia 8.26 / 16.14 / 5.76, protanopia 41.16 / 19.40 / 31.85, tritanopia 127.72 / 109.82 / 91.31 (dark / light / high contrast). Heikin-Ashi draws through the same candle ring and tokens. The non-colour cue in the accessible representation is the numbers themselves: SCR-045 gives OHLC as text, so up or down never rests on hue. Baseline, the volume sub-pane and the partial-history marker are not yet built (#533, the E12-S08 story, #535).

### 3.5 Reduced motion

Against E12-D10: every built moment is a cut in both modes (D10:55–62; only M-07, the progress fill, animates, and it is not yet built — #535). CMP-029 is static under reduce (§3.3). The engine redraws a series-type switch in one frame with no transition (E12-S07's `setSeriesKind`; code reading, heuristic). `apps/web/e2e/motion-reduce.spec.ts` has no E12 case because nothing is mounted.

### 3.6 The Security-notes parity row

Run offline against D07:238 as the ruling asks; its outcome is routed to the coordinator and is not recorded here (BQ-0 rider).

### 3.7 Layout criteria: not run

Every criterion here needs a laid-out, mounted surface: jsdom has no layout and no E12 surface is on a route (§0). Each is **not run: not mounted** on SCR-041, SCR-043, the SCR-045 shell and SCR-048, and moves to OR-7 (§6) and the closing slice's sweep.

| SC                                              | What it needs                                                     | Design oracle (cited, not run)                                             |
| ----------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 1.4.4 Resize text, 1.4.10 Reflow (200 %, 400 %) | the surfaces at 200 % and 400 % zoom and at the in-app text scale | `05`:165 and `05` R-12 (`05`:120); D07's stacked reflow at 200 % (D07:215) |
| 1.4.12 Text spacing                             | the WCAG spacing overrides applied to the mounted surfaces        | none named in D07 or D11                                                   |
| 2.5.8 Target size (minimum)                     | measured target boxes in a real layout                            | D11 rates it compliant (D11:654)                                           |
| 2.4.7 Focus visible, 2.4.11 Focus not obscured  | the focus ring seen on each stop, unclipped, in a laid-out panel  | D11 rates both compliant (D11:651, :652)                                   |
| Forced colours / high-contrast mode             | the OS forced-colours mode over the mounted surfaces              | the high-contrast token theme passes the gate (§3.4); the OS mode is unrun |

The Storybook leg (§3.3) lays out CMP-029 in Chromium but does not zoom it or force colours, so it covers none of these rows.

## 4. Findings

| #   | Where                        | SC    | Severity             | Evidence                                                                                                                       | Disposition                                                                                                                 | Register        |
| --- | ---------------------------- | ----- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | --------------- |
| F-1 | SCR-045, delta and CVD cells | 1.3.1 | moderate (heuristic) | the absent value is the bare glyph "—" in its cell; a reader at its default punctuation level may say nothing after the header | open, owner: #521; D07's named form ("no delta: bar from exchange klines") lands with #521; severity provisional until OR-3 | report only (1) |

1. F-1 is not a register row yet: `findings.json` admits a finding only on a screen its sweep audited (`covered` or `partial`), and SCR-045's row is E47-T01's "unreachable: not built" (C-3). The row is appended with the next free `A11Y-F` id once SCR-045 is mounted and swept, or when the coordinator rules another way (BQ-3's rider, a deviation recorded in §5).

No serious or critical finding is open on the built set. Notes that are not defects:

- **N-1 (windowing):** the shell draws the cursor ± 30 rows (61), one over the mirror's 60-row default, well inside the 200-row and 1,800-node caps (D11:96). The 60 is the cursor mirror's number; the table's buffer is E11-D04's.
- **N-2 (T01 rows):** T01 reads SCR-043 and SCR-045 "not built" (T01:180, :182) while `PriceScaleMenu.tsx` and the SCR-045 shell are built, not mounted (C-3).
- **N-3 (SCR-047):** the engine posts `dataState` with no `apps/web` consumer, so the empty state has no surface to audit yet (#487).
- **N-4 (jsdom axe):** BQ-2 read `apps/web` as having no axe in vitest; four of the cited files already run it through the transitive axe-core. No test of this PR adds one (the ruling declined the jsdom leg).

## 5. Acceptance criteria and Definition of Done

| Item                                        | Result                                            | Evidence and what remains                                                                                                                                      |
| ------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC 1: zero serious or critical in the sweep | **not run: not mounted**                          | §0; the jsdom and Storybook legs (§3.1, §3.3) are supplementary. F-1 is report-only, not a ticket (BQ-3; note 1 of §4)                                         |
| AC 2: every bar family readable             | **heuristic for time bars; not yet built — #521** | §3.2 parity and windowing; the `state` cell with `forming` (D07:225) and the per-mode columns are #521's; the "42 seconds to close" utterance is refuted (C-2) |
| AC 3: an unavailable mode explains itself   | **not yet built — #535**                          | SCR-042 is not built; the oracle is D11 BQ-13 and the D03 C-24, C-25 and C-28 strings, checked, never edited                                                   |
| AC 4: keyboard rebuild cancel, focus return | **not yet built — #535**                          | the test is held for the closing slice, never merged skipped (BQ-7); R-7 when the invoker is mounted, R-4's plot cursor when it is gone                        |
| AC 5: reduced motion loses nothing          | **heuristic for the built set**                   | §3.5; the rebuild progress is #535's                                                                                                                           |
| DoD: sweep wired as a required check        | **deviation**                                     | the existing `a11y` check aggregates axe (`05`:304); no new check name                                                                                         |
| DoD: both manual screen-reader passes       | **owner-run (OR-1 to OR-3)**                      | the script is D11's §6 (D11:285, :291: 70 rows), cited and not restated                                                                                        |
| DoD: report with SC, severity, disposition  | **pass for PR 1**                                 | §4                                                                                                                                                             |
| DoD: keyboard journeys in the E2E suite     | **held**                                          | RTL now (§3.1); the Playwright encoding waits for #5829 and a mounted route                                                                                    |
| DoD: `14` / `15` a11y notes                 | **pass: none found wrong in the built set**       | no A-row in PR 1                                                                                                                                               |
| DoD: sprint-review recording                | **owner-run (OR-5)**                              | SCR-042 is not built, so there is no menu to record yet                                                                                                        |

**Deviations:** the ticket's "E12-Q07: …" PR title (a conventional-commit title instead), no new required check, register rows instead of a ticket per moderate (F-1 report-only until SCR-045 is swept, §4 note 1), the owner-run heard passes, AC 1's sweep not run while nothing is mounted.

## 6. Owner-run rows (the checklist, ≤ 10)

| Row  | What the owner runs                                                                                                                                               | Standard              |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| OR-1 | NVDA + Electron, D11's script over the built rows, heard; the record follows `05` §8.4 (text transcripts, the E47-T04 template)                                   | `05` §8.1 row 1       |
| OR-2 | VoiceOver + Electron, the same                                                                                                                                    | `05` §8.1 row 4       |
| OR-3 | NVDA + Chromium, the fast leg, including whether "—" is spoken in an SCR-045 delta cell (F-1)                                                                     | `05` §8.1 row 3       |
| OR-4 | JAWS + Electron is not covered by this ticket; stated so it is not assumed                                                                                        | `05` §8.1 row 2       |
| OR-5 | The sprint-review recording of SCR-042 once #535 lands, reviewed for incidental disclosure before it is attached                                                  | the ticket's DoD      |
| OR-6 | A waiver or a fix decision on F-1 under the delegation, and QA sign-off of this record                                                                            | the DoD's waiver line |
| OR-7 | Once a route mounts them: zoom to 200 % and 400 %, text spacing, target size, focus appearance and forced colours on SCR-041, SCR-043, SCR-045 and SCR-048 (§3.7) | `05`:165, WCAG 2.2 AA |

The heard passes are E12-D13's OR-3 (D13:514). An agent-run pass counts toward none of `05` §8.1 (`05`:293).

## 7. Rows routed to their owners

| Row | Kind | Item                                                                                                                                                                       | Owner                    |
| --- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| F-2 | F    | `pnpm test:a11y` (`AGENTS.md`:384) has no script; the runner is `_job-a11y.yml`'s `npx playwright test -c e2e/playwright.a11y.config.ts`                                   | the `AGENTS.md` §4 owner |
| F-3 | F    | D11's FM-11 restores a vanished Cancel's focus to the plot cursor (D11:240); AC 4 asks for the invoker; D04E47:122 R-7 outranks when it is mounted                         | E12-D11's owner          |
| C-1 | C    | D11 pins `05`:219–222 for the screen-reader matrix (D11:89, :289); §8.1 is at `05`:257 now; BG-01's `05`:147 pointer (D11:529) names order-status cues, not ambient values | E12-D11's owner          |
| C-2 | C    | the ticket's "bar forming, 42 seconds to close" utterance is refuted by D11's BG-01 and BG-03: the countdown is never announced                                            | the ticket text          |
| C-3 | C    | N-2: T01's SCR-043 and SCR-045 rows read "not built" at the pin                                                                                                            | E47-T01 #1323            |

No G-row and no A-row in PR 1.

## 8. Reproduce

1. `pnpm install --frozen-lockfile --offline`, then `pnpm --filter @candleviewer/ui build:tokens`.
2. `pnpm --filter @candleviewer/web exec vitest run test/chart/a11y test/features/chart-price-scale test/features/chart-errors test/features/symbol-search/QuickSwitcher.test.tsx` (§3.1 and §3.2).
3. `pnpm --filter @candleviewer/ui exec vitest run --project storybook src/components/Skeleton.stories.tsx src/components/SkeletonChart.stories.tsx` (§3.3) and `pnpm --filter @candleviewer/ui contrast:gate` (§3.4).
4. `python3 -I docs/design/_tools/e12_q07_bars_audit.py --check` and `--self-test`; `python3 -I docs/plan/a11y/_tools/register.py --check`.
