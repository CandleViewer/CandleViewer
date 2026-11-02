# E15-D16 — Engineering hand-off pack for the layouts and workspaces band (US-LAY-001..008)

**Ticket:** E15-D16 (#370) · **Epic:** E15 · **Kind:** design hand-off pack, text only · **Status:** v1, the
**pre-stage** (PR 1 of 2, `Refs #370`, `Partial:`). The closing version v1.1 (PR 2) follows when the boards of
E15-D09, E15-D10, E15-D11 and E15-D13 have merged and the E15-D15 hold is lifted (§15). Every question of the
BQ list (#370, 6573343304) is ruled: **R370**, the orchestrator's ruling of 2026-11-02 10:01Z — Option 2,
BQ-02b, BQ-12, BQ-16b and BQ-19 overridden, every other row accepted with its rider. Cited below as
"R370 BQ-nn". The rows marked PROPOSED are still the owner's to accept. **Owner approval pending.**

**What this file is.** The single entry point for the engineers who build US-LAY-001..008 in Sprints 06–09:
for each story, the screens, the components, the spec sections, the boards and the acceptance-relevant states
(§2); the build order (§3); the test-id convention (§4); the catalogue reconciliation (§5); the Storybook list
(§6); the copy deck and its consistency diff (§7); the gated controls (§8); the accessibility contract (§9);
what must not regress (§10); the events (§11); the gaps (§13) and the design-QA preview (§16). It designs
nothing (T Out of scope): a question that needs design goes back to its owning ticket as a row here.

**Base.** `origin/main` 67fe8b5265 (2026-11-02; re-read from ecadc403e6, which differs only in `docs/plan/` 20, 21 and 24, none a cite key). Every `KEY`:line cite below is read there; the parents'
texts have not changed since the BQ list's base e5b286ed50. **In flight, pinned at their heads (`RULE`:79,
R6):** #5410 at 417ae42c8c, #5411 at 08e055c5f5, #5439 at 7b62ed4ec8 and #5447 at d77d02a176, each read
"if #N merges as is" and re-pinned to its merge commit at v1.1.

**Key.** `D02`..`D15` = `docs/design/E15/E15-Dnn.md`; `D03H`..`D13H` = the `-handoff.md` twins; `LF`, `MG`,
`RD`, `DSC` = the builder specs [`e15-layout-flows.md`](e15-layout-flows.md),
[`e15-multichart-grid.md`](e15-multichart-grid.md),
[`e15-responsive-and-degraded.md`](e15-responsive-and-degraded.md) and
[`e15-design-system-contributions.md`](e15-design-system-contributions.md); `02`, `03`, `05`, `11`, `12`, `14`,
`15`, `16`, `18` = the `docs/plan/` files with those numbers; `RULE` = `.claude/rules/32-design-specs.md` (the
G-T2 gates and R1–R7); `FER` = `.claude/rules/30-frontend-react.md`; `README` = `docs/design/README.md`; `CON`
= `CONSTITUTION.md`; `E15J` = `docs/plan/backlog/E15.json`; `CAL` = `docs/plan/backlog/_tools/calendar_cv.py`;
`DECK` = [`E15-D16-copy.json`](../E15/E15-D16-copy.json); `T` = the ticket text (#370).

**The check.** [`docs/design/_tools/e15_d16_handoff_check.py`](../_tools/e15_d16_handoff_check.py) (stdlib,
offline) runs four gates: G-LINK (every link and every `KEY`:line cite resolves — T test plan item 7), G-HASH
(every lifted block's hash), G-INDEX (every `18` §2.16 story, screen and component has its row here — T test
plan item 1) and G-DECK (every deck string verbatim on its source line; the concept groups — T test plan
item 4). Its test is `docs/design/_tools/test_e15_d16_handoff_check.py`.

## Acceptance-criteria trace (#370)

| Ticket item                                                                     | Where        | Status at v1                                                                                                                   |
| ------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| AC 1 — every story names its screens, components, spec pages, frames and states | §2           | done: eight story rows, each with a spec section (G-INDEX); four parents' boards "text only, boards PENDING" with a G-row each |
| AC 2 — an engineer builds CMP-082 PanelHeader from the pack alone               | §3.2, §14.2  | the dry run at READY, labelled (heuristic); every NOT FOUND answered here as a gap (R370 BQ-15)                                |
| AC 3 — a prop mismatch is resolved; the catalogue is corrected                  | §5           | PROPOSED A-rows; applied by E15-D13 PR 3 or by this pack's closing version, one `15` writer at a time (R370 BQ-09)             |
| AC 4 — copy is consistent across surfaces                                       | §7; DECK     | 13 concept groups diffed; each difference noted as deliberate or given one PROPOSED wording (G-DECK)                           |
| AC 5 — an open question is listed with an owner and a date; the story flagged   | §13          | the register: grade, owner lane, decision date before the consuming sprint, the story flagged                                  |
| Scope — handoff index                                                           | §2           | done                                                                                                                           |
| Scope — component build order                                                   | §3           | done; "agreed with the FE lead" = an orchestrator ruling plus a consumer comment on #403 (R370 BQ-07)                          |
| Scope — test-id convention                                                      | §4           | PROPOSED; QA's confirmation is G-12 (R370 BQ-08)                                                                               |
| Scope — state / prop reconciliation                                             | §5           | done; mismatches as A-rows (AC 3)                                                                                              |
| Scope — Storybook story list                                                    | §6           | done; the differences from #5411's stories are C-rows                                                                          |
| Scope — copy deck                                                               | §7; DECK     | 508<!--=COUNT:deck.entries--> strings from eleven sources                                                                      |
| Scope — known gaps and deferrals                                                | §13          | done                                                                                                                           |
| Scope — handoff session                                                         | §14          | no session claimed: a written protocol for the owner, the dry run, the Q&A log (R370 BQ-15; Deviation D-2)                     |
| Scope — design-QA criteria preview                                              | §16.1        | published unticked, each item with its evidence source (R370 BQ-16a)                                                           |
| T Security — the carried rules as build requirements                            | §10.1        | six rules, each with its source                                                                                                |
| T Accessibility — E15-D15's output as a build requirement                       | §9           | lifted by hash; the acceptance-blocking list per story (§9.4)                                                                  |
| T Performance — the budgets and the protective constraints                      | §10.2, §10.3 | each budget with its owner; the frame budget is C-14.2's (60 fps), the 55 fps row cited from `11` (R370 BQ-14)                 |
| T Observability — one event table, the required events flagged                  | §11          | done; `workspace.restore_completed{ms, paneCount, failedPanes}` lifted (R370 BQ-12)                                            |
| DoD — CDO sign-off; the session held; the cold build passed                     | §16.2        | substituted (Agent-delivery adaptations): the owner's approval; not ticked as human-run (R370 BQ-15)                           |

## R. Rulings applied (R370; the BQ list 6573343304)

| BQ                                                  | Ruling, as applied here                                                                                                                                                                                                                         |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 01                                                  | One pre-stage text PR (`Refs #370`, `Partial:`), then the closing v1.1 — closed only when the four boards PRs have merged and the D15 hold is lifted (§15)                                                                                      |
| 02b (OVERRIDE)                                      | **Option 2:** this pack, DECK and one small index / deck / link / hash check with its test; no 2,500-line audit tool and no ruled-pins file (C-4.9)                                                                                             |
| 03b                                                 | Undrawn parents are "text only, boards PENDING" with a G-row each (G-P1..G-P4); re-pinned at each boards PR's head "if #N merges as is" and re-cited at its merge (R6)                                                                          |
| 05                                                  | The three focus rows stay PROPOSED (§9.3); the exception on #369 is the orchestrator's to record, only after the owner has seen F-01 / F-02 / F-12; the hold stands until E15-D05's text carries them (`D15`:509); F-02 does not reopen D15-C-d |
| 06                                                  | One row per story; shared components by pointer into `15`, which owns them (C-16.5)                                                                                                                                                             |
| 07                                                  | The build order adds CMP-249..253 and keeps the ticket's relative order; "FE lead" = an orchestrator ruling plus a comment on #403                                                                                                              |
| 08                                                  | The test-id convention is PROPOSED, role and label first (`FER`:39); never "agreed with QA"                                                                                                                                                     |
| 09                                                  | A-rows applied by E15-D13 PR 3 or by the closing PR; PROPOSED; one `15` writer at a time                                                                                                                                                        |
| 11b                                                 | A-rows against closed parents go as consumer comments on the existing issues; this pack never edits a parent; no new issue                                                                                                                      |
| 12 (OVERRIDE)                                       | `workspace.restore_completed{ms, paneCount, failedPanes}` at interactive is lifted from D12 C-11 and `RD`:268, not PROPOSED; the ticket's two-property shape is a C-row; only the name and property drift pairs stay PROPOSED C-rows (§11)      |
| 13b                                                 | A PROPOSED T2 row per gated control found on SCR-049, SCR-150 and SCR-153, or "no gated control" after a read; a missing reason key is PROPOSED with its vocabulary owner (`RULE`:49–:56); RBAC stays presentation only (§8.2)                  |
| 15                                                  | No session; an agent dry run at READY labelled (heuristic) and the owner protocol; "cold-build passed" and "session held" are not ticked as human-run                                                                                           |
| 16b (OVERRIDE)                                      | No `14` pointer lines: T names no `14` edit (C-4.9); the pointers live in this pack (§2.3)                                                                                                                                                      |
| 18                                                  | Text only, no Penpot page and no PNG in PR 1, recorded as a **PROPOSED Deviation** (D-1): README's line says "no exceptions" (`README`:44); only the owner's C-10.1 approval waives it                                                          |
| 19 (OVERRIDE)                                       | `large-pr-approved` is asked in advance for PR 1, justified at open; PR 2 stays small; two PRs in total                                                                                                                                         |
| 02a, 03a, 04, 06, 10, 11a, 13a, 14, 16a, 17, 20, 21 | As proposed. Riders: BQ-14 cites `11` and names C-14.2 (60 fps) as the owner, never 55 fps as the Done line; BQ-16a an unticked checklist; BQ-20 the title and branch fit C-4.4; BQ-21 a lift of D15's own text                                 |

No `22` / `23` / `24` change and no new issue. The G-T2 statement appears once (§8.1) and every section that
shows a gated control cites it (`RULE`:57–:59, G-T2.5 / G-T2.6).

## 0. Status and evidence

**Nothing of the band is built on `main`.** In flight: E15-T02's first two slices, #5410 (`packages/dock`, the
layout tree and its pure operations, at 417ae42c8c) and #5411 (CMP-080 DockPanel, CMP-081 DockGrid, CMP-082
PanelHeader and CMP-083 SplitPane with their stories, at 08e055c5f5); E15-X01's STRIDE model, #5439 at
7b62ed4ec8; and the workspace route `/w/:workspaceId`, #5447 at d77d02a176 — each "if #N merges as is".

| Parent        | #   | State at the base | Cited at                                                                                   |
| ------------- | --- | ----------------- | ------------------------------------------------------------------------------------------ |
| E15-D02       | 248 | closed            | the wireframe spec, merged; `D02`:957 names it this pack's structural baseline             |
| E15-D03       | 319 | closed            | text #4478, boards #4915 / #4932                                                           |
| E15-D04       | 320 | closed            | text #4454, boards #4486; `D04`:458 names it this pack's baseline                          |
| E15-D05       | 321 | closed            | text #4507, boards #4533                                                                   |
| E15-D06       | 360 | closed            | text #4470, boards #4496                                                                   |
| E15-D07       | 361 | closed            | text #4502, boards #4640                                                                   |
| E15-D08       | 362 | closed            | text #4503, boards #4911                                                                   |
| E15-D09       | 363 | **open**          | text #4553 (tritan re-derive #4659); its boards PENDING (G-P1)                             |
| E15-D10       | 364 | **open**          | PR 1 #5094, PR 2 #5108; PR 3 (boards) PENDING (G-P2)                                       |
| E15-D11       | 365 | **open**          | PR 1 #5074, PR 2 #5098; PR 3 (boards) PENDING (G-P3)                                       |
| E15-D12       | 366 | closed            | #5071, #5088, boards #5390                                                                 |
| E15-D13       | 367 | **open**          | PR 1 #5055, PR 2 #5073, PR 2T #5075; PR 3 (boards) PENDING (G-P4)                          |
| E15-D14       | 368 | closed            | #5077, rows #5097                                                                          |
| E15-D15 input | 369 | closed            | #5034; **the hold F-01 / F-02 / F-12** (`D15`:509, :791); added to `blocked_by` in this PR |

**Readers.** E15-T02 (#403) and E15-S01 (#401), building now in Sprint 06; E15-S02 (#435), E15-T03 (#436) and
E15-X01 (#437) in Sprint 07; E15-S03 (#476) and E15-S04 (#477) in Sprint 08; E15-S05..S08 (#558..#561) and the
QA lane E15-Q01 (#434), E15-Q02 (#552) and E15-Q06 (#555) in Sprint 09; E15-D17 (#551) runs §16.1 at design QA.

## 1. Locked inputs, the source ladder and the lift table

### 1.1 Locked inputs (cited, never re-decided)

| Parent | What the pack takes as given                                                                               | Cite                                          |
| ------ | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| D02    | the layout tree, the hotkey map, the regions and order, the gated set and the state keys, the events       | `D02`:576, :610, :639, :679                   |
| D03    | the panel chrome and the tab strip at hi-fi, the region name (D-4, D-5), the copy deck, the security rules | `D03`:169–:170, :272, :630, :820              |
| D04    | the dock: zones, the pointer and keyboard storyboards, move mode, keys and announcements, the copy deck    | `D04`:139, :147, :171, :240, :311, :390       |
| D05    | the gallery, the apply, the rail switcher, keys and announcements, the copy deck                           | `D05`:344, :360, :362, :476                   |
| D06    | the sync groups and axes, the account axis, names and announcements, the copy deck                         | `D06`:212, :239, :351, :395                   |
| D07    | the picker and the panel menu, the copy deck, keys and announcements, security                             | `D07`:260, :381, :606, :698, :758             |
| D08    | SCR-025 and SCR-029, the copy deck, the A, C and G rows                                                    | `D08`:275, :696, :852                         |
| D09    | export and import, the preview and the report, untrusted strings, the copy deck, the G-rows                | `D09`:239, :489, :693, :895, :1028            |
| D10    | the floating window: the OS title, the window's keyboard and focus, the quoted strings, the C and G rows   | `D10`:121, :260, :300, :385                   |
| D11    | the multi-chart grid; normative text in `MG`                                                               | `D11`:184; `MG`:5                             |
| D12    | the responsive and reduced-capability rules; normative text in `RD`                                        | `D12`:123, :152; `RD`:5                       |
| D13    | the dock band's catalogue entries (CMP-249..252) and the eleven reconciled ones; Tables K, N, R, S         | `D13`:314; `D13H`:41, :66, :79, :93           |
| D14    | the motion inventory, the never-animates set, the budgets by owner                                         | `D14`:62, :122, :242                          |
| D15    | the keyboard model, the focus model, the naming rule, the script, the budget, the T2 table, the findings   | `D15`:177, :218, :279, :289, :355, :370, :507 |

### 1.2 The source ladder (one rung over the next; each departure a C-row) (R370 BQ-04)

1. **T** — the ticket text (#370; `E15J`, the E15-D16 entry).
2. **The plan rows** — `11` US-LAY-001..008 (`11`:2738–:2893), `14` SCR-011 / 020..029 / 049 / 150 / 153, `15`'s
   E15 entries, `18` §2.16 (`18`:298–:311).
3. **The contract** — `22` and `23` as served at the base; this pack changes neither.
4. **The normative source per concern:** structure — D02 and `LF`; values — D13 and `D13H` Table R; composition
   — the D03..D12 frames; names, focus and announcements — D15; motion — D14. Where a frame and a spec disagree
   the spec wins and the frame is corrected at its source, never annotated here.
5. **The parents' own rulings**, as each parent records them.

### 1.3 Lift, copy or cite (R370 BQ-04)

| Block                                             | Source         | Form                                             | Where here  |
| ------------------------------------------------- | -------------- | ------------------------------------------------ | ----------- |
| D15 §1.6 the review's own PROPOSED defaults       | `D15`:123      | lifted by hash 183ffdf94b8e<!--=HASH:d15.s1_6--> | §9.3        |
| D15 §3.1 the keyboard model (KB-01..KB-24)        | `D15`:177      | lifted by hash a4aae91f736a<!--=HASH:d15.s3_1--> | §9.1        |
| D15 §4 the focus model (FM-01..FM-29)             | `D15`:218      | lifted by hash be61da14514c<!--=HASH:d15.s4-->   | §9.1, §9.3  |
| D15 §5.2 the naming rule (R-5)                    | `D15`:279      | lifted by hash f575649b75db<!--=HASH:d15.s5_2--> | §9.1        |
| D15 §6.1 the script (SR-01..SR-50)                | `D15`:289      | lifted by hash 49775ed2b8b9<!--=HASH:d15.s6_1--> | §7, §9.1    |
| D15 §7 the announcement budget (BG-01..BG-08)     | `D15`:355      | lifted by hash 660f1b28072a<!--=HASH:d15.s7-->   | §9.1        |
| D15 §8.1 the T2 table (T2-01..T2-20)              | `D15`:370      | lifted by hash cb1593756d5d<!--=HASH:d15.s8_1--> | §8          |
| D15 §8.2 the safety disclosures (SD-01..SD-08)    | `D15`:399      | lifted by hash 8bb27888d586<!--=HASH:d15.s8_2--> | §10.1       |
| D15 §11 the findings (F-01..F-12)                 | `D15`:507      | lifted by hash 0cfcd381f9d1<!--=HASH:d15.s11-->  | §9.2–§9.4   |
| D14 §2 the motion inventory                       | `D14`:62       | lifted by hash 030fd6f57501<!--=HASH:d14.s2-->   | §9.5        |
| D14 §4 the never-animates set and the safety rule | `D14`:122      | lifted by hash 1ccd8d8656ea<!--=HASH:d14.s4-->   | §9.5, §10.3 |
| D13H Table K, keyboard of the four new entries    | `D13H`:41      | lifted by hash d97160893011<!--=HASH:d13h.k-->   | §3.2        |
| D13H Table N, names and roles                     | `D13H`:66      | lifted by hash 4656914e47b6<!--=HASH:d13h.n-->   | §3.2        |
| D13H Table S, Storybook lists and builders        | `D13H`:93      | lifted by hash f5dfdc16ffb2<!--=HASH:d13h.s-->   | §6          |
| the parents' copy tables and D15's script         | eleven sources | copied by the check, string by string            | DECK, §7    |
| everything else                                   | by section     | cited, never restated                            | —           |

A lifted block is pinned by its hash: when its parent changes, the hash moves, G-HASH fails and the pack is
re-issued under §15's rule rather than quietly out of date.

## 2. The index — every story to its screens, components, spec sections, boards and states (R370 BQ-06)

One row per US-LAY story in §2.1 (spec, boards and states) and one in §2.2 (every component `18` lists for it).
**Boards** name the parent's committed PNGs under `docs/design/E15/img/` (the Figma frames of T, in Penpot per
the Agent-delivery adaptations), or say **text only, boards PENDING** with the G-row that tracks them (§13).
**Built at the base** names what exists: nothing on `main`; in-flight PRs "if #N merges as is".

### 2.1 Stories, specs, boards and states

| Story      | Builds (sprint)                                                                        | Screens                                              | Spec sections (normative)                                                                                                                                 | Boards                                                                                                                               | Acceptance-relevant states                                                                                                                                                                                                                                                                                                          | Built at the base                                           |
| ---------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| US-LAY-001 | E15-T02 #403 (06); E15-S01 #401 (06); E15-S06 #559 (09); E15-K01 #371 the budget curve | SCR-020, SCR-021, SCR-022, SCR-049                   | D02 §4 the tree; D03 §3, §4 the chrome (`D03`:183, :272); D04 §3–§6 (`D04`:139, :147); D05 §9 the apply (`D05`:344); `MG` §3–§12; D15 FM-01..FM-14        | E15-D02 boards 02, 03, 04, 09, 10, 20; E15-D03 01–05, 08; E15-D04 01–06; E15-D05 01–05; **SCR-049 text only, boards PENDING (G-P3)** | populated; panel focused (the inset frame); splitter at its minimum; a refused zone; drop; the cost confirm with the measured frame cost (`11`:2749–:2751); preset apply (one summary); the dirty apply routed to SCR-029; grid arrangement, over budget, maximised; gated controls: T2-01, T2-02, T2-09, T2-10, T2-21 (§8.1; §8.2) | #5410, #5411 (CMP-080..083, the tree), if each merges as is |
| US-LAY-002 | E15-T01 #402 (06); E15-S03 #476 (08)                                                   | SCR-020, SCR-025, SCR-029, SCR-150                   | D03 §5 states (`D03`:440); D05 §10 the switch (`D05`:360); D08 §2–§6 (`D08`:275); D12 §8 and `RD` §9 restore (`D12`:123; `RD`:190); `LF` F-LAY-1, F-LAY-2 | E15-D02 boards 06, 08, 13, 17, 21; E15-D03 06, 07, 10; E15-D05 07, 08; E15-D08 01–10; E15-D12 07, 08, 10                             | dirty; restored, not saved; save failed; the 412 conflict queued; the unsaved dialog; delete workspace (typed confirm); the boot stages; partial restore; interactive ("Workspace ready"); gated controls: T2-01..T2-03, T2-06, T2-08, T2-22 (§8.1; §8.2)                                                                           | nothing                                                     |
| US-LAY-003 | E15-T03 #436 (07); E15-S04 #477 (08); E15-S06 #559 (09)                                | SCR-023, SCR-025, SCR-049                            | D06 §5–§10 (`D06`:212, :239, :351); `MG` §9 sync and rebinding (`MG`:75); D15 SR-30..SR-38                                                                | E15-D06 boards 01–10; E15-D02 14, 15; **SCR-049 text only, boards PENDING (G-P3)**                                                   | joined; left; an interval conflict; the account axis absent and the environment span refused; the popover and the 200 % modal; provenance "set by sync group A"                                                                                                                                                                     | nothing                                                     |
| US-LAY-004 | E15-S05 #558 (09); E15-T03 #436 (07)                                                   | SCR-023, SCR-043                                     | D06 §6, §7 the scale link (`D06`:239; `D06`:366); D15 SR-39..SR-41, T2-13                                                                                 | E15-D06 boards 05, 06; E15-D02 15                                                                                                    | linked; independent; the refusal (`alertdialog`, assertive); percent accepted; no group (T2-13)                                                                                                                                                                                                                                     | nothing                                                     |
| US-LAY-005 | E15-S02 #435 (07); E15-T02 #403 (06)                                                   | SCR-010, SCR-020, SCR-021, SCR-024, SCR-027, SCR-028 | D04 §4–§10 (`D04`:147, :240); D07 §4–§12 (`D07`:260, :381, :698); D10 §2–§7 (`D10`:121, :300); D15 FM-01..FM-13, FM-26                                    | E15-D04 boards 01–10; E15-D07 01–10; E15-D02 09, 10, 11, 16, 19; E15-D03 03; **SCR-027 text only, boards PENDING (G-P2)**            | move mode stages one and two; refused; cancelled; the Undo toast; maximise, minimise, the tray; pop out and return; the compact view and its disarm; picker T2 entries; menu variants                                                                                                                                               | #5411 (CMP-080, CMP-083), if it merges as is                |
| US-LAY-006 | E15-S01 #401 (06)                                                                      | SCR-011, SCR-022                                     | D02 §7 the hotkey map (`D02`:576); D05 §9–§11 (`D05`:344, :362); D15 KB-01..KB-03, F-03                                                                   | E15-D05 boards 01–10; E15-D02 08, 12, 23                                                                                             | a hotkey assigned; a key taken (409); a cross-context conflict (F-03); the rail switch; rename; Delete layout (F-01); gated controls: T2-01, T2-06, T2-07 (§8.1; §8.2)                                                                                                                                                              | nothing                                                     |
| US-LAY-007 | E15-S07 #560 (09); E15-X01 #437 (07)                                                   | SCR-026, SCR-089                                     | D09 §2–§7 (`D09`:239, :489, :693); `LF` F-LAY-6 (`LF`:139); D15 FM-22, FM-23, SR-25, SR-26                                                                | **text only, boards PENDING (G-P1)**; E15-D02 board 18                                                                               | export: preparing, preview, done, over the limit; import: pick, preview (dropped, remapped), the refusals, the report, a name clash; gated controls: T2-04, T2-05 (§8.1; §8.2)                                                                                                                                                      | nothing                                                     |
| US-LAY-008 | E15-S08 #561 (09); E15-K01 #371                                                        | SCR-021, SCR-153                                     | `RD` §2–§8 and §10 (`RD`:9, :46, :123, :204); D12 §8, §11 (`D12`:123, :162); D15 SR-45, SR-46                                                             | E15-D12 boards 01–06, 09; E15-D02 22                                                                                                 | the narrow collapse to tabs; an armed panel hidden and disarmed; the suggestion row; reduced active; full by choice; the manual controls; the never-shed list                                                                                                                                                                       | nothing                                                     |

**Owned elsewhere, by pointer.** SCR-010 the app shell (`14`:276, E10's), SCR-043 the price-scale menus
(`14`:1071, E11's; E15 adds only its link item, D06) and SCR-089 rule import / export (`14`:2081, E26's; US-LAY-007
shares its file-import pattern only). Their components are the shared rows of §2.2.

### 2.2 Components per story (every `18` §2.16 component; E15-owned in §3.2, shared by pointer to `15`)

| Story      | E15-owned (full entry in §3.2)                                                                                                    | Shared (the `15` entry owns it; C-16.5)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| US-LAY-001 | CMP-073, CMP-080, CMP-081, CMP-082, CMP-083, CMP-214, CMP-215, CMP-216, CMP-217, CMP-218; plus CMP-249, CMP-251, CMP-252, CMP-253 | CMP-001 Button (`15`:48); CMP-043 Dialog (`15`:505); CMP-050 Card (`15`:594); CMP-196 MultiChartLinker (`15`:2560)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| US-LAY-002 | CMP-073, CMP-080, CMP-081, CMP-082, CMP-217, CMP-218; plus CMP-252                                                                | CMP-001 Button (`15`:48); CMP-004 Toggle (`15`:82); CMP-014 Spinner (`15`:186); CMP-015 Skeleton (`15`:195); CMP-027 ErrorState (`15`:323); CMP-038 InlineSpinnerText (`15`:443); CMP-040 FormField (`15`:470); CMP-043 Dialog (`15`:505); CMP-044 ConfirmDialog (`15`:516); CMP-065 FormSection (`15`:739); CMP-207 BuildFooter (`15`:2706)                                                                                                                                                                                                                                                                                                        |
| US-LAY-003 | CMP-080, CMP-081, CMP-217, CMP-218; plus CMP-253                                                                                  | CMP-001 Button (`15`:48); CMP-004 Toggle (`15`:82); CMP-011 Tag / Chip (`15`:153); CMP-040 FormField (`15`:470); CMP-043 Dialog (`15`:505); CMP-065 FormSection (`15`:739); CMP-196 MultiChartLinker (`15`:2560)                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| US-LAY-004 | CMP-218                                                                                                                           | CMP-004 Toggle (`15`:82); CMP-011 Tag / Chip (`15`:153); CMP-040 FormField (`15`:470); CMP-041 Menu (`15`:482); CMP-043 Dialog (`15`:505); CMP-188 PriceAxis (`15`:2423); CMP-189 TimeAxis (`15`:2436)                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| US-LAY-005 | CMP-073, CMP-080, CMP-081, CMP-082, CMP-083, CMP-213, CMP-214, CMP-215, CMP-216, CMP-217, CMP-218; plus CMP-249, CMP-250, CMP-251 | CMP-041 Menu (`15`:482); CMP-043 Dialog (`15`:505); CMP-048 Combobox (`15`:565); CMP-050 Card (`15`:594); CMP-061 UserMenu (`15`:699); CMP-070 AppShell (`15`:793); CMP-071 NavRail (`15`:803); CMP-072 TopBar (`15`:813); CMP-075 EnvBadgeLocal (`15`:843); CMP-076 ConnectionStatus (`15`:853); CMP-084 GlobalSearchTrigger (`15`:949); CMP-085 SkipLink (`15`:958); CMP-105 AccountMultiSelect (`15`:1194); CMP-208 StatusBar (`15`:2719); CMP-209 RightRail (`15`:2730); CMP-210 HealthChips (`15`:2741); CMP-211 PanicButtons (`15`:2751); CMP-212 ToastHost (`15`:2764); CMP-219 SymbolPicker (`15`:2839); CMP-220 IntervalPicker (`15`:2851) |
| US-LAY-006 | CMP-073, CMP-217                                                                                                                  | CMP-001 Button (`15`:48); CMP-016 Tooltip (`15`:206); CMP-019 Icon (`15`:238); CMP-022 Kbd (`15`:269); CMP-043 Dialog (`15`:505); CMP-050 Card (`15`:594); CMP-071 NavRail (`15`:803)                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| US-LAY-007 | none                                                                                                                              | CMP-001 Button (`15`:48); CMP-027 ErrorState (`15`:323); CMP-033 CopyButton (`15`:390); CMP-043 Dialog (`15`:505); CMP-044 ConfirmDialog (`15`:516); CMP-067 FileDrop (`15`:759); CMP-068 CopyableCodeBlock (`15`:769); CMP-234 ValidationPanel (`15`:3019)                                                                                                                                                                                                                                                                                                                                                                                         |
| US-LAY-008 | CMP-083, CMP-214, CMP-215, CMP-216; plus CMP-251 (the collapsed group)                                                            | CMP-028 Callout / Banner (`15`:334); CMP-069 InfoPanel (`15`:778); CMP-092 DegradedModeBanner (`15`:1028); CMP-227 EstimatedBadge (`15`:2931)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

**Gated controls on every row (G-T2.6):** CMP-079 RbacGate (`15`:890) and CMP-019 Icon `lock` (`15`:238) join
the component list of every story whose surfaces show a T2 control — US-LAY-001, 002, 004, 005, 006 and 007 —
and of US-LAY-001 / 003 through SCR-049's maximised cell (§8.2). The statement is §8.1's.

### 2.3 The screens and their entry points (the `14` pointers live here, R370 BQ-16b)

| Screen                       | `14` entry | Normative source here          | Stories                |
| ---------------------------- | ---------- | ------------------------------ | ---------------------- |
| SCR-011 rail and switcher    | `14`:314   | D05 §10–§11; §9 (FM-15, SR-14) | US-LAY-002, US-LAY-006 |
| SCR-020 workspace page       | `14`:508   | D03; D02 §4                    | US-LAY-001, 002, 005   |
| SCR-021 dock                 | `14`:543   | D04; D15 §4                    | US-LAY-001, 005, 008   |
| SCR-022 preset gallery       | `14`:568   | D05 §2–§9                      | US-LAY-001, US-LAY-006 |
| SCR-023 sync configuration   | `14`:593   | D06                            | US-LAY-003, US-LAY-004 |
| SCR-024 panel picker         | `14`:621   | D07 §4                         | US-LAY-005             |
| SCR-025 workspace settings   | `14`:636   | D08 §2–§5                      | US-LAY-002, US-LAY-003 |
| SCR-026 import (and Export…) | `14`:652   | D09                            | US-LAY-007             |
| SCR-027 floating window      | `14`:666   | D10 (boards PENDING, G-P2)     | US-LAY-005             |
| SCR-028 panel context menu   | `14`:680   | D07 §5                         | US-LAY-005             |
| SCR-029 unsaved / conflict   | `14`:693   | D08 §4–§6                      | US-LAY-002             |
| SCR-049 multi-chart grid     | `14`:1165  | `MG` (boards PENDING, G-P3)    | US-LAY-001, US-LAY-003 |
| SCR-150 boot and restore     | `14`:3055  | `RD` §9; D12 §8                | US-LAY-002             |
| SCR-153 degraded mode        | `14`:3110  | `RD` §6–§8                     | US-LAY-008             |

## 3. The component build order (R370 BQ-07)

### 3.1 The order (the ticket's relative order kept; CMP-249..253 added; in-flight steps reported, never reordered)

| Step | Components                                                    | Depends on                                                    | Builder (sprint)                            | At the base                           |
| ---- | ------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------- | ------------------------------------- |
| 1    | CMP-080 DockPanel, CMP-082 PanelHeader                        | the tokens (`DSC` §3); CMP-075, CMP-229 in the header         | E15-T02 #403 (06); the badge E15-S04        | in #5411, if it merges as is          |
| 2    | CMP-081 DockGrid                                              | step 1; `packages/dock`'s tree (#5410)                        | E15-T02 #403 (06)                           | in #5411, if it merges as is          |
| 3    | CMP-083 SplitPane, CMP-214 DockDropZone                       | step 2 (the gutters and the zones read the tree's rectangles) | E15-T02 #403 (06); E15-S02 the chooser      | CMP-083 in #5411; CMP-214 not started |
| 4    | CMP-251 DockTabGroup                                          | steps 2–3 (the centre drop makes a tab group)                 | E15-S02 #435 (07)                           | not started                           |
| 5    | CMP-249 MoveModeBar, CMP-250 MinimisedPanelTray               | step 3 (the chooser's targets), step 4                        | E15-S02 #435 (07)                           | not started                           |
| 6    | CMP-216 PanelMenu, CMP-217 LayoutPresetMenu, CMP-218 SyncMenu | steps 1–5 (the menu's Move panel enters step 5's mode)        | E15-S02 (216); E15-S01 (217); E15-S04 (218) | not started                           |
| 7    | CMP-215 FloatingWindowFrame                                   | steps 1, 6 (the window's ⋮ is CMP-216's)                      | E15-S02 #435 (07); D10 holds the rest       | not started; boards PENDING (G-P2)    |
| 8    | CMP-252 WorkspaceTabStrip, then CMP-073 WorkspaceSwitcher     | step 1; CMP-252's overflow opens CMP-073                      | E15-S03 #476 (08)                           | not started                           |
| 9    | CMP-213 FuzzyList in the picker                               | step 6 (the picker's Place options read the dock's outcomes)  | E15-S02 #435 (07)                           | not started                           |
| 10   | CMP-253 MultiChartGrid                                        | steps 1–3, 6 (CMP-217 `cell` mode); E15-T03's sync            | E15-S06 #559 (09)                           | not started; boards PENDING (G-P3)    |

E15-S01 (#401) builds CMP-217 in Sprint 06 against step 2 while E15-S02 builds steps 4–6 in Sprint 07: the
order is the dependency order, not a sprint order. "Agreed with the FE lead" (T DoD) is this table under R370
BQ-07 plus a consumer comment on #403 at merge.

### 3.2 The E15-owned entries — role, keyboard model and axe expectations (T Accessibility)

Each entry's contract is its `15` text (C-16.5); the role and keys below are the lifted tables' (`D13H` Tables
K and N, hash in §1.3; D15 §3.1 and §5.1); the axe expectation is the same for every entry: **zero serious or
critical violations** in every story of §6 in dark and light (`FER`:39), plus the named check.

| Entry                       | `15`      | Role                                                      | Keyboard model                                                              | Axe and the named check                                                                                             |
| --------------------------- | --------- | --------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| CMP-073 WorkspaceSwitcher   | `15`:824  | `tree` on the rail; the combobox search (CMP-048)         | D15 KB-17 (no chord), KB-23; FM-15, FM-24, FM-25                            | `aria-current` on the open row; the dirty and restored markers in words                                             |
| CMP-080 DockPanel           | `15`:901  | `region`, named by R-5 (§9.1)                             | D15 KB-05, KB-06, KB-11 (PROPOSED); the panel is a focus target, not a stop | the region's name carries the environment word on `chart`, `dom`, `positions` (A-01)                                |
| CMP-081 DockGrid            | `15`:913  | the layout; RG-10, the one polite region                  | D15 KB-07 (PROPOSED), the ring (`D15`:277)                                  | DOM order equals reading order after every move (A-03)                                                              |
| CMP-082 PanelHeader         | `15`:925  | heading (`h2`; `h3` in a tab group) + `toolbar`           | D15 KB-22; the handle a button "Move {Kind}"                                | every control and the handle ≥ 24 px; the name never changes with width                                             |
| CMP-083 SplitPane           | `15`:937  | `separator`                                               | D15 KB-14: arrows 2 %, `Shift` 10 %, `Home`, `End`                          | `aria-valuenow`, `aria-valuemin`, `aria-valuemax`; the 24 px band                                                   |
| CMP-213 FuzzyList           | `15`:2775 | `listbox` half of the combobox                            | D15 KB-23; FM-13                                                            | T2 options `aria-disabled`, arrow-reachable; the count throttled (SR-44); T2 options per §8.1 (T2-11, T2-12, T2-14) |
| CMP-214 DockDropZone        | `15`:2786 | overlay (no role); the chooser is CMP-249's               | D15 KB-13 (the two stages)                                                  | no zone takes `aria-disabled` (T2-20); the refusal is a sentence, once                                              |
| CMP-215 FloatingWindowFrame | `15`:2798 | an independent document                                   | D10 §7 (`D10`:300); FM-06, FM-07                                            | the environment word in every window title (SD-02; D10 C-t)                                                         |
| CMP-216 PanelMenu           | `15`:2809 | `menu` on CMP-041, named "Panel options, {region name}"   | D15 KB-10 (PROPOSED), KB-23; FM-26                                          | the first item neither T2 nor sentence-form takes focus; T2 items per §8.1 (T2-09, T2-10)                           |
| CMP-217 LayoutPresetMenu    | `15`:2819 | `menu`; the gallery's `listbox`                           | D15 KB-01, KB-02, KB-03, KB-23; FM-14, FM-16                                | each preset named in words ("Two by two, four panels"); T2 per §8.1 (T2-01..T2-03)                                  |
| CMP-218 SyncMenu            | `15`:2829 | the popover (CMP-017) or the 200 % modal (CMP-043)        | D15 KB-08, KB-09 (PROPOSED, pending H-3), KB-22; FM-27                      | each axis a labelled `switch`; a group's colour never without its letter                                            |
| CMP-249 MoveModeBar         | `15`:3129 | `status`, `aria-atomic="false"`                           | `D13H` Table K rows CMP-249; D15 KB-13                                      | F-05: the bar's own line is spoken (§9.2)                                                                           |
| CMP-250 MinimisedPanelTray  | `15`:3144 | `toolbar` "Minimised panels"                              | `D13H` Table K rows CMP-250                                                 | each tab named by its panel's region name, with the environment word                                                |
| CMP-251 DockTabGroup        | `15`:3159 | `tablist`, automatic activation                           | `D13H` Table K rows CMP-251                                                 | each tab `aria-controls` its panel's `region`; no `tabpanel` added                                                  |
| CMP-252 WorkspaceTabStrip   | `15`:3174 | `tablist` "Workspaces", manual activation                 | `D13H` Table K rows CMP-252; KB-20 (`F2`, PROPOSED), KB-21                  | the dirty and restored states in the tab's name; T2 writes `aria-disabled`; T2 per §8.1 (T2-01..T2-08)              |
| CMP-253 MultiChartGrid      | `15`:3189 | `region` "Chart grid, 2 by 2, Live"; each cell a `region` | D15 KB-15 (PROPOSED); `MG` §6                                               | one `Tab` stop, roving cells; the maximised cell's arm control T2 (§8.2); the arm control T2-21 per §8.1            |

## 4. The test-id convention — PROPOSED (R370 BQ-08)

**Status.** PROPOSED under R370 BQ-08 for the E2E suite (Playwright, web and Electron). The QA lane's
confirmation is G-12 (E15-Q01 #434, due before Sprint 07); this pack never calls it "agreed with QA". It is
compatible with what is in flight: #5411's tests query by role and name only (`packages/ui/test/Dock.test.tsx`
at 08e055c5f5) and its components carry `data-cmp`.

1. **The accessible role and name come first** (`FER`:39). E15's names are fixed by rule — the panel region's
   R-5 name, the menu's "Panel options, {region name}", "Workspaces", "Minimised panels", "Close Scalping" — so
   a test asserts the layout tree, the focus order and the announcement text through them (T Technical notes).
2. **`data-cmp="CMP-nnn"`** stays on every E15 component root (the `packages/ui` practice) and is never a
   selector for behaviour, only for "which component rendered".
3. **`data-testid`** is used only where no stable name exists, in the form `e15-<surface>-<part>[-<key>]`,
   lower-case, ASCII, hyphenated, with no user text, symbol, account or id that names data in it:

   | Where (T Scope)           | Required id                                                                                                        | Example                      |
   | ------------------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------- |
   | every panel host          | `e15-dock-panel-<slot>` — `<slot>` the reading-order index, from 1                                                 | `e15-dock-panel-3`           |
   | every drop zone and side  | `e15-dock-zone-<slot>-<side>` — `left`, `right`, `top`, `bottom`, `centre`                                         | `e15-dock-zone-2-left`       |
   | every dialog action       | `e15-<dialog>-action-<verb>` — `gallery`, `settings`, `unsaved`, `conflict`, `import`, `export`, `saveas`, `newws` | `e15-unsaved-action-discard` |
   | every sync-axis switch    | `e15-sync-axis-<axis>` — `symbol`, `crosshair`, `interval`, `timerange`, `drawings`                                | `e15-sync-axis-interval`     |
   | the minimised tray's tabs | `e15-tray-tab-<slot>`                                                                                              | `e15-tray-tab-1`             |
   | a grid cell (SCR-049)     | `e15-grid-cell-<n>` — the cell number, from 1                                                                      | `e15-grid-cell-4`            |

4. **Forbidden inside the WebGL canvas.** No `data-testid` or other selector is placed on anything the engine
   draws; a chart assertion reads the existing diagnostics probe (`chart-diagnostics-json`, `apps/web/e2e`),
   never a pixel or a canvas child.
5. **Never on the slot after a move by position alone.** A move rebuilds the DOM order (`D15`:277), so a
   test that needs one panel through a move selects it by its region name; the slot ids are for layouts the
   test itself just built.

## 5. The state and prop reconciliation (AC 3; R370 BQ-09)

Each E15 entry's `15` props and states against what the merged designs require. A mismatch becomes a
copy-ready **A-row, PROPOSED**: E15-D13's PR 3 (#367, open) applies it if it opens first, otherwise this
pack's closing version applies it to `15` by these rows alone — one `15` writer at a time; nothing is reduced
silently. The three rows E15-D15 routed to `15` (`D15`:581–:583, A-3..A-5) were applied by #5073 and stand at
the base; G-04 (no `15` entry for the three new dock components, `D15`:564) was closed by the same PR.

### 5.1 The table

| Entry   | `15` props and states against the designs                                                                                                                                                           | Result                                               |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| CMP-073 | `workspaces[]` carries `dirty` but no `restored`, while the rail marks a restored workspace (`D05`:514) and CMP-252 has `restored`                                                                  | **A-01**                                             |
| CMP-080 | `title` is "kind, symbol and the spelled interval" and the A11y line binds `aria-label={title}`, while the same line says an order-capable panel's name ends with the environment word (R-5; SD-01) | **A-02** (a safety disclosure; also CR-01 for #5411) |
| CMP-080 | `state?` has no value for the dock-side placeholder a popped-out panel leaves (FM-06; `D04`:229; `D10`:281)                                                                                         | **A-03**                                             |
| CMP-080 | the description's qualifiers (R-5 item 2: sync group and axes, environment for non-order kinds, conflict, provenance, "Reduced") have no slot                                                       | **A-04**                                             |
| CMP-081 | the A11y line keeps the `aria-owns` fallback that D15 §5.1 rules out (`D15`:277; `D02`:611)                                                                                                         | **A-05**                                             |
| CMP-082 | props express every designed state (sync badge, provenance, arm, status words, the collapse order)                                                                                                  | none                                                 |
| CMP-083 | `minSizes?`, `label`, the 24 px band, "Minimum size." once per stop                                                                                                                                 | none                                                 |
| CMP-213 | T2 and sentence-form options, chips, empty state                                                                                                                                                    | none                                                 |
| CMP-214 | the two-stage chooser (A-5 applied), `reason`, `withdrawn`                                                                                                                                          | none                                                 |
| CMP-215 | `environment: "demo"\|"live"` has no testnet                                                                                                                                                        | none here: E15-D10 G-3 owns it (`D10`:453)           |
| CMP-216 | `regionName`, `undoAvailable`, `footnote`, `foldedActions`                                                                                                                                          | none                                                 |
| CMP-217 | `mode: "layout" \| "cell"` and the cell arrangements (E15-D11)                                                                                                                                      | none                                                 |
| CMP-218 | `account: "unavailable"`, `scaleLink`, `conflicts`, `variant`                                                                                                                                       | none                                                 |
| CMP-249 | the speech is the bar's own line, "PROPOSED, its owner E15-D04's follow-up" (`15`:3135), pending this pack's lift (`D13`:326 OQ-1)                                                                  | **A-06** (the lift; §9.2)                            |
| CMP-250 | `panels[]` with `environment?`                                                                                                                                                                      | none                                                 |
| CMP-251 | `collapsed?`, `overflow?`, conditions (E15-D12 added)                                                                                                                                               | none                                                 |
| CMP-252 | `dirty`, `restored`, `canSave` + `saveReason?`, `renameError?`                                                                                                                                      | none                                                 |
| CMP-253 | E15-D11's own entry, ruled                                                                                                                                                                          | none                                                 |

### 5.2 The A-rows (PROPOSED; copy-ready; "Old" is the `15` text at the base)

| Id   | Where                          | Old                                                                             | New                                                                                                                                                                                                            | Route                                   |
| ---- | ------------------------------ | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| A-01 | `15`:827 CMP-073 Props         | "`workspaces: {id, name, isDefault, isOpen, dirty, sortOrder}[]`"               | "`workspaces: {id, name, isDefault, isOpen, dirty, restored, sortOrder}[]`" (the rail's "Restored" marker, `D05`:514)                                                                                          | E15-D13 PR 3; builder E15-S03 #476      |
| A-02 | `15`:905 CMP-080 A11y          | "`role=\"region\"` `aria-label={title}`"                                        | "`role=\"region\"` named by E15-D15 R-5: `{title}`, then `, {Environment}` (\"Live\" or \"Demo\") when `kind` is `chart`, `dom` or `positions` — \"Chart, BTCUSDT 1 minute, Live\""                            | E15-D13 PR 3; builder E15-T02 #403      |
| A-03 | `15`:904 CMP-080 Props         | "`state?: \"loading\" \| \"compact\" \| \"error\" \| \"maximised\"`"            | "`state?: \"loading\" \| \"compact\" \| \"error\" \| \"maximised\" \| \"popped-out\"` (the dock-side placeholder a Pop out leaves, E15-D04 §7; E15-D15 FM-06)"                                                 | E15-D13 PR 3; builder E15-S02 #435      |
| A-04 | `15`:905 CMP-080 A11y (append) | —                                                                               | "the region's description (`aria-describedby`) carries the state qualifiers in E15-D15 R-5's order: sync group and axes, environment (non-order kinds), conflict, provenance, \"Reduced\"; never a live value" | E15-D13 PR 3; builders E15-T02, E15-S04 |
| A-05 | `15`:917 CMP-081 A11y          | "re-computed and exposed via `aria-owns` if DOM order can't match visual order" | "the DOM order is rebuilt to the visual order after every mutation by moving the per-pane hosts, never remounting them; no `aria-owns` path (E15-D15 §5.1)"                                                    | E15-D13 PR 3; builder E15-T02 #403      |
| A-06 | `15`:3135 CMP-249 A11y         | "PROPOSED, its owner E15-D04's follow-up"                                       | "lifted by E15-D16 §9.2 (E15-D15 F-05; E15-D13 OQ-1)"                                                                                                                                                          | E15-D13 PR 3 or this pack's v1.1        |

The `15` line numbers are the base's; whichever PR applies a row re-reads its Old text first. A-02 is a
safety disclosure (SD-01, C-2.11 "separate UI chrome"), so the builder applies it from the pack before the
catalogue edit lands; it is on E15-T02's acceptance-blocking list (§9.4).

### 5.3 C-rows on in-flight code (consumer comments on #403; R6)

| Id    | In flight (if #5411 merges as is, 08e055c5f5)                                                                                   | Reading taken                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| CR-01 | `DockPanel` has no `environment` prop and its test names the region "Chart BTCUSDT 1 minute" (`packages/ui/test/Dock.test.tsx`) | R-5's form, "Chart, BTCUSDT 1 minute, Live" (A-02); the fixture's commas and environment word |
| CR-02 | the header's toolbar is named "{kind} actions" ("Chart actions")                                                                | RG-08 names it by the panel's name (`D15`:269); the builder confirms with E15-D13's Table N   |
| CR-03 | the stories differ from `15`'s lists (§6.2)                                                                                     | `15` owns the lists; the missing stories land with their builders                             |
| CR-04 | `DockGridView` and `SplitPane` are in `packages/ui` while `packages/dock` (#5410) holds the tree                                | consistent with step 1–3 of §3.1; nothing to change                                           |

## 6. The Storybook story list (R370 BQ-10)

### 6.1 The consolidated list (`15` owns each list; every story in dark / light × compact / comfortable)

| Entry   | Title (`Organisms/Dock/*` unless named) | Stories (`15`)                                                                                                                                                                                                                                                                    | Builder                                         | `15`      |
| ------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | --------- |
| CMP-073 | its own tree                            | Default, Empty(first-run), ManyWorkspaces, Dirty, ViewAs, FromTabOverflow                                                                                                                                                                                                         | E15-S03 #476                                    | `15`:830  |
| CMP-080 | DockPanel                               | Default, Focused, FocusSameBox, Loading, CompactView, Error, Maximised, ReadOnlyNotice, Closable, Resizing(keyboard demo)                                                                                                                                                         | E15-T02 #403                                    | `15`:907  |
| CMP-081 | DockGrid                                | OnePane, TwoByTwo, OnePlusThree, CustomDrag, NAryRow, TabsetLeaf, FourPanelsCompact1280                                                                                                                                                                                           | E15-T02 #403                                    | `15`:919  |
| CMP-082 | PanelHeader                             | Default, WithActions, WithSyncBadge, NoSync, NarrowHeader, CollapseSteps, ConflictGlyph, Focused, OrderPanelLive                                                                                                                                                                  | E15-S02 #435; E15-S04 badge                     | `15`:931  |
| CMP-083 | SplitPane                               | Horizontal, Vertical, Focused, AtMinimum, Dragging, NAry, InPanel                                                                                                                                                                                                                 | E15-T02 #403                                    | `15`:943  |
| CMP-213 | `Molecules/*`                           | Default, Grouped, WithChips, DisabledWithReason, SearchActive, CategoryFiltered, NoResults, Skeleton, LongList                                                                                                                                                                    | E15-S02 #435; T2 per §8.1 (T2-11, T2-12, T2-14) | `15`:2781 |
| CMP-214 | DockDropZone                            | EdgeZones, CentreTabify, ActiveZone, InvalidZone, ReducedSet, KeyboardChooser, LargeOverSmall                                                                                                                                                                                     | E15-T02 geometry; E15-S02                       | `15`:2792 |
| CMP-215 | FloatingWindowFrame                     | Demo, Live, Unfocused, AlwaysOnTop, PinInOverflow, Unconfirmed, ViewAs, NarrowStep1..NarrowStep4, DisplayGone                                                                                                                                                                     | E15-S02 #435                                    | `15`:2804 |
| CMP-216 | PanelMenu                               | Default, WithSyncGroup, ViewerRestricted, BrowserBuild, NoSettings, UndoAvailable, CollapsedOwnActions, LimitT2, ResetConfirm, EdgeFlip, Clamped                                                                                                                                  | E15-S02 #435; T2 per §8.1 (T2-09, T2-10)        | `15`:2815 |
| CMP-217 | `Organisms/*`                           | Default, ActiveLayout, WithSavedLayouts, Overflow, SavesGated, CellMode, CellModeShrinkConfirm                                                                                                                                                                                    | E15-S01 #401; T2 per §8.1 (T2-01..T2-03)        | `15`:2825 |
| CMP-218 | `Molecules/*`                           | Unsynced, GroupA, AllAxesOn, PartialAxes, Conflict, ScaleLinkRefused, Modal200, GridNewCells                                                                                                                                                                                      | E15-S04 #477                                    | `15`:2835 |
| CMP-249 | MoveModeBar                             | StageOne, StageTwo, Refused, TwoLines200, Leaving                                                                                                                                                                                                                                 | E15-S02 #435                                    | `15`:3137 |
| CMP-250 | MinimisedPanelTray                      | OnePanel, ThreePanels, OrderPanelLive, FocusedTab                                                                                                                                                                                                                                 | E15-S02 #435                                    | `15`:3152 |
| CMP-251 | DockTabGroup                            | TwoTabs, FiveTabs, FocusedTab, DraggingTab, LongLabel, Collapsed1100, CollapsedOverflow1024, PendingConditions, HiddenArmedDisarmed                                                                                                                                               | E15-S02 #435; E15-S08 #561                      | `15`:3167 |
| CMP-252 | WorkspaceTabStrip                       | Default, Dirty, Restored, LongName, Overflow, RenameInPlace, RenameError, CloseOnFocus, SavesGated                                                                                                                                                                                | E15-S03 #476; T2 per §8.1 (T2-01..T2-08)        | `15`:3182 |
| CMP-253 | MultiChartGrid                          | OneByTwo, TwoByTwo, ThreeByThree, OnePlusThree, Custom, ActiveCell, NarrowSteps, Switcher, Zoom200, Maximised, EmptyCell, LoadingCell, UnavailableCell, DelistedCell, ShortHistory, BudgetConfirm, BudgetRunning, Reduced, TradingLocked, MaximisedArmed, Disarming, DisarmFailed | E15-S06 #559; T2-21 per §8.1                    | `15`:3197 |

The visual-regression baseline is complete on day one when every row is a committed story (T Scope). A
story list changes only in `15`, by its owner's A-row; this table re-reads `15` at v1.1.

### 6.2 Differences recorded (C-rows; nothing is dropped)

| Id    | Difference                                                                                                                       | Reading taken                                                                      |
| ----- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| CS-01 | `D13H` Table S lists CMP-251's five stories; `15`:3167 adds E15-D12's four                                                       | `15`'s nine (E15-D12's later ruled text); Table S is the earlier snapshot          |
| CS-02 | #5411 DockPanel: Default, Focused, Loading, CompactView, Error, Maximised, Closable — not FocusSameBox, ReadOnlyNotice, Resizing | `15`'s ten; the three land with E15-T02's later slices (CR-03)                     |
| CS-03 | #5411 DockGrid adds FocusedPanel and KeyboardResize and has not CustomDrag or FourPanelsCompact1280                              | the two missing stories land with E15-T02; the two extra are kept as the builder's |
| CS-04 | #5411 PanelHeader: Default, WithActions, InTabGroup, NarrowHeader                                                                | the rest are E15-S02's and E15-S04's (their builders, §6.1); InTabGroup kept       |
| CS-05 | #5411 SplitPane adds KeyboardResize and has not Focused, Dragging or InPanel                                                     | the three land with E15-T02; KeyboardResize kept                                   |

## 7. The copy deck and its consistency diff (AC 4; T test plan item 4)

### 7.1 The deck

DECK holds 508<!--=COUNT:deck.entries--> strings: every row of the parents' copy tables — E15-D03 §9 (45), E15-D04 §13
(26), E15-D05 §14 (52), E15-D06 §11 (30), E15-D07 §9 (27, and its §12.3 close line), E15-D08 §8 (109), E15-D09 §9
(83), E15-D10 §5.10 (27), `MG` §14 (32), `RD` §10 (26) — and E15-D15's script SR-01..SR-50 (50). Each key is
`<source>:<line> <the parent's row id>`; each value is the parent's String cell, verbatim. **The parent owns
every string; the deck adds none** (T Out of scope). G-DECK fails a string that no longer stands whole on its line (a quoted string with both
its quotes, a bare one as a whole table cell),
so a parent's edit re-issues the deck under §15. Translation, if ever needed, has this one source (T Scope).

**Rules every string keeps** (lifted, cited): the panel first, the location second (`D15`:283); no account,
balance or count outside the caller's scope (`D15`:115, R-6); a reason one sentence of at most 60 characters
naming no data (G-T2.4, `RULE`:49); a measurement with its window and its target, never a verdict about the
machine (`RD`:206); imported and saved strings are text, cleaned and capped (§10.1 rule 3); fixtures use the
parents' placeholder names (Scalping, Swing, alex) and never a real account.

### 7.2 The consistency diff (thirteen concept groups; `DECK` `concepts`)

| Group | Concept                          | Result                                                                                                                                                                                                                                                                                                                                                                                 | Disposition                                                                                                                                                                                                                                                              |
| ----- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CG-01 | unsaved changes                  | identical: "{name}, unsaved changes" (D03, D05, D08), "This workspace isn't saved." (D03, D05, D08, D09), "This layout isn't saved yet." (D03, D05), "You have unsaved layout changes." (D05, D08)                                                                                                                                                                                     | consistent                                                                                                                                                                                                                                                               |
| CG-02 | nothing to save                  | "No unsaved changes" (`D03`:643, no full stop) against "No unsaved changes." (`D03`:658; `D08`:718)                                                                                                                                                                                                                                                                                    | **AC-01 PROPOSED:** `ws.save.clean` takes the full stop, as a reason sentence does (G-T2.4's form); owner E15-D03 (closed) by a consumer comment on #319; builders E15-S01, E15-S03                                                                                      |
| CG-03 | discarding                       | "Discard changes" identical on the settings and the unsaved dialogs; "Discard changes loses them." against "Your unsaved changes are lost." (revert)                                                                                                                                                                                                                                   | deliberate: the first names a button's consequence, the second the result of Revert to saved                                                                                                                                                                             |
| CG-04 | what cannot be taken back        | "It can't be restored." (`D05`:500, delete layout) against "It can't be undone." / "Deleting can't be undone." (`D08`:727, :751) and "can't be recovered" for a replaced version (`D08`:744, :745, :794, :796)                                                                                                                                                                         | **AC-02 PROPOSED:** delete layout reads "It can't be undone." as delete workspace does, so "restore" keeps only its restore senses (CG-13); "can't be recovered" stays for a version replaced — deliberate. Owner E15-D05 by a consumer comment on #321; builder E15-S01 |
| CG-05 | what a preset replaces           | "Applying a preset replaces the current layout. Settings of surviving panels are kept." (`D05`:486); "Applying {preset} replaces them." (`D05`:511; `D08`:766); "Then {preset} is applied." (`D08`:804)                                                                                                                                                                                | consistent: no surface says settings are reset (T Technical notes' example does not occur); the autosave line's "replaces the saved layout" (`D08`:723) is a different concept                                                                                           |
| CG-06 | what an import drops             | D09's report "Imported {clash}: {panels}, {layouts}, {dropped_items} dropped, {remapped} remapped." (`D09`:956) against SR-25 "Imported Scalping (2): 7 panels, 2 layouts, 2 items dropped." (`D15`:319, from the wireframe `D02`:520)                                                                                                                                                 | **AC-03 PROPOSED:** the build speaks D09's string (the import's hi-fi, later than the wireframe); SR-25's fixture is not a second string. Owner E15-D15 by a consumer comment on #369; builder E15-S07                                                                   |
| CG-07 | what reduced mode still supports | "Order entry and positions keep full speed." (`RD`:210, :214) against "Order entry and positions are unaffected." (`RD`:213 = SR-45) and the grid's "Every chart still shows its price, your orders and your positions." (`MG`:150)                                                                                                                                                    | deliberate: before (the suggestion: speed) and during (the reduced row: effect); the grid names its own sheds. E15-D11 confirms CP-28 against `RD`'s CP-4 at its PR 3 (G-07)                                                                                             |
| CG-08 | an automatic disarm              | "One-click trading disarmed: {Kind} too small to trade." (D03, D04, SR-34) and "…: {Kind} hidden in a tab." (`RD`:224) share one grammar; the grid's "One-click trading disarmed: chart returned to the grid." is `polite` (`MG`:138) and its "Chart trading is still armed on chart 3." (`MG`:152–:153) differs from `RD`'s "Couldn't disarm one-click trading on {Kind}." (`RD`:232) | **AC-04 PROPOSED:** the grid's CP-16 is assertive, once, with its reason (A30; SR-34's level, `D15`:328; BG-01) — a safety announcement. "Chart trading" against "one-click trading": G-08 to E15-D11 with E30's arm vocabulary                                          |
| CG-09 | close and undo                   | "{Kind} closed." + "Undo" (`D07`:633) and SR-10 "Tape closed." (`D15`:304) against D07's polite line "{Kind} closed. Undo is available." (`D07`:737)                                                                                                                                                                                                                                   | C-u (`D15`:552): one utterance, the toast's text; the build never speaks `D07`:737's line                                                                                                                                                                                |
| CG-10 | the interval in a name           | the region name spells it ("Chart, BTCUSDT 1 minute, Live", R-5; the grid "4 hours", `MG`:140) while the sync strings say "Chart 15m" (`D06`:412; SR-30, SR-31, SR-35, SR-37) and the picker "BTCUSDT 1m" (`D07`:619)                                                                                                                                                                  | visible compact labels keep "15m" (deliberate). Spoken strings: **G-10** (open; default PROPOSED: they spell the interval as the name does, HR-3 `(heuristic)`), owner E15-S04 with E15-D06's lane                                                                       |
| CG-11 | the environment word             | the region name "Live" / "Demo" (`D10`:283–:284; R-5); the OS window title "DOM · BTCUSDT · LIVE" (`D10`:266, E10-D03's form; D10 C-t); "DEMO and LIVE" in the span refusal (`D06`:414; SR-38) and the export's excluded list (`D09`:911)                                                                                                                                              | deliberate: the name follows R-5 ("never LIVE", `D15`:114); the title is E10-D03's; a sentence names the environment as its badge prints it                                                                                                                              |
| CG-12 | a partial restore                | "{n} panel couldn't load: {Kind}, {symbol}." (`D03`:675; SR-28; `RD`:231) and the grid's "1 chart couldn't load: ABCUSDT" (`MG`:135)                                                                                                                                                                                                                                                   | consistent; the grid drops the kind because a cell is always a chart (deliberate)                                                                                                                                                                                        |
| CG-13 | the word "restore"               | "Restore (F11)" (`D04`:336) and "Chart restored." (SR-09): un-maximise; "Restored your layout from 14:02…" (`D03`:647, :649): the launch restore; "Restore full quality" / "Full quality restored." (`RD`:213, :215): the profile                                                                                                                                                      | deliberate: three senses, each with its object named; AC-02 removes a fourth ("can't be restored")                                                                                                                                                                       |

**What the diff finds:** 13 groups; 8 consistent or deliberate; 4 PROPOSED wordings (AC-01..AC-04) routed to
their owners as consumer comments (closed parents) or into E15-D11's PR 3 (open); 1 open question (G-10). No
two surfaces describe the same state differently once AC-01..AC-04 land (AC 4).

## 8. Gated controls — G-T2 for every gated control (R370 BQ-13)

### 8.1 The rule, stated once (every later section that shows a gated control cites "§8.1")

A control that `14` §0.5 rule 5 and E09-D09 §2.1 route to T2 — gated by an active view-as context, a
permission, grant, account or environment leg, or a registered state — is built as follows (`RULE`:27–:59):
it keeps its native role and its full label (G-T2.1a); it is `aria-disabled="true"`, never `disabled`, so it
stays in the Tab order and a menu item stays arrow-reachable (G-T2.1b); its reason node is in the DOM at mount
and linked by `aria-describedby`, rendered **2a** inline, **2b** as a tooltip echo or in the **sentence** form,
and each row below names which (G-T2.1c); CMP-079 RbacGate wraps every role leg and the CMP-019 `lock` glyph,
named "Not available", leads the label in 2a (G-T2.1d); the label is `color.text.tertiary` and the reason
`color.text.secondary`, never `color.text.disabled` or `opacity.disabled` (G-T2.2); `Enter`, `Space` or the bound
chord changes nothing and re-shows the reason once, politely (G-T2.3; SR-42); every reason is a key of E09-D09
§3.1 or of a registered state vocabulary, one sentence of at most 60 characters naming no data, and a missing
key is PROPOSED with its vocabulary owner named (G-T2.4); a panel read-only for the session carries **one
notice, and every gated control's `aria-describedby` points at it** (G-T2.5); T2 and CMP-079 / CMP-019 `lock`
are named in every state row and component list that covers the control (G-T2.6; §2.2). **RBAC is
presentation only:** the server enforces every gate (C-12.4; `D07`:760); a T2 control is a hint, never the
protection, and a protective action — cancel, close, flatten, attaching or tightening a stop — is never gated
(C-2.6; `MG`:69; `RD`:121).

### 8.2 The table

**T2-01..T2-20 are E15-D15 §8.1's rows, lifted by hash** (§1.3; `D15`:376–:395): the save family (T2-01..T2-03),
new and import (T2-04, T2-05), the rail's writes (T2-06), Your layouts (T2-07), SCR-025 through one notice
(T2-08), the panel and layout limits (T2-09, T2-10), the picker's order tickets, recorded symbols and owner-only
entries (T2-11, T2-12, T2-14), the scale link without a group (T2-13), and the six rows classed outside the
grammar — validity, busy, availability, sentence, absence, outcome (T2-15..T2-20). The rows the four surfaces
outside D15's review add (F-11, `D15`:523):

| Id    | Surface                                                        | Control                                                                        | Legs, then the state                                                                       | Key and string                                                                                                                                               | Rendering                                                                                                                        | Status                                                       | Source               |
| ----- | -------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | -------------------- |
| T2-21 | SCR-049 grid                                                   | the maximised cell's arm control (CMP-229 under CMP-079, CMP-019 `lock` badge) | view-as; `orders:write`; an account not assigned                                           | `rbac.view_as` "Read-only while viewing as {user}."; `rbac.permission` "Your role can't place orders."; `rbac.account` "This account isn't assigned to you." | **2b** (a 24 px row has no room for 2a); the whole grid read-only: one grid-header notice, every control pointing at it (G-T2.5) | PROPOSED as a T2 row; the control's form is merged `MG` text | `MG`:70–:71          |
| T2-22 | SCR-150 / SCR-153, the restore notice in its narrow toast form | Save restored layout in the restore notice's CMP-045 toast at H2               | as T2-01                                                                                   | as T2-01                                                                                                                                                     | 2a on the toast's action line, as on the notice row                                                                              | PROPOSED (T2-01's control in a second host)                  | `RD`:107; `D15`:376  |
| —     | SCR-027 floating window chrome                                 | Return to workspace, Pin on top, ⋮, ×                                          | none: T1 for every session, view-as included; the hosted panel keeps its own T2            | —                                                                                                                                                            | the view-as banner under the bar is the one notice                                                                               | ruled by E15-D10 (BQ-10)                                     | `D10`:39             |
| —     | SCR-150 boot stages; SCR-153's E15 rows                        | the suggestion row, the reduced row, the manual controls, the narrow collapse  | none found on a read of `RD` §6–§8: a device-scoped display preference, no workspace write | —                                                                                                                                                            | —                                                                                                                                | "no gated control" after a read; confirmed at build (G-09)   | `RD`:123, :182, :186 |

No new reason key is needed: `rbac.account` is E09-D09 §3.1's. RBAC stays presentation only (§8.1).

## 9. Accessibility — E15-D15's output as a build requirement (T Accessibility; R370 BQ-14, BQ-21)

### 9.1 The contract (lifted by hash, §1.3; never restated)

| Part                                     | Lifted block      | What the build must hold                                                                                                                                                                                   |
| ---------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the keyboard model (KB-01..KB-24)        | D15 §3.1          | the seven shipped rows exactly as the key map binds them; the PROPOSED rows added only by E15-S01, E15-S02 and E15-S04 with the keymap's owner; `Ctrl+Tab` dropped; no close, undo or next-workspace chord |
| the focus model (FM-01..FM-29)           | D15 §4            | one destination per mutation, an element that exists after it; focus never moved by a sync change, a restore or a background event                                                                         |
| the region map and the naming rule (R-5) | D15 §5.2          | "{Kind}, {symbol} {interval spelled}" plus ", {Environment}" for `chart`, `dom`, `positions`; the qualifiers in the description; the panel first, the location second                                      |
| the script (SR-01..SR-50)                | D15 §6.1          | each string verbatim from the deck (§7), its politeness and its queueing; the three assertive E15 rows are SR-33, SR-34 and SR-40                                                                          |
| the budget (BG-01..BG-08)                | D15 §7            | one polite summary per mutation; an assertive safety row the mutation trips follows it, never swallowed (BG-08)                                                                                            |
| the T2 table                             | D15 §8.1; §8 here | §8.1's statement                                                                                                                                                                                           |
| the safety disclosures (SD-01..SD-08)    | D15 §8.2          | §10.1                                                                                                                                                                                                      |

### 9.2 Every finding's version, lifted (`D15`:513–:524; R-2's target E15-D16)

| F    | Severity | The version the build takes                                                                                                                                                                             | Builder               |
| ---- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| F-01 | Blocking | §9.3 AF-01 (PROPOSED; the hold)                                                                                                                                                                         | E15-S01 #401          |
| F-02 | Blocking | §9.3 AF-02 (PROPOSED; the hold)                                                                                                                                                                         | E15-S01 #401          |
| F-03 | Major    | conflict detection over the new chord's co-active focus contexts, blocking the save and naming the conflicting action (`D15`:515); the keymap's owner fixes                                             | E15-S01 #401          |
| F-04 | Minor    | FM-15: focus stays on the activated tab or tree item, announced once (SR-14)                                                                                                                            | E15-S03 #476          |
| F-05 | Major    | the MoveModeBar's `status` node speaks the bar's own line on entry and on stage two (`D15`:517; SR-03 `D15`:297; RG-06 `D15`:267) — CMP-249's speech, lifted (A-06; `D13`:326 OQ-1 closed by this lift) | E15-S02 #435          |
| F-06 | Minor    | SR-21: SCR-029 is read by role with its title and description; no live-region utterance                                                                                                                 | E15-S01, E15-S03      |
| F-07 | Minor    | SR-24: no `role="alert"` on the error summary while focus moves to its heading                                                                                                                          | E15-S03 #476          |
| F-08 | Minor    | the maximise key read from the live binding through CMP-022, never written per screen                                                                                                                   | E15-S02 #435          |
| F-09 | Minor    | the MoveModeBar's key words from CMP-022's name table once the mode keys are keymap rows (G-02)                                                                                                         | E15-S02 #435          |
| F-10 | Info     | `F2` on the focused tab and no global rename chord: two scopes, consistent (C-r)                                                                                                                        | E15-S03 #476 (a note) |
| F-11 | Info     | SCR-027, SCR-049, SCR-150, SCR-153 reviewed as wireframe structure; their T2 rows are §8.2's                                                                                                            | this pack             |
| F-12 | Blocking | §9.3 AF-12 (PROPOSED; the hold)                                                                                                                                                                         | E15-S01 #401          |

The contradictions D15 routes here: **D15-C-d** focus after Close — D04's rule, FM-11, "the panel that took the
space" (`D15`:535); **D15-C-g** the compact-view disarm is assertive (`D15`:538; E30-S04 #1088 builds the arm
side); **D15-C-j** the interval spelled in the name (`D15`:541); **D15-C-u** one close utterance, the toast's
(`D15`:552); **D15-C-v** the menu's name "Panel options, {region name}" (`D15`:553). Each is a build rule for
E15-S02 (C-d, C-g, C-u, C-v) or E15-T02 (C-j); none edits a closed parent. **G-04** is closed (§5); **G-05** is
§9.3's AF-12.

### 9.3 The hold — F-01, F-02 and F-12 (R370 BQ-05)

**E15-D16 cannot be Done until F-01, F-02 and F-12 are fixed in E15-D05's text or an exception is recorded on
#369** (`D15`:509, :791). The orchestrator records that exception only after the owner has seen these three
rows (C-10.1; the digest). Until then the rows below are **PROPOSED A-rows for E15-D05's text** (owner
E15-D05 · area/charting-ui; consumer comment on #321), written in the FM grammar; they are not ruled by being
written here. E15-S01 (#401) builds against them; its own BQ-12 (the Undo toast's successor) is answered by AF-12.

| Id    | Operation                                | Destination (PROPOSED)                                                                                                                                                                                                                              | Source of the form                                                                                   |
| ----- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| AF-01 | Delete layout (Your layouts), FM-18      | on Cancel: returns to the row's Delete…; after Delete layout: moves to the neighbouring row's name field (the row below, else the row above), or to the Presets listbox's first card when the section empties; announced once (SR-17)               | D15's own default 3, lifted (`D15`:131); the form of D08-D13's neighbouring tab (`D08`:153)          |
| AF-02 | Preset apply, FM-14                      | kept on the element that had focus when the chord was pressed, if it survives the apply; else moves to the first surviving panel's header in reading order; announced once (SR-01); the gallery's own return (FM-16) unchanged                      | D15's own default 1, lifted (`D15`:129); `05`:96 read for a layout mutation                          |
| AF-12 | The Undo toast closes under focus, FM-12 | returns to the element that held focus before the toast took it; if that element is gone, the case's own successor — FM-11's (`D04`:264) for an Undo after Close, AF-02's for an Undo after a preset apply; announced once by the undo's own string | R370 BQ-05; no merged text or `05` rule yields it (G-05), so this row is the pack's PROPOSED default |

**AF-02 does not reopen D15-C-d.** A preset apply rebuilds every panel (`D05`:344): FM-11's "panel that took
the space" does not exist there, so FM-11 stands for Close and AF-02 governs only the apply. **AF-01** takes
D15's own default (the neighbouring row's name field), not the BQ list's earlier draft (the next row's
Delete…): the pack lifts D15's text and adds no new design.

### 9.4 The acceptance-blocking list per builder (cannot be deferred to a follow-up)

The Blocking and Major F rows, the safety disclosures and the `05` floors: zero serious or critical axe
violations; a dragging alternative for every drag (WCAG 2.5.7); targets of at least 24 px (2.5.8); focus never
obscured (2.4.11) (`05`:94–:101).

| Builder      | Blocking for its acceptance                                                                                                                                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E15-T02 #403 | A-02 (the environment in the region name, SD-01); A-05 (DOM order rebuilt, nodes moved, never remounted, `D02`:611); FM-01..FM-12's successors; the inset focus that never resizes a canvas; KB-14 and `aria-valuenow`           |
| E15-S01 #401 | **AF-01, AF-02, AF-12** (the hold); F-03; the defects H-1 and H-2 (`D15`:216); BG-03's one summary and BG-08's order; KB-07 and KB-10 as keymap rows with the owner                                                              |
| E15-S02 #435 | **F-05**; KB-13 with `Esc` never reaching a trading binding (SD-07); SR-34 assertive (D15-C-g; SD-08); FM-11 (D15-C-d); D15-C-u, D15-C-v; T2-09..T2-12, T2-14, T2-18..T2-20; the window's environment title (SD-02) (§8.1; §8.2) |
| E15-S03 #476 | FM-15..FM-25; F-06, F-07; T2-01..T2-08, T2-15..T2-17, T2-22; SD-05 (§8.1; §8.2)                                                                                                                                                  |
| E15-S04 #477 | KB-08 and KB-09 only after the H-3 fix; SR-30..SR-38; the account axis an absence (SD-06)                                                                                                                                        |
| E15-S05 #558 | T2-13; SR-40 assertive as an `alertdialog`; SR-39, SR-41                                                                                                                                                                         |
| E15-S06 #559 | T2-21; AC-04 (the grid's disarm assertive); every cell named by R-5                                                                                                                                                              |
| E15-S07 #560 | FM-22, FM-23; SR-25 as AC-03 reads it, SR-26; SR-49 never; §10.1 rules 3 and 4                                                                                                                                                   |
| E15-S08 #561 | SD-04; SR-45, SR-46; the never-shed list (§10.1 rule 6); one disarm announcement per hidden armed panel (`RD`:224)                                                                                                               |

### 9.5 Motion (E15-D14's inventory as this pack's motion section; `D14`:345)

D14 §2 (every candidate, its verdict and its reduce pair) and §4 (the never-animates set and the safety rule)
are lifted by hash (§1.3). What the build holds: a drop commit, a preset apply, a layout switch and a workspace
switch are **cuts**; no row animates a box, so no transition resizes a GL viewport (the rejection form,
`D14`:244); every reduce cell is the end state at frame 0. Routed through this pack for E15-D04's next text
pass (consumer comment on #320): **D14-C-d** the toast's reduce is "instant", not "fade only" (`D14`:308);
**D14-C-p** the maximise binds B-2 alone and the restore is a cut (`D14`:320); **D14-C-r** the tray is a cut,
its tab's environment word at frame 0 (`D14`:322).

### 9.6 The floating window (E15-D10's rows for this pack; `D10`:483, :493)

The window is an independent document with its own title, skip link and focus scope (`D10`:300). **Every
floating window's OS title carries the environment word, whatever the hosted kind** (D10 C-t; SD-02). No T2 on
the window chrome (`D10`:39; §8.2). **D10 C-u** (`D10`:444): the skip link is the first focusable node, hidden
until focused, and the view-as banner's Exit, then Return to workspace, are the first visible stops — a C-row
for E15-D02's lane through this pack and a build rule for E15-S02 (FM-06 reads "Return to workspace" as the
first _visible_ stop). Pop out is desktop only (KB-12). The window's own gaps D10 G-1..G-20 stay E15-D10's and
E15-S02's (`D10`:451–:470).

## 10. Must not regress (T Security, T Performance; R370 BQ-14)

### 10.1 Security — six rules carried as build requirements, each with its source

1. **The environment is disclosed on every order-capable panel and every floating window** — in the region's
   name (R-5; A-02), the header's CMP-075 badge that never collapses, and the window's OS title (`D03`:169–:170;
   D10 C-t; SD-01, SD-02; C-2.11).
2. **RBAC gating is presentation only; the server enforces** (`D07`:760; C-12.4). An offered-but-unauthorised
   panel fails safely at mount; a reason names a capability, never data (`D07`:761).
3. **Imported and saved workspace strings are untrusted:** one text node each, never HTML, Markdown, a link or a
   format string; cleaned of control and bidi characters; capped (a key 64, a file name 40 characters); never
   logged (`D09`:697–:700).
4. **An export carries no credentials, accounts, trade-group or user ids, environment binding, alert or rule
   bindings, P&L, positions or orders** (`D09`:911, `e15.export.excluded`; `D09`:283).
5. **A deep link carries workspace and panel identity only** — `/w/:workspaceId?focus=:panelId`, never an account
   id, key, token or symbol; opening it re-authorises through the normal session (`D07`:762; the route
   `/w/:workspaceId`, #5447 if it merges as is).
6. **Degraded mode never sheds a safety disclosure:** the environment badge, the arm state, positions and
   orders and their update rate, and every error state stay (`RD`:143–:149; SD-04).

Also held: SD-01..SD-08 (D15 §8.2, lifted); protective actions never gated (§8.1); analytics carry closed sets
only, never a symbol, a name or an account (`D02`:681); the pack's examples use the parents' placeholder names
only. **E15-X01's STRIDE model** (#5439 at 7b62ed4ec8, if it merges as is) is the threat source; its rows are
cited at v1.1, once merged (D09 G-12 until then).

### 10.2 The budgets (each number its owner's; R370 BQ-14)

| Budget                                                   | Story      | Owner of the number                                  | Cite                 |
| -------------------------------------------------------- | ---------- | ---------------------------------------------------- | -------------------- |
| the frame budget: 60 fps, < 16 ms p95 frame              | all        | **C-14.2** (the Done line)                           | `CON`:936, :960–:961 |
| ≥ 55 fps with four active order-flow panes               | US-LAY-001 | `11`'s NFR; C-14.2 owns the frame budget, not 55 fps | `11`:2754            |
| ≤ 3 s four-pane restore to interactive (warm cache)      | US-LAY-002 | `11`                                                 | `11`:2774            |
| sync propagation within one frame                        | US-LAY-003 | `11`                                                 | `11`:2794            |
| crosshair sync ≤ 4 ms across six panels, no React render | US-LAY-003 | `14` SCR-023                                         | `14`:611             |
| panel mount ≤ 150 ms                                     | US-LAY-005 | `14` SCR-024                                         | `14`:629             |
| layout transition ≤ 200 ms                               | US-LAY-001 | `15` CMP-080                                         | `15`:922             |
| preset rebuild ≤ 300 ms                                  | US-LAY-001 | `14` SCR-022                                         | `14`:586             |
| context menu open ≤ 80 ms                                | US-LAY-005 | `14` SCR-028                                         | `14`:684             |
| a 2 MB import checked within 500 ms, in a worker         | US-LAY-007 | E15-D09 (the ticket's figure)                        | `D09`:144            |

### 10.3 The protective constraints (implemented, never rediscovered)

| Constraint                                                       | Why                                                        | Source    |
| ---------------------------------------------------------------- | ---------------------------------------------------------- | --------- |
| panel focus is the 2 px **inset** frame plus the header bar      | a changed content box resizes the canvas and drops a frame | `DSC`:43  |
| **static chrome**: no per-frame repaint                          | the chrome never competes with the engine                  | `15`:922  |
| the drag preview is **CSS-transform-only**, never a live panel   | a drag costs no chart frame                                | `D04`:392 |
| **one layout mutation per drop**; per-pane hosts re-parented     | no WebGL context remounted; focus survives the move        | `D04`:393 |
| splitter writes **one per animation frame**                      | a recreated GL context stalls visibly                      | `D04`:394 |
| the zone overlay is one layer, built once per drag               | hit-testing reads bands, not the DOM                       | `D04`:395 |
| **no canvas resize in any animation**: every layout change a cut | the rejection form                                         | `D14`:244 |
| no synced state in React-rendered chrome                         | the crosshair and linked scale are engine-drawn            | `D06`:527 |

## 11. Events (T Observability; R370 BQ-12; analytics, never audit)

**Rules** (`D02`:681, :702; `D03`:818): analytics, never audit; properties are small closed sets, never a
symbol, a name or an account; a T2 control emits nothing; no sink exists yet (E15-D01 OQ-11, G-03). The
**required** events (T Observability) are marked ★.

| Event (primary name)                                                                                                                       | Properties                                                                            | Fires                                       | Source                    | Builder      |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | ------------------------------------------- | ------------------------- | ------------ |
| ★ `layout.panel_moved`                                                                                                                     | `from`, `to`, `method: pointer \| keyboard`, `zone`                                   | P9, K5, a Move to ▸ outcome                 | `D04`:381; `D02`:687      | E15-S02      |
| ★ `layout.preset_applied`                                                                                                                  | `presetId`, `entry: first_run · gallery · menu · hotkey`, `keepSymbols`, `panelCount` | Apply or `Enter` on a card                  | `D05`:152; `D03`:811      | E15-S01      |
| ★ `workspace.restore_completed`                                                                                                            | `ms`, `paneCount`, `failedPanes`                                                      | the workspace is interactive (`RD` §9)      | `RD`:268; `D12`:152       | E15-S03, S08 |
| `workspace.restored`                                                                                                                       | `source: crash · clean_quit · never_stored`                                           | launch restored a working copy              | `D03`:813; `D02`:697      | E15-S03      |
| `workspace.restore_resolved`                                                                                                               | `resolution: save · revert · discard`                                                 | the restored chip cleared                   | `D03`:814                 | E15-S03      |
| `workspace.switched`                                                                                                                       | `from`, `to` (ids), `dirty`                                                           | a workspace opened from the rail or a tab   | `D05`:152                 | E15-S03      |
| `layout.panel_added`                                                                                                                       | `type`, `placement`, `entry`                                                          | a panel added                               | `D07`:751; `D03`:809      | E15-S02      |
| `layout.panel_removed`                                                                                                                     | `type`                                                                                | Close                                       | `D03`:810                 | E15-S02      |
| `layout.split_created`                                                                                                                     | `orientation`                                                                         | an edge drop that made a split              | `D04`:382                 | E15-S02      |
| `layout.drop_rejected`, `layout.move_cancelled`                                                                                            | `reason`, `method`; `method`                                                          | per refused zone or target; P8, K6          | `D04`:385–:386            | E15-S02      |
| `layout.panel_floated`; `panel.redocked`; `window.*`                                                                                       | —; `originSlotExists`; D10's                                                          | Pop out; Return; the window's life          | `D04`:383; `D10`:44, :569 | E15-S02      |
| `layout.maximised`; `layout.panel_minimised`, `layout.panel_restored`                                                                      | —                                                                                     | `F11` or the menu; the tray                 | `D04`:384, :388           | E15-S02      |
| `layout.saved`; `layout.reset`                                                                                                             | `trigger`, `restored`; `trigger`                                                      | Save, Save restored layout; Revert to saved | `D03`:808, :812           | E15-S01, S03 |
| `layout.preset_previewed`, `layout.preset_saved_as`, `layout.preset_deleted`                                                               | `presetId`; `layoutId`, `hotkeySlot`; `layoutId`                                      | the gallery                                 | `D05`:563–:566            | E15-S01      |
| `layout.cost_confirm`; metric `layout.frame_cost_at_confirm`                                                                               | `choice`, `panel_count_bucket`; `measured_p95_ms`, `estimated_p95_ms`                 | the cost confirm                            | `D03`:815–:816            | E15-S01      |
| `sync.group_created`, `sync.group_changed`, `sync.axis_toggled`, `sync.panel_joined_group`, `sync.panel_left_group`, `sync.conflict_shown` | per `D06`                                                                             | the popover                                 | `D06`:516–:521            | E15-S04      |
| `scale.link_refused`; `scale.percent_suggested_accepted`                                                                                   | `reason`, `decadeA`, `decadeB`; —                                                     | the refusal; the percent accepted           | `D06`:522–:523            | E15-S05      |
| `panel.picker_searched`, `panel.picker_disabled_entry_focused`, `panel.context_menu_opened`                                                | per `D07`                                                                             | the picker; the menu                        | `D07`:752–:754            | E15-S02      |
| `layout.conflict_detected`, `layout.conflict_resolved`                                                                                     | `revisionLocal`, `revisionRemote`; `choice`                                           | SCR-029                                     | `D08`:505                 | E15-S03      |
| `workspace.updated`, `workspace.deleted`, `workspace.default_account_changed`, `workspace.environment_pinned`                              | per `D08`                                                                             | SCR-025                                     | `D08`:244                 | E15-S03      |
| `workspace.exported`; `layout.imported`; `layout.import_rejected`                                                                          | per `D09`                                                                             | export done; import report; a refusal       | `D09`:252, :501; `LF`:170 | E15-S07      |
| `multichart.*` (five)                                                                                                                      | per `MG`                                                                              | the grid                                    | `MG`:158                  | E15-S06      |
| `degraded.*`, `capability.profile_*`, `layout.collapsed`, `layout.expanded`                                                                | per `RD`                                                                              | the reduced profile; the narrow collapse    | `RD`:260–:267             | E15-S08      |
| metric `layout.transition_ms` (development builds)                                                                                         | start the drop commit, stop the first frame after                                     | every layout change                         | `D14`:330                 | E15-Q04 #553 |

**C-rows (PROPOSED; routed to the builders):**

| Id    | Drift                                                                                                                                                                       | Reading taken                                                                                                             |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| EV-C1 | T's `workspace.restore_completed{ms,paneCount}` against D12's `{ms, paneCount, failedPanes}` (`RD`:268; D12 C-11)                                                           | **lifted, not PROPOSED (R370 BQ-12):** D12's three properties, fired at interactive; T's shape is its subset              |
| EV-C2 | `layout.preset_applied` is `{entry, panel_count_bucket}` in `D03`:811 and `{presetId, entry, keepSymbols, panelCount}` in D05 D-15 (`D05`:152)                              | PROPOSED: D05's union is primary (the gallery's owner); `panelCount` sent as D03's bucket (`D03`:818). E15-S01            |
| EV-C3 | `14` lists `layout.panel_moved` without properties (`14`:562); D04-A-4 adds them                                                                                            | D04's `{from, to, method, zone}`; `method` is the required signal. E15-S02                                                |
| EV-C4 | `panel.added` (`14`:535, :630) against `layout.panel_added` (`14`:562); `panel.removed` against `layout.panel_removed`; `workspace.saved` against `layout.saved` (`14`:535) | PROPOSED: the `layout.*` names primary (`D02` §9's ticket names), the `panel.*` / `workspace.saved` aliases. E15-S01, S02 |
| EV-C5 | `panel.floated{panelType, display}` (`14`:674) against `layout.panel_floated` (`14`:562)                                                                                    | PROPOSED: `layout.panel_floated` primary, `panel.floated` its alias with D10's properties. E15-S02                        |
| EV-C6 | `sync.scale_link_refused{symbolA, symbolB}` (the ticket's) against `scale.link_refused{reason, decadeA, decadeB}` (`D06`:522)                                               | D06's: a symbol is never a property. E15-S05                                                                              |

## 12. Design-ahead (reports, promises nothing; R370 BQ-17)

From `CAL` (Sprint 01 = 2026-09-25, seven-day sprints): Sprint 05 = 10-23..10-29 (this ticket's, missed);
Sprint 06 = 10-30..11-05 (now); Sprint 07 = 11-06..11-12; Sprint 08 = 11-13..11-19; Sprint 09 = 11-20..11-26.

| Consumer                                                          | Sprint | Ahead of it at this PR | Note                                                                           |
| ----------------------------------------------------------------- | ------ | ---------------------- | ------------------------------------------------------------------------------ |
| E15-T02 #403, E15-S01 #401, E15-T01 #402                          | 06     | late (building now)    | to be flagged on #403 and #401: §3, §4, §5's A-02 / A-05, §9.3's PROPOSED rows |
| E15-S02 #435, E15-T03 #436, E15-X01 #437, E15-Q01 #434            | 07     | 0 sprints              | the pack lands in Sprint 06 if approved; the boards PENDING rows G-P2, G-P4    |
| E15-S03 #476, E15-S04 #477, E15-Q03 #475                          | 08     | 1 sprint               | —                                                                              |
| E15-S05..S08 #558..#561, E15-Q02 #552, E15-Q06 #555, E15-D17 #551 | 09     | 2 sprints              | G-P1, G-P3 due before it                                                       |

## 13. The known-gaps register (AC 5; R370 BQ-17)

Grades Blocking · Major · Minor · Info. **Decide by** is the last day before the consuming sprint; a row whose
date has passed reads "late — flagged on #nnn" and is never back-dated. The affected story is flagged so it is
not started blind.

| Id   | Grade    | Gap                                                                                                                   | Owner lane                                                                   | Decide by  | Story flagged                                        |
| ---- | -------- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---------- | ---------------------------------------------------- |
| G-H1 | Blocking | the D15 hold: F-01, F-02, F-12 in E15-D05's text, or the exception on #369 (§9.3)                                     | E15-D05 · area/charting-ui; the exception the orchestrator's after the owner | 2026-11-05 | US-LAY-006, US-LAY-001 — late, to be flagged on #401 |
| G-P1 | Major    | SCR-026's boards (E15-D09's last PR) — US-LAY-007's frames are text only                                              | E15-D09 #363                                                                 | 2026-11-19 | US-LAY-007                                           |
| G-P2 | Major    | SCR-027's boards (E15-D10 PR 3)                                                                                       | E15-D10 #364                                                                 | 2026-11-05 | US-LAY-005                                           |
| G-P3 | Major    | SCR-049's boards (E15-D11 PR 3)                                                                                       | E15-D11 #365                                                                 | 2026-11-19 | US-LAY-001, US-LAY-003                               |
| G-P4 | Major    | the dock band's boards for CMP-249..252 (E15-D13 PR 3)                                                                | E15-D13 #367                                                                 | 2026-11-05 | US-LAY-001, US-LAY-005                               |
| G-07 | Minor    | the grid's still-works sentence (`MG`:150) against `RD`'s reduced row (CG-07)                                         | E15-D11 #365 (PR 3)                                                          | 2026-11-19 | US-LAY-001                                           |
| G-08 | Minor    | "chart trading" (`MG`:151–:153) against "one-click trading" (`RD`:232; SR-33, SR-34) for the same arm state (CG-08)   | E15-D11 with E30-D05's lane                                                  | 2026-11-19 | US-LAY-001, US-LAY-003                               |
| G-09 | Minor    | SCR-153's E15 rows hold no gated control (§8.2), to be confirmed against E09-D09 §2.1 step 3a                         | E15-S08 #561 with E09-D09's lane                                             | 2026-11-19 | US-LAY-008                                           |
| G-10 | Minor    | the sync announcements name "Chart 15m" where the region name spells the interval (CG-10); default PROPOSED: spell it | E15-S04 #477 with E15-D06's lane                                             | 2026-11-12 | US-LAY-003                                           |
| G-12 | Major    | QA's confirmation of the test-id convention (§4)                                                                      | E15-Q01 #434                                                                 | 2026-11-05 | all — late for #403 and #401, to be flagged there    |
| G-14 | Minor    | the header toolbar's name: "{kind} actions" in #5411 against RG-08's panel name (CR-02)                               | E15-T02 #403 with E15-D13's Table N                                          | 2026-11-05 | US-LAY-001, US-LAY-005 — late, to be flagged on #403 |
| G-15 | Info     | D15 §15.1 routes E15-S07 as #1093 (`D15`:797); the published map gives #560, which this pack uses                     | E15-D15's owner (a consumer comment on #369)                                 | —          | US-LAY-007                                           |

**Inherited, by pointer** (each parent's owner and date stand; listed so no builder meets them mid-sprint): D15
G-01 — the "ready" string — is answered by `RD`'s "Workspace ready: …" (`RD`:231), so E15-S03 builds it; D15
G-02 (keymap rows) and G-03 (the two a11y signals, no sink) (`D15`:562–:563); D08-G1..G8 (`D08`:860–:867); D09-G1..
G15 (`D09`:1036–:1050); D10 G-1..G-20 (`D10`:451–:470); D11 G-1..G-3 (`D11`:226–:228); D12 G-1..G-6
(`D12`:170–:175); D13 G-2, G-3 (`D13`:323–:324); D14 G-1, G-2 (`D14`:329–:330).

## 14. The walkthrough, the dry run and the Q&A log (R370 BQ-15)

No hand-off session is claimed (Deviation D-2). In its place:

### 14.1 The owner protocol (≤ 10 items; one comment on #370 after Done)

1. Read §2.1 for US-LAY-005: can every state named there be found on a board or in a spec section?
2. Read §9.3: do AF-01, AF-02 and AF-12 put focus where you expect after Delete layout, a preset apply and the
   Undo toast?
3. Read §7.2: are AC-01..AC-04 the wording you want, and is G-10's default right?
4. Read §4: would you accept `e15-dock-panel-3` and the role-first rule as the E2E selectors?
5. Read §8.2: is T2-21's 2b rendering right for the grid's maximised cell?
6. Read §10.2: are the budgets' owners right (C-14.2 for the frame budget)?
7. Read §11: are the three required events the ones you want reported after release?
8. Read §5.2: should A-02 (the environment word in the region name) land before E15-T02 merges?
9. Confirm the PROPOSED Deviation D-1 (no Penpot page and no PNG for this pack) or ask for boards.
10. Note any question as a gap: it joins §13 with an owner and a date.

### 14.2 The dry run (AC 2) — at READY, by a reader outside E15, labelled (heuristic)

**Task:** rebuild CMP-082 PanelHeader from this pack alone. **Pass:** every question is answered by a
section here or a cite it names; each NOT FOUND joins §13 and the Q&A log. The author's own trace below shows
where each answer sits (heuristic); the outside reader's run is recorded at READY and is not claimed here.

| Question a builder asks                           | Answered by                                                           |
| ------------------------------------------------- | --------------------------------------------------------------------- |
| which props, which states?                        | §3.2 → `15`:925; §5.1 (none missing)                                  |
| which role, which heading level?                  | §3.2: heading `h2`, `h3` in a tab group, and a `toolbar`              |
| what is the region's name?                        | §9.1 R-5; A-02                                                        |
| what is the toolbar's name?                       | **open: G-14** (CR-02)                                                |
| which keys?                                       | §3.2 → D15 KB-22; the handle a button "Move {Kind}"                   |
| what collapses first at narrow widths?            | `15`:925's contract, E15-D03 D-3's order (`D03`:168)                  |
| which sizes and tokens?                           | `D13H` Table R (`D13H`:79): header 24 / 32, the badge pill 20 / 28    |
| what does focus look like?                        | §10.3: the inset frame and the header bar; never a resize             |
| which stories?                                    | §6.1 (nine; E15-S02 and E15-S04 build them)                           |
| what is announced?                                | SR-04 on focus arrival; the deck's `panel.focus.announce` (`D03`:671) |
| which test ids?                                   | §4: none — role and name first                                        |
| what does the environment badge and arm state do? | §10.1 rule 1; CMP-075, CMP-229 never collapse                         |
| what motion?                                      | §9.5: the header paints at frame 0                                    |

### 14.3 The Q&A log

| #   | Question                                                           | Answer, folded into |
| --- | ------------------------------------------------------------------ | ------------------- |
| 1   | (the author's trace) what is the header toolbar's accessible name? | open — G-14         |

## 15. Versions and the late-change rule

- **v1 (this PR, the pre-stage):** the merged texts cited at the base; the four parents' boards PENDING
  (G-P1..G-P4); the in-flight PRs pinned at their heads.
- **v1.1 (PR 2, closing):** when E15-D09's, E15-D10's, E15-D11's and E15-D13's boards PRs have merged and the
  hold is lifted (§9.3): each boards PR is re-pinned at its head when it opens and re-cited at its merge; the
  "text only" marks become board ids; the in-flight PRs are re-cited at their merge commits; the A-rows E15-D13
  PR 3 did not apply are applied to `15`; the dry run's record is attached; `Closes #370`.
- **A late change.** A parent edit moves a lifted hash (G-HASH) or a deck string (G-DECK): the pack is
  re-issued in the parent's PR or the next pack PR, never left stale. A decision made after Sprint 05 joins §13
  with an owner and a date before its consuming sprint (AC 5).

## 16. The design-QA preview, sign-off, deviations, paths and the check

### 16.1 The design-QA checklist E15-D17 (#551) will use — published unticked (T Scope; R370 BQ-16a)

- [ ] Every story's states of §2.1 are built and reachable (evidence: the story's E2E run, E15-Q02 #552).
- [ ] Every order-capable panel names its environment in its region name and its badge (§10.1 rule 1; SD-01).
- [ ] Every floating window's OS title carries the environment word (SD-02; D10 C-t).
- [ ] Focus lands where §9.1's FM table and §9.3 say after every layout mutation (E15-Q06 #555's script, `D15` §13).
- [ ] Every announcement is the deck's string at its politeness, one summary per mutation (§7; BG-03, BG-08).
- [ ] Every gated control follows §8.1, its rendering as §8.2 names (axe and the T2 checks).
- [ ] No transition resizes a canvas; every layout change is a cut; reduce is the end state at frame 0 (§9.5).
- [ ] The budgets of §10.2 hold on the reference machine (E15-Q04 #553's scripts).
- [ ] The protective constraints of §10.3 hold (code review plus the bench).
- [ ] Imported and saved strings render as capped text; an export carries nothing of §10.1 rule 4 (E15-X02 #562).
- [ ] Degraded mode sheds nothing of §10.1 rule 6 (E15-S08's tests).
- [ ] Every story of §6.1 exists, in dark and light, compact and comfortable; zero serious or critical axe.
- [ ] Every test id follows §4; none inside the canvas.
- [ ] The three required events of §11 fire with their properties.
- [ ] Every Blocking and Major F row of §9.2 is closed in the build (§9.4).

### 16.2 Sign-off and the Definition of Done (the delegation's substitutions)

The CDO sign-off and the Architect's attendance become **the owner's approval** (Agent-delivery adaptations;
C-10.1): owner approval pending. The DoD is reported, never pre-ticked:

- [ ] `docs/design/specs/e15-handoff.md` merged with an entry for every US-LAY-001..008 — this PR (pre-stage).
- [ ] Build order recommended and agreed with the FE lead — §3; the orchestrator's ruling plus #403's comment.
- [ ] Test-id convention agreed with QA — §4, PROPOSED; G-12.
- [ ] Reconciliation complete; the catalogue corrected — §5; A-01..A-06 PROPOSED, applied at E15-D13 PR 3 or v1.1.
- [ ] Storybook story list published — §6.
- [ ] Copy deck complete and consistency-diffed — §7; DECK.
- [ ] Security, accessibility and performance lists carried — §9, §10.
- [ ] Analytics table consolidated, required events flagged — §11.
- [ ] Known gaps with owners and dates — §13.
- [ ] Cold build passed — **not ticked as human-run** (R370 BQ-15): the dry run at READY (§14.2).
- [ ] Handoff session held — **substituted**: the protocol (§14.1); no session claimed.
- [ ] Design-QA checklist published in advance — §16.1.
- [ ] CDO sign-off (Status = Done) — the owner's approval; not in Sprint 05; the D15 hold must be lifted first.

### 16.3 Deviations (recorded, not hidden)

- **D-1 (PROPOSED, for the owner):** no Penpot page and no PNG for this pack. README requires both on every
  design ticket, "no exceptions" (`README`:44–:57); the orchestrator does not waive it (R370 BQ-18). The pack
  draws nothing (T Out of scope) and points at the parents' committed PNGs; only the owner's approval (C-10.1)
  can accept this, as for E14-D12's D-2.
- **D-2:** no hand-off session; a written protocol, a dry run and a Q&A log stand in (§14; Agent-delivery
  adaptations).
- **D-3:** two PRs, a pre-stage and a closing version (R370 BQ-01); `Refs #370` with a `Partial:` line here.
- **D-4:** larger than C-4.8's preference under one ticket; `large-pr-approved` asked in advance (R370 BQ-19).
- **D-5:** the test-id convention is PROPOSED under the orchestrator's ruling, not agreed with QA (R370 BQ-08).
- **D-6:** catalogue corrections are A-rows, applied by E15-D13 PR 3 or v1.1, not by this PR (R370 BQ-09).
- **D-7:** the PR title `docs(charting-ui): add the E15-D16 layouts and workspaces hand-off pack (pre-stage)` and the
  docs-only paths and gates replace the brief's generic frontend paths, commands and the issue's title
  `[E15-D16] Engineering handoff pack for the layouts & workspaces band` (C-4.4, C-4.10).
- **D-8:** E15-D15 is consumed as an input; this PR adds it to E15-D16's `blocked_by` (`E15J`; validated).

### 16.4 Paths and the check

| Path                                               | What                                                               |
| -------------------------------------------------- | ------------------------------------------------------------------ |
| `docs/design/specs/e15-handoff.md`                 | this pack (T Scope's path)                                         |
| `docs/design/E15/E15-D16-copy.json`                | DECK                                                               |
| `docs/design/_tools/e15_d16_handoff_check.py`      | the check: G-LINK, G-HASH, G-INDEX, G-DECK; `--fill`, `--json`     |
| `docs/design/_tools/test_e15_d16_handoff_check.py` | its test: the gates pass on the tree and fail on one mutation each |
| `docs/plan/backlog/E15.json`, `all-tickets.json`   | unchanged here: E15-D15 joins E15-D16's `blocked_by` in #5460      |

Run `python3 -I docs/design/_tools/e15_d16_handoff_check.py` from the repository root; it exits 0 when every
gate passes. It does not check G-T2 coverage (§8), the R6 pin format or a boards-PENDING row per undrawn
parent; those stand as reviewed prose (Option 2, R370 BQ-02b).
