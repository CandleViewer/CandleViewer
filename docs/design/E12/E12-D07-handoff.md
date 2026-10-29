# E12-D07 — Hand-off (`16` §11.4; SCR-045 per bar mode)

Components: **CMP-049 Table** (the non-time row header, the separator row, the `state` words), **CMP-056 ColumnPicker** (the per-mode sets and the auto columns), **CMP-053 Pagination** (the **Older** control inside the lookback separator row), plus the SCR-045 and SCR-030 rows of `14` and E11-D04's column contract. CMP-099 and CMP-225 are unchanged. The spec is [E12-D07.md](E12-D07.md); every "§" below without a prefix is the spec's. This screen changes component contracts, so the hand-off is due.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-049 Table (SCR-045 per mode)                                          | CMP-056 ColumnPicker                                                                                  | CMP-053 Pagination (in a separator row)        |
| ------------------------ | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Final Penpot link        | [ ] PR 2: boards 01–05, 07–10                                             | [ ] PR 2: boards 02, 08                                                                               | [ ] PR 2: board 05                             |
| Variants × states        | [x] spec §2, §6, §7                                                       | [x] spec §3.1 tiers P / A / E per mode, §4                                                            | [x] spec §7.1 (the lookback row's `Load more`) |
| Keyboard table           | [x] E11-D04's, unchanged; separator rows are grid rows (spec §7.2, §11)   | [x] E11-D04's, unchanged                                                                              | [x] E11-D04's **Older** control                |
| Accessible name and role | [x] the row header's name (spec §2.2); a separator row's name is its text | [x] each column by its header word; the auto state named "Auto (shows when the table is wide enough)" | [x] "Older"                                    |
| Live data                | [x] patches at E11-D04's cadence; the edge announcement once (spec §9.1)  | [x] none                                                                                              | [x] E11-D04's                                  |
| Motion pair              | [x] none: separator rows appear at once                                   | [x] none                                                                                              | [x] none                                       |
| Density notes            | [x] compact; fixed 24 px rows (spec §5)                                   | [x] widths per mode (spec §5)                                                                         | [x] compact                                    |
| Essential exceptions     | [x] none                                                                  | [x] none                                                                                              | [x] none                                       |
| Tokens used              | [x] spec §14                                                              | [x] E11-D04's                                                                                         | [x] E11-D04's                                  |
| Data contract            | [ ] NO: D07-G1 … D07-G4                                                   | [x] spec §3.1                                                                                         | [x] E11-D04's                                  |
| Contrast                 | [x] spec §14 (computed)                                                   | [x] E11-D04's                                                                                         | [x] E11-D04's                                  |
| Storybook                | [x] §D                                                                    | [x] §D                                                                                                | [x] §D                                         |
| Sign-off                 | [ ] owner approval pending                                                | [ ] owner approval pending                                                                            | [ ] owner approval pending                     |

## §B Who applies what

| A                      | Target                             | Applied by                               |
| ---------------------- | ---------------------------------- | ---------------------------------------- |
| D07-A1, D07-A4, D07-A5 | E11-D04 §5.1, §6.3, §13            | E11-D04's owner                          |
| D07-A2, D07-A3, D07-A6 | `14` SCR-030's E12 matrix, SCR-045 | `14`'s owner, at the owner's sign-off PR |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `83f18fd4c` (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A      | Target                   | Field (`file`:line)                    | Old                                                                                                        | New                                                                                                                           |
| ------ | ------------------------ | -------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| D07-A1 | E11-D04 §13              | `chart.data_table_opened` (D04E11:403) | `interval` (`bar_type` + `param`),                                                                         | insert after: `bar_type` (the `22` `BarType` value), `param` (string), — market data only, no account context                 |
| D07-A2 | `14` SCR-030 forming-bar | Screen reader (`14`:734)               | SCR-045 state column "Forming"                                                                             | SCR-045 `state` word `forming` (E12-D07 §6)                                                                                   |
| D07-A3 | `14` SCR-030 closed-bar  | Screen reader (`14`:735)               | SCR-045 state "Closed" or "Closed, corrected"                                                              | SCR-045 `state` word `corrected` for a live amend, a closed bar otherwise unmarked (E12-D07 §6)                               |
| D07-A4 | E11-D04 §5.1             | close time, Source (D04E11:187)        | `Bar.close_t`                                                                                              | `Bar.close_time` / `close_t_ms`                                                                                               |
| D07-A5 | E11-D04 §6.3             | Rows (D04E11:260)                      | `aria-rowcount` = loaded bars + 1                                                                          | `aria-rowcount` = loaded bars + separator rows + 1 (E12-D07 §7.2); and the `state` cell 9 characters (D04E11:183, E12-D07 §5) |
| D07-A6 | `14` SCR-030 E12 matrix  | intro (`14`:727)                       | the SCR-045 separator rows, its "Closed, corrected" state and its rebuild caption named below are proposed | the SCR-045 separator rows, its `corrected` state and its rebuild caption are specified in E12-D07 §6–§7                      |

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component            | Stories                                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| CMP-049 Table        | the merged list + NonTimeRowHeader · SeparatorRows · StateWords · KlineBackfillDelta · CorrectedLive · StackedNonTime200 |
| CMP-056 ColumnPicker | the merged list + PerModeSets · AutoColumns                                                                              |
| CMP-053 Pagination   | the merged list + InSeparatorRow                                                                                         |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

- [ ] Board 01: the time set reads as E11-D04's, with `state` words and the units in the caption.
- [ ] Board 02: a tick row says when it opened, its position, when it closed, how long it took and how many trades closed it.
- [ ] Board 03: a range row's ticks and a renko row's direction are words or numbers, never a fill alone.
- [ ] Board 04: every `state` word appears once; a closed bar is unmarked.
- [ ] Board 05: each separator row says what happened in words; "bar k of n" restarts after a seam.
- [ ] Board 06: baseline, delta-volume and equi-volume add their cells and nothing else.
- [ ] Board 07: moving before the loaded window lands on the first loaded row under its boundary row.
- [ ] Board 08: at 200 % the stacked block keeps every value of the tick row.
- [ ] Boards 09–10: the light twins keep every word.
- [ ] Record `approved` on #242, or the findings `(heuristic)` with board and frame names; rule D07-Q1 on #2701.

## §F Consumer pointers

| Consumer                | Builds from                               | Waits on                                                  |
| ----------------------- | ----------------------------------------- | --------------------------------------------------------- |
| E11-S14 (#521)          | spec §2–§12, §C's A-rows for E11-D04, §D  | D07-G1 … D07-G4 through E12-T05 (#398) and E12-T06 (#399) |
| E12-D12 (#313)          | spec §3 (the per-mode table), §6, §7      | —                                                         |
| E12-Q03 (#419), E12-Q07 | spec §3, §4, §6, §7, §9                   | —                                                         |
| E12-S10 (#396)          | spec §6 (`forming`, `stale`, `corrected`) | D07-G3                                                    |

## §G Dry-run needs (spec §18; one item per need, the spec pointer after the arrow)

An item marked (not found) had no pointer when the role ran; its fold is named after it.

| Role                  | Needs                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| story: E11-S14 (#521) | the column set per mode and tier → §3.1 · each cell's contract field → §3.1 · the non-time row header and its name → §2.2 · row keys → §1.4 · the `state` words and their order → §6 · kline-backfilled delta → §6.1 · stale per row → §6.2 · corrected after a REST re-read → §6.3 · separator rows and their order → §7.1 · separator rows in the grid and under a value sort (not found) → §7.2 · the caption clauses → §7.4 · widths and the reflow per mode → §5 · the edge focus and its announcement → §9.1 · a copied separator row (not found) → §12.1 · the open event's properties → §12.1 · the cost of derived cells → §12.3 |
| story: E12-Q07        | open and close time on every non-time row as text → §2.2 · the close time when its column is hidden (not found) → §2.2 · OHLC and volume per family → §3.1 · the forming word → §6 · separator rows read in the grid → §7.2 · the announcement rate → §9.1 · the keys → §11                                                                                                                                                                                                                                                                                                                                                               |
| story: E12-Q03 (#419) | the bar count read from the table → §1.4 · Heikin-Ashi values in the table → §4 · the partial-history marker as a row → §7.1 · no fetch on a chart-type switch → §1.4                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| story: E12-S10 (#396) | the forming row's word → §6 · a correction in the table → §6.3 · a stale forming row → §6.2                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| story: E12-D12 (#313) | the per-mode table with its fields → §3.1 · the closing quantity per mode → §3.2 · the state list and its order → §6 · the row text per mode → §2.2 · the gaps to route → §17.2                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| QA: E12-D13           | the per-mode sets → §3.1 · the chart-type cells → §4 · the state words → §6 · the separator copy → §13 · tokens and contrast → §14 · the frames → §0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

## §H The board plan for PR 2 (a Penpot lane)

The boards of spec §0; frames named `SCR-045/<mode-or-state> · <theme>`. Data: the recorded fixture paths E12-D06 used, verified at the base by PR 2 before it cites them. Each board's frames:

| Board | Frames                                                                                           |
| ----- | ------------------------------------------------------------------------------------------------ |
| 01    | `time/default · dark`, `time/forming-last · dark`, `time/sorted-delta · dark`                    |
| 02    | `tick/default · dark`, `tick/wide-auto · dark`, `volume/default · dark`, `delta/default · dark`  |
| 03    | `range/default · dark`, `renko/default · dark`, `renko/seam · dark`                              |
| 04    | `states/all-words · dark`, `states/stale-caption · dark`                                         |
| 05    | `separators/non-time · dark`, `separators/time-axis · dark`, `captions/rebuild-and-cache · dark` |
| 06    | `chart-type/baseline · dark`, `chart-type/delta-volume · dark`, `chart-type/equi-volume · dark`  |
| 07    | `sync/before-loaded · dark`, `sync/stale-banner-non-time · dark`                                 |
| 08    | `reflow/tick-200 · dark`                                                                         |
| 09    | `states/all-words · light`                                                                       |
| 10    | `separators/non-time · light`, `separators/time-axis · light`                                    |

## §I Summary for #242

1. Text-first SCR-045 per-mode spec + hand-off + default-deny audit tool; 10<!--=COUNT:boards--> boards follow in PR 2 by a Penpot lane (8<!--=COUNT:boards.dark--> dark, 2<!--=COUNT:boards.light--> light twins).
2. A non-time row leads with its open time to the ms and "bar k of n", keyed `(generation, index)`; the close time and duration are auto columns and always in the row's name.
3. Each mode's set is mapped field by field to `22`'s `Bar` and `23`'s bars item; derived cells state their formula; nothing the canvas series lacks.
4. One lowercase `state` list; `stale` and `corrected` are words; "corrected" is live-only and its loss on a REST re-read is stated.
5. Seams, gaps, partial history and the built-range start are separator rows on E11-D04's band-row form.
6. No aggregated rows: the ratio stays in the caption.
7. Owner item pending on #2701: the design-ahead waiver (D07-Q1).
