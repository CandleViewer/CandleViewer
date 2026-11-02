# E47-D13 — Hand-off (`16` §11.4; the statement, the report and the limitations register)

Components: **CMP-086 SettingsLayout** (the `SCR-119/statement` sub-view), **CMP-049 Table** in its static `table` variant (the limitations and the criteria tables), **CMP-028 Callout** `tone="info"` (the stale and version-unknown notices), **CMP-033 CopyButton** (the problem template), **CMP-021 Link**, **CMP-085 SkipLink**, **CMP-015** skeleton and **CMP-027** error with Retry, **CMP-207 BuildFooter** (the running version), and **CMP-079 RbacGate** with the **CMP-019 Icon** `lock` glyph (none used today: no control is T2; a gated control added later follows spec §7.8's T2 paragraph, rendering 2a). No new component, no new token.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | The statement page (`SCR-119/statement`)                             | The report (`47-conformance-report.md`) | The register (`47-limitations.json`) |
| ------------------------ | -------------------------------------------------------------------- | --------------------------------------- | ------------------------------------ |
| Final Penpot link        | [ ] page `E47-D13 — Conformance statement`: boards pending (spec §0) | [x] n/a (generated text)                | [x] n/a (data)                       |
| Variants × states        | [x] spec §7.3                                                        | [x] spec §2.2 (frozen format)           | [x] spec §6.2                        |
| Keyboard table           | [x] spec §7.4                                                        | [x] n/a                                 | [x] n/a                              |
| Accessible name and role | [x] spec §7.2 (one `h1`, `h2` per section, real tables)              | [x] real tables with headers            | [x] n/a                              |
| Live data                | [x] none; the notices are `role="status"` once                       | [x] none                                | [x] none                             |
| Motion pair              | [x] none                                                             | [x] n/a                                 | [x] n/a                              |
| Density notes            | [x] one column at every density                                      | [x] n/a                                 | [x] n/a                              |
| Essential exceptions     | [x] none                                                             | [x] none                                | [x] spec §6.4 (sign-off blocked)     |
| Tokens used              | [x] spec §7.6, §7.7                                                  | [x] n/a                                 | [x] n/a                              |
| Data contract            | [ ] NO: D13-G1, D13-G2, D13-G3                                       | [ ] NO: D13-G4, D13-G5                  | [x] spec §6.2                        |
| Contrast                 | [x] spec §7.6 (computed)                                             | [x] n/a                                 | [x] n/a                              |
| Storybook                | [x] §D                                                               | [x] n/a                                 | [x] n/a                              |
| Sign-off                 | [ ] owner approval pending                                           | [ ] owner approval pending              | [ ] owner approval pending           |

## §B Who applies what

| A                      | Target                | Applied by                                 |
| ---------------------- | --------------------- | ------------------------------------------ |
| `05` §8.3 bullet       | `05`                  | this PR (BQ-10)                            |
| D13-A1                 | `12` settings routes  | the `12` owner, at the owner's sign-off PR |
| D13-A2, D13-A3, D13-A4 | `14` SCR-117, SCR-119 | the `14` owner, at the owner's sign-off PR |
| §C.2 carried rows      | the producer tickets  | posted as comments when the PR opens       |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `4c662fd5b` (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A      | Target       | Field (`file`:line)         | Old                                        | New                                                                                                                                                               |
| ------ | ------------ | --------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D13-A1 | `12` routes  | the R-205 row (`12`:97)     | Electron window/monitor layout preferences | insert after the row: a route row for `/accessibility`, "Accessibility statement (SCR-119 sub-view `statement`; E47-D13 §7)", roles O, M, V; id by the `12` owner |
| D13-A2 | `14` SCR-117 | Type (`14`:2476)            | and a link to the a11y statement.          | and a link to the accessibility statement (`/accessibility`, the SCR-119 sub-view `statement`; E47-D13 §7).                                                       |
| D13-A3 | `14` SCR-119 | Type (`14`:2497)            | and the licence/attribution list.          | insert after: The accessibility statement is its sub-view `statement` at `/accessibility`, a lazy chunk that works offline (E47-D13 §7).                          |
| D13-A4 | `14` SCR-119 | Analytics/audit (`14`:2502) | `help.update_check_requested` (analytics)  | insert after: ; `a11y.statement_viewed {entry, stale}` and `a11y.problem_report_copied {}` (analytics, aggregated, no identifiers; E47-D13 §7.9)                  |

### §C.2 Carried evidence rows (posted on each producer when the PR opens; their tickets are not edited)

| Producer                         | Produces (spec §4.1 kinds)                | For classes                       | Reference                |
| -------------------------------- | ----------------------------------------- | --------------------------------- | ------------------------ |
| E47-T04 (#1359), E47-Q02 (#1355) | `pass`                                    | every class but K-W22 and K-FLASH | `pass:<record id>@<sha>` |
| E47-D12 (#1369)                  | `d12`                                     | K-W22, K-SR                       | `d12:<verdict id>@<sha>` |
| E47-Q05 (#1357)                  | `flash`, `q05`                            | K-FLASH, K-MOTION                 | `q05:<row id>@<sha>`     |
| E47-Q03                          | `keyboard` (the suite behind `A11Y-G004`) | K-KEY                             | `t01:keyboard@<sha>`     |
| E47-T03 (closed; its matrix)     | `t03`, `contrast`                         | K-CONTRAST                        | `t03:<row id>@<sha>`     |
| E47-S01 (#1316), E47-S02 (#1358) | the four canvas layers' evidence          | the canvas rows (spec §5)         | `pass:<record id>@<sha>` |
| E47-S03, E47-S05, E47-S08        | re-runs of the T01 cells on their screens | K-AXE, K-KEY, K-ZOOM              | `t01:<kind>@<sha>`       |

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component                     | Stories                                                                                               |
| ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| AccessibilityStatement (page) | Default · NoSupportsYet · Stale · VersionUnknown · Loading · ChunkFailed · Reflow320 · LongLimitation |
| CMP-033 CopyButton            | the merged list + ProblemReportTemplate                                                               |
| CMP-049 Table                 | the merged list + StatementCriteria (static, stacked at 320 CSS px)                                   |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

- [ ] Board 01: the page reads top to bottom as status, target, version, supported, limitations, alternatives, criteria, report.
- [ ] Board 02: the status and the version line say, in words, how far the app conforms and for which release.
- [ ] Board 03: a stale statement is plainly marked as out of date before the version line.
- [ ] Board 04: each limitation reads as what you notice, who it affects and what to do; no criterion number stands alone.
- [ ] Boards 05–06: each alternative names its key; every level in the criteria table is a word.
- [ ] Board 07: the problem template asks for nothing personal.
- [ ] Boards 09–10: nothing is clipped at 200 % or 320 CSS px; the Tab order matches the reading order.
- [ ] Read the limitations as a non-specialist reader would; mark each sentence you had to read twice (T Test).
- [ ] Run `--json` and check each of the ten drawn rows against its cited evidence (spec §10); log any mismatch.
- [ ] Record `approved` on #1311, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer        | Builds from                        | Waits on        |
| --------------- | ---------------------------------- | --------------- |
| E47-T05 (#1360) | spec §2–§9; the tool; the register | D13-G1 … D13-G5 |
| E47-Q01 (#1314) | §G; spec §7                        | D13-C6          |
| E47-Q09 (#1388) | the report's format (spec §2.2)    | E47-T05         |
| E47-X04 (#1389) | spec §6.5                          | —               |
| E47-D05 (#1304) | spec §7.1 (the entry link)         | —               |

## §G QA draft assertions (deterministic; for E47-Q01's TC-606 … TC-608 and E47-T05's staleness check)

| QA   | Given / when                                                                   | Then (assert)                                                                                                           | Q01             |
| ---- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | --------------- |
| QA-1 | on SCR-117, activate the "Accessibility statement" link by keyboard            | the statement renders at `/accessibility`; `document.activeElement` is its `h1`; one `h1`; every table has `th` headers | TC-606          |
| QA-2 | serve a statement whose `appliesTo` differs from the running version           | the W-7 notice is present above the version line, with `role="status"`; the page still renders                          | no case; new    |
| QA-3 | at 200 % zoom and at 320 CSS px, in dark, light and high contrast              | no horizontal scroll; every control in the Tab order; axe reports no violation                                          | TC-608          |
| QA-4 | activate "Copy problem report"                                                 | the clipboard holds W-14 with the running version; one polite "Copied"; no field asks for a name                        | no case; new    |
| QA-5 | run the tool's `--check` on a commit that adds a Supports row without evidence | exit 1, G-CLAIM                                                                                                         | TC-607 (D13-C6) |

## §H The board plan (pending; spec §0)

The boards of spec §0, on page `E47-D13 — Conformance statement`; frames named `<section>/<state> · <theme>`. Data: the dry run, declared on every board's face.

| Board | Frames                                                                        |
| ----- | ----------------------------------------------------------------------------- |
| 01    | `statement/anatomy · dark`, `statement/redlines · dark`                       |
| 02    | `statement/top · light`                                                       |
| 03    | `statement/stale · dark`, `statement/version-unknown · dark`                  |
| 04    | `limitations/table · hc`, `limitations/generic · hc`                          |
| 05    | `alternatives/keys · dark`                                                    |
| 06    | `criteria/table · dark`                                                       |
| 07    | `feedback/default · dark`, `feedback/copied · dark`, `feedback/failed · dark` |
| 08    | `entry/scr-117 · dark`, `entry/scr-119 · dark`                                |
| 09    | `reflow/200 · dark`, `reflow/320 · dark`                                      |
| 10    | `keyboard/tab-order · light`, `keyboard/reading-order · light`                |

## §I Summary for #1311

1. Text-first statement, report and register + hand-off + default-deny audit tool; the 10<!--=COUNT:boards--> boards of spec §0 are pending (pre-stage; BQ-0 … BQ-16 defaults built, ruling pending).
2. The report: 55<!--=COUNT:report.rows--> rows, four words, generated from the registers by blob; the dry run committed with its banner.
3. Supports only with every required artefact on every screen; missing evidence is said; reviewers lower, never raise.
4. The evidence contract: ten classes, their artefact kinds and producers, carried as rows to the stories.
5. One limitations register; 2<!--=COUNT:limits.blocked--> rows block sign-off at the base because their only owner is the audit.
6. The statement at `/accessibility`, a lazy, offline, versioned sub-view of SCR-119, read-only for every role; stale is flagged.
7. The audit's G-CITE checks that each cited line exists and is non-blank, not that it says what is claimed; cite content is a reviewer's check.
