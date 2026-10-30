# E15-D13 — Per-component hand-off (`16` §11.4; the dock and panel-chrome band)

Four new entries — **CMP-249 MoveModeBar**, **CMP-250 MinimisedPanelTray**, **CMP-251 DockTabGroup**, **CMP-252 WorkspaceTabStrip** — and the eleven entries the pack reconciles. The pack is [E15-D13.md](E15-D13.md); every "§" and "A-n" below is the pack's, and the catalogue text itself is §C's (this file never restates a props table, C-16.5). Every number is the tool's (`docs/design/_tools/e15_d13_ds_audit.py`), filled at its anchor. The usage rules a later panel epic follows are [`docs/design/specs/e15-design-system-contributions.md`](../specs/e15-design-system-contributions.md).

## Hand-off checklist (E15-D13, #367) — the four new entries

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason (`16` §11.4, §13.3).

| Item                     | CMP-249 MoveModeBar                                               | CMP-250 MinimisedPanelTray                          | CMP-251 DockTabGroup | CMP-252 WorkspaceTabStrip                                       |
| ------------------------ | ----------------------------------------------------------------- | --------------------------------------------------- | -------------------- | --------------------------------------------------------------- |
| Final Penpot link        | [ ] PR 3, page `E15-D13 dock band`                                | [ ] PR 3                                            | [ ] PR 3             | [ ] PR 3                                                        |
| Variants × states        | [x] A-3; merged frames `D04`:176–181                              | [x] A-3; `D04`:228                                  | [x] A-3; P6          | [x] A-3; `D03`:387–399                                          |
| Keyboard table           | [x] Table K                                                       | [x] Table K                                         | [x] Table K          | [x] Table K                                                     |
| Accessible name and role | [x] Table N                                                       | [x] Table N                                         | [x] Table N          | [x] Table N                                                     |
| Live data                | [x] the `status` node, once per step, the latest under key repeat | [x] polite once per minimise and restore            | [x] none             | [x] none (the restore announcements are E15-D03's)              |
| Motion pair              | [x] A-3's Motion spec; the timings E15-D14's                      | [x] A-3; E15-D14's                                  | [x] none (a cut)     | [x] none (a cut)                                                |
| Density notes            | [x] Table R                                                       | [x] Table R                                         | [x] Table R          | [x] Table R                                                     |
| Essential exceptions     | [x] none                                                          | [x] none                                            | [x] none             | [x] none                                                        |
| Tokens used              | [x] Table R; the `16` §3 derivation (C-16)                        | [x] Table R; §5 T-3                                 | [x] Table R; §5 T-2  | [x] Table R; the `16` §3 derivation (C-16)                      |
| Data contract            | [x] none new                                                      | [x] none new (the remembered place is E15-D02 §4's) | [x] none new         | [x] none new (`22` `Workspace`)                                 |
| Contrast and CVD         | [x] the tab strip's pairs, E15-D03 §11.2                          | [x] as CMP-252's inactive label                     | [x] CMP-042's (J9)   | [x] E15-D03 §11.2 `tab-active`, `tab-inactive`, `restored-chip` |
| Storybook                | [x] Table S                                                       | [x] Table S                                         | [x] Table S          | [x] Table S                                                     |
| Sign-off                 | [ ] the orchestrator's design approval (BQ-19)                    | [ ] as CMP-249                                      | [ ] as CMP-249       | [ ] as CMP-249                                                  |

## The eleven entries — what each hand-off adds

| Entry                       | §C rows           | The checklist line this pack adds                                                                                                                        | Builder                                       |
| --------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| CMP-073 WorkspaceSwitcher   | A-7 … A-10        | opened from CMP-252's overflow, focus on its first entry; Delete… the typed confirm                                                                      | E15-S03 (#476)                                |
| CMP-080 DockPanel           | A-11 … A-16, A-80 | the focus frame inside the box (a geometry test: the content rectangle equal in both states); the frame is not CMP-039's ring (A-80 notes it in CMP-039) | E15-T02 (#403)                                |
| CMP-081 DockGrid            | A-17 … A-23       | one polite summary per mutation; DOM order by moving the per-pane hosts                                                                                  | E15-T02 (#403)                                |
| CMP-082 PanelHeader         | A-24 … A-30       | every control and the handle at least the 24 px target; the letter rule                                                                                  | E15-S02 (#435), E15-S04 (#477) for the badge  |
| CMP-083 SplitPane           | A-31 … A-37, A-79 | the dock separator's keys and states; the 24 px band                                                                                                     | E15-T02 (#403)                                |
| CMP-213 FuzzyList           | A-61 … A-64       | E15-D07's Table A                                                                                                                                        | E15-S02 (#435)                                |
| CMP-214 DockDropZone        | A-38 … A-43       | the two-stage chooser; the carrier measured two-tone                                                                                                     | E15-T02 (#403), E15-S02 (#435)                |
| CMP-215 FloatingWindowFrame | A-44 … A-46       | the environment word in every window; the rule and the word measured in both chrome states                                                               | E15-S02 (#435); E15-D10 (#364) holds the rest |
| CMP-216 PanelMenu           | A-47 … A-50       | E15-D07's Table A and Table S                                                                                                                            | E15-S02 (#435)                                |
| CMP-217 LayoutPresetMenu    | A-51 … A-55       | E15-D05 A-1                                                                                                                                              | E15-S01 (#401)                                |
| CMP-218 SyncMenu            | A-56 … A-60       | the letter rule; E15-D06 A-1                                                                                                                             | E15-S04 (#477)                                |

## Table K — Keyboard (the four new entries)

| Entry   | Key                                      | Effect                                                                                                             | Source          |
| ------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------- |
| CMP-249 | arrows, `Tab` / `Shift+Tab`              | stage one: the target panel by shared edge, or in reading order                                                    | `D04`:183       |
| CMP-249 | `Enter`                                  | stage one: take the target; stage two: drop on the chosen side                                                     | `D04`:176–180   |
| CMP-249 | arrows                                   | stage two: left, right, top, bottom; the opposite arrow back to the centre                                         | `D04`:183       |
| CMP-249 | `Backspace`                              | back to stage one with the same target                                                                             | `D04`:183       |
| CMP-249 | `Esc`                                    | leave the mode at any step, the layout unchanged; never gated                                                      | `D04`:181       |
| CMP-250 | arrows                                   | move between the tray's tabs (roving `tabindex`)                                                                   | `D04`:228       |
| CMP-250 | `Enter`                                  | restore the panel to its remembered place                                                                          | `D04`:228       |
| CMP-250 | `Shift+F10`                              | that panel's menu (PROPOSED `workspace.panel_menu`)                                                                | `D04`:228       |
| CMP-251 | arrows                                   | move and select (automatic activation)                                                                             | `D02`:610       |
| CMP-251 | `Home` / `End`                           | the first and the last tab                                                                                         | BQ-11           |
| CMP-251 | `Shift+F10`, context-menu key            | that panel's menu (CMP-216); its Move panel enters move mode (no direct chord, RULED Q-4)                          | `D04`:171, :252 |
| CMP-252 | arrows                                   | move focus without activating (manual activation)                                                                  | `D03`:392       |
| CMP-252 | `Enter` / `Space`                        | activate the focused tab                                                                                           | `D03`:390       |
| CMP-252 | `F2`                                     | rename in place; `Enter` commits, `Esc` cancels                                                                    | `D03`:175       |
| CMP-252 | `Home` / `End`                           | the first and the last tab                                                                                         | `D03`:779       |
| CMP-252 | `Shift+F10`, context-menu key            | the tab's menu: Rename…, Close tab (PROPOSED-PENDING; until the row ships, the ×)                                  | `D03`:777, :399 |
| CMP-252 | `Tab` from the tablist                   | the focused tab's × "Close Scalping", then the overflow button, the "+", the toolbar (PROPOSED)                    | `D03`:396–399   |
| CMP-252 | `Enter` / `Space` on the ×               | close the tab: never a prompt, the working copy kept, never gated; focus to the tab that becomes active (PROPOSED) | `D03`:399       |
| CMP-252 | `Enter` / `Space` on "2 more workspaces" | open CMP-073 with focus on its first entry                                                                         | `D03`:396       |
| CMP-252 | `Enter` / `Space` on "+"                 | open its menu: New workspace…, Open workspace… (CMP-073), Import…                                                  | `D03`:397       |

## Table N — Accessible names and roles

| Entry            | Role                               | Name                                                                                                | Notes                                                                                                                                                              |
| ---------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CMP-249          | `status` (`aria-atomic="false"`)   | — (a status has no name)                                                                            | the instruction line spoken on entry and on stage two (E15-D15 F-05, PROPOSED)                                                                                     |
| CMP-250          | `toolbar`                          | "Minimised panels"                                                                                  | each tab a button named for its panel, with the environment word on an order-capable panel                                                                         |
| CMP-251          | `tablist`; each `tab`              | the panel's region name (E15-D03 D-5)                                                               | `aria-selected`; each tab `aria-controls` its panel's `region` (CMP-080 keeps the role; no `tabpanel` is added, `D02`:610); `Shift+F10` › Move panel starts a move |
| CMP-252          | `tablist` "Workspaces"; each `tab` | the workspace's name, with ", unsaved changes" or ", restored, not saved"; a truncated name in full | the T2 writes keep their roles, `aria-disabled` with the reason; a long name's CMP-016 tooltip                                                                     |
| CMP-252 ×        | `button`                           | "Close Scalping"                                                                                    | on the active tab, and on a hovered or focused one; Close tab in the tab's menu                                                                                    |
| CMP-252 overflow | `button`                           | "2 more workspaces"                                                                                 | opens CMP-073                                                                                                                                                      |
| CMP-252 "+"      | `button` (CMP-002) with a menu     | "New or open workspace"                                                                             | New workspace…, Open workspace…, Import…                                                                                                                           |
| CMP-252 rename   | `textbox` (CMP-007)                | the tab's name                                                                                      | `maxlength` 40; on an invalid name `aria-invalid` and `aria-describedby` → the inline error under the row                                                          |

## Table R — Redlines (compact · comfortable; pack §5, §7)

| Element                                     | Compact                                       | Comfortable                                   | Tokens                                                                                                                |
| ------------------------------------------- | --------------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| CMP-249 row (one line)                      | 32<!--=BUDGET:tabs.compact-->                 | 40<!--=BUDGET:tabs.comfortable-->             | derived by `16` §3's rule, no token (C-16); `color.surface.raised`; a bottom `border.hairline` `color.border.default` |
| CMP-250 row                                 | 24<!--=BUDGET:tray.compact-->                 | 32<!--=BUDGET:tray.comfortable-->             | `space.dock.tray.height.*`; `color.surface.raised`; a top `border.hairline` `color.border.default`                    |
| CMP-251 row                                 | 24<!--=BUDGET:header.compact-->               | 32<!--=BUDGET:header.comfortable-->           | `space.panelheader.height.*`; the tabs as CMP-042's (J9)                                                              |
| CMP-252 row                                 | 32<!--=BUDGET:tabs.compact-->                 | 40<!--=BUDGET:tabs.comfortable-->             | derived by `16` §3's rule, no token (C-16); tab padding `space.inset.md`                                              |
| Focus frame (CMP-080) and header bar        | 2<!--=BUDGET:frame--> / 3<!--=BUDGET:bar-->   | 2<!--=BUDGET:frame--> / 3<!--=BUDGET:bar-->   | `border.panel.focus`; `border.thick` + `border.hairline`; `color.focus.ring`                                          |
| Gutter and splitter band (CMP-081, CMP-083) | 4<!--=BUDGET:gutter--> / 24<!--=BUDGET:hit--> | 4<!--=BUDGET:gutter--> / 24<!--=BUDGET:hit--> | `space.dockgrid.gutter`; `size.dock.splitter.hit`                                                                     |
| Sync badge pill (CMP-082)                   | 20<!--=BUDGET:badge.compact-->                | 28<!--=BUDGET:badge.comfortable-->            | `size.control.*` less `space.1`; its hit box the row                                                                  |

**Deprecated, still shipped:** `elevation.dock-focus` (= `elevation.2`) is bound by no dock surface after A-75, because panel focus is the inset frame and never an elevation step (A40). It stays in the token source; removing it is the token owner's MINOR (`16` §11.2 step 7), not this pack's.

## Table S — Storybook lists and builders (`Organisms/Dock/<Name>`; every story in dark / light × compact / comfortable)

| Entry                      | Stories                                                                                                                            | Builder                                  |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| CMP-249 MoveModeBar        | StageOne · StageTwo · Refused · TwoLines200 · Leaving                                                                              | E15-S02 (#435)                           |
| CMP-250 MinimisedPanelTray | OnePanel · ThreePanels · OrderPanelLive · FocusedTab                                                                               | E15-S02 (#435)                           |
| CMP-251 DockTabGroup       | TwoTabs · FiveTabs · FocusedTab · DraggingTab · LongLabel                                                                          | E15-S02 (#435)                           |
| CMP-252 WorkspaceTabStrip  | Default · Dirty · Restored · LongName · Overflow · RenameInPlace · RenameError · CloseOnFocus · SavesGated                         | E15-S03 (#476)                           |
| CMP-080 DockPanel          | Default · Focused · FocusSameBox · Loading · CompactView · Error · Maximised · ReadOnlyNotice · Closable · Resizing(keyboard demo) | E15-T02 (#403)                           |
| CMP-081 DockGrid           | OnePane · TwoByTwo · OnePlusThree · CustomDrag · NAryRow · TabsetLeaf · FourPanelsCompact1280                                      | E15-T02 (#403)                           |
| CMP-082 PanelHeader        | Default · WithActions · WithSyncBadge · NoSync · NarrowHeader · CollapseSteps · ConflictGlyph · Focused · OrderPanelLive           | E15-S02 (#435); E15-S04 (#477) the badge |
| CMP-083 SplitPane          | Horizontal · Vertical · Focused · AtMinimum · Dragging · NAry · InPanel                                                            | E15-T02 (#403)                           |
| CMP-214 DockDropZone       | EdgeZones · CentreTabify · ActiveZone · InvalidZone · ReducedSet · KeyboardChooser · LargeOverSmall                                | E15-T02 (#403) geometry; E15-S02 (#435)  |
| CMP-216 PanelMenu          | E15-D07's Table S (A-49)                                                                                                           | E15-S02 (#435)                           |

The other entries' lists stay in their own trees (`15` §0.3 rule 8): CMP-073 and CMP-217 under `Organisms/*` and `Molecules/*`, CMP-213 and CMP-218 under `Molecules/*`; their rows are A-9, A-55, A-64 and A-59.
