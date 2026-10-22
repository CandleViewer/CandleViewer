# E15 layout flows — F-LAY-1..6 (E15-D02)

**Actors:** P1 owner and P2 manager; P3 viewer where a frame shows the refusal. No order is placed from these surfaces, and no layout action is audited (layout is user preference). **Route:** `/w/:workspaceId` (SCR-020), with modals as `?modal=<name>` (`docs/plan/14-screens-catalogue.md` §0.3). **Screens:** SCR-011, SCR-020, SCR-021, SCR-022, SCR-024, SCR-025, SCR-026, SCR-027, SCR-028, SCR-029. Frames, copy and decisions: `docs/design/E15/E15-D02.md` (D-n, OQ-A..T); board 25 draws each flow as a frame. Shared rules: a layout change writes nothing until Save (`updateLayout`), the working copy of every layout is kept on the device, SCR-029 opens only before a working copy would be discarded, and focus is never moved by a system event. The calls are the contract's (`docs/plan/22-api-openapi.yaml`); each flow ends with what it needs that the contract does not offer yet.

## F-LAY-1 — Create a workspace

```mermaid
flowchart TD
  A1["Rail: New workspace, or the tab strip's + then New workspace"] --> B1{"Role holds workspaces:write?"}
  B1 -->|viewer| C1["New workspace disabled: Your role can't save workspaces."]
  B1 -->|owner or manager| D1["New workspace dialog: name, 1 to 40 characters, and Start from: a preset, Scalping preselected, or a blank layout"]
  D1 -->|Cancel or Esc| E1["Nothing created"]
  D1 -->|Create workspace| F1["createWorkspace: POST /workspaces"]
  F1 -->|409 name_taken| G1["Inline: That name is already in use."]
  G1 --> D1
  F1 -->|409 limit_reached| H1["Inline: You have 32 workspaces, the most you can have."]
  F1 -->|201 with its ETag| I1["createLayout: POST /workspaces/:id/layouts, Layout 1 on Ctrl+1, the preset's tree and panels, the current symbol kept"]
  I1 -->|201| J1["The new tab opens and activates: dock frame with real headers, panels mount on first visibility"]
  I1 -->|fails| K1["The tab opens on the no-layout state: No layout yet, with Browse presets and Start with a blank layout"]
  J1 --> L1["Polite: Workspace Scalping 2 created. Events: workspace.opened, layout.preset_applied entry new_workspace"]
```

- **Keyboard:** the tab strip's `+` by `Tab` and `Enter`; in the dialog the name field takes focus, `Tab` reaches Start from (the gallery's presets in its order, then Blank layout; spec §5.6), `Enter` creates, `Esc` cancels. The gallery is not a step of this flow.
- **Events:** `workspace.opened`; `layout.preset_applied {presetId, entry, keepSymbols, panelCount}`.
- **Contract:** `createWorkspace` then `createLayout`, two calls and not atomic; a workspace with no layout is legal, hence `K1`. Gaps: the role defaults of E15-D01 AD-1 need workflow presets that `listLayoutPresets` does not serve yet (`services/api/candleviewer/api/workspaces_presets.py` serves six grids), and the order ticket has no pane kind, so Scalping opens it as its drawer (G-06).

## F-LAY-2 — Switch workspace with unsaved changes

```mermaid
flowchart TD
  A2["Scalping active, Layout 1 dirty: the tab reads Scalping *"] --> B2{"How does the user leave it?"}
  B2 -->|another tab: arrows, then Enter| C2["Layout 1's working copy kept on this device, no prompt"]
  B2 -->|Ctrl+2 in Scalping| D2["Layout 2 opens, Layout 1 keeps its working copy, no prompt"]
  B2 -->|closes the Scalping tab| E2["Tab closes, working copy kept, the rail shows Scalping *"]
  B2 -->|Revert to saved| F2["SCR-029 revert form, Cancel focused"]
  F2 -->|Cancel or Esc| A2
  F2 -->|Revert to saved| G2["Working copy discarded, the saved layout shown. Event: layout.reset trigger menu"]
  C2 --> H2["getWorkspace for Swing 4H: skeleton, then panels mount"]
  H2 --> I2["Swing 4H active. The Scalping tab still reads Scalping *, named Scalping, unsaved changes"]
  I2 -->|back to Scalping| J2["Working copy restored exactly, still unsaved"]
  E2 -->|reopened from the rail| J2
  J2 -->|Ctrl+S| K2{"updateLayout with If-Match"}
  K2 -->|200| L2["Saved, the * cleared. Event: layout.saved"]
  K2 -->|412| M2["SCR-029 conflict variant, as in F-LAY-3"]
```

- **Keyboard:** the tab strip activates manually (arrows move, `Enter` opens), `Ctrl+1..9` switches layouts, `Ctrl+S` saves.
- **Events:** `workspace.opened`, `layout.saved`, `layout.reset {trigger}`.
- **Contract:** `getWorkspace` returns the workspace with every layout and its token in one request; `updateLayout` with `If-Match` answers `412` when stale. The working copy and the token it started from are client-local by design. This flow replaces `14` SCR-020's "prompt on navigation" (E15-D01 AD-10, E15-D02 A-3).

## F-LAY-3 — Apply a preset over a dirty layout

```mermaid
flowchart TD
  A3["Layout 1 dirty: Scalping *"] --> B3["Layout menu: Browse presets"]
  B3 --> C3["SCR-022: Order-flow chosen, Keep current symbols on. Event: layout.preset_previewed"]
  C3 -->|Cancel or Esc| Z3["Gallery closes, nothing changes"]
  C3 -->|Apply| D3{"Working copy dirty?"}
  D3 -->|no| H3["Working copy replaced by Order-flow, panels reused by kind, Undo offered"]
  D3 -->|yes| E3["SCR-029 unsaved variant, Cancel focused"]
  E3 -->|Cancel or Esc| C3
  E3 -->|Discard changes| H3
  E3 -->|Save layout| F3{"updateLayout for Layout 1 with If-Match"}
  F3 -->|200| H3
  F3 -->|412| G3["SCR-029 conflict variant: re-read with getLayout, differences as text, the line Then Order-flow is applied, Cancel focused"]
  G3 -->|Keep mine, with the fresh token| F3
  G3 -->|Load theirs| H3
  G3 -->|Save mine as new layout| S3["Save-as dialog, createLayout, then the preset applies to Layout 1"]
  G3 -->|Cancel or Esc| E3
  S3 --> H3
  H3 --> I3["Polite: Layout changed to Order-flow, 4 panels. Layout 1 stays dirty until saved"]
  I3 --> J3["Events: layout.preset_applied entry gallery, and layout.conflict_resolved choice whenever SCR-029 opened"]
```

- **Conflict from a pending preset:** every choice but Cancel settles the save and then applies the preset (spec §5.7): Keep mine after its write, Load theirs at once (the stored version becomes the base the preset replaces, and Undo returns it), Save mine as new layout once the new layout exists; Cancel returns to the unsaved variant.
- **Keyboard:** `[Layout ▾]` by `Tab` and `Enter`; cards by arrows; `Space` toggles Keep current symbols; `Enter` applies; in SCR-029 `Tab` moves between the verbs and `Esc` is Cancel.
- **Events:** `layout.preset_previewed`, `layout.preset_applied`, `layout.conflict_detected`, `layout.conflict_resolved {choice}`.
- **Contract:** `listLayoutPresets` gives a complete `LayoutInput` without symbols; there is no server "apply". `updateLayout` replaces the whole pane set and `docs/plan/21-database-schema.md` §3.8.1 keeps no history, so Undo is the client's. `createLayout` may answer `409 name_taken`, `hotkey_slot_taken` or `limit_reached` (32 layouts).

## F-LAY-4 — Add a panel

```mermaid
flowchart TD
  A4["Add panel in the tab strip, or Add panel from the Ctrl+K palette"] --> B4["SCR-024: search and categories, entries disabled with their reasons"]
  B4 -->|Esc| Z4["Picker closes, nothing added"]
  B4 --> C4["CVD chosen"]
  C4 --> D4["Place: Right of Chart, with the mini-map preview"]
  D4 --> E4{"Layout already holds 16 panels?"}
  E4 -->|yes| F4["Add disabled: This layout has 16 panels, the most it can hold. Close one first."]
  E4 -->|no| G4{"Estimated frame cost over the budget?"}
  G4 -->|yes| H4["Confirm with the measured and the estimated cost, Cancel focused"]
  H4 -->|Cancel| D4
  H4 -->|Add panel anyway| I4
  G4 -->|no| I4["New pane at the next free slot, its leaf at the chosen place, layout dirty"]
  I4 --> J4["Panel mounts, then subscribes its topics"]
  J4 --> K4["Polite: CVD added to the right of Chart. Event: layout.panel_added type cvd, placement right"]
```

- **Keyboard:** typing filters, arrows move through results, `Tab` reaches the Place select, `Enter` adds.
- **Events:** `layout.panel_added {type, placement}` (SCR-024 calls it `panel.added`).
- **Contract:** nothing is written until Save (`updateLayout`); at most 16 panes per layout; a kind must be one of `PaneKind`'s twelve, and the account kinds carry no symbol or interval. The cost estimate is client-side, from E15-K01's measurements.

## F-LAY-5 — Pop out and return (float and re-dock)

```mermaid
flowchart TD
  A5["DOM focused: Shift+F10 opens its panel menu"] --> B5{"Desktop app?"}
  B5 -->|browser| C5["No Pop out item. Footnote: Multi-window workspaces need the desktop app."]
  B5 -->|desktop| D5["Pop out, or Ctrl+Shift+O"]
  D5 --> E5{"A fifth GPU-heavy window?"}
  E5 -->|yes| F5["Confirm with the measured and the estimated cost, Cancel focused"]
  F5 -->|Cancel| A5
  F5 -->|Pop out anyway| G5
  E5 -->|no| G5["Window opens at its remembered bounds: DOM, BTCUSDT, LIVE badge, feed chip, sync badge, Pin on top"]
  G5 --> H5["Leaf removed, pane kept, layout dirty. Polite: DOM popped out to its own window."]
  H5 --> I5{"How does it come back?"}
  I5 -->|Return to workspace, or the window's close| J5{"Is its old place still in the tree?"}
  J5 -->|yes| K5["Leaf re-inserted at its old place"]
  J5 -->|no| L5["Docked right of the focused panel"]
  K5 --> M5["Window closes. Polite: DOM returned to the workspace."]
  L5 --> M5
  I5 -->|the app quits| N5["Windows close with the app and reopen at the next launch"]
  N5 -->|their display is gone| O5["Reopens on the primary display, with a notice"]
  M5 --> P5["Events: layout.panel_floated, panel.redocked, window.opened, window.closed"]
```

- **Keyboard:** `Shift+F10`, arrows, `Enter`; in the window `Tab` reaches Return to workspace first.
- **Events:** `layout.panel_floated` (SCR-027 calls it `panel.floated`), `panel.redocked`, `window.opened`, `window.closed`.
- **Contract:** no layout call: `ShellPort.windows` `float(paneId, route)`, `redock(windowId)`, `saveState`, `restoreState` (`apps/web/src/shell/ShellPort.ts`), and the pane stays in the layout with no leaf ("kept (floating or minimised, placed by the client)", `LayoutGridSpec`). Gaps: the shell's `paneId` against the contract's `slot_index` (G-03); bounds stay on the device, since `/settings/windows` (`docs/plan/12-sitemap.md` §6.2, R-205) is a route with no operation (G-05).

## F-LAY-6 — Export, then import on another machine

```mermaid
flowchart TD
  A6["Machine 1, owner: the workspace menu's Export"] --> B6["exportWorkspace: GET /workspaces/:id/export while the preview shows Preparing the file"]
  B6 -->|fails| R6["Couldn't prepare the file, with Try again. Nothing exported"]
  B6 -->|200| C6["Export preview built from that bundle: what it includes, by count, and what is never included"]
  C6 -->|Cancel| Z6["Nothing exported"]
  C6 -->|Download file| S6["The same bundle saved as a file, exactly what the preview listed. Event: workspace.exported"]
  S6 --> D6["Machine 2, owner or manager: the tab strip's +, then Import"]
  D6 --> E6{"Role holds workspaces:write?"}
  E6 -->|viewer| F6["Import disabled: Your role can't save workspaces."]
  E6 -->|yes| G6["SCR-026: Choose file, or drop it"]
  G6 --> H6["Validated in a worker: size, format, schema, version, panels"]
  H6 -->|over the size cap, 2 MB by E15-S07's default| I6["Rejected: the size and the limit stated, nothing imported"]
  H6 -->|malformed or schema error| J6["Rejected: the offending key named, nothing imported"]
  H6 -->|exported by a newer version| K6["Refused: both versions stated, nothing imported"]
  I6 --> X6["Event: layout.import_rejected reason"]
  J6 --> X6
  K6 --> X6
  H6 -->|valid| L6["Preview table: layouts, panels, symbols, groups, dropped items with reasons, and the no-credentials line"]
  L6 -->|Cancel| Y6["Nothing imported"]
  L6 -->|Import as new workspace| M6{"32 workspaces already?"}
  M6 -->|yes| N6["Refused: delete one, then import again"]
  M6 -->|no| O6["A new workspace, then each layout, the name made unique"]
  O6 --> P6["The new tab opens. Polite: Imported Scalping 2, 7 panels, 2 layouts, 2 items dropped. Event: layout.imported"]
```

- **Keyboard:** the file input is a labelled button reached by `Tab`; the drop zone only adds to it; the preview table is read row by row.
- **Events:** `workspace.exported`, `layout.imported`, `layout.import_rejected {reason: size | parse | schema | version | semantic}`.
- **Contract:** `exportWorkspace` is specified but not yet served (`openapi_pending` in `services/api/tests/unit/architecture/composition_allowlist.json`); its text promises "no credentials, account identifiers or PnL figures". The preview is built from the fetched bundle and Download file saves that same bundle, so what the owner checks is what is sent; a bundle can also carry drawings (with their text labels), chart templates and indicator presets, which the preview counts. No operation takes a bundle yet (`WorkspaceBundle`), and the `POST /workspaces` with `from_bundle` that the export text names has no field in `WorkspaceInput`; done client-side as `createWorkspace` then `createLayout` per layout, the import is not atomic. E15-S07 lands the contract first (G-12), including how a bundle's drawings find their new layout ids and the size cap (its default 2 MB).
