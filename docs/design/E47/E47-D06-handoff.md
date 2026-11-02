# E47-D06 — Hand-off (`16` §11.4; the canvas accessibility layers)

Components: **CMP-049 Table** in grid mode with **CMP-055 FilterBar**, **CMP-056 ColumnPicker**, **CMP-053 Pagination** and **CMP-099 PrintExportBar** (the one table shell, spec §6.1), **CMP-028 Banner** (the stale banner, §6.5), **CMP-026 EmptyState** (§6.6), **CMP-180 ChartRoot** (the mirror container and the canvas label, §3, §8), the canvas primitives **CMP-109**, **CMP-110**, **CMP-111**, **CMP-112**, **CMP-183** … **CMP-187** (§2), **CMP-108 DomLadderRow** and **CMP-225 DeepStatsStrip** (native DOM), **CMP-227 EstimatedBadge** (R-5), **CMP-079 RbacGate** with the **CMP-019 Icon** `lock` glyph (the T2 controls, rendering 2a and the one-notice form: spec §10's T2 paragraph; board 08), **CMP-041 Menu** (the row actions), **CMP-039 FocusRing**. Spec: [E47-D06.md](E47-D06.md). Owner approval pending (#2701).

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-049 table shell (profile, ladder, heatmap, CVD) | CMP-180 ChartRoot + canvas primitives | CMP-079 RbacGate (row actions, trade keys) |
| ------------------------ | --------------------------------------------------- | ------------------------------------- | ------------------------------------------ |
| Final Penpot link        | [ ] boards 03–07, 10 PENDING (spec §0)              | [ ] boards 01, 02, 09 PENDING         | [ ] board 08 PENDING                       |
| Variants × states        | [x] spec §6.2 … §6.6                                | [x] spec §2, §3                       | [x] spec §10                               |
| Keyboard table           | [x] spec §6.7                                       | [x] spec §3.1, §3.2                   | [x] spec §10 (`Enter`, `Space`, arrows)    |
| Accessible name and role | [x] spec §5                                         | [x] spec §5, §8                       | [x] spec §10 (full label, `aria-disabled`) |
| Live data                | [x] spec §6.4 (in place), §6.5 (stale)              | [x] spec §8 (cadence, feed clause)    | [x] none                                   |
| Motion pair              | [x] none                                            | [x] none                              | [x] none                                   |
| Density notes            | [x] spec §6.7 (200 %, text scale)                   | [x] spec §4 (the ceiling)             | [x] none                                   |
| Essential exceptions     | [x] none (R-1)                                      | [x] none (R-1)                        | [x] none                                   |
| Tokens used              | [x] D04E11's                                        | [x] none new                          | [x] `color.text.tertiary`, `.secondary`    |
| Data contract            | [ ] NO: D06-G2, D06-G4, D06-G5                      | [ ] NO: D06-G1, D06-G3                | [x] the session's permissions              |
| Contrast                 | [x] D04E11's and D03E47's tokens                    | [x] D03E47's tokens                   | [x] D09E09's measured pair                 |
| Storybook                | [x] §D                                              | [x] §D                                | [x] §D                                     |
| Sign-off                 | [ ] owner approval pending                          | [ ] owner approval pending            | [ ] owner approval pending                 |

## §B Who applies what

| A                 | Target                                           | Applied by                                 |
| ----------------- | ------------------------------------------------ | ------------------------------------------ |
| D06-A1 … D06-A7   | `05` §6 (the normative expansion, T DoD)         | the `05` owner, at the owner's sign-off PR |
| D06-A8 … D06-A12  | `15` CMP-109, CMP-184, CMP-185, CMP-111, CMP-227 | E47-D10 (#1309), the CMP contribution      |
| D06-A13 … D06-A15 | `14` SCR-050, SCR-052, SCR-045                   | the `14` owner, at the owner's sign-off PR |
| D06-A16           | the keymap (`chart.table_toggle`, `Shift+R`)     | E47-S08 (#1322)                            |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `85b6b6c1c` (the tool checks it); New replaces it, or follows it where the row says "insert after". D06-A2, D06-A3, D06-A4 and D06-A8 carry E11-D07's A-08, A-10, A-11 and A-19, re-pinned.

| A       | Target       | Field (`file`:line)     | Old                                                                            | New                                                                                                                                                                          |
| ------- | ------------ | ----------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D06-A1  | `05` §6      | intro (`05`:135)        | Strategy has three complementary layers, all mandatory                         | Strategy has four complementary layers (§6.1–§6.4), all mandatory; the per-surface expansion (inventory, grammars, tables, labels, the parity oracle) is E47-D06             |
| D06-A2  | `05` §6.1    | surrogate (`05`:140)    | a `tabindex`-able, ARIA-labelled DOM element per logical unit (bar, cell, row) | the logical unit by one of two grammars — a cursor window (one roving stop, `aria-current`, detail on `Enter`) or a sparse surrogate set (≤ 200, `aria-setsize`; E47-D06 §3) |
| D06-A3  | `05` §6.3    | sort (`05`:191)         | resets to default when the underlying bar/level focus changes                  | resets to default on a level table when the focused bar or period changes; a bar table never resets on a cursor move (E47-D06 §6.3)                                          |
| D06-A4  | `05` §6.3    | live sync (`05`:193)    | press Alt+T to refresh to current                                              | press Shift+R or Refresh to current                                                                                                                                          |
| D06-A5  | `05` §6.3    | ladder table (`05`:189) | Filter-only ("My levels only" toggle)                                          | insert after the ladder table: the heatmap level table and the CVD table of E47-D06 §6.2, with their columns                                                                 |
| D06-A6  | `05` §6.4    | label (`05`:199)        | so there is no silent/empty node in the accessibility tree                     | insert after: ; each surface's template, its trigger and its feed-state clause are E47-D06 §8                                                                                |
| D06-A7  | `05` §6.3    | toggle (`05`:158)       | The exact column set per surface is fixed (below)                              | insert after: ; the per-panel switch, the stale condition per surface and the parity oracle are E47-D06 §6–§9                                                                |
| D06-A8  | `15` CMP-109 | A11y (`15`:1262)        | **every cell is mirrored**                                                     | the cursor bar's levels are exposed on `Enter` (≤ 40 nodes); bars are mirrored as rows (E06-D03 D1; E47-D06 §3.1)                                                            |
| D06-A9  | `15` CMP-184 | A11y (`15`:2383)        | each TPO letter-block is DOM-mirrored with its period/price-range/letter       | the cursor's price level is mirrored with its period letters as text, the cursor-window grammar (E47-D06 §3.1, N-4)                                                          |
| D06-A10 | `15` CMP-185 | Tokens (`15`:2392)      | `color.text.buy/sell`.                                                         | insert after: a new line — A11y: canvas `role="img"` (E47-D06 L-4); the chart's bar cursor; the CVD table of E47-D06 §6.2; signs and divergence as text                      |
| D06-A11 | `15` CMP-111 | A11y (`15`:1302)        | per §6.2 "windowed accessibility tree"                                         | per `05` §6.1 "windowed accessibility tree" (the sparse set of E47-D06 §3.2)                                                                                                 |
| D06-A12 | `15` CMP-227 | A11y (`15`:2931)        | "Estimated, <display name>                                                     | "Estimated, <display name>, the display name being the reason text of `05` §6.3 (E47-D06 R-5)                                                                                |
| D06-A13 | `14` SCR-050 | A11y (`14`:1217)        | a table alternative listing the top-N levels with density values               | a table alternative listing the levels with density values, sortable by size (the heatmap level table, E47-D06 §6.2)                                                         |
| D06-A14 | `14` SCR-052 | A11y (`14`:1274)        | table alternative with per-bar delta and CVD                                   | table alternative with per-bar delta and CVD (the CVD table, E47-D06 §6.2)                                                                                                   |
| D06-A15 | `14` SCR-045 | Analytics (`14`:1109)   | `chart.data_table_opened`, `chart.data_table_exported` (analytics)             | `chart.data_table_opened`, `chart.data_table_exported` (analytics), each with `surface` (E47-D06 §10)                                                                        |
| D06-A16 | the keymap   | `validWhen` (KM:342)    | "validWhen": "chart panel focused"                                             | "validWhen": "an inventory panel focused" (E47-D06 §7), and a `Shift+R` refresh row in the same contexts                                                                     |

## §D Storybook story lists (each story per theme and density, `15`:41–42)

| Component              | Stories                                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| CMP-049 Table (shells) | ProfileTable · TpoPeriods · LadderTableDepthSort · LadderMyLevels · HeatmapLevels · HeatmapHistory · CvdTable |
| CMP-049 Table (states) | StaleBanner per surface · FeedStale · Empty · NoData · FilteredToZero · LoadMore · PatchInPlace               |
| CMP-180 ChartRoot      | the merged list + DistantJumpRewindow · CanvasLabelStale                                                      |
| CMP-112 BigTradeBubble | the merged list + SparseSetWindowed                                                                           |
| CMP-079 RbacGate       | the merged list + LadderTradeKeysOneNotice · RowActionCreateAlertT2 · MyLevelsFilterT2                        |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

- [ ] Board 01: every surface shows four layers; nothing reads "exempt".
- [ ] Board 02: one stop over the chart, a button per bubble, every reachable target at least 24 px.
- [ ] Board 03: the profile table names POC, VAH and VAL in words; the In VA filter narrows rows only.
- [ ] Board 04: sorted by cumulative depth with My levels only, a tick changes values and nothing else.
- [ ] Board 05: the heatmap table says bid or ask in words; `Enter` opens a level's history.
- [ ] Board 06: a divergence reads as words; every delta has its sign as text.
- [ ] Board 07: the stale banner names the unit and offers `Shift+R`; a stale feed says "as of".
- [ ] Board 08: the switch sits in each panel header; a gated row action keeps its label and says why.
- [ ] Board 09: the footprint bar's five values appear in the mirror label and the table row.
- [ ] Record `approved` on #1305, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer        | Builds from                       | Waits on               |
| --------------- | --------------------------------- | ---------------------- |
| E11-S13 (#520)  | spec §3, §4, §8                   | D06-G1, D06-G2, D06-Q4 |
| E19-S01 (#638)  | spec §6.2 profile, L-2, P-6 … P-9 | D06-G5                 |
| E21-S01 (#648)  | spec §6.2 ladder and heatmap      | D06-G3, D06-G5         |
| E22-S01 (#714)  | spec §3.2 bubbles, L-5, P-16      | D06-G5                 |
| E23-S01 (#763)  | spec §6.2 CVD, L-4, P-14, P-15    | D06-G4                 |
| E47-D07 (#1306) | spec §11, §13                     | —                      |
| E47-Q01 (#1314) | spec §9; §G                       | D06-G1, D06-G4, D06-G5 |
| E47-S08 (#1322) | D06-A16                           | —                      |

## §G The parity oracle and the QA draft assertions (for E47-Q01)

The oracle is spec §9, one row per visual datum. For a fixed recorded fixture, for every row: read the value at the mirror field (the `Enter` detail, the level row or the surrogate name) and at the table column; assert equality of the text, the sign as text and the flag words; a row whose mirror field is "not in the mirror row" asserts the table only.

| QA   | Given / when                                                                                 | Then (assert)                                                                                            |
| ---- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| QA-1 | the fixture's footprint bar with an estimated, imbalanced level; read P-1 … P-5              | bid, ask, delta with `+` / `−`, the flag word and "estimated, {reason}" equal in the label and the table |
| QA-2 | the ladder table sorted by cumulative depth, My levels only, focus on a row; replay one tick | the same row node keeps focus; the sort and filter state are unchanged; no row node was recreated        |
| QA-3 | open the CVD table on a bar, then pan the chart past it                                      | the banner names the bar; `Shift+R` focuses the current bar's row; the banner is gone                    |
| QA-4 | load 100,000 bars, measure the accessibility tree; jump to the first bar                     | the mirror's materialised units stay within §4's chart ceiling before and after; one range label         |
| QA-5 | a session without `alerts:write`; arrow to the row action Create alert here, press `Enter`   | the item has `aria-disabled="true"` and its reason; nothing is created; one polite announcement          |

## §H Session protocol (for the owner; none has been run)

Two screen readers (NVDA with Firefox, JAWS with Chrome) on a coded prototype of the footprint table, the ladder table and the profile table over a recorded fixture. Tasks: (1) open the table from the panel header with `Alt+T`; (2) read a footprint bar's five values in table mode (`Ctrl+Alt+arrows`); (3) sort a column and hear `aria-sort`; (4) apply and clear a filter and hear the count; (5) let three ticks pass with focus on a row; (6) pan the chart away and refresh with `Shift+R`. Record per task: completed or not, what was announced, the number of keystrokes; no timings or quotes are invented. The tree measurement at 100,000 bars (QA-4) and the engine lead's query-surface confirmation (D06-Q4) are recorded beside it.

## §I The board plan (PENDING; spec §0)

The boards of spec §0, on page `E47-D06 — Canvas accessibility`; frames named `<surface>/<state> · <theme>`. Data: a seeded synthetic stream declared synthetic on every board's face; only the instrument's tick size comes from a recorded fixture.

| Board | Frames                                                                                             |
| ----- | -------------------------------------------------------------------------------------------------- |
| 01    | `inventory/sheet · dark`                                                                           |
| 02    | `grammar/cursor-window · dark`, `grammar/sparse-set · dark`, `grammar/targets · dark`              |
| 03    | `profile/sorted · dark`, `profile/in-va · dark`                                                    |
| 04    | `ladder/depth-sort-my-levels · dark`, `ladder/patch-tick · dark`                                   |
| 05    | `heatmap/levels · dark`, `heatmap/history · dark`                                                  |
| 06    | `cvd/divergence · dark`                                                                            |
| 07    | `states/stale · dark`, `states/feed-stale · dark`, `states/empty · dark`, `states/filtered · dark` |
| 08    | `headers/switches · dark`, `headers/t2-row-action · dark`                                          |
| 09    | `parity/footprint-bar · dark`                                                                      |
| 10    | `profile/sorted · light`, `profile/in-va · light`                                                  |

## §J Summary for #1305

1. Text-first four-layer spec + hand-off + default-deny audit tool; 10<!--=COUNT:boards--> boards PENDING, drawn later in this PR; BQ-0 … BQ-15 defaults built, ruling pending (comment 6569517180).
2. 15<!--=COUNT:inv--> surfaces, each with its mirror unit, live-region class, table and canvas label; native DOM surfaces meet layers 1 and 3 by the element; no exemption.
3. Two grammars: a cursor window for dense surfaces, a sparse surrogate set for sparse ones; 24 px, aligned, never `display:none`.
4. Per-panel ceilings are sums of merged caps; no new cap; a distant jump re-windows and announces its range once.
5. One table shell; `05`'s footprint, profile and ladder sets verbatim; heatmap and CVD sets PROPOSED; patched in place, keyed by identity; the stale banner per surface.
6. One name grammar with provenance as text; one parity oracle of 19<!--=COUNT:parity--> rows for QA.
7. The normative expansion of `05` §6 is 16<!--=COUNT:arows--> copy-ready A-rows, never an edit here; owner approval pending (#2701).
8. The audit's G-CITE checks that each cited line exists and is non-blank, not that it says what is claimed; cite content is a reviewer's check.
