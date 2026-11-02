# E47-D04 — Hand-off (`16` §11.4; the focus model)

Components: **CMP-039 FocusRing** (the enclosed two-tone ring, the thick geometry), **CMP-043 Dialog** and **CMP-044 ConfirmDialog** (trap, initial focus, restore), **CMP-049 Table** in `grid` mode (one stop, `Tab` out, `Esc` layers, logical identity), **CMP-070 AppShell** with **CMP-085 SkipLink** (landmarks, the ring), **CMP-079 RbacGate** with the **CMP-019 Icon** `lock` glyph (a T2 control, rendering 2a: spec §10's T2 paragraph; board 07), plus the SCR-010 and SCR-050 rows of `14`. CMP-080's panel frame is unchanged. The spec is [E47-D04.md](E47-D04.md); every "§" below without a prefix is the spec's. These are component contracts, so the hand-off is due.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-039 FocusRing                                                                                               | CMP-043 / CMP-044 Dialog, ConfirmDialog | CMP-049 Table (`grid`)                    | CMP-070 AppShell + CMP-085 SkipLink        |
| ------------------------ | --------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ----------------------------------------- | ------------------------------------------ |
| Final Penpot link        | [x] page `E47-D04 — Focus model` (page id `cb0c3916-2579-81a4-8008-e0bd553f9c60`); boards 08–10 drawn (spec §0) | [x] the same page: boards 05, 06 drawn  | [x] the same page: boards 03, 04 drawn    | [x] the same page: boards 01, 02, 07 drawn |
| Variants × states        | [x] spec §7.1 normal / inset / thick                                                                            | [x] spec §9.1 per dialog type           | [x] spec §6                               | [x] spec §2, §3                            |
| Keyboard table           | [x] n/a (a utility)                                                                                             | [x] spec §9.2                           | [x] spec §6.1, §6.3                       | [x] spec §3 (the ring keys)                |
| Accessible name and role | [x] n/a                                                                                                         | [x] CMP-043's, unchanged                | [x] spec §6.2 (the entry label)           | [x] spec §2 (landmarks, headings)          |
| Live data                | [x] none                                                                                                        | [x] the outcome in the assertive region | [x] spec §8                               | [x] W-1 per arrival, ≤ 1 Hz                |
| Motion pair              | [x] none: the ring appears at once                                                                              | [x] CMP-043's, unchanged                | [x] none                                  | [x] none                                   |
| Density notes            | [x] one geometry for every density                                                                              | [x] R-12 (reflow)                       | [x] spec §12 (the ceiling)                | [x] none                                   |
| Essential exceptions     | [x] none                                                                                                        | [x] none                                | [x] none                                  | [x] none                                   |
| Tokens used              | [x] spec §7.1; D04-G5                                                                                           | [x] CMP-043's                           | [x] CMP-039 `inset`                       | [x] CMP-039; `border.panel.focus`          |
| Data contract            | [x] none                                                                                                        | [x] none                                | [ ] NO: R-3's logical ids per grid (§6.2) | [ ] NO: D04-G3, D04-G4                     |
| Contrast                 | [x] spec §7.6 (computed); D04-G1                                                                                | [x] CMP-039's                           | [x] CMP-039's                             | [x] CMP-039's                              |
| Storybook                | [x] §D                                                                                                          | [x] §D                                  | [x] §D                                    | [x] §D                                     |
| Sign-off                 | [ ] owner approval pending                                                                                      | [ ] owner approval pending              | [ ] owner approval pending                | [ ] owner approval pending                 |

## §B Who applies what

| A                                      | Target                         | Applied by                                 |
| -------------------------------------- | ------------------------------ | ------------------------------------------ |
| `05` §3.4 item 11, the `05`:46 pointer | `05`                           | this PR (BQ-2)                             |
| E29-D05's A-02, the `05`:63 cell       | `05`                           | this PR (BQ-4, ruled)                      |
| D04-A1, D04-A2                         | `15` CMP-039                   | E47-D10 (#1309), the CMP-039 contribution  |
| D04-A3, D04-A4, D04-A5                 | `15` CMP-043, CMP-044, CMP-049 | the `15` owner, at the owner's sign-off PR |
| D04-A6, D04-A7                         | `14` SCR-010, SCR-050          | the `14` owner, at the owner's sign-off PR |
| D04-A8                                 | `16` §3 focus / interaction    | the `16` owner, with E47-D03 (#1302)       |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `95a4f2765` (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A      | Target       | Field (`file`:line)         | Old                                                                                                      | New                                                                                                                                                            |
| ------ | ------------ | --------------------------- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D04-A1 | `15` CMP-039 | A11y (`15`:458)             | guarantees ≥3:1 contrast ring, 2px offset, `:focus-visible` only                                         | insert after: ; the ring is enclosed by a 1 px `color.surface.canvas` halo on each side, the two-tone technique, measured over E47-D04 §7.6's 12 backgrounds   |
| D04-A2 | `15` CMP-039 | Tokens (`15`:459)           | `border.focus` (2 px width)                                                                              | insert after: · thick: 3 px ring, 2 px halo under `data-focus-ring="thick"` (PROPOSED `border.focus.thick`; E47-D04 §7.3)                                      |
| D04-A3 | `15` CMP-043 | A11y (`15`:510)             | `aria-describedby`, focus-trap,                                                                          | insert after: every close path restores focus to the invoker (else `fallbackFocusRef`), a scrim click on a blocking dialog does nothing (E47-D04 §9.2),        |
| D04-A4 | `15` CMP-044 | A11y (`15`:521)             | focus starts on Cancel;                                                                                  | insert after: on `Esc`, Cancel or completion focus returns to the invoker (E47-D04 §9.2);                                                                      |
| D04-A5 | `15` CMP-049 | A11y (`15`:584)             | one Tab stop and a roving tabindex (`05-accessibility-standard.md` §3.4 item 2),                         | insert after: `Tab` leaves in one press, `Esc` closes the innermost transient and then exits to the panel header, focus is keyed by a logical id (E47-D04 §6), |
| D04-A6 | `14` SCR-010 | Interactions (`14`:302)     | `Ctrl+\` cycles focus through the landmarks, which the reader names as each takes focus (05 §3.4 rule 1) | `Ctrl+\` cycles focus through the regions in visual order and back, wrapping, the reader naming each (05 §3.4 rules 1 and 11; E47-D04 §3)                      |
| D04-A7 | `14` SCR-050 | A11y (`14`:1209)            | every price row is focusable                                                                             | the ladder is one Tab stop with a roving tabindex, every price row reachable by the arrows (E47-D04 §6)                                                        |
| D04-A8 | `16` §3      | Focus/interaction (`16`:59) | validated per tier, not just once;                                                                       | insert after: drawn as the enclosed two-tone ring of E47-D04 §7.2 and measured over its 12 backgrounds;                                                        |

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component             | Stories                                                                               |
| --------------------- | ------------------------------------------------------------------------------------- |
| CMP-039 FocusRing     | the merged list + EnclosedHalo · Inset · Thick · OverHeatmapBright · OverHeatmapDim   |
| CMP-043 Dialog        | the merged list + RestoreToInvoker · BlockingScrim · NestedStepUp                     |
| CMP-044 ConfirmDialog | the merged list + FlattenAllRestore                                                   |
| CMP-049 Table         | the merged list + GridOneStop · GridEscLayers · GridRetentionNearest · GridRowRemoved |
| CMP-070 AppShell      | the merged list + RegionRing · RegionRingReverse                                      |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

- [ ] Board 01: every landmark is named once; the ring numbers follow the picture, not the DOM.
- [ ] Board 02: each panel is one run of stops; the header comes first.
- [ ] Board 03: one `Tab` leaves the ladder; `Esc` peels the menu, then the selection, then lands on the header.
- [ ] Board 04: after a re-seed the focus is on the same price, or on the nearest with W-4; a closed position hands focus to the next row.
- [ ] Board 05: the flatten-all confirm opens on Cancel; both exits end on FLATTEN ALL.
- [ ] Board 06: the palette opens on its field; `Esc` returns to the invoker.
- [ ] Board 07: a gated control is in the order with its reason; an admin item a manager cannot reach is not there at all.
- [ ] Boards 08–10: the ring is visible on all 12 backgrounds in each theme; the thick ring reads as more prominent.
- [ ] Walk each archetype's Tab order on paper against the boards with a second reviewer (T Test); log each discrepancy.
- [ ] Record `approved` on #1303, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer         | Builds from                | Waits on                       |
| ---------------- | -------------------------- | ------------------------------ |
| E47-S05 (#1319)  | spec §2–§10, §C, §G        | D04-G2 … D04-G6                |
| E47-D06 (#1305)  | spec §6.2, §12, R-3        | D04-Q1                         |
| E47-D07 (#1306)  | spec §15 (labels), R-8     | —                              |
| E47-D09 (#1308)  | spec §3 keys, §6.1         | D04-C1                         |
| E47-D10 (#1309)  | spec §7, §C D04-A1, D04-A2 | D04-G1 through E47-D03 (#1302) |
| E47-Q01, E47-Q03 | §G                         | —                              |

## §G QA draft assertions (deterministic; for E47-Q03's keyboard-only Playwright suite, `05`:258)

| QA   | Given / when                                                                                           | Then (assert)                                                                                                                                        | Q01                      |
| ---- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| QA-1 | focus on a ladder row (200 levels); press `Tab`; then re-enter, press `Esc` with nothing open          | after one `Tab`, `document.activeElement` is outside the grid and is the panel's next stop; after `Esc`, it is in the panel header's toolbar         | TC-108                   |
| QA-2 | open the flatten-all confirm from FLATTEN ALL; press `Tab` 20 times; press `Esc`; reopen; confirm      | every focused element during the 20 presses is inside the dialog; the first focused is Cancel; after `Esc` and after completion focus is FLATTEN ALL | no Q01 case; new for Q03 |
| QA-3 | focus a ladder level; replay a recorded re-seed without that level                                     | focus is on the nearest level by price (ties toward the touch); the polite region received exactly one W-4; `activeElement` is never the body        | no Q01 case; new for Q03 |
| QA-4 | from the TopBar press `Ctrl+\` once per region, then once more; repeat under `data-focus-ring="thick"` | the regions arrive in §3's order and wrap to the TopBar; one W-1 per arrival; the ring's computed outline matches §7.1 in both geometries            | TC-105, TC-117           |

## §H The board plan (drawn in this PR; spec §0 as built)

The boards of spec §0, on page `E47-D04 — Focus model`; frames named `<archetype>/<state> · <theme>`. Data: a seeded synthetic book and position set, declared synthetic on every board's face; only the instrument's tick size comes from a recorded fixture. Each board's frames:

| Board | Frames                                                                                                                     |
| ----- | -------------------------------------------------------------------------------------------------------------------------- |
| 01    | `shell/landmarks · dark`, `shell/ring-order · dark`                                                                        |
| 02    | `workspace/tab-sequence · dark`, `workspace/roving-zones · dark`                                                           |
| 03    | `grid/entry · dark`, `grid/tab-out · dark`, `grid/esc-layers · dark`                                                       |
| 04    | `retention/level-kept · dark`, `retention/nearest · dark`, `retention/row-removed · dark`, `retention/not-obscured · dark` |
| 05    | `dialog/flatten-open · dark`, `dialog/flatten-restore · dark`                                                              |
| 06    | `overlay/palette · dark`, `overlay/cheatsheet · dark`, `overlay/menu-tab-out · dark`                                       |
| 07    | `form/settings-sequence · dark`, `form/admin-t2-t3 · dark`                                                                 |
| 08    | `ring/geometry · dark`, `ring/backgrounds · dark`                                                                          |
| 09    | `ring/geometry · light`, `ring/backgrounds · light`                                                                        |
| 10    | `ring/thick-hc · hc`, `ring/backgrounds · hc`                                                                              |

## §I Summary for #1303

1. Text-first focus model + hand-off + default-deny audit tool; 10<!--=COUNT:boards--> boards drawn in this PR (spec §0 as built); `05` §3.4 item 11 is the normative expansion.
2. Landmarks and one `h1`; E15-D15's ring generalised to five archetypes, each with its sequence, zones, keys and initial target.
3. Every one of the 159<!--=COUNT:map.ids--> `14` ids mapped to one archetype; the tool checks each against its `14` Type line.
4. A dense grid is one stop: one `Tab` out, `Esc` by layers to the panel header, focus keyed by logical id.
5. The ring is two-tone and enclosed by its halo; measured over 12 backgrounds in three themes; a thick variant on the shipped preference.
6. Data never moves focus; a vanished level or row hands focus to a named successor with one label; never the body.
7. Dialogs trap, open on a safe target and restore to the invoker; BQ-0 … BQ-10 are ruled (eight defaults; one PR with `Closes #1303`, `Esc` never cancels with `05`:63 fixed, no third surrogate ceiling).
8. The audit's G-CITE checks that each cited line exists and is non-blank, not that it says what is claimed; cite content is a reviewer's check.
