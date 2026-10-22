# E12-D03 — Component handoff (`16` §11.4), a11y template (`05` §10) and design QA (`16` §12)

Ticket E12-D03 (#201); spec `docs/design/E12/E12-D03.md`. SCR-042 introduces variants of four components, so it carries
one `16` §11.4 block each (`16` §13.3 item 8): CMP-220 IntervalPicker (with the candidates NC-8 and NC-9), CMP-041 Menu,
CMP-069 InfoPanel and CMP-008 NumericStepperInput. CMP-007, CMP-017 and CMP-022 are used as catalogued, apart from
their Tokens lines (spec DS-5), and so are CMP-079 RbacGate (T2) and CMP-019 Icon (the `lock`). The `15` entries stay
with E12-D09 (#244), which adopts or rejects each variant; this file is its input. Tables 4, 5, Density and Essential
exceptions share one shape and are given once. **Status:** text pass; Penpot and PNG lines are PENDING until the
boards step (page `E12-D03`, boards 01–18); the stories are E12-S11's and E12-S12's. Penpot token sets =
`packages/ui/tokens` at `3f0843a8bf5d1570b069e12758f2f891d38e07a3`.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3). `[ ] PENDING` marks a line the boards step or a named ticket closes.

## Handoff checklist — CMP-220 IntervalPicker (E12-D03, #201)

- [ ] **Final Penpot link** — PENDING: page `E12-D03`, boards 01–12 and 16; PNGs `docs/design/E12/img/E12-D03-NN-scr-042-*.png`
- [x] **Variants × States matrix** — table 1; the Penpot variants are PENDING on board 16; E12-S11 and E12-S12 write the stories
- [x] **Keyboard table** — table 2; checked against `keymap.json` (71 commands): the popover root stops every key but the four Global chords, so `1`–`9` never fire `chart.interval_preset` twice; `I` is a proposal (spec §8.2); `Esc` and `Ctrl+K` untouched
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: nothing streams; the trigger's name changes on commit and while pending
- [x] **Motion pair** — shared table 4
- [x] **Density notes** — shared density table
- [x] **Essential-exceptions log** — one shared row: comfortable targets at 32 px (shared table)
- [ ] **Tokens used** — PENDING (E12-D09, DS-2): the entry's Tokens line names `font.mono` and `space.1`; the spec binds `type.num.sm` / `type.num.base`, `color.surface.overlay`, `elevation.popover`, `radius.card`, `radius.control`, `color.action.selected`, `color.border.selected` at `border.thick`, `color.surface.hover` (light: `color.surface.selected` until DS-5), `color.focus.ring` at `border.focus`, `color.text.primary` / `secondary` / `tertiary` (spec §3); E12-D09 corrects the line (DS-2)
- [x] **Data contract confirmed** — `/market/bars` `bar_type` and `param` with the shipped bounds (spec §2); `meta.recording_started_at` (`22:15440`); `PATCH /settings`; G-1b, G-2 and G-3 are named gaps with routes (spec CR-1–CR-3)
- [ ] **Contrast and CVD** — measured by `docs/design/_tools/e12_d03_menu_audit.py` (exit 0, spec §9); the new pairs join `tools/contrast/pairs.mjs` in a separate chore PR; CVD on the exports PENDING
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #201 or the merge

### Table 1 — Variants × States

| Variant                | State                                                                                                           | Penpot variant | Story name                                                 | Notes                          |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- | -------------- | ---------------------------------------------------------- | ------------------------------ |
| trigger                | rest, hover, focus, expanded, pending                                                                           | board 01       | `Molecules/IntervalPicker/Trigger`, `TriggerPending` (new) | name C-39; pending adds " …"   |
| trigger                | non-time mode                                                                                                   | 02             | `TriggerBarMode` (new)                                     | "Vol 50 BTC"                   |
| menu                   | R1 default (flag off)                                                                                           | 01             | `TimeIntervals` (catalogued)                               | Favourites and Time            |
| menu                   | flag on; without Renko                                                                                          | 02, 18         | `BarModes` (catalogued), `BarModesNoRenko` (new)           | the Renko row absent           |
| menu                   | no recorded prints; shallow recording                                                                           | 06             | `NeedsRecordedPrints`, `ShallowRecording` (new)            | rows focusable; the depth line |
| favourites row         | nine, fewer, a non-time slot, an unavailable slot                                                               | 01, 09         | `Favourites` (catalogued)                                  | slot N is digit N              |
| Recent and custom      | open, invalid, not yet, ladder value, Recent full                                                               | 08             | `CustomInterval` (new)                                     | waits for G-1b                 |
| NC-8 parameter editor  | each mode; invalid; estimating; estimate; failed; too many bars; from `Change size…`; after a cancel; ATR typed | 03–05, 07, 10  | `ParamEditor` (new)                                        | outside the menu subtree       |
| NC-9 favourites editor | default, picker, moved, cleared, save failed, Viewer (T2, lock), before G-3                                     | 09             | `FavouritesEditor` (new)                                   | in place, no dialog            |
| density                | comfortable                                                                                                     | 12             | `Comfortable` (new)                                        | 32 px                          |
| placement              | below, shifted, flipped, clamped and scrolled, in place from SCR-041                                            | 11, 15         | `Placement` (new)                                          | spec §7                        |

### Table 2 — Keyboard

| Key                           | Action                                   | Focus after                              | Global conflict?                                         | Notes                              |
| ----------------------------- | ---------------------------------------- | ---------------------------------------- | -------------------------------------------------------- | ---------------------------------- |
| `Enter` / `Space` / `↓` / `↑` | open the menu                            | the checked item                         | none (APG menu button)                                   | —                                  |
| `I` (chart focused)           | open the menu                            | the checked item                         | none today; proposed (D02 OQ-4)                          | E12-D04 and E11-S13 bind it        |
| `1`–`9` (menu)                | activate favourite N                     | the trigger (commit) or the editor (D-2) | `chart.interval_preset` (Chart); stopped at the root     | empty slot: "No favourite on 3"    |
| `→` (mode row)                | open the editor                          | the field, value selected                | none                                                     | the › zone's twin                  |
| `Enter` (editor)              | commit, or refuse with the message       | the trigger, or stays                    | none                                                     | never on blur or `Tab` (spec D3-3) |
| `Esc`                         | back one level; from the menu, close     | the opener                               | Chart's `chart.cancel_drawing`; stopped at the root      | never changes the chart            |
| `Alt+↑` / `Alt+↓`, `Delete`   | move or clear a slot (favourites editor) | the moved slot                           | Rules' reorder (another context); Chart's `Del`, stopped | —                                  |

### Table 3 — Accessible name / role

| Element                | Role                                              | Accessible name (source)                                   | States / properties                                                                |
| ---------------------- | ------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| trigger                | `button`                                          | "Interval: 15 minutes", "Bar mode: Volume, 50 BTC per bar" | `aria-haspopup="menu"`, `aria-expanded`, `aria-controls`                           |
| favourites, time chips | `menuitemradio`                                   | "15 minutes"                                               | `aria-checked`; favourites `aria-keyshortcuts`                                     |
| mode rows              | `menuitemradio`                                   | "Volume, 50 BTC per bar"                                   | `aria-checked`; `aria-disabled` + description (C-24, C-25); description C-3 + C-30 |
| NC-8 editor            | `group` with a CMP-008 `spinbutton`               | "Volume per bar, BTC"                                      | `aria-valuetext`, `aria-invalid`, `aria-describedby` → message, estimate           |
| NC-9 editor            | `group` with a `listbox` of `option`s and buttons | "Edit favourites"; "Slot 4, 15 minutes"                    | `aria-selected`; buttons outside the options                                       |

## Handoff checklist — CMP-041 Menu (E12-D03, #201)

- [ ] **Final Penpot link** — PENDING: page `E12-D03`, boards 14 and 16
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; APG menu keys plus `←` / `→` aliases on chip rows; typeahead lands on disabled items too (E11-D03 §3.2)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A: static chrome (shared table 5)
- [x] **Motion pair** — shared table 4
- [x] **Density notes** — shared density table
- [x] **Essential-exceptions log** — one shared row: comfortable targets at 32 px (shared table)
- [ ] **Tokens used** — PENDING (E12-D09, DS-1): the entry names `elevation.3`; the spec binds `elevation.popover` and `radius.card` (E11-D03's D03-CR-1 pattern, spec DS-1)
- [x] **Data contract confirmed** — N/A for chrome; the items' data is CMP-220's
- [ ] **Contrast and CVD** — as CMP-220's
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #201 or the merge

### Table 1 — Variants × States

| Variant                                 | State                                            | Penpot variant | Story name                                 | Notes                                                                                                                                                                                         |
| --------------------------------------- | ------------------------------------------------ | -------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| chip item                               | rest, hover, focused, checked, checked + focused | board 16       | `ChipItems` (new)                          | rows wrap, never truncate                                                                                                                                                                     |
| row item with a description             | rest, hover, focused, checked                    | 16             | `WithDescription` (new)                    | two lines; the description is `aria-describedby`                                                                                                                                              |
| disabled-with-reason, state             | rest, focused                                    | 16             | `DisabledWithReason` (D03-CR-1)            | ⊘, the label in `color.text.secondary`, the reason line; focusable (spec D3-5, V-12)                                                                                                          |
| disabled-with-reason, RBAC (CMP-079 T2) | rest, focused                                    | 09, 16         | `Denied(Permission)` (CMP-079, catalogued) | the `lock` (CMP-019, `decorative=false`, "Not available") leads the full label in `color.text.tertiary`; the reason line in `color.text.secondary`; `aria-disabled`, focusable (E09-D09 §2.2) |
| trailing secondary zone                 | rest, hover                                      | 16             | `TrailingZone` (new)                       | pointer twin of `→`; no Tab stop                                                                                                                                                              |
| content slot outside the menu           | editor, disclosure panel                         | 16             | `ContentSlot` (new)                        | not in the `menu` subtree; the rows below move down once                                                                                                                                      |
| groups and separators                   | with a caption; with a header action (About)     | 16             | `Groups` (D03-CR-1)                        | the header action is the group's first item                                                                                                                                                   |

### Table 2 — Keyboard

| Key                       | Action                                       | Focus after    | Global conflict?                | Notes                              |
| ------------------------- | -------------------------------------------- | -------------- | ------------------------------- | ---------------------------------- |
| `↓` / `↑`, `Home` / `End` | next / previous item, wrapping; first / last | that item      | none: widget keys, root-stopped | linear across groups and chip rows |
| `←` / `→` (chip row)      | previous / next item                         | that item      | none                            | aliases                            |
| letters                   | typeahead                                    | the next match | none: root-stopped              | disabled items included            |
| `Tab`                     | close without change                         | the next stop  | none                            | APG                                |

### Table 3 — Accessible name / role

| Element   | Role                         | Accessible name (source) | States / properties                                                            |
| --------- | ---------------------------- | ------------------------ | ------------------------------------------------------------------------------ |
| menu      | `menu`                       | the host's label         | vertical                                                                       |
| group     | `group`                      | its header               | `aria-describedby` its caption                                                 |
| item      | `menuitemradio` / `menuitem` | its text                 | `aria-checked`; `aria-disabled` + description; `aria-expanded` (About, Custom) |
| separator | `separator`                  | —                        | —                                                                              |

## Handoff checklist — CMP-069 InfoPanel (E12-D03, #201)

- [ ] **Final Penpot link** — PENDING: page `E12-D03`, boards 02, 06 and 16
- [x] **Variants × States matrix** — table 1: the new inline variant (Q10); the drawer variant is unchanged
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — shared table 5: the recorder line updates silently (focus never moves)
- [x] **Motion pair** — shared table 4: 0 ms in both modes
- [x] **Density notes** — shared density table
- [x] **Essential-exceptions log** — one shared row: comfortable targets at 32 px (shared table)
- [x] **Tokens used** — inherits CMP-046 in the drawer; the inline variant binds `color.surface.raised`, `type.ui.label`, `type.ui.caption`, `color.text.secondary`, CMP-001 secondary for the route
- [x] **Data contract confirmed** — `meta.recording_started_at` (`22:15440`); the recorder status line of SCR-047 (`22` `/recording/status`); the session's permissions for `recording:write` (`auth/rbac_seed.json`)
- [ ] **Contrast and CVD** — as CMP-220's; `color.text.link` is not used (6.66:1 in high contrast, H-8)
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #201 or the merge

### Table 1 — Variants × States

| Variant | State                                                                  | Penpot variant | Story name             | Notes                                           |
| ------- | ---------------------------------------------------------------------- | -------------- | ---------------------- | ----------------------------------------------- |
| inline  | collapsed; expanded with prints (C-32, C-33)                           | board 02       | `Inline` (new)         | outside the host menu                           |
| inline  | expanded, no prints: holder of `recording:write` (C-35) / other (C-36) | 06             | `InlineNoPrints` (new) | the route is a button: it opens M-023, a dialog |

### Table 2 — Keyboard

| Key                       | Action            | Focus after         | Global conflict? | Notes                          |
| ------------------------- | ----------------- | ------------------- | ---------------- | ------------------------------ |
| `Enter` / `Space` (About) | expand / collapse | the panel's heading | none             | `tabindex="-1"` on the heading |
| `Esc` (panel)             | collapse          | the About item      | root-stopped     | —                              |
| `Tab` (panel)             | the route button  | the button          | none             | —                              |

### Table 3 — Accessible name / role

| Element    | Role       | Accessible name (source)            | States / properties               |
| ---------- | ---------- | ----------------------------------- | --------------------------------- |
| About item | `menuitem` | "About bar modes"                   | `aria-expanded`, `aria-controls`  |
| panel      | `region`   | its heading                         | —                                 |
| route      | `button`   | "Recording settings for ETHFIUSDT…" | shown only with `recording:write` |

## Handoff checklist — CMP-008 NumericStepperInput (E12-D03, #201)

- [ ] **Final Penpot link** — PENDING: page `E12-D03`, boards 03–05, 07 and 16
- [x] **Variants × States matrix** — table 1
- [x] **Keyboard table** — table 2; the catalogued spinbutton keys, plus `←` at the start and `Esc` returning to the host row
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A: user input (shared table 5)
- [x] **Motion pair** — N/A: nothing animates
- [x] **Density notes** — shared density table
- [x] **Essential-exceptions log** — one shared row: comfortable targets at 32 px (shared table)
- [ ] **Tokens used** — PENDING (E12-D09, DS-4 and DS-5): the entry names `font.mono` and `color.border.*`; the spec binds `type.num.sm` / `type.num.base`, `color.surface.app`, 1 px `color.text.tertiary` (CR `color.border.input`), 2 px `color.status.danger.strong` when invalid (DS-4, DS-5)
- [x] **Data contract confirmed** — the bounds and the 24-character `param` (spec §2)
- [ ] **Contrast and CVD** — as CMP-220's
- [x] **Design QA checklist (16 §12)** and the **a11y template (05 §10)** — at the end
- [ ] **Sign-off** — PENDING: the owner's `approved` on #201 or the merge

### Table 1 — Variants × States

| Variant                       | State                            | Penpot variant | Story name                   | Notes                                          |
| ----------------------------- | -------------------------------- | -------------- | ---------------------------- | ---------------------------------------------- |
| with a unit suffix            | default, focused, value selected | board 03       | `WithUnit` (new)             | "BTC", "trades", "ticks" inside, right-aligned |
| whole numbers with separators | typing "1,000"                   | 03             | `WholeNumber` (new)          | commas and spaces dropped; no decimal point    |
| invalid                       | below, above, a fraction, `atr:` | 07             | `Invalid` (catalogued)       | ✕ + the message; `aria-invalid`                |
| steppers                      | rest, hover, at the minimum      | 03             | `MinMaxClamped` (catalogued) | pointer only; `↑` / `↓` for keys               |

### Table 2 — Keyboard

| Key                                              | Action               | Focus after         | Global conflict?   | Notes                      |
| ------------------------------------------------ | -------------------- | ------------------- | ------------------ | -------------------------- |
| `↑` / `↓`, `PageUp` / `PageDown`, `Home` / `End` | step, ×10, min / max | stays               | none: root-stopped | steps per mode (spec §6.1) |
| `←` at the start                                 | back to the host row | the row             | none               | otherwise moves the caret  |
| `Enter`                                          | commit or refuse     | the trigger / stays | none               | the message is spoken once |

### Table 3 — Accessible name / role

| Element | Role         | Accessible name (source) | States / properties                                                                                                          |
| ------- | ------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| field   | `spinbutton` | its label with the unit  | `aria-valuemin`, `aria-valuemax`, `aria-valuenow`, `aria-valuetext`, `aria-invalid`, `inputmode="numeric"`, `maxlength="24"` |

## Shared tables (Tables 4, 5, Density and Essential exceptions for the four blocks)

| Table 4 — Motion pair: component      | Property                                                         | motion-safe                                  | motion-reduce | Tokens                                           |
| ------------------------------------- | ---------------------------------------------------------------- | -------------------------------------------- | ------------- | ------------------------------------------------ |
| CMP-220 popover (CMP-017)             | open and close: opacity                                          | `motion.duration.fast` fade (E11-D06 row 39) | 0 ms          | `motion.duration.fast`, `motion.easing.standard` |
| CMP-041, CMP-069, CMP-008, NC-8, NC-9 | the editor, panel and favourites editor appear; scroll into view | 0 ms                                         | 0 ms          | none (E12-D10 owns motion)                       |

| Table 5 — Live data: component | Field                          | Politeness                         | Cadence             | Coalescing  |
| ------------------------------ | ------------------------------ | ---------------------------------- | ------------------- | ----------- |
| CMP-220                        | an invalid `Enter`, C-19, C-42 | polite, one region empty at mount  | once per event      | latest only |
| CMP-220                        | the estimate line              | none: read on demand (description) | 300 ms after typing | latest only |
| CMP-069 inline                 | the recorder line              | none                               | on change           | latest only |

| Density: component | Mode        | Row / control height                             | Padding tokens   | Smallest target                             |
| ------------------ | ----------- | ------------------------------------------------ | ---------------- | ------------------------------------------- |
| all four           | compact     | 24 px (`size.control.height`, `size.row.height`) | `space.inset.sm` | 24 × 24 px (chip, › zone, stepper)          |
| all four           | comfortable | 32 px                                            | `space.inset.md` | 32 × 32 px (logged in the exceptions table) |

| Essential exceptions: component | Exception                                                                                                              | Compensating control                                                                                | Reviewer                                             | Date       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------- |
| all four, compact               | none                                                                                                                   | —                                                                                                   | —                                                    | —          |
| all four, comfortable           | targets are 32 × 32 px (`size.control.comfortable`), short of the 40–44 px that `16:126` and `16:611` give as practice | `05` §3.4 item 7's 24 × 24 floor is met with room, and every target has a keyboard path (spec §8.2) | the owner, with the accessibility sign-off (pending) | 2026-10-22 |

## `05` §10 accessibility acceptance criteria (SCR-042)

```gherkin
Feature: SCR-042 interval and bar-mode menu — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user opens the menu from the toolbar, types "V", presses Right, types 75 and presses Enter
    Then every item is reachable with the arrow keys across all groups, and the editor with Right
    And a commit happens only on Enter or Apply, never on blur or Tab
    And Escape steps back one level and never changes the chart
    And digits inside the menu never also fire the chart's interval preset
    And focus never moves on an estimate, a recording change or a store update
    And every focused item, chip and control shows a ring of at least 3:1

  Scenario: Screen-reader operation
    Given NVDA on the Electron shell (spec §8.6, a script not yet run)
    Then the menu, its groups and each item's name, state and description are announced
    And a disabled mode reads its reason, "Needs recorded prints: none yet"
    And an invalid Enter speaks its message once; the estimate is read on demand, never streamed

  Scenario: Colour-independence, contrast and reduced motion
    Then checked, focused, disabled, invalid and pending states each carry a shape or words
    And every gated pair passes in dark, light and high contrast (text 4.5:1, non-text 3:1, HC text 7:1)
    And under prefers-reduced-motion nothing animates

  Scenario: Automated gates
    Given the consuming FE ticket's PR
    Then axe-core reports no serious or critical violation and the keyboard-only E2E covers the path above
    And Lighthouse stays at 95 or more
```

Screen reader: written, not run; the release-level pass (`05` §8) runs it. Exceptions: none.

## `16` §12 design QA checklist

- [ ] Published Tier-2 / Tier-3 tokens only — yes in the spec; the missing names are change requests (spec DS-5), none
      invented; PENDING the boards' read-back.
- [ ] Three themes × two densities — measured for contrast; PENDING on the boards (twins of 01–04, 06–10 and 12; 12 comfortable; 13–15 HC).
- [x] Contrast matrix for every pair introduced — the audit script, exit 0.
- [x] CVD simulation reviewed — section C of the script; the ✕ and ⚠ glyphs share one amber in light, shapes and words
      carry them.
- [ ] A Penpot variant and a story per state — variants PENDING (board 16); stories named above.
- [x] Disabled-with-reason (CMP-079) for RBAC-gated actions — "Edit favourites…" for a Viewer in the T2 form (the
      `lock`, the full label in `color.text.tertiary`, the reason in `color.text.secondary`); the recording route as
      its T2 sentence form (C-36).
- [x] Loading, empty and error designed — the depth line while unknown, no recorded prints, the estimate states, a
      failed save.
- [x] Keyboard table matches a keyboard path — spec §8.6; the test is the FE ticket's.
- [x] Accessible name / role table — spec §8.1 and the tables above.
- [x] Canvas strategy — N/A: no canvas in SCR-042. Motion pair — table 4.
- [x] Hit targets ≥ 24 px compact — yes; comfortable stays at 32 px, logged once in the exceptions table.
- [ ] Accessibility sign-off — PENDING: the owner's approval (agent-delivery adaptation).
- [x] Order placement, positions, arming — SCR-042 places no orders.
- [x] Estimated values chip-tagged — N/A: the build estimate is labelled "about" and is not a market value.
- [x] Reuses existing CMP-\* — yes; the variants go to E12-D09 rather than new ids.
- [ ] Stories match the matrix — PENDING the FE tickets. Published library components only — PENDING boards.
