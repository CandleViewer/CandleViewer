# E15-D05 — Per-component handoff checklist (`16` §11.4; the contracts of CMP-217 and CMP-073 change)

Two blocks (CMP-217 LayoutPresetMenu, CMP-073 WorkspaceSwitcher — every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table once each with a leading `Component` column, then §A the `16` §12 design-QA checklist and §B the `05` §10 template for SCR-022 and SCR-011. Boards are PENDING (text-first PR; the boards PR completes #321): the spec `docs/design/E15/E15-D05.md` names 48 named frames in its §3.2 and every number here is its tool's (`docs/design/_tools/e15_d05_presets_audit.py --json`). Story names are PROPOSED until engineering agrees (the ticket's "agreed with FE").

## Handoff checklist — CMP-217 LayoutPresetMenu (E15-D05, #321)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (boards PR): page `E15-D05 Presets and switcher` (page id pinned after the first build), frames `CMP-217/trigger`, `CMP-217/menu-default`, `CMP-217/menu-twelve`, `CMP-217/menu-saves-t2`, `CMP-217/menu-viewer`, `CMP-217/menu-view-as`, `CMP-217/menu-limit`, `CMP-217/light-menu-t2` and the gallery frames `SCR-022/*` of spec §3.2; PNGs planned at `docs/design/E15/img/E15-D05-01-scr-022-gallery-1920.png` … `E15-D05-06-cmp-217-layout-menu.png`, `E15-D05-10-light-composite.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): variants menu / gallery × states Default / ActiveLayout / WithSavedLayouts / Overflow / SavesGated (the Storybook list, PROPOSED; spec §7, §8, §12); Table 1
- [x] **Keyboard table** — the trigger `Enter` / `Space` / `↓` opens the menu on the active layout; arrows move, `Enter` switches and closes, `Esc` closes and returns focus to the trigger, never gated; `Ctrl+1..9` switches the layout holding that `hotkey_slot` without a prompt (`workspace.preset`, keymap :91; label "Switch layout" PROPOSED, E15-D02 A-6); `Ctrl+S` / `Ctrl+Shift+S` save / save as (`workspace.save` :103, `workspace.save_as` :121) and, while T2, change nothing and re-show the reason once; the gallery: initial focus on the first card, Your layouts' rows → the listbox (one stop, arrows, `Home` / `End`, type-ahead, `Enter` applies, `Space` selects) → Keep current symbols → Apply → Cancel; Table 2
- [x] **Accessible name / role table** — the trigger `button` "{layout}, unsaved changes, Switch layout" with `aria-haspopup="menu"`; `menu` with `menuitemradio` layouts (`aria-checked` on the active one, the chip in the name through CMP-022's expansion) and `menuitem` commands; a T2 item `aria-disabled="true"` + `aria-describedby` → its second line or the banner's node; the gallery `dialog` "Layouts", `listbox` "Presets" with `option` cards named as spec §6.1 ("Two by two: four charts in a grid, four panels"), `aria-selected` on the selected card; Table 3
- [x] **Live data** — none streams: the saved layouts come from `listLayouts` on open, the presets from `listLayoutPresets` once (static); announcements once per committed change (spec §11.3); Table 5
- [x] **Motion pair** — the menu and the dialog open with CMP-041's / CMP-043's pair; motion-reduce = instant (E15-D14 owns the durations); Table 4
- [x] **Density notes** — the menu 320 px wide, rows 24 compact / 32 comfortable, 9 px separators; twelve layouts 410 px in compact; scrolls inside the menu from 22 layouts at compact and 15 at comfortable at 1280×800; the gallery 960×640 / 920×620, header 40 / 48, footer 82 / 90, 5 columns of 169 / 161 px cards 242 / 237 px tall, thumbnails 145×87 / 137×82, Your layouts rows 24 / 32 showing 5 rows (compact) then scrolling; at 200 % the body is the one scroll container and each card a 120 px row (the thumbnail beside its text), so a whole card always fits; the smallest target the 24 × 24 key picker in compact; Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px in compact)
- [x] **Tokens used** — `color.surface.overlay` (menu, dialog), `color.surface.raised` (cards, chips, a gated fill), `color.border.default` (hairlines), `color.border.selected` (the selected ring), `color.focus.ring`, `color.text.primary` / `.secondary` / `.tertiary`, `color.text.disabled` (the availability grey only), `color.text.on-action` + `color.action.primary.default` (Apply), `color.status.danger.default` (Delete layout), `opacity.disabled` (the validity look only), `elevation.popover` / `.dialog`, `radius.card` / `.dialog` / `.xs`, `space.dialog.padding` / `space.inset.*`, `size.row.height`, `size.icon.sm` / `.md`, `type.ui.body` / `.caption` / `.heading-sm`; never `color.text.disabled` or `opacity.disabled` on a T2 label, glyph or reason
- [x] **Data contract confirmed** — `22` `listLayoutPresets` (static, one page; `LayoutPreset {id, name, description, is_builtin, pane_count, layout}`), `listLayouts` / `createLayout` / `updateLayout` / `deleteLayout` (`LayoutInput.hotkey_slot` 1..9 unique, 409 `hotkey_slot_taken` / `name_taken` / `limit_reached`, 412 on `If-Match`); gaps G-1 … G-8 of spec §19 (no served semantic presets, no thumbnail field, no dirty field) — contract-first, never edited here
- [ ] **Contrast and CVD** — PENDING until the boards PR (the pairs are PROPOSED `tools/contrast/pairs.mjs` rows for E15-S04): spec §13 — 60 gated pairs, 0 FAIL; card name 14.35 / 15.62 / 16.25, T2 label 5.20 / 5.44 / 10.36, T2 reason 8.14 / 8.26 / 13.27, the selected ring on the dialog 4.52 / 3.80 / 6.15, the key chip 14.35 / 15.62 / 16.25; the validity look 2.59 / 1.96 / 2.58 reported with its full-opacity reason; the CVD rows in spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-073 WorkspaceSwitcher (E15-D05, #321)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E15-D05 Presets and switcher`, frames `SCR-011/expanded`, `SCR-011/collapsed`, `SCR-011/search`, `SCR-011/context-menu`, `SCR-011/rename-inplace`, `SCR-011/rename-clash`, `SCR-011/dirty`, `SCR-011/empty`, `SCR-011/loading`, `SCR-011/error`, `SCR-011/menu-viewer`, `SCR-011/menu-view-as`, `SCR-011/last-workspace`, `SCR-011/limit`, `SCR-011/switch-dirty`, `SCR-011/new-workspace`, `SCR-011/light-rail`; PNGs planned at `docs/design/E15/img/E15-D05-07-scr-011-rail-switcher.png`, `E15-D05-08-scr-011-states-gates.png`, `E15-D05-10-light-composite.png`
- [ ] **Variants × States matrix** — PENDING: variants rail-tree / search-combobox × states Default / Empty / ManyWorkspaces / Dirty / ViewAs (the Storybook list, PROPOSED; spec §10); Table 1
- [x] **Keyboard table** — the rail is one Tab stop (`role="tree"`): arrows move, `Enter` opens, type-ahead; `Shift+F10` (PROPOSED) or the Menu key opens the row's menu (Open, Rename…, Duplicate, Set as default, Move up, Move down, Export…, Delete…); Rename… turns the row into the "Workspace name" input — `Enter` saves, `Esc` reverts; the search combobox above 20 workspaces: typing filters, `Enter` opens the first match, `Esc` clears; `Alt+1..9` (`global.nav_rail` :81) moves between the rail's items, never between workspaces; a T2 item is arrow-reachable, `Enter` re-shows its reason; no next / previous workspace chord yet (E15-D02 §7 row 17, E15-D15); Table 2
- [x] **Accessible name / role table** — `tree` "Primary" (CMP-071's `nav`) with `treeitem` rows named "{name}", "{name}, unsaved changes", "{name}, open", "{name}, default", `aria-current="page"` on the current one; the "+" row `button` "New workspace"; the search `combobox` "Search workspaces" with `aria-expanded` and the results count polite once per settled query; the rename `textbox` "Workspace name"; the menu's T2 items `aria-disabled="true"` + `aria-describedby`; Table 3
- [x] **Live data** — none streams: `listWorkspaces` once (≤ 32, one page) and on a write; the dirty marker is client state (G-3) re-derived on a working-copy change, never per tick; Table 5
- [x] **Motion pair** — expand / collapse transform-only within 120 ms (`14` :329), motion-reduce = instant; E15-D14 owns the durations; Table 4
- [x] **Density notes** — the rail 240 px expanded / 64 collapsed, rows 24 compact / 32 comfortable, the 3 px current bar, the name column 193 px; 18 workspace rows fit at compact and 11 at comfortable at 1280×800 with the search field (19 / 12 without), 30 / 20 at 1920×1080 with it; the cap stacks to 768 / 1,024 px, so the list is a focusable scroll region above the fit; at 125 % the rail grows to a 300 px cap, at 200 % it collapses to 64 px with 48 px rows (E10-D03 §5.4); the New workspace dialog 480×240; the smallest target the 24 × 24 row in compact; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.raised` (the rail, CMP-071), `color.border.selected` (the 3 px bar), `color.surface.selected` (the current row's fill, E10-D03 §5.2) with `font.weight.medium`, `color.text.primary` (names, the dirty marker), `color.text.secondary` (a T2 reason, "default", the "open" ring glyph), `color.text.tertiary` (a T2 label and its lock), `color.text.disabled` (Export… in the availability look only), `color.focus.ring`, `color.surface.overlay` (the menu, the dialog), `color.status.danger.strong` (the 409 glyph), `opacity.disabled` (the validity look only), `size.row.height`, `size.icon.md`, `space.inset.*`, `type.ui.body` / `.caption`
- [x] **Data contract confirmed** — `22` `listWorkspaces` (≤ 32, by `sort_order` then `id`), `createWorkspace` (409 `name_taken` / `limit_reached`), `updateWorkspace` (rename, `is_default`, `sort_order`; `If-Match`, 412), `deleteWorkspace` (409 `last_workspace` "You need at least one workspace."); `WorkspaceInput.name` 1–40 unique per user; no dirty, recency or bulk-order field (G-3, G-5) — contract-first, never edited here
- [ ] **Contrast and CVD** — PENDING until the boards PR: spec §13 — row name 14.35 / 15.62 / 16.25, the current bar 4.89 / 4.13 / 6.66, the focus ring on the rail 6.66 / 5.86 / 17.30, T2 label 5.62 / 5.92 / 11.21 on a gated fill, T2 reason under the button 8.81 / 8.98 / 14.35, all PASS; the open ring glyph 8.81 / 8.98 / 14.35 PASS (E10-D03 §5.2), the current label on its fill 10.17 / 12.82 / 11.51 and the bar on that fill 3.46 / 3.39 / 4.72 PASS; the CVD rows of the bar in spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component | Variant              | State (every one is a Penpot variant and a story)                                                                                                                                                                                            | Penpot variant (planned)                                                                                                                                                                             | Story (planned, PROPOSED)                                     | Notes                                                         |
| --------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------- |
| CMP-217   | menu                 | Default · ActiveLayout (✓, stronger weight) · WithSavedLayouts (keyed, then "(no key)") · Overflow (twelve; scrolling from 22 at compact) · SavesGated (T2: viewer, view-as, 32 layouts) · the viewer's Revert in the availability look      | `CMP-217/menu-default`, `CMP-217/menu-twelve`, `CMP-217/menu-saves-t2`, `CMP-217/menu-viewer`, `CMP-217/menu-view-as`, `CMP-217/menu-limit`                                                          | Default, ActiveLayout, WithSavedLayouts, Overflow, SavesGated | the one T2 class of these surfaces (spec §12); "panels" (D-4) |
| CMP-217   | trigger              | clean · dirty (`*`, "unsaved changes")                                                                                                                                                                                                       | `CMP-217/trigger`                                                                                                                                                                                    | (in Default / ActiveLayout)                                   | no inline key chip: merged E15-D03 D-9; its §4.5 is the hi-fi |
| CMP-217   | gallery (SCR-022)    | Default · Loading · Error · Zoom200 · Text125 · YourLayoutsEmpty · YourLayoutsTwelve · ViewerSentence · ViewAs · KeyPicker · RenameClash · DeleteConfirm · SaveAs · SaveAsInvalid · SaveAsLimit · ApplyClean · ApplyDirty · ApplyDirtyViewer | the `SCR-022/*` frames of spec §3.2                                                                                                                                                                  | (SCR-022 screen stories, E15-S01)                             | one listbox in one order (RULED Q-8)                          |
| CMP-073   | rail tree            | Default · Empty (after a failed create) · ManyWorkspaces (search above 20) · Dirty · ViewAs (writes T2) · Viewer · Limit · LastWorkspace · Loading · Error                                                                                   | `SCR-011/expanded`, `SCR-011/empty`, `SCR-011/search`, `SCR-011/dirty`, `SCR-011/menu-view-as`, `SCR-011/menu-viewer`, `SCR-011/limit`, `SCR-011/last-workspace`, `SCR-011/loading`, `SCR-011/error` | Default, Empty, ManyWorkspaces, Dirty, ViewAs                 | the rail host is the tree, the search the combobox (D-8)      |
| CMP-073   | row menu, rename     | menu open · rename-in-place · rename clash                                                                                                                                                                                                   | `SCR-011/context-menu`, `SCR-011/rename-inplace`, `SCR-011/rename-clash`                                                                                                                             | (in Default / Dirty)                                          | Delete… → SCR-025's typed confirm (E15-D08)                   |
| CMP-073   | New workspace dialog | default · invalid Name (validity look)                                                                                                                                                                                                       | `SCR-011/new-workspace`                                                                                                                                                                              | NewWorkspace                                                  | Start from in the gallery's order, Scalping preselected       |

### Table 2 — Keyboard

| Component | Key                                                 | Action                                                         | Focus after                   | Global conflict? (`05` §3.2 / §3.3)                   | Notes                                                      |
| --------- | --------------------------------------------------- | -------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| CMP-217   | `Ctrl+1..9`                                         | switch to the layout holding that slot; no prompt              | unchanged                     | browser tab switch — `reservedOverride` (keymap :98)  | `workspace.preset` :91; defect H-1 (ranges never dispatch) |
| CMP-217   | `Ctrl+S` / `Ctrl+Shift+S`                           | save / save as; while T2 nothing, the reason re-shown once     | unchanged / the dialog's Name | browser save — `reservedOverride` (:103); none (:121) | `workspace.save`, `workspace.save_as`                      |
| CMP-217   | `Enter` / `Space` / `↓` on the trigger              | open the menu                                                  | the active layout             | none                                                  | —                                                          |
| CMP-217   | arrows, `Enter`, `Esc`                              | move; switch and close; close                                  | the trigger on close          | none (`Esc` the innermost cancel)                     | a T2 item is reached, never activated                      |
| CMP-217   | gallery `Tab` order                                 | rows → listbox → Keep current symbols → Apply → Cancel → Close | the next stop                 | none                                                  | initial focus the first card                               |
| CMP-217   | listbox arrows / `Home` / `End` / `Enter` / `Space` | move the selection; apply; select                              | the card / the workspace      | none                                                  | type-ahead by name                                         |
| CMP-073   | arrows, `Enter`, type-ahead                         | move in the tree; open                                         | the row / the workspace       | none                                                  | `role="tree"` (D-8)                                        |
| CMP-073   | `Shift+F10` (PROPOSED), Menu key                    | the row's menu                                                 | Open                          | none at the base                                      | E15-D02 §7 row 10 :591; the same key opens the panel menu  |
| CMP-073   | `Enter` / `Esc` in the rename input                 | save / revert                                                  | the row                       | none                                                  | no `F2` (RULED Q-22)                                       |
| CMP-073   | typing / `Enter` / `Esc` in the search              | filter; open the first match; clear                            | the field                     | none                                                  | CMP-048; above 20 workspaces                               |
| CMP-073   | `Alt+1..9`                                          | the rail's items                                               | the item                      | none                                                  | `global.nav_rail` :81; never a workspace                   |
| —         | next / previous workspace                           | none yet                                                       | —                             | `Ctrl+Tab` is the browser's                           | E15-D02 §7 row 17; E15-D15 chooses the PROPOSED chord      |

### Table 3 — Accessible name / role

| Component | Element              | Role                          | Accessible name (source)                                                                                                                          | States / properties                                                                     |
| --------- | -------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| CMP-217   | the trigger          | `button`                      | "{layout}, Switch layout", dirty "{layout}, unsaved changes, Switch layout" (spec §7)                                                             | `aria-haspopup="menu"`, `aria-expanded`                                                 |
| CMP-217   | a saved layout item  | `menuitemradio`               | "{name}, Control plus {n}" (CMP-022's expansion) or "{name}, no key"                                                                              | `aria-checked` on the active one                                                        |
| CMP-217   | a command item       | `menuitem`                    | "Save layout" · "Save as new layout…" · "Revert to saved…" · "Browse presets…"                                                                    | T2: `aria-disabled="true"` + `aria-describedby` → the second line or the banner's node  |
| CMP-217   | the gallery          | `dialog`                      | "Layouts"                                                                                                                                         | `aria-modal`; close "Close Layouts"                                                     |
| CMP-217   | the Presets listbox  | `listbox` / `option`          | "Presets"; the §6.1 names ("Scalping: one large chart beside the DOM ladder and tape, stacked, three panels; the order ticket opens as a drawer") | `aria-selected`; `aria-activedescendant`; `aria-busy` while loading                     |
| CMP-217   | a thumbnail          | `img`                         | the §6.1 `alt` ("Scalping: chart, DOM ladder, tape")                                                                                              | static SVG                                                                              |
| CMP-217   | Keep current symbols | `checkbox`                    | "Keep current symbols"                                                                                                                            | checked by default                                                                      |
| CMP-217   | a Your layouts row   | `textbox`, `button`, `button` | "Layout name"; "Hotkey, Control plus 3"; "Delete Wide chart"                                                                                      | T2 on the writes for a session that cannot save; the viewer's section the sentence form |
| CMP-217   | the empty sentence   | `status` (CMP-026)            | the sentence                                                                                                                                      | the CTA omitted for a viewer                                                            |
| CMP-073   | the rail             | `tree` inside `nav` "Primary" | —                                                                                                                                                 | one Tab stop                                                                            |
| CMP-073   | a workspace row      | `treeitem`                    | "{name}" · "{name}, unsaved changes" · "{name}, open" · "{name}, default"                                                                         | `aria-current="page"` on the current one                                                |
| CMP-073   | the "+" row          | `button`                      | "New workspace"                                                                                                                                   | T2 for a session that cannot save (2a under it)                                         |
| CMP-073   | the search           | `combobox`                    | "Search workspaces"                                                                                                                               | `aria-expanded`; results count polite                                                   |
| CMP-073   | the rename input     | `textbox`                     | "Workspace name"                                                                                                                                  | 1–40; the validity look on the implicit submit                                          |
| CMP-073   | the row menu         | `menu` / `menuitem`           | the eight items                                                                                                                                   | T2 on the six writes; Delete… opens an `alertdialog` (E15-D08)                          |
| CMP-073   | New workspace…       | `dialog`                      | "New workspace"                                                                                                                                   | `select` "Start from"                                                                   |

### Table 4 — Motion pair

| Component | Property               | motion-safe                                        | motion-reduce | Duration / easing tokens             |
| --------- | ---------------------- | -------------------------------------------------- | ------------- | ------------------------------------ |
| CMP-217   | menu open              | CMP-041's pair (E15-D14 owns the timing)           | instant       | CMP-041's                            |
| CMP-217   | gallery open           | CMP-043's pair (the scrim fades, the card at once) | instant       | `motion.duration.normal` (CMP-043's) |
| CMP-217   | the Undo toast         | CMP-045's pair                                     | instant       | CMP-045's                            |
| CMP-073   | rail expand / collapse | transform-only within 120 ms (`14` :329)           | instant       | E15-D14                              |
| CMP-073   | rename-in-place        | none (the label becomes the input)                 | none          | —                                    |

### Table 5 — Live data

| Component | Field                           | Politeness | Cadence                         | Coalescing | Notes               |
| --------- | ------------------------------- | ---------- | ------------------------------- | ---------- | ------------------- |
| CMP-217   | saved layouts, presets          | none       | fetched on open; presets static | n/a        | never a live region |
| CMP-217   | the layout-changed announcement | polite     | once per apply or switch        | n/a        | AN-1 / AN-2         |
| CMP-073   | the workspace list              | none       | once; after a write             | n/a        | ≤ 32, one page      |
| CMP-073   | the dirty marker                | none       | on a working-copy change        | n/a        | client state (G-3)  |
| CMP-073   | the search results count        | polite     | once per settled query (500 ms) | n/a        | CMP-048             |

### Density

| Component | Mode        | Row / control height                                                                            | Padding tokens                                 | Smallest target                   |
| --------- | ----------- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------- | --------------------------------- |
| CMP-217   | compact     | menu rows 24, separators 9; gallery header 40, footer 82, Your layouts rows 24, cards 242 / 237 | `space.dialog.padding` 24; `space.inset.md` 12 | 24 × 24 (the key picker, Delete…) |
| CMP-217   | comfortable | menu rows 32; header 48, footer 90, Your layouts rows 32                                        | `space.dialog.padding` 24                      | 32 × 32                           |
| CMP-073   | compact     | rows 24; the 3 px bar; the 64 px collapsed rail                                                 | `space.inset.sm` 8; `space.inset.md` 12        | 24 × 24 (a row)                   |
| CMP-073   | comfortable | rows 32                                                                                         | `space.inset.sm` 8                             | 32 × 32                           |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| —         | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-022 and SCR-011

- [x] Tier-2 / Tier-3 tokens only; 40 bound, 0 missing; no new token (spec §13)
- [ ] Verified in three themes × two densities — PENDING (boards)
- [x] Contrast-matrix: 60 gated pairs, 0 FAIL (the tool's §13 table); PROPOSED `pairs.mjs` rows for E15-S04
- [x] CVD simulation reviewed: the selected ring and the current bar under three deficiencies + greyscale, never alone (spec §13)
- [ ] Every state a Penpot variant and a story — PENDING (boards); the lists in Table 1
- [x] Disabled states: T2 only on merged E15-D02 §8.1's writes (thirteen frames, spec §12); the validity look on Name and the typed delete's Confirm; availability on Revert / Export…; never a bare disabled control
- [x] Loading / empty / error: card skeletons and skeleton rows; the Your layouts sentence and the sentence form; the rail's failed-create empty state; "Presets didn't load." with Retry / "Couldn't load workspaces." with Try again
- [x] Keyboard-interaction table (spec §11.1–§11.2; Table 2)
- [x] Accessible-name / role table (spec §6.1, §11; Table 3)
- [x] Canvas-adjacent strategy: none here (no canvas on these surfaces; the thumbnails are static SVG with `alt`)
- [x] Motion pair: instant under motion-reduce (Table 4; E15-D14)
- [x] Hit targets ≥ 24 px compact; none logged
- [ ] Accessibility role sign-off — E15-D15
- [x] Trading-specific safety: applying a preset never changes the selected account or environment (the footer sentence, RULED Q-19); no workspace delete without the typed confirm; nothing here submits an order
- [x] Estimated values: none here

## B. Accessibility acceptance criteria (`05` §10) — SCR-022 and SCR-011

```gherkin
Feature: SCR-022 preset gallery and SCR-011 workspace switcher — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user opens the layout menu, browses presets, applies one, saves the result as a new layout, renames it, assigns its hotkey and switches workspaces from the rail
    Then every control involved is reachable via Tab or arrow-key navigation (the menu, the listbox, the Your layouts rows, the save-as dialog, the rail tree, the row menu, the rename input, the search)
    And every pointer action has a documented keyboard and click-only path (Move up / Move down for the drag reorder)
    And focus is never moved by a load, a refusal or an announcement
    And a visible 2 px focus ring meeting at least 3:1 is present at every step (6.15 / 5.39 / 15.99 on the dialog, 6.66 / 5.86 / 17.30 on the rail)

  Scenario: Screen-reader operation
    Given the user is using NVDA or VoiceOver with the keyboard and images suppressed
    When the user opens the gallery from "Browse presets…"
    Then the dialog is named "Layouts" and focus lands on the first card
    And each card is announced by its name alone ("Scalping: one large chart beside the DOM ladder and tape, stacked, three panels; the order ticket opens as a drawer") with no "this" and no position word
    And applying announces "Layout changed to Order-flow, 4 panels." politely once
    And in the rail each workspace row is announced with its markers in words ("Scalping, unsaved changes"; "Swing 4H, open"; "Fanout review, default")

  Scenario: Unsaved changes
    Given Layout 1 in Scalping is dirty
    When the user applies Order-flow from the gallery
    Then an alertdialog "You have unsaved layout changes." opens with Save layout, Discard changes and Cancel, focus on Cancel, and Esc cancels
    When the user instead opens Swing 4H from the rail
    Then no dialog opens, the working copy survives, and the Scalping row keeps "unsaved changes" in its name

  Scenario: The gated writes and the exits
    Given a viewer, or a session viewing as another user
    Then Save layout, Save as new layout…, the key picker, Rename, Delete…, New workspace and the row menu's writes keep their role and full label, are aria-disabled, carry the lock glyph and their registered reason (view-as first), and Enter or the chord changes nothing and re-shows the reason once
    And applying a preset, switching a layout or a workspace, Browse presets…, Open, the search, Cancel, Discard changes and Esc are never gated in any session
    And a Name out of range, a 409 refusal, a load failure and a completed change are never drawn as a lock

  Scenario: Colour independence and zoom
    Given the selected card, the current workspace and the dirty marker
    Then each carries a glyph, a weight or a word beside its colour and reads under protanopia, deuteranopia, tritanopia, greyscale and forced-colors
    And at 200 % the gallery fills the modal between the TopBar and the StatusBar with one sticky footer row, the Your layouts disclosure and the body as the one scroll container (each card a row), nothing clipped
    And at the 125 % and 150 % text scales every card, sentence and row reflows without truncation
```
