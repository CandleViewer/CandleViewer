# E11-Q05 (#517): chart engine WCAG 2.2 AA audit, test plan (PR-1)

Status: **plan only**, PR-1 of the ticket (`Refs #517`). Nothing in this file is a result. The run
record, the axe artefacts and the findings land in PR-2; the screen-reader rows and every sign-off
are the owner's and the accessibility specialist's, and stay **pending** here. The coordinator's
ruling of 2026-11-02 13:23Z accepted the BQ defaults (§13) and the conditions folded below.

## 0. Honest scope

- **Agent-run vs owner-run.** Every row an agent can run is marked `(heuristic)` or `measured`: an
  agent reads the DOM, the computed accessibility tree and axe output; it does not hear a screen
  reader, judge a cadence or see a colour. Rows a person must run are `OR-n` (§12) and stay
  `pending` until the owner or the accessibility specialist records them.
- **No claim of conformance.** This plan never says "the canvas is accessible". axe and the tree
  cover the root wrapper, the canvas label, the mirror and the table only; the most an agent row
  can say is that a named role, name or attribute was present and axe reported a count. Every
  agent-run pass is `(heuristic)` (`03` §12 puts screen-reader passes with QA and the
  accessibility role).
- **Surrogate not on main.** The E11-S13 query surface (#5467) and DOM mirror (#5480,
  `ChartOptions.a11y.mirror`) are unmerged. The harness (§4.1) requests the mirror and detects at
  runtime whether the engine honoured it; until it does, every mirror row reads
  **"not assessed: surrogate not on main (pending #5480)"**. Live regions, the plot tab stop and the
  keys (E11-S13 PR-3) and the table sync, `Alt+T` and the stale banner (E11-S14) are not built.
- **Not built, so not assessed** (`shipped:false`, pinned in
  `apps/web/e2e/a11y/chart-harness/surfaces.ts`): SCR-031 settings dialog, SCR-044 go-to-date,
  SCR-047 empty state, SCR-049 multi-chart grid; the reduce-announcements toggle. The list is
  static: nothing detects a surface landing, so PR-2 re-checks each `shipped:false` entry against
  `main` before its run and updates the list and this plan.
- **No chart route exists** (R-101 / R-102 render `StubRoute`). The audit runs on an e2e-only
  harness page, not on a route (BQ-2).

### 0.1 Contracts in flight, PR split and coordination (C-4.15, R6)

- **Pins.** #5467 (E11-S13 PR-1, query surface) at `fe79691e`, #5480 (E11-S13 PR-2, DOM mirror)
  at `1e238289` and #5443 (E47-D06) at `7a9002db`; every cite of them holds **if they merge as is**
  and is re-pinned to the merge commit at merge. PR-1 stays draft until #5480 is on `main` or
  these pins are stated in its body.
- **Two PRs at most**, ≤ 800 counted lines each, a C-4.8 note above 400 (§14). PR-1 carries
  `Refs #517` + `Partial:`; PR-2 carries `Closes #517` with the sign-off rows listed pending
  (In Test is the C-10.4 step).
- **Overlap scan** of `apps/web/e2e/a11y/**` and `tools/a11y/**` (2026-11-02, one
  `gh pr list --state open --limit 100` read, open PRs 5349–5502; older open PRs not covered):
  #5440 (E29-S01 3/3) edits `apps/web/e2e/a11y/{open,screens,tags}.ts`; `screens.ts` is also
  edited here (an additive `CHART_SCREENS` re-export), so whichever merges second rebases.
  #5438 (E10-Q03) touches neither glob but edits `docs/plan/a11y/findings.json` and
  `docs/plan/a11y/_tools/`, PR-2's findings and driver paths; PR-2 rebases on it. No open PR in
  that range touches `tools/a11y/**`.

## 1. Tools

| Tool                 | Version | Source           |
| -------------------- | ------- | ---------------- |
| axe-core             | 4.14.0  | `pnpm-lock.yaml` |
| @axe-core/playwright | 4.14.0  | `pnpm-lock.yaml` |
| @playwright/test     | 1.64.1  | `pnpm-lock.yaml` |
| Electron (OR rows)   | 45.x    | `pnpm-lock.yaml` |

New dependencies: none. No axe or jsdom is added to `packages/chart-engine` (an ADR would be needed,
CLAUDE.md §9); the audit runs from `apps/web/e2e/a11y`.

## 2. Surfaces under audit

| S-id | Screen  | Surface                                                       | On main                               | Harness state (PR-1)   |
| ---- | ------- | ------------------------------------------------------------- | ------------------------------------- | ---------------------- |
| S1   | SCR-030 | chart panel: root wrapper, canvas `img`, mirror table, cursor | engine mount; mirror unmerged (#5480) | `mirror`, `mirror-off` |
| S2   | SCR-045 | data table (`ChartTablePanel`, `ChartDataTable`)              | yes                                   | PR-2                   |
| S3   | SCR-043 | price / time-scale menus (`features/chart-price-scale`)       | yes                                   | PR-2                   |
| S4   | SCR-031 | chart settings dialog                                         | no (`shipped:false`)                  | none                   |
| S5   | SCR-046 | diagnostics overlay (`features/chart-errors`)                 | yes                                   | PR-2                   |
| S6   | SCR-048 | error state incl. context loss (`ChartErrorSurface`)          | yes                                   | PR-2                   |
| S7   | SCR-047 | empty state                                                   | no (`shipped:false`)                  | none                   |
| S8   | SCR-044 | go-to-date                                                    | no (`shipped:false`)                  | none                   |
| S9   | SCR-049 | multi-chart grid                                              | no (`shipped:false`)                  | none                   |

The `mirror-off` state is BQ-10's evidence: the default tree (canvas `aria-hidden`) is recorded so
a later default-on flip of the mirror flag is gated by evidence, not assumed.

## 3. Criteria x surface matrix

Rows: every WCAG 2.2 A/AA success criterion the E11-D07 §6.3 cross-walk maps or judges (its clause
table, its second table of seven, and 1.3.2, 1.4.5, 1.4.12, 3.2.1, 3.3.1 and 3.3.3 it judges in
prose), plus the `05` clauses the ticket names. The criteria §6.3 leaves to the app shell (E05) or
rules not applicable to a chart are not rows; it names them once. The 45 E11-D07 clause ids are
carried, not re-judged here. Method key: **axe** (the required `a11y` check, §4), **tree** (computed
accessibility tree, `(heuristic)`), **drv** (PR-2 driver, measured), **OR** (owner-run, §12).
Verdicts are written in PR-2's run record only; every cell is `pending` today. `n/b` = not built
(S4, S7, S8, S9: `shipped:false`, not assessed).

| Criterion                       | S1 chart              | S2 table       | S3 scale menus | S5 diag   | S6 error  | S4/S7/S8/S9 |
| ------------------------------- | --------------------- | -------------- | -------------- | --------- | --------- | ----------- |
| 1.1.1 non-text content          | axe, tree, OR         | axe            | axe            | axe       | axe       | n/b         |
| 1.3.1 info and relationships    | axe, tree, OR         | axe, tree, OR  | axe, tree      | axe       | axe, tree | n/b         |
| 1.3.2 meaningful sequence       | tree, OR              | tree, OR       | tree           | tree      | tree      | n/b         |
| 1.3.3 sensory characteristics   | drv (CVD), OR         | tree           | tree           | tree      | tree      | n/b         |
| 1.4.1 use of colour             | drv (CVD), OR         | drv (CVD)      | drv            | drv       | drv       | n/b         |
| 1.4.3 contrast (minimum)        | axe, drv              | axe            | axe            | axe       | axe       | n/b         |
| 1.4.4 resize text (200 %)       | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 1.4.5 images of text (by alt.)  | tree, OR              | tree           | —              | —         | —         | n/b         |
| 1.4.10 reflow (400 %)           | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 1.4.11 non-text contrast        | drv, OR               | axe, drv       | drv            | drv       | drv       | n/b         |
| 1.4.12 text spacing             | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 1.4.13 content on hover/focus   | drv                   | drv            | drv            | drv       | —         | n/b         |
| 2.1.1 keyboard                  | drv, OR               | drv, OR        | drv            | drv       | drv       | n/b         |
| 2.1.2 no keyboard trap          | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 2.1.4 character key shortcuts   | drv, OR (R-T2)        | OR             | —              | —         | —         | n/b         |
| 2.2.2 pause, stop, hide         | drv (`05` §7), OR     | drv            | —              | —         | —         | n/b         |
| 2.3.1 three flashes (hard)      | drv (`05` 7.3), OR    | drv            | —              | —         | drv       | n/b         |
| 2.4.3 focus order               | drv, OR (R-T1)        | drv            | drv            | drv       | drv       | n/b         |
| 2.4.7 focus visible             | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 2.4.11 focus not obscured       | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 2.5.1 pointer gestures          | drv (PG twins)        | —              | —              | —         | —         | n/b         |
| 2.5.2 pointer cancellation      | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 2.5.3 label in name             | tree (F-32)           | tree           | tree           | tree      | tree      | n/b         |
| 2.5.7 dragging movements        | drv (§3.1.6)          | —              | —              | —         | —         | n/b         |
| 2.5.8 target size (minimum)     | axe, drv              | axe, drv       | axe, drv       | axe       | axe       | n/b         |
| 3.2.1 on focus                  | drv                   | drv            | drv            | drv       | drv       | n/b         |
| 3.2.2 on input                  | drv (view sw.)        | drv (view sw.) | drv            | —         | —         | n/b         |
| 3.3.1 / 3.3.3 error id. / sugg. | —                     | —              | —              | —         | —         | n/b (S8)    |
| 4.1.2 name, role, value         | axe, tree, OR         | axe, tree, OR  | axe, tree      | axe, tree | axe, tree | n/b         |
| 4.1.3 status messages           | drv, OR               | drv, OR        | —              | —         | drv, OR   | n/b         |
| `05` §3.1.6 no hover/drag-only  | drv                   | drv            | drv            | —         | —         | n/b         |
| `05` §4 colour independence     | drv (CVD), OR         | drv            | —              | —         | drv       | n/b         |
| `05` §6.1 DOM mirror            | tree, drv, OR         | —              | —              | —         | —         | n/b         |
| `05` §6.2 live regions          | drv, OR               | drv, OR        | —              | —         | drv, OR   | n/b         |
| `05` §6.3 table                 | —                     | axe, drv, OR   | —              | —         | —         | n/b         |
| `05` §6.4 canvas `img` label    | tree, OR (IMG-IN-APP) | —              | —              | —         | —         | n/b         |
| `05` §7 reduced motion          | drv                   | drv            | drv            | drv       | drv       | n/b         |

`2.3.1` is a hard gate (`05` §7 item 3): chart price-flash and the error state's transitions are
measured by the driver (flash count per second and area), never judged by eye. `2.5.1` checks the
pinch and two-finger drag have the single-pointer and keyboard twins (E11-D07 §8 PG12); `2.5.3`
carries E11-D07's F-32 (the `auto` segment); `3.2.2` is the manual-activation view-switch
radiogroup E11-D07 §6.3 routes here. `1.4.5` and `1.4.12` are met by the alternative (mirror and
table), not the canvas, so their S1 rows read the mirror. `3.3.1` / `3.3.3` are SCR-044's errors,
not built.

S1 rows that read the mirror record "not assessed: surrogate not on main (pending #5480)" until the
harness reports `mirrorEngaged: true` (§4.1).

## 4. Automated audit

### 4.1 The chart harness (PR-1, in the required `a11y` check)

- **Entry:** `apps/web/e2e/a11y/chart-harness/index.html` + `main.ts`, built by its own
  `vite.config.ts` (the app's aliases and defines, root = the harness directory, outDir under
  `node_modules/.cache`) and served by a second `vite preview` web server in
  `apps/web/e2e/playwright.a11y.config.ts`. It is never in the app bundle:
  `apps/web/test/e2e-a11y-chart-harness.test.ts` pins that the app build keeps its one entry
  (`apps/web/index.html`), that no app source imports the harness, and that the harness outDir is
  outside `dist`. There is no `?harness` switch in the app.
- **Mount:** `createChart` from `@candleviewer/chart-engine` as on `main`, a seeded synthetic candle
  series (500 bars, LCG seed 517; no network, C-13.5). It passes `a11y: { mirror: true }` (state
  `mirror`) or `false` (state `mirror-off`); an engine without the option ignores it, and the
  harness publishes `mirrorEngaged` from the DOM (`[data-cv-chart-root]`).
- **Collectors:** `screens.ts` re-exports `CHART_SCREENS` (`SCR-030-mirror`, `SCR-030-mirror-off`);
  `axe.collect.ts` and `tree.collect.ts` visit them after the route screens, so gate 1 (A11Y-G001,
  serious/critical against the shrink-only baseline) covers the chart from this PR on. Until #5480
  lands the engine ignores `a11y.mirror`, so the `mirror` and `mirror-off` states render the same
  DOM and the `mirror` state's axe coverage is nominal (`chart.collect.ts` records
  `mirrorEngaged: false`).
  `chart.collect.ts` writes `reports/a11y/chart-harness.json`: each state's report, the root and
  canvas roles/names, the mirror table count, the `shipped:false` surfaces and toggles. Like every
  collector it fails only when it cannot collect (no canvas mounted).
- **Per-PR scope** (A11Y-G007, 12 min, `05` §9 item 7): the per-PR job runs axe + tree only. The
  chart states must hold axe serious / critical = 0 (`30-frontend-react`, C-9.1 #9); the
  shrink-only `tools/a11y/axe-baseline.json` never grows for a new screen: the violation is fixed
  or the surface is unmounted. The 20 Hz storm, the CVD captures, the 400 % reflow and the
  AT-attached frame-time passes live in PR-2's committed driver run, never the per-PR job.
- **Tree baseline:** no `tools/a11y/tree-snapshots/SCR-030-*.txt` is committed in PR-1: the tree
  changes when #5480 lands, so the baseline is committed in PR-2 against the merged surrogate.

### 4.2 The audit driver (PR-2)

`docs/plan/a11y/_tools/e11-q05-chart.{qa,config}.ts` + `-merge.mjs` (E10-Q03 precedent): axe with
**every impact** and `best-practice` per surface x state (AC1's "zero violations"; BQ-1), the tree
via `ariaSnapshot` and CDP `Accessibility.getFullAXTree`, the Tab walk with keystroke counts, 200 /
400 % reflow, text-spacing CSS, `forcedColors: 'active'`, CVD captures, the 20 Hz storm. Every
driver step carries an oracle id (an E11-D07 clause, an E06-D03 T-n, E47-D06 §9 or a `05` §n); a
step without one is not run. Results to `docs/qa/a11y/e11-q05-chart-results/` and the run record
`e11-q05-chart-audit-run.md`. The `a11y` job's artefact upload already carries `reports/a11y/`
(incl. `chart-harness.json`); per-route axe artefacts for the chart states are therefore published
from PR-1. Further job wiring is PR-2 (workflow edit, `security-review`).

### 4.3 Keyboard (PR-2, needs E11-S13 PR-3)

Tab walk from the panel header: stop count, no trap, focus visible on every stop, `Alt+T` to the
table and back, every documented chart hotkey, and a named **no-hover / no-drag** step: every
action reachable by pointer hover or drag (crosshair, pan, scale drag) is reached by keys alone,
with the mouse-event counter of `keyboard.collect.ts` at 0 (`05` §3.1.6, 2.5.7). Blocked until the
plot stop and keys exist; recorded `not assessed` meanwhile.

## 5. Low vision (PR-2 driver, measured; owner rows for real HCM)

- 200 % and 400 % browser zoom at 1280 x 800: no loss of content, no 2-D scroll for primary
  content, the table's primary columns readable without horizontal scroll (AC5; 1.4.4, 1.4.10).
- Text spacing (1.4.12): the WCAG bookmarklet values injected as CSS; no clipping or overlap.
- High-contrast theme: the dark-high-contrast token set; contrast via axe and the token gate
  (`tools/contrast`).
- Forced colours: Playwright `forcedColors: 'active'` emulation is a `(heuristic)` agent row
  (BQ-8); Windows High Contrast Mode on Windows 11, incl. the D10 cursor (R-T5, E06-D03 §8 item 12),
  is OR-4.

## 6. Colour independence (PR-2; feeds O5)

Every S1-S6 state captured under deuteranopia, protanopia and tritanopia (SVG colour-matrix filter
over the page) and greyscale; each encoding listed with its non-colour carrier (shape, glyph, label,
pattern). Any encoding carried by colour alone is a **Blocking** finding (AC6). The token-level
collapse check is `tools/contrast` A11Y-C003; the captures are judged against the same
A11Y-C003 JND floor (CIE76 dE, `05` §9 item 3), and where a capture cannot be measured that way
its threshold is written PROPOSED. O5 (`26` §16) closes only by an ADR amendment that
PR-2 drafts as **PROPOSED**, naming the ADR it amends; closure is OR-9 (BQ-9).

## 7. Live regions and performance with AT (PR-2; needs E11-S13 PR-3)

- **20 Hz storm** (AC4): the seeded bench tape replayed at 20 updates/s for 2 min; the driver counts
  polite and assertive region writes per minute and the mirror's `desync_detected` and
  `mirror_rewindows` counters, compared with `engine.a11y.announcements_per_minute`
  `(heuristic)`, judged against `05` §6.2: ambient `polite` at most 1 update per 2 s per field,
  always the latest value; `assertive` events once each, in full. Whether the cadence is
  **tolerable** stays OR-1 / OR-2's (the owner's) judgement, never an agent's.
- **Discrete alerts** announced once and in full; **reduce-announcements toggle** honoured:
  `shipped:false` today, recorded `not assessed`.
- **Mirror cost** (ticket performance notes): frame time p50/p95 with the mirror on vs off on the
  same scene `(heuristic)`, and again with an AT attached in the committed driver run (gap 1);
  the NVDA-attached measurement is OR-1 (a chart smooth without AT and janky with it is a real
  defect).
- **Markup safety** (E11-X01, verified from outside): a harness state whose mirrored labels carry
  markup-like text (`<img src=x onerror=…>`); the tree and DOM must show it as text with no element
  created. Added with the mirror (#5480), so PR-2.
- **Context loss** (AC7): `WEBGL_lose_context` lose / restore; the driver asserts one region write
  per event, focus and cursor index unchanged `(heuristic)`; hearing it is OR-1.

## 8. Equal status of the table (PR-2; needs E11-S14)

Value parity: every value the canvas shows for a bar is in the table row (the E47-D06 §9 parity
oracle, `docs/design/E47/E47-D06.md` §9 at `7a9002dbd`, the #5443 head; if #5443 merges as is). The
driver reads the window and rows by E06-D03 D9's names as on `main`: `getA11yWindow()` (`firstBar`,
`lastBar`, `viewFirstBar`, `viewLastBar`, `cursorBar`, `cursorTime`, `footprintTier`, `candleTier`,
`barsPerColumn`) and `onA11yWindowChange`'s `A11yRows` (`time`, `open`, `high`, `low`, `close`,
`volume`, `delta`, `priceOrigin`, `tickSize`, `priceDecimals`), formatted by
`getBarSummary(barIndex, "full")`. Keystrokes from the panel header to the table vs to every other
primary chart control, counted by the driver (AC3); the screen-reader confirmation is OR-1 / OR-3.

## 9. Screen-reader matrix (`05` §8.1 pinned; owner-run, pending)

| Combo (`05` §8.1 row)                  | Surfaces    | Tasks                                             | Priority    | Status  |
| -------------------------------------- | ----------- | ------------------------------------------------- | ----------- | ------- |
| NVDA 2024.x + Electron, Windows 11 (1) | S1, S2, S6  | Q-T1..Q-T9, T1-T14, R-T1..R-T6, IMG-IN-APP, H1-H6 | P0 primary  | pending |
| NVDA 2024.x + Chromium, Windows 11 (3) | S1, S2      | Q-T1..Q-T3, Q-T6                                  | P0 dev gate | pending |
| VoiceOver + Electron, macOS 14 (4)     | S1, S2      | Q-T1..Q-T9, R-T2, R-T3, IMG-IN-APP                | full        | pending |
| JAWS 2024.x + Electron, Windows 11 (2) | S2, regions | Q-T5, Q-T6, Q-T8, R-T2 (JAWS rows), IMG-IN-APP    | spot-check  | pending |

The ticket names NVDA + Chrome as the primary combo, JAWS + Chrome for the spot-check and
VoiceOver + Safari. `05` §8.1 is Electron-first and puts Safari out of scope, so the primary NVDA,
the JAWS and the VoiceOver rows run in the Electron shell; NVDA + Chromium (row 3) covers the
ticket's Chrome leg only as the P0 dev gate, and JAWS + Chrome is not run (BQ-3, Deviations).
Sessions are recorded on the **demo** environment with synthetic data and stored in the private QA
drive, referenced here by date and id only.

## 10. Task ids (the same for every reader)

| Id             | Task                                                                                                       | Source                                  |
| -------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Q-T1           | find the current price                                                                                     | ticket; oracle E06-D03 T4, `05` §6.2    |
| Q-T2           | navigate to a specific bar                                                                                 | ticket; oracle E06-D03 T2, T3, T4       |
| Q-T3           | read a bar's OHLCV                                                                                         | ticket; oracle E06-D03 T2, E47-D06 §9   |
| Q-T4           | switch to log scale (S3)                                                                                   | ticket; oracle `05` §3.4 item 2         |
| Q-T5           | open the data table and read three bars                                                                    | ticket; oracle E06-D03 T6, E47-D06 §9   |
| Q-T6           | sort the table by delta (`aria-sort`, tri-state)                                                           | ticket; oracle `05` §6.3, handoff H3    |
| Q-T7           | move the crosshair; the table follows                                                                      | ticket; oracle E06-D03 T6, T13          |
| Q-T8           | discover that the chart went stale                                                                         | ticket; oracle `05` §6.2, §6.3          |
| Q-T9           | recover from a lost graphics context (AC7)                                                                 | ticket; oracle `05` §6.2 (assertive)    |
| T1-T14         | mode cue, cadence, hold, `Alt+T`, mode switching, storm, degraded-2d, D10, hover vs selection, data origin | E06-D03 §7.3                            |
| R-T1..R-T6     | stop order, browse vs focus keys, `Alt+T` four-way, 200 % / greyscale, WHCM D10, the root-role test        | E11-D07 §17                             |
| H1-H6          | table: `Alt+T` from the header, table mode, sort, filter count, focus over 3 ticks, `Shift+R`              | E47-D06-handoff §H (†)                  |
| **IMG-IN-APP** | img inside application (below)                                                                             | Q05-owned; oracle `05` §6.4, E11-D07 §2 |

(†) Tasks (1)-(6) of `docs/design/E47/E47-D06-handoff.md` §H, pinned at `7a9002dbd` (the #5443
head); E47-D06 is not on `main`, so the cite holds if #5443 merges as is and is re-pinned to the
merge commit then.

**IMG-IN-APP** (renamed from the scout's "H10", which collides with E06-D03 H10 / E11-D07's H10 grid
swap). With the root `role=application` focused, can each reader reach and read the canvas
`role=img` label at all (browse mode is off inside an application; VoiceOver needs interaction), is
the label double-read with the root's name, and does the E11-D07 §2 H10 grid swap (`grid` mirror +
coalesced `aria-activedescendant`) change it. Agent part `(heuristic)`: axe and the tree show the
`img` node exposed, named, not focusable, inside the application node (`chart.collect.ts` records
the roles and names). Owner part: hear it (OR-1, OR-3). IMG-IN-APP is read alongside R-T6 (OR-8).

**Root role (BQ-7).** `application` stays PROPOSED (E11-D07 Q8 / §2). The agent records tree and
axe evidence for `application` and the H10 `grid` swap `(heuristic)`; the verdict is the owner's
R-T6 run (OR-8). The grid model is adopted only if T2 / T3 fail under `application` and pass
under `grid`.

## 11. Severity and findings

| Ticket severity | Meaning                                                    | `03` priority | Gate                         |
| --------------- | ---------------------------------------------------------- | ------------- | ---------------------------- |
| Blocking        | a task cannot be completed, or information is unavailable  | P0            | gates the E11 Epic DoD       |
| Major           | completable but substantially harder than the pointer path | P1            | owner and date before R1 PRR |
| Minor           | friction                                                   | P2            | backlog                      |

Audit defects are A11Y-F rows in `docs/plan/a11y/findings.json` (`finding-record.schema.json`,
regenerate the register with `register.py`), each with the WCAG criterion, severity, owner and
target ticket. An issue (`priority/*`, linked to the E11 ticket it came from) is filed only for a
blocking P0–P1 finding. PR-1 adds no rows (its harness run found none to record). AC1's "zero
violations": the required gate blocks serious / critical (A11Y-G001); moderate and minor are
counted in the run record and each becomes an A11Y-F row (BQ-1).

## 12. AC / DoD trace and owner-run rows

| AC / DoD item                                   | Verified by                                                                                 | Who / when             |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------- | ---------------------- |
| AC1 axe clean and required                      | §4.1 harness in the `a11y` check (PR-1); §4.2 all-impact run                                | agent; PR-1, PR-2      |
| AC2 SR user completes every task                | §9 / §10 on NVDA and VoiceOver                                                              | OR-1, OR-3; pending    |
| AC3 table equal status                          | §8 parity + keystroke count; SR confirmation                                                | agent PR-2; OR-1       |
| AC4 announcements usable at 20 Hz               | §7 write counts `(heuristic)` vs `05` §6.2; tolerability                                    | agent PR-2; OR-1, OR-2 |
| AC5 400 % reflow                                | §5                                                                                          | agent PR-2             |
| AC6 meaning without colour                      | §6 captures; O5 ADR amendment (PROPOSED)                                                    | agent PR-2; owner      |
| AC7 recovery perceivable                        | §7 context loss `(heuristic)`; hearing it                                                   | agent PR-2; OR-1       |
| DoD keyboard-only, `Alt+T`, no hover/drag       | §4.3                                                                                        | agent PR-2             |
| DoD 200/400 %, HC theme, WHCM, text spacing     | §5; WHCM                                                                                    | agent PR-2; OR-4       |
| DoD JAWS spot-check                             | §9 row 2                                                                                    | OR-2; pending          |
| DoD defects filed with `priority/*`             | §11                                                                                         | agent PR-2             |
| DoD coverage contribution                       | N/A: e2e-only harness and collectors, no unit-covered package code; recorded as N/A in PR-2 | agent                  |
| DoD test plan reviewed by the chart-engine lead | review of this file                                                                         | OR-5; pending          |
| DoD QA sign-off comment, pass/fail per scenario | issue comment after PR-2                                                                    | OR-6; pending          |
| DoD accessibility specialist sign-off           | `05` §8.3                                                                                   | OR-7; pending          |
| Re-test after remediation                       | a pending row under #517 (no follow-up ticket; ruling 13:23Z, gap 6)                        | owner; pending         |

Owner-run rows (never run or marked by an agent):

| OR    | What                                                                                                     | Status  |
| ----- | -------------------------------------------------------------------------------------------------------- | ------- |
| OR-1  | NVDA + Electron, Windows 11: full task set, 20 Hz listen, mirror frame time with NVDA attached, recorded | pending |
| OR-2  | JAWS spot-check (§9 row 2), recorded                                                                     | pending |
| OR-3  | VoiceOver + Electron, macOS 14: task set, IMG-IN-APP, recorded                                           | pending |
| OR-4  | Windows High Contrast Mode, R-T5                                                                         | pending |
| OR-5  | chart-engine lead review of this plan                                                                    | pending |
| OR-6  | QA/SDET sign-off comment                                                                                 | pending |
| OR-7  | accessibility specialist sign-off (gates the E11 DoD)                                                    | pending |
| OR-8  | the R-T6 root-role verdict (`application` vs the H10 grid)                                               | pending |
| OR-9  | O5 closure: approval of PR-2's PROPOSED ADR amendment                                                    | pending |
| OR-10 | the owner's `approved`                                                                                   | pending |

## 13. BQ defaults (all ACCEPTED, ruling 2026-11-02 13:23Z)

| BQ    | Question                                          | Accepted default                                                                  |
| ----- | ------------------------------------------------- | --------------------------------------------------------------------------------- |
| BQ-1  | "zero violations" vs serious/critical gate        | gate stays serious/critical; moderate/minor counted in PR-2, each an A11Y-F row   |
| BQ-2  | no chart route                                    | audit the e2e-only harness; add R-101 to `screens.ts` when E15 mounts the chart   |
| BQ-3  | ticket combos NVDA/JAWS + Chrome, VO + Safari     | Electron rows per `05` §8.1; NVDA + Chromium as dev gate only; no JAWS + Chrome   |
| BQ-4  | ticket repo paths name `packages/chart-engine/**` | no engine edits; harness and collectors in `apps/web/e2e/a11y` (Deviation)        |
| BQ-5  | branch name                                       | keep the claimed `test/e11-q05-wcag-audit` (Deviation)                            |
| BQ-6  | unbuilt surfaces                                  | `shipped:false`, not assessed; not blocking Q05                                   |
| BQ-7  | root role                                         | evidence `(heuristic)`; verdict is the owner's R-T6; `application` stays PROPOSED |
| BQ-8  | forced-colors emulation vs WHCM                   | emulation is a heuristic agent row; WHCM is OR-4                                  |
| BQ-9  | O5 closure                                        | PR-2 drafts the ADR amendment as PROPOSED; closure needs owner approval           |
| BQ-10 | mirror flag default off                           | harness requests it on; the off tree is recorded too                              |
| BQ-11 | recordings                                        | owner-run, demo env, private QA drive, referenced by date and id                  |

## 14. PR plan

- **PR-1 (this):** this plan; the e2e-only chart harness and its exclusion test; `CHART_SCREENS` in
  the `a11y` collectors. No workflow, engine or baseline change.
- **PR-2 (`security-review`):** the axe driver run with every impact, the artefacts and run record,
  the `a11y` job wiring, the tree baselines, a built-output check that `vite build` leaves no
  harness file in `dist`, the `shipped:false` re-check, findings rows, the O5 amendment draft.
  Branched fresh from `main` once #5480, E11-S13 PR-3 and E11-S14 have merged (C-4.3). Carries
  `Closes #517`, with OR-1..OR-10 listed pending (they are owner-run; In Test is the C-10.4 step).
- **Critic gaps** (ruling condition 5): 1 AT-attached frame time, PR-2 §7 + OR-1; 2 the
  poisoned-label text-not-markup fixture, PR-2 §7; 3 the per-route axe artefact, PR-1 (§4.1
  `chart-harness.json` in `reports/a11y/`); 4 the no-hover / drag-only step, PR-2 §4.3; 5 the DoD
  rows, PR-1 §12, evidenced in PR-2; 7 reduce-announcements as `shipped:false`, PR-1
  (`surfaces.ts`, §0). Gap 6 (a re-test ticket) is overridden: the re-test is a pending row (§12).
