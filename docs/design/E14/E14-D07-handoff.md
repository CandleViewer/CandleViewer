# E14-D07 — Per-component handoff checklist (`16` §11.4)

Per `docs/plan/16-design-system-brief.md` §11.4 and §13.3 item 8 (`02` §4.2): this SCR ticket **changes** two PROPOSED component contracts — **CMP-240 TreeView** (E13-D02 G-1: the drawings-row kind gains the sync-marker column, the sync row kind, the off-screen tag, the anchor read-out in the label, the label-template slot, `aria-setsize` / `aria-posinset` per sibling set, the type sub-groups, the row-kind T2 rule and the locked state leg — CMP-079 RbacGate on the role legs, CMP-019 Icon `lock` as the T2 badge and the leading glyph) and **CMP-243 BulkActionBar** (E13-D02 G-4: the drawings legs — the T2-by-row-kind rule with CMP-079 RbacGate on the role legs and CMP-019 Icon `lock` leading the T2 actions, the locked-skip, the delete-confirm hook with the multi-pane copy, the 12 px gaps around Delete, the two-row wrap at the shell's widths; the deferred Apply template entry absent, spec C-23) — and **introduces** one contract without a component id: **the drawing row label templates** (the visible label = the accessible name, per `DrawingTool`). The component ids are E13-D02's PROPOSED G-1 / G-4 — **no id is invented here; E05 / `15`'s owner registers them** (the standing deviation). Consumers: E05 / `15`'s owner (the ids and the catalogue text), E13-D04 (the tree's `15` text if E13 keeps it), E14-S08 (the implementation story), E14-D10 (the keyboard and name tables, the screen-reader script) and E14-D12 (the handoff pack). Every PENDING line below waits for the boards PR that completes #351; nothing is claimed drawn.

## Handoff checklist — PROPOSED CMP-240 TreeView — the drawings-row kind (E14-D07, #351)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: PENDING the boards PR. Page `E14-D07 Object tree drawings and sync` (id pinned once created; never a URL, host, team or file id); planned PNGs `docs/design/E14/img/E14-D07-01-branch-anatomy-20.png`, `-02-row-states-dark.png`, `-03-row-states-light.png`, `-06-scale-0-20-500.png`, `-07-sync-and-coupling-dark.png`, `-08-sync-and-coupling-light.png`, `-09-a11y-contrast-storybook.png`
- [ ] N/A — **Variants × States matrix**: PENDING until drawn; Table 1 lists the planned frames (spec §4's 25 state rows as `SCR-036/drawings-<state>` frames across boards 02, 03, 04 / 05 (`drawings-restored-reduced`), 06, 07, 08, 09)
- [x] **Keyboard table** — Table 2: E13-D02 D25 cited row by row (never re-typed), with this ticket's rows marked — `Enter` on the sync row (SCR-023), `Esc` in the filter clearing first (spec C-17), the T2 and the locked-row keys; the eye, lock and tag buttons are pointer targets with key twins (D25: one roving stop); no key added, the tool's lint gate (spec §9.1)
- [x] **Accessible name / role table** — Table 3: the shell's names cited (E13-D02 §11.3) plus the drawings-only rows — the row's name = the template label untruncated + the state words + the position from `aria-posinset` / `aria-setsize`; the tag button "Off-screen — reveal on chart" (a pointer target); the sync row "Shared with every BTCUSDT pane in this layout · Sync group" (a level-2 `treeitem`); the sub-group row "Lines (7)" with `aria-expanded`; the T2 surfaces compose CMP-079 RbacGate (the role legs, view-as first then `workspaces:write`; the locked state leg is not wrapped) and CMP-019 Icon `lock` (`decorative=false`, "Not available") — the 8 px badge on the T2 eye / lock buttons and the glyph leading the T2 menu items (spec §9.3, §9.4, §11)
- [x] **Live data** — Table 5: the anchor read-out updates on commit (the 500 ms drag debounce of `batchUpsertDrawings`, `22` 8812), never per frame; the group and sub-group counts; the hide-all count; none announced per change beyond E13-D02 §11.4's rows (spec §5.1, §9.5)
- [x] **Motion pair** — Table 4: the restore flash `motion.duration.normal` / `motion.easing.standard` ↔ `motion.duration.instant` under `motion-reduce` with the "restored" tag as the carrier (E14-D09 owns the curve); the sub-group expand instant in both modes (E13-D02 §11.6) (spec §8.2)
- [x] **Density notes** — Density table: rows 24 / 32 px, the indent step 16 / 20, the 12 px tile glyph, the 20 px tag in a 24 px hit box where it is a button, the icon buttons 24 × 24 / 32 × 32; the smallest target 24 × 24 in both modes (spec §3)
- [x] **Essential-exceptions log** — none (24 × 24 is the floor; the tag button has a 24 px hit box)
- [x] **Tokens used** — spec §3, §4, §10: `color.surface.overlay`, `color.surface.hover`, `color.surface.selected`, `color.surface.raised`, `color.surface.canvas`, `color.text.primary`, `color.text.secondary`, `color.text.tertiary`, `color.action.secondary.default` (the CMP-001 secondary face of the toast's Undo), `color.border.default`, `color.focus.ring`, `color.status.warning.subtle`, `color.status.warning.strong`, `color.status.danger.strong`, `type.ui.label`, `type.ui.caption`, `size.icon.sm`, `radius.xs`, `space.1`, `motion.duration.normal`, `motion.duration.instant`, `motion.easing.standard`; none invented (CMP-011's `color.chip.*` does not exist — spec G-4, PROPOSED); Penpot token sets = `packages/ui/tokens` at the base `698276854abd6f1dd3dba5c0005746257ef8b9b7`
- [x] **Data contract confirmed** — `22` `listDrawings` (the rows; `limit` ≤ 500 per page, spec G-7), `updateDrawing` (`DrawingInput.visible` / `.locked` / `label` / `z_index`), `deleteDrawing`, `createDrawing` (Duplicate), `batchUpsertDrawings` (the bulk legs); the off-screen test is the engine's viewport intersection over `26` §3.9's object index — `22`'s `Drawing` carries `geometry.points` only (spec G-12); the sync state against PROPOSED fields (spec G-1, G-2) — read as text, never edited
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; the tool's numbers (35 pairs × 3 themes, FAIL 0; 33 CVD rows, 6 fill or same-token collapses carrying no meaning alone) and the 10 PROPOSED `pairs.mjs` rows are spec §10
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#351)

## Handoff checklist — PROPOSED CMP-243 BulkActionBar — the drawings legs (E14-D07, #351)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: PENDING the boards PR. Page `E14-D07 Object tree drawings and sync`; planned PNGs `docs/design/E14/img/E14-D07-04-bulk-confirms-undo-dark.png`, `-05-bulk-confirms-undo-light.png`, `-06-scale-0-20-500.png`
- [ ] N/A — **Variants × States matrix**: PENDING until drawn; Table 1 lists the planned frames (spec §7: drawings-only selection · mixed · indicator-only (E13's, cited) · Viewer · view-as · a locked drawing in the selection, on boards 04 / 05 / 06)
- [x] **Keyboard table** — Table 2: the bar is one Tab stop after the tree (E13-D02 §11.1), a `role="toolbar"` whose arrows move along its actions (E13-D02 G-4); `Enter` / `Space` on Delete opens the confirm (Cancel focused); a T2 press re-shows the reason under the pressed action (the notice's sentence; the header notice stays); no key added (spec §7, §9.4)
- [x] **Accessible name / role table** — Table 3: "Delete 7 drawings…" with `aria-describedby` "destructive action" (the removable count of the 9 selected); the T2 legs' `aria-describedby` on the drawer-header notice — composed of CMP-079 RbacGate (the role legs) and CMP-019 Icon `lock` (`decorative=false`, "Not available") leading the T2 Hide / Show / Lock / Unlock / Delete (spec §9.4, §11); no Apply template entry (absent until E14-D04 — spec C-23) (spec §9.3)
- [x] **Live data** — Table 5: the count "9 selected" changes per selection change, never per tick; no live region of its own (E13-D02 §11.4's "3 selected" announces)
- [x] **Motion pair** — Table 4: none — the bar appears and leaves instantly in both modes (E13-D02 §11.6)
- [x] **Density notes** — Density table: the bar 32 / 40 px (E13-D02 §2), wrapping onto two rows at 320 and 360 px (2 × 32 / 2 × 40 — PROPOSED, spec §7.1, A-7), buttons CMP-001 secondary 24 / 32 high on `color.action.secondary.default`, the two 12 px gaps around Delete, the 1 px separator; the smallest target 24 × 24
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — spec §7: `color.surface.hover` (the bar), `color.text.tertiary` (the 1 px edge and the separator), `color.action.secondary.default` (the CMP-001 secondary face), `color.text.primary` (the words), `color.status.danger.strong` (the trash glyph), `color.surface.raised` + `color.border.default` (the T2 fill and hairline), `color.text.secondary` (the reason); never `color.status.danger.default` as a word's ink (2.92 in dark, spec §10.1) and never a red button face
- [x] **Data contract confirmed** — `batchUpsertDrawings` for Hide / Show / Lock / Unlock / Delete over the selected drawings (`operations` ≤ 200 per call; E14-T02 chunks; Delete skips the locked ones — spec C-21); the indicator part of a mixed selection is E13's session state (E13-D03 G-11, merged as #4212)
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; spec §10.1 — the words 12.22 / 14.37 / 13.83 on the bar, the button labels 10.17 / 12.82 / 11.51 on the secondary face, the trash glyph 6.60 / 3.37 / 6.60 on it, the edge 4.79 / 5.44 / 9.54, the ring 5.66 / 5.39 / 14.72
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#351)

## Handoff checklist — the drawing row label templates, the accessible-name contract per `DrawingTool` (E14-D07, #351; no CMP id)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: PENDING the boards PR. Page `E14-D07 Object tree drawings and sync`; the templates card is on board 01 (`docs/design/E14/img/E14-D07-01-branch-anatomy-20.png`)
- [x] **Variants × States matrix** — the 25 templates of spec §2.2 (one per `DrawingTool`, the tool's section 1 renders every example and gates the spec's table); the fragment-drop ladder per drawer width (spec §2.4); Table 1 below lists them by arity class
- [x] **Keyboard table** — N/A for a text contract: type-ahead by the type word that opens every label (E13-D02 D25); Table 2 row
- [x] **Accessible name / role table** — Table 3: the row's name = the template untruncated + the state words, set as a text node (threat model DR7), the user label last; the collision ordinal "(2)" (spec §2.5)
- [x] **Live data** — Table 5: the anchors in the label update on commit, never per frame (spec §5.1)
- [x] **Motion pair** — N/A — nothing animates; a label change is an instant text swap
- [x] **Density notes** — Density table: `type.ui.label` 12 px in both modes; the visible budget 20 (320 compact), 22 (360 comfortable), 8 / 4 (240 compact / comfortable) characters — the shell's real pairings, from spec §3.1's redline (spec §2.4, an estimate at Inter's 0.56 em average advance)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `type.ui.label`, `color.text.primary` / `color.text.secondary` / `color.text.tertiary` (the label by state); none invented
- [x] **Data contract confirmed** — `22` `DrawingTool` (the 25 values; the point counts 1 / 2 / 3 / n = 4 / 13 / 6 / 2), `DrawingPoint` (`t` RFC 3339, `p` a decimal string), `DrawingGeometry.levels` / `.bands` / `.text`, `DrawingInput.label` ≤ 120 code points — read as text
- [ ] N/A — **Contrast and CVD**: the label's inks are the row's (block 1); PENDING on the exports
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#351)

### Table 1 — Variants × States

| Component          | Variant                                        | State (every one a nested frame on the boards of spec §0 and a story)                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Penpot frame (board)                                                           | Story name                                                                                                                                                                       |
| ------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-240 (drawings) | compact / comfortable × dark / light / hc      | default · hover · focus-visible · selected · multi-selected · locked (+ its menu: Move up / Move down / Remove T2, the state leg; + the refused key) · hidden · hidden + selected · pane-local · off-screen · unsaved · conflict · restored · approximate · T2 Viewer · T2 view-as (+ the T2 menu and the T2 header menu's Delete all) · sub-group expanded / collapsed · the empty line (T1 and the sentence form) · the sync row (shared / sync off) · 200 % · forced-colors · hc · reduced motion · loading (the shell's) | 02, 03 (`SCR-036/drawings-<state>`), 04 / 05 (`drawings-restored-reduced`), 09 | `DrawingRow`, `DrawingRowHidden`, `DrawingRowLocked`, `DrawingRowPaneLocal`, `DrawingRowOffscreen`, `DrawingRowRestored`, `DrawingSubGroups`, `ViewerReadOnly`, `ViewAsReadOnly` |
| CMP-240 (scale)    | 0 · 20 · 200 · 500 rows                        | expanded · collapsed by default above 200 · the filter typed · filtered-empty · "500 drawings hidden"                                                                                                                                                                                                                                                                                                                                                                                                                        | 06                                                                             | `Virtualised500`, `FilteredEmpty`, `DrawingSubGroups`                                                                                                                            |
| CMP-243 (drawings) | compact / comfortable × dark / light           | drawings-only selection · mixed · indicator-only (E13's) · Viewer (T2 legs under the one notice) · view-as (T2 legs, checked first) · a locked drawing in the selection (Delete skips it) · a mixed selection holding a locked indicator (Delete T2 under E13-D03's rule, C-21)                                                                                                                                                                                                                                              | 04, 05, 06                                                                     | `DrawingsSelected`, `MixedSelection`, `ViewerReadOnly`                                                                                                                           |
| the templates      | by arity: 1 (4 tools) · 2 (13) · 3 (6) · n (2) | full · the type word dropped (never for a glyph-less tool) · the user label dropped · the end ellipsis (per pairing, spec §2.4; every form a substring of the name); the ordinal "(2)"                                                                                                                                                                                                                                                                                                                                       | 01 (the templates card)                                                        | every `DrawingRow*` story's label                                                                                                                                                |

### Table 2 — Keyboard

| Component          | Key                                 | Action                                                                                                                                                                         | Focus after                                     | Global conflict?                  | Notes                                 |
| ------------------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- | --------------------------------- | ------------------------------------- |
| CMP-240            | E13-D02 D25's rows, verbatim        | `↑/↓`, `←/→`, `Home/End`, type-ahead, `Enter`, `Space`, `Ctrl+Space`, `Shift+↑/↓`, `Shift+Space`, `Ctrl+A`, `Del`, `F2`, `Alt+↑/↓`, `Shift+F10` / Menu, `Ctrl+Z`, `Esc`, `Tab` | per D25                                         | per D25's declared shadows (OQ-G) | cited, not re-typed (spec §9.1)       |
| CMP-240 (drawings) | `Enter` on the sync row             | opens SCR-023 / CMP-218 (E15's); the eye, lock and tag buttons have no tree key — `Space`, the menu's Lock / Unlock and Reveal on chart are their twins                        | the popover; `Esc` returns to the row           | none                              | spec §6.1 (the tree's `Enter`, D25)   |
| CMP-240 (drawings) | `Esc` in the filter                 | clear the filter first, then D25's `Esc` order                                                                                                                                 | the filter                                      | `Esc` reserved, untouched         | spec C-17 for E13's owner             |
| CMP-240 (drawings) | `Enter` on a row                    | the properties popover (read-only for a T2 session)                                                                                                                            | the popover's first field; `Esc` returns        | none                              | E14-D02 §7.1                          |
| CMP-240 (T2)       | `Space`, `F2`, `Del`, `Alt+↑/↓`     | nothing changes; the reason (the notice's sentence) re-shown once under the row, announced once                                                                                | stays                                           | none                              | E09-D09 §9.3 (spec §9.4)              |
| CMP-240 (locked)   | `Del`, `F2`, `Alt+↑/↓`, the drag    | nothing changes; "This drawing is locked." re-shown at the row, announced once (the state leg, no CMP-079)                                                                     | stays                                           | none                              | spec §9.4 (PROPOSED `drawing.locked`) |
| CMP-243            | `Tab` (from the tree); `←` / `→`    | the bar's first action (Hide); the arrows move along the actions (`role="toolbar"`)                                                                                            | the action                                      | none                              | E13-D02 §11.1, G-4                    |
| CMP-243            | `Enter` / `Space` on Delete         | opens the confirm; Cancel focused; nothing acts on the opening key-up                                                                                                          | the dialog, then back to Delete or the next row | none                              | spec §7.2                             |
| CMP-243 (T2)       | `Enter` / `Space` on a gated action | nothing changes; the reason re-shown once under the pressed action, announced once                                                                                             | stays                                           | none                              | spec §7.1                             |
| the templates      | type-ahead letters                  | the next row whose label starts with the letters (the type word opens every label)                                                                                             | the row                                         | none                              | E13-D02 D25                           |

### Table 3 — Accessible name / role

| Component          | Element                                     | Role                    | Accessible name (source)                                                                                | States / properties                                                                                                                                                        |
| ------------------ | ------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-240 (drawings) | a drawings row                              | `treeitem`              | the template untruncated + the state words as text nodes (spec §9.3)                                    | `aria-level="3"`, `aria-selected`, `aria-posinset` / `aria-setsize` (the sub-group), `aria-describedby` → the one notice for a T2 session                                  |
| CMP-240 (drawings) | a sub-group row                             | `treeitem` (parent)     | "Lines (7)"                                                                                             | `aria-expanded`; children in a `role="group"`                                                                                                                              |
| CMP-240 (drawings) | the off-screen tag                          | `button`                | "Off-screen — reveal on chart"                                                                          | a 24 px hit box; a pointer target (`tabindex="-1"`) — the menu's Reveal on chart is the key twin                                                                           |
| CMP-240 (drawings) | the sync row                                | `treeitem` (level 2)    | "Shared with every BTCUSDT pane in this layout · Sync group" / "This pane only — sync off · Sync group" | not selectable; `aria-haspopup="dialog"`; `Enter` opens SCR-023 / CMP-218 (spec §6.1)                                                                                      |
| CMP-240 (drawings) | a locked row's Move up / Move down / Remove | `menuitem` (CMP-041)    | the label                                                                                               | `aria-disabled`; `aria-describedby` → the second line "This drawing is locked." (spec §9.4)                                                                                |
| CMP-240 (drawings) | the eye / lock / menu                       | `button` (CMP-002)      | "{label} visible" · "Lock {label}" · "More actions for {label}" (E13-D02 §11.3)                         | `aria-pressed`; `aria-disabled` + `aria-describedby` for a T2 session; pointer targets (`tabindex="-1"`) with the key twins `Space`, the menu's Lock / Unlock, `Shift+F10` |
| CMP-243            | an action                                   | `button` (CMP-001)      | "Hide" · "Show" · "Lock" · "Unlock" · "Delete 7 drawings…" · "Clear selection" (a `role="toolbar"`)     | Delete: `aria-describedby` "destructive action"; the T2 legs per spec §7.1                                                                                                 |
| CMP-243            | the confirm                                 | `alertdialog` (CMP-044) | "Delete 7 drawings on BTCUSDT?"                                                                         | initial focus Cancel                                                                                                                                                       |
| the templates      | the label                                   | text (the row's name)   | spec §2.2's 25 templates, e.g. "Trendline 13:40 63,900 → 14:05 64,420 · weekly support"                 | never truncated in the name; the tooltip echoes it                                                                                                                         |

### Table 4 — Motion pair

| Component          | Property                        | motion-safe                                                          | motion-reduce                     | Duration / easing tokens                                                       |
| ------------------ | ------------------------------- | -------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------ |
| CMP-240 (drawings) | the restore flash               | `color.surface.selected` → the resting fill (E14-D09 owns the curve) | none — the "restored" tag carries | `motion.duration.normal`, `motion.easing.standard` ↔ `motion.duration.instant` |
| CMP-240            | the sub-group expand / collapse | instant (E13-D02 §11.6)                                              | identical                         | `motion.duration.instant`                                                      |
| CMP-243            | appear / leave                  | instant                                                              | identical                         | `motion.duration.instant`                                                      |
| the templates      | a label change                  | an instant text swap                                                 | identical                         | none                                                                           |

### Table 5 — Live data

| Component          | Field                                    | Politeness | Cadence                         | Coalescing      | Notes                                   |
| ------------------ | ---------------------------------------- | ---------- | ------------------------------- | --------------- | --------------------------------------- |
| CMP-240 (drawings) | the anchor read-out in the label         | none       | on commit (the 500 ms debounce) | the last commit | never per frame (spec §5.1)             |
| CMP-240 (drawings) | the group / sub-group counts             | none       | per add / remove                | —               | the row events announce (E13-D02 §11.4) |
| CMP-240 (drawings) | the hide-all count "500 drawings hidden" | polite     | once per toggle                 | —               | D02 §12                                 |
| CMP-240 (drawings) | the filter's match count                 | polite     | debounced 300 ms                | the last count  | "12 drawings match '64,1'" (spec §9.5)  |
| CMP-243            | "9 selected"                             | none       | per selection change            | —               | "3 selected" announces (E13-D02 §12)    |
| CMP-240 (drawings) | the sync row's text                      | polite     | on change only                  | —               | E14-S09's event (spec §6.1)             |
| the templates      | the label                                | none       | on commit                       | —               | —                                       |

### Density

| Component          | Mode        | Row / control height                                                              | Padding tokens             | Smallest hit target       | Notes                            |
| ------------------ | ----------- | --------------------------------------------------------------------------------- | -------------------------- | ------------------------- | -------------------------------- |
| CMP-240 (drawings) | compact     | row 24 px; icon buttons 24 × 24; the indent step 16                               | `space.1` between controls | 24 × 24                   | the tag 20 px in a 24 px hit box |
| CMP-240 (drawings) | comfortable | row 32 px; icon buttons 32 × 32; the indent step 20                               | `space.1`                  | 24 × 24                   | the tile and the glyph unchanged |
| CMP-243            | compact     | the bar 32 px, two rows (64) at 320 px; buttons 24 high; gaps 12 px around Delete | `space.3` (the gaps)       | 24 × 24                   | E13-D02 §2; the wrap spec A-7    |
| CMP-243            | comfortable | the bar 40 px, two rows (80) at 360 px; buttons 32 high                           | `space.3`                  | 32 × 32                   | the wrap spec A-7                |
| the templates      | both        | `type.ui.label` 12 px                                                             | —                          | — (the row is the target) | the visible budget per spec §2.4 |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all three | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12), filled

**Tokens & visual**

- [x] Uses only published Tier-2 / Tier-3 tokens — spec §3, §10 bind existing names (resolved by the tool); the one missing family CMP-011 names (`color.chip.*`) is a PROPOSED DS request (spec G-4); zero hard-coded hex or px beyond the measured tables and E13-D02's px, which stand.
- [~] Verified in all three themes at both density modes — the matrix is measured in all three themes (spec §10.1); the frames are planned dark compact with the comfortable column and three light twins; PENDING until the boards exist.
- [x] Passes the automated contrast-matrix check for every pair it introduces or touches — the tool: 36 pairs × 3 themes, 26 gated, FAIL 0 (the 11 `pairs.mjs` rows themselves are the DS request of spec §10.4).
- [~] CVD simulation reviewed for any new colour-carrying state — computed now (33 rows, 6 fill or same-token collapses, none carrying meaning alone; spec §10.3); the `cvd_sim.py` run on the exports follows the boards.

**Behaviour & states**

- [~] Every documented State has a corresponding Penpot variant and Storybook story — the states are specified (spec §4; Table 1) and the stories named (spec §12.1); the Penpot frames are PENDING.
- [x] Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control — every role / session leg is E09-D09's T2 under the one drawer-header notice by row kind (spec §9.4); a locked drawing's writes are the state leg (T2 without CMP-079 under PROPOSED `drawing.locked`); the deferred Apply template entry is absent, never a disabled control (the lane ruling; spec C-23); form validity applies to no control (spec §1.4).
- [x] Loading / empty / error states are explicitly designed — loading is the shell's skeleton (cited); the empty line in both forms, the filtered-empty row, the unsaved and conflict tags (spec §4, §5.4).

**Accessibility**

- [x] Keyboard-interaction table completed and matches an implemented, tested keyboard path — Table 2 cites D25 and adds the sync row's `Enter`, the filter's `Esc` step and the T2 / locked rows; E14-S08 implements, E14-Q07 tests.
- [x] Accessible-name / role table completed — Table 3.
- [x] For any canvas-adjacent component the DOM-mirror / windowed-tree strategy is specified — the tree is the objects' accessible equivalent, virtualised with `aria-setsize` / `aria-posinset` per sibling set; the mirror is the data's (E13-D02 D26; spec §5.1, §8.1).
- [x] Motion-safe / motion-reduce pair specified for any animated property — Table 4.
- [x] Hit targets meet the 24 px minimum (compact) / 32 px (comfortable) — Density table; no essential exception.
- [~] Accessibility role has signed off — the owner's `approved` on #351 is the sign-off (Agent-delivery adaptations); E14-D10 re-verifies.

**Trading-specific safety**

- [x] Any component touching order placement, position modification or rule arming states its confirm-gate variant — none does: the branch never trades, arms or creates (spec §1.3); the destructive deletes use CMP-044 `variant="standard"` with Cancel focused and one undo (spec §7).
- [x] Any heuristic / estimated value is chip-tagged — the anchored VWAP's "approximate" word is E14-D05's badge, cited (spec §4).
- [x] Demo / Live env context is visually unambiguous wherever the component can trigger a trading action — N/A: no trading action on the branch; drawings are environment-agnostic (D02 §11).

**Consistency**

- [x] Reuses an existing CMP-\* rather than introducing a near-duplicate — no new component; E13-D02's PROPOSED G-1 / G-4 are cited.
- [x] Storybook stories match the full Variants × States matrix — Table 1 and spec §12.1 (14 stories).
- [~] Component or screen composes only published-library Penpot components — the boards paint literal colours resolved from the token JSON (the lane's export rule); the DS library entries are E13-D04 / E05's.

## B. Accessibility acceptance-criteria template (`05` §10), filled once for "manage a drawing from the object tree without a mouse"

The tree's keyboard contract, names and live regions are E13-D02 §11's (fixed, cited); E14-D02 §9.5 covers creation. This block covers the primary task this ticket adds: **find one line among 500 by keyboard, hide and lock it, delete three and bring them back.**

```gherkin
Feature: SCR-036 drawings branch (E14-D07) — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user finds the horizontal line at 65,684 among 500 drawings, hides and locks it, deletes three lines and undoes the delete
    Then every control involved (the filter, the sub-group rows, the rows, the sync row, the bulk bar, the confirm, the toast's Undo) is reachable via Tab / arrow-key navigation — the eye and lock buttons are pointer targets whose key twins are Space and the menu's Lock (E13-D02 D25)
    And every action has a documented non-drag keyboard equivalent (E13-D02 D25; Table 2) — the filter path is at most 24 keystrokes with the shell's keys (spec §5.3)
    And focus is never silently moved by a background data update or a canvas selection outside the tree
    And a visible focus indicator meeting >= 3:1 contrast is present at every step (color.focus.ring 6.15 / 5.39 / 15.99 on the drawer, 4.72 / 4.81 / 12.26 on a selected row)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the user performs the task
    Then every row reads its template label, its state words and its position (item 3 of 315), the buttons their names and pressed state, the confirm its sentence
    And live data follows E13-D02 §11.4 and spec §9.5: hidden / locked / selected / deleted / restored announced once, polite; the anchors never announced per commit
    And the tree is the objects' accessible equivalent with full parity to the canvas actions (spec §9.2)

  Scenario: Colour-independence
    Given hidden, locked, selected, pane-local, off-screen, unsaved, conflict, restored and T2 rows
    When the frame is rendered in greyscale
    Then every state is still read from its words and glyphs (spec §4, §10.3)
    And the pairs pass deuteranopia / protanopia / tritanopia simulation review (33 rows; the 6 collapses are fills or same-token glyph pairs that carry no meaning alone)

  Scenario: Contrast
    Given the branch is rendered in the dark theme and the high-contrast theme
    Then all text meets >= 4.5:1 (the label 13.27 / 15.02 on the drawer; the T2 label 5.62 / 11.21) and all meaning-carrying glyphs meet >= 3:1 (the trash glyph 6.60 / 6.60 on the secondary face; the type glyph 9.33 / 15.20), per spec §10.1

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When a row is restored by an undo
    Then the row appears in its resting state with the "restored" tag and no flash (Table 4); nothing flashes more than 3 times per second and nothing moves for more than 5 s

  Scenario: Automated gates
    Given the first story that renders the drawings branch is opened
    Then axe-core reports zero new serious/critical violations over the tree, the bar and the confirm
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering the filter path, the T2 press and the confirm's Esc passes
```

Screen-reader spot-testing is deferred to E14-D10 and E14-Q07 / the release-level pass (`05` §8) — stated, not assumed. No owner-approved exception exists.
