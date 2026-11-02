# E47-D09 — Hand-off (`16` §11.4; keyboard operability)

Components: **CMP-059 CommandPalette** (the binding column, "unbound", the invalid-here row), **CMP-094 HotkeyOverlay** (search by name or key, the remap mark, `Ctrl+/`), **CMP-064 KeyboardShortcutRow** (SCR-113's redlines), **CMP-020 Toast** (the inert message), **CMP-079 RbacGate** with **CMP-019** Icon `lock` (the T2 paragraph, spec §12), and the keyboard paths of the census (spec §3) for the surfaces that own them. The spec is [E47-D09.md](E47-D09.md); every "§" below without a prefix is the spec's. These are copy-ready proposals; nothing here edits an owner document.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-059 CommandPalette                    | CMP-094 HotkeyOverlay         | CMP-064 (SCR-113)          | The census paths (§3)                      |
| ------------------------ | ----------------------------------------- | ----------------------------- | -------------------------- | ------------------------------------------ |
| Final Penpot link        | [ ] boards 05, 06, 10 pending             | [ ] board 07 pending          | [ ] board 08 pending       | [ ] boards 01–04, 09 pending               |
| Variants × states        | [x] spec §8                               | [x] spec §9                   | [x] spec §10 (RL-1 … RL-5) | [x] spec §2, §3                            |
| Keyboard table           | [x] CMP-059's, unchanged                  | [x] spec §9 (search)          | [x] RL-1, RL-4             | [x] spec §2, §4, §7                        |
| Accessible name and role | [x] CMP-059's                             | [x] CMP-094's                 | [x] CMP-064's              | [x] spec §2 (select announces)             |
| Live data                | [x] the count, once per query             | [x] the count, once per query | [x] the row's message      | [x] spec §6 (D5)                           |
| Motion pair              | [x] none                                  | [x] none                      | [x] none                   | [x] the view follows; reduced motion snaps |
| Density notes            | [x] E10-D03's                             | [x] E10-D03's                 | [x] none                   | [x] none                                   |
| Essential exceptions     | [x] none                                  | [x] none                      | [x] none                   | [x] none                                   |
| Tokens used              | [x] E10-D03 §6.1's                        | [x] E10-D03 §6.2's            | [x] CMP-064's              | [x] the pending line: §0 board 01          |
| Data contract            | [ ] NO: D09-G5                            | [x] the registry              | [x] the registry           | [ ] NO: D09-G4, D09-G6                     |
| Contrast                 | [ ] measured when boards 05, 10 are drawn | [ ] board 07                  | [ ] board 08               | [ ] boards 01–04                           |
| Storybook                | [x] §D                                    | [x] §D                        | [x] §D                     | [x] §D                                     |
| Sign-off                 | [ ] owner approval pending                | [ ] owner approval pending    | [ ] owner approval pending | [ ] owner approval pending                 |

## §B Who applies what

| A                                        | Target                                           | Applied by                                  |
| ---------------------------------------- | ------------------------------------------------ | ------------------------------------------- |
| `05` §3.5, `05`:36, `05`:88, `05`:101    | `05`                                             | this PR (BQ-12)                             |
| D09-A1 … D09-A4                          | the keymap registry                              | E47-S08 (registry rows; E37-S05 for D09-A4) |
| D09-A5, D09-A6                           | `15` CMP-094, CMP-059                            | the `15` owner, at the owner's sign-off PR  |
| D09-A7, D09-A8, D09-A9, D09-A13, D09-A14 | `14` SCR-012, SCR-013, SCR-113, SCR-040, SCR-021 | the `14` owner, at the owner's sign-off PR  |
| D09-A10, D09-A15, D09-A17                | the inert notice, the refusal, Reset all         | E47-S08                                     |
| D09-A11, D09-A12, D09-A16                | the palette's sources and events (#5280)         | E10-S05 (#5236)                             |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at its pinned commit (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A       | Target                 | Field (`file`:line)     | Old                                                                        | New                                                                                                                                                      |
| ------- | ---------------------- | ----------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D09-A1  | `global.cheatsheet`    | KMAP:62                 | "label": "Hotkey cheatsheet"                                               | insert after: an alias `?` (`Shift+/`), scoped outside text fields, remappable (E47-D09 §9; D09-Q2)                                                      |
| D09-A2  | `global.region_cycle`  | KMAP:105                | "label": "Region cycling"                                                  | insert after the command: a reverse row, `Ctrl+Shift+\` (E47-D04 D04-C1; PROPOSED)                                                                       |
| D09-A3  | `chart.delete_drawing` | KMAP:306                | "confirm": true                                                            | remove: a single delete is undoable and its toast is the confirmation (A11Y-R-E14-D10-F-02)                                                              |
| D09-A4  | `rules.rename`         | KMAP:809                | "label": "Rename node"                                                     | insert after the command: `rules.move_node`, `M`, context Rules, "Move node" (E47-D09 §7; D09-Q1)                                                        |
| D09-A5  | `15` CMP-094           | Purpose (`15`:1047)     | full hotkey cheatsheet overlay, triggered by                               | full hotkey cheatsheet overlay, triggered by `Ctrl+/` (`global.cheatsheet`; `?` a PROPOSED alias), searchable by action or key (E47-D09 §9)              |
| D09-A6  | `15` CMP-059           | Props (`15`:681)        | running it opens its confirmation                                          | insert after: ; `availableIn?` names where an invalid-here command works, shown as its second line (E47-D09 §8; D09-G5)                                  |
| D09-A7  | `14` SCR-012           | Interactions (`14`:368) | fuzzy filter;                                                              | insert after: every registered command is a row — unbound ("unbound"), pointer-only and invalid-here ones included (E47-D09 §8);                         |
| D09-A8  | `14` SCR-013           | Type (`14`:379)         | Two columns grouped by context (Global, Chart, DOM, Ticket, Replay, Rules) | Two columns grouped by the nine shipped contexts (`cheatsheetContexts`), searchable by action or key (E47-D09 §9)                                        |
| D09-A9  | `14` SCR-113           | Validation (`14`:2429)  | a binding cannot collide within the same context                           | insert after: ; a conflict is shown at capture with both actions, and Save stays disabled with the reason until it is resolved (E47-D09 RL-1)            |
| D09-A10 | the inert notice       | DISP:90                 | is not available here                                                      | the sentence W-6: "{label} works in the {contexts} view, not in this view." (E47-D09 §11)                                                                |
| D09-A11 | the palette's actions  | PSRC:122                | !ctx.isValid(c.id)                                                         | list the command; an invalid-here row is T2 with W-8 as its reason; a range command (`isRange`) is one row whose binding reads as its range (E47-D09 §8) |
| D09-A12 | `palette.ran`          | PEV:21                  | readonly name: "palette.ran";                                              | insert after: a PROPOSED `bound` flag, true when the command had a binding (E47-D09 §15)                                                                 |
| D09-A13 | `14` SCR-040           | Validation (`14`:1033)  | drag-to-amend confirms when the new SL is on the wrong side of the mark    | drag-to-amend is refused when the new SL is on the wrong side of the mark, the stop unchanged and the reason shown (`11` US-ORD-008; E47-D09 §4)         |
| D09-A14 | `14` SCR-021           | Behaviour (`14`:556)    | splitters resize by mouse or                                               | splitters resize by mouse or by the focused splitter's own keys (E15-D15 KB-14), never                                                                   |
| D09-A15 | the reserved refusal   | VAL:187                 | is reserved by                                                             | the sentence W-12: "{key} is used by the browser or the system; choose another." (RL-2)                                                                  |
| D09-A16 | the palette's actions  | PSRC:133                | binding === ""                                                             | show "unbound" as the row's binding (K-8)                                                                                                                |
| D09-A17 | Reset all              | HKE:374                 | Every binding is back to its default.                                      | the sentence W-17: "{n} bindings are back to their defaults." (RL-3)                                                                                     |

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component              | Stories                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------ |
| CMP-059 CommandPalette | the merged list + UnboundRow · InvalidHereRow · PointerChordRow · RemappedBinding    |
| CMP-094 HotkeyOverlay  | the merged list + SearchByName · SearchByKey · SearchNoMatch · Remapped              |
| CMP-064 (SCR-113)      | the merged list + ConflictAtCapture · ReservedRefusal · CaptureMode · ResetAllResult |
| CMP-020 Toast          | the merged list + InertBinding                                                       |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

- [ ] Board 01: select a stop, press `↑` five times, hold `↑` under NVDA (one value per half second, no flood), then `Esc`: the stop is where it was, nothing was sent, and W-2 was spoken.
- [ ] Board 01: the same with `Enter`: the confirm opens as the drag's would; one amend is sent.
- [ ] Board 03: a drawing's anchor moves one tick per arrow; the "Edit values…" fields reach the same anchor without a drag.
- [ ] Board 04: Move mode moves a node by arrows, the view follows, `Esc` puts it back.
- [ ] Board 05: an unbound command is listed with "unbound" and runs from the palette; an invalid-here row says where it works.
- [ ] Board 07: after remapping Close all in view to `Ctrl+Shift+F`, the cheatsheet shows it, found by "close all" and by "ctrl shift f".
- [ ] Board 08: a conflicting key is reported before Save, with both actions; a reserved key's refusal names no internals.
- [ ] Board 09: `Ctrl+Enter` in the journal shows the inert message once, non-modally, and says where the action works.
- [ ] Walk every DE row of §3 with the keyboard only on the current build, without documentation; log each row that cannot be completed (T Test).
- [ ] Record `approved` on #1308, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer         | Builds from                        | Waits on       |
| ---------------- | ---------------------------------- | -------------- |
| E31-D01          | spec §4, DE-01, DE-04              | D09-G4         |
| E37-D04, E37-S05 | spec §7, D09-A4                    | D09-G6, D09-Q1 |
| E10-S05 (#5236)  | spec §8, D09-A11, D09-A12, D09-A16 | D09-G5         |
| E47-S08          | spec §9–§11, §C                    | D09-G1, D09-G2 |
| E47-D07 (#1306)  | spec §6, §16                       | —              |
| E47-Q01, E47-Q03 | §G                                 | —              |

## §G QA draft assertions (deterministic; for E47-Q03's keyboard-only Playwright suite)

| QA   | Given / when                                                                                                | Then (assert)                                                                                                                                                                                                        |
| ---- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| QA-1 | as an Owner, enumerate the ids of `keymap.json` minus `global.palette`; open the palette; search each label | every id has exactly one row; each row's binding cell equals the active profile's binding or reads "unbound"; an invalid-here row is `aria-disabled`                                                                 |
| QA-2 | select a working stop; press `↑` three times; press `Esc`                                                   | no amend request was issued; the stop's price equals its price before; the polite region received W-1 and then W-2                                                                                                   |
| QA-3 | remap `positions.close_all` to `Ctrl+Shift+F` and two others; open the cheatsheet and the palette           | both show the three new bindings with "remapped"; a search for the label and for "ctrl shift f" each return the row                                                                                                  |
| QA-4 | focus the journal; press `Ctrl+Enter`                                                                       | one non-modal status message names the Ticket view; focus is unchanged; nothing else ran; a second press within 5 s adds no toast while the first is shown; a press after 5 s shows it again; SCR-014's log holds it |
| QA-5 | hold `↑` on a selected stop for 3 s under a fake clock; release                                             | the polite region received at most one message per 500 ms window and a final message within 250 ms of release; the readout's state updates match; the region is `aria-live="polite"`, never assertive                |

## §H The board plan (drawn later in this PR; a Penpot lane)

The boards of spec §0, on page `E47-D09`; frames named `<surface>/<state> · <theme>`. Data: a seeded synthetic order, book and graph, declared synthetic on every board's face; only the instrument's tick size comes from a recorded fixture. Each board's frames:

| Board | Frames                                                                                                                |
| ----- | --------------------------------------------------------------------------------------------------------------------- |
| 01    | `order-line/selected · dark`, `order-line/pending · dark`, `order-line/confirm · dark`, `order-line/cancelled · dark` |
| 02    | the frames of 01 · light                                                                                              |
| 03    | `drawing/anchor-nudge · dark`, `drawing/edit-values · dark`, `profile/anchor-range · dark`                            |
| 04    | `node/move-mode · dark`, `node/view-follows · dark`, `node/placed · dark`                                             |
| 05    | `palette/unbound · dark`, `palette/invalid-here · dark`, `palette/t2 · dark`, `palette/no-match · dark`               |
| 06    | the frames of 05 · light                                                                                              |
| 07    | `cheatsheet/search-name · dark`, `cheatsheet/search-key · dark`, `cheatsheet/no-match · dark`                         |
| 08    | `hotkeys/conflict-at-capture · dark`, `hotkeys/reserved · dark`, `hotkeys/reset-all · dark`                           |
| 09    | `inert/journal · dark`                                                                                                |
| 10    | the frames of 05 · hc                                                                                                 |

Contrast: every ratio (the "unbound" word, the pending label, the lock row) is measured with the repo contrast tool in each theme when its board is drawn; none is quoted before.

## §I Summary for #1308

1. Text-first keyboard-operability spec + hand-off + default-deny audit tool; 10<!--=COUNT:boards--> boards pending, drawn later in this PR; `05` §3.5 is the normative expansion.
2. One grammar — select, adjust by unit (`Shift` ×10, `PageUp` / `PageDown` ×100), commit through the pointer's own path, cancel restores — with the merged twins as instances.
3. 21<!--=COUNT:census--> census rows cover every drag- and hover-only interaction; the tool maps every `14` line that names one.
4. The order line sends nothing until `Enter`, through the drag's confirm path; `Esc` restores; never one amend per keypress.
5. The palette lists all 75<!--=COUNT:palette--> commands with their current binding or "unbound"; the cheatsheet is searchable by action or key and shows remaps.
6. The inert message says where an action works; SCR-113 reports conflicts before Save; refusals name no internals.
7. The chart keys are E06-D03's and the node graph E37-D02's, with node Move mode added and the pan through it; BQ-0 … BQ-15 are RULED as the defaults (comment 6566806943).
