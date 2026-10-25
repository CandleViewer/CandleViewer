# E15-D04 — Per-component handoff checklist (`16` §11.4; the two contracts SCR-021 changes)

Two blocks (CMP-083 SplitPane as the dock separator, CMP-214 DockDropZone — every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table **once each with a leading `Component` column** (the E36-D02 handoff's shape); then A. the `16` §12 Design QA checklist and B. the `05` §10 accessibility acceptance criteria for SCR-021. CMP-215 FloatingWindowFrame and CMP-216 PanelMenu get **no block**: SCR-021 references the window as a frame placeholder (E15-D10 owns its contract) and the menu as the entry point to move mode (E15-D07 owns its items). The new MoveModeBar, MinimisedPanelTray and DockTabGroup are named, not numbered, and filed by E15-D13 (spec §14); their contracts are stated in the spec and summarised in the tables below under their names. Every "Final Penpot link" names the page by name (page id pinned after the first build), never a host or a workspace URL. Every number is `docs/design/_tools/e15_d04_dock_audit.py`'s.

## Handoff checklist — CMP-083 SplitPane (E15-D04, #320)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E15-D04 Dock system` (page id pinned after the first build), specimens `CMP-083 · SplitPane` as the dock separator on this ticket's own page (never the DS library file); PNG planned at `docs/design/E15/img/E15-D04-06-splitters-resize.png` (and `E15-D04-10-light-composite.png` for the light twin)
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): horizontal · vertical × rest / hover / active-drag / focused / at-minimum (spec §6, D04-D-10); Table 1
- [x] **Keyboard table** — `Tab` reaches the separator after the panel it follows; arrows 2 %, `Shift`+arrows 10 %, `Home` equal, `End` maximum; `Alt+Shift+arrows` PROPOSED-PENDING (E15-D01 OQ-16, E15-D15); no view-local override of a global binding, no single unmodified key for a trading action, `Esc` / `Ctrl+K` untouched (spec §6, §10); Table 2
- [x] **Accessible name / role table** — `role="separator"`, `aria-orientation`, `aria-valuenow` %, `aria-valuemin` / `aria-valuemax` (PROPOSED), name "{Left panel} and {Right panel} splitter" (spec §6); Table 3
- [ ] N/A — **Live data**: no streaming value; `aria-valuenow` changes only on a user action, announced once per change
- [x] **Motion pair** — none animated: the five states are instant token swaps; the live resize is unanimated in both modes (spec §16 item 6); Table 4
- [x] **Density notes** — the 24 px hit band over the 4 px gutter in both densities; grip 24×4 compact, 32×4 comfortable; smallest target 24 px in both (spec §6, §12); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.border.subtle`, `color.border.strong`, `color.focus.ring`, `color.surface.canvas`, `color.text.primary`, `radius.pill`, `size.target.min`; all resolve at `packages/ui/tokens` at the base `9ba1cbc0204421aa4b567214d9110b19187646e0`; none invented; the catalogue's `color.border.subtle` kept, the rest PROPOSED in spec D04-A-1
- [ ] N/A — **Data contract**: client state; a resize changes one split's `sizes` in the working copy (E15-D02 §4) and only Save writes (`updateLayout`)
- [x] **Contrast and CVD** — the focused grip and the stop mark measured over the darkest and lightest content in three themes (spec §12: worst 6.30:1, bar 3:1); PROPOSED `tools/contrast/pairs.mjs` rows: `color.focus.ring` on `color.surface.canvas`, `color.text.primary` on `color.surface.canvas`, `color.border.strong` on `color.surface.canvas`; the greyscale twin of every ratio computed; `cvd_sim.py` on the exports pending
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — the owner's `approved` comment on #320, pending

## Handoff checklist — CMP-214 DockDropZone (E15-D04, #320)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E15-D04 Dock system` (page id pinned after the first build), specimens `CMP-214 · DockDropZone` on this ticket's own page; PNGs planned at `docs/design/E15/img/E15-D04-01-zone-geometry.png`, `E15-D04-02-pointer-zones.png`, `E15-D04-03-pointer-invalid-esc-drop.png`, `E15-D04-05-move-chooser-parity.png`
- [ ] **Variants × States matrix** — PENDING: edge (left, right, top, bottom) · centre × idle / active / invalid / withdrawn, plus the chooser's stage one and stage two (spec §3–§5, D04-D-1 … D-4, D-9); Table 1
- [x] **Keyboard table** — stage one: arrows by shared edge, `Tab` / `Shift+Tab` in reading order, `Enter` takes the panel; stage two: arrows choose a side (centre first), `Backspace` back, `Enter` drops; `Esc` restores at any step and is never gated; captured ahead of panel bindings (spec §5, §10); Table 2
- [x] **Accessible name / role table** — the overlay is `aria-hidden`; the MoveModeBar is E15-D02's `status` (§8 line 610, CARRIED) and speaks each move-mode step once, the latest only under key repeat (`05` §6.2); the dock's visually hidden polite region (PROPOSED) carries the pointer's steps, so nothing is heard twice; the chooser's targets are announced, not focused (spec §5, §10, D04-D-8); Table 3
- [ ] N/A — **Live data**: no streaming value; each step is a discrete polite announcement
- [x] **Motion pair** — ghost appear / leave `motion.duration.fast` fade → instant; zone lit instant in both; drop commit instant (one mutation) (spec §16 item 6); Table 4
- [x] **Density notes** — bands scale with the panel (25 % of the smaller side, 48–160 px) and do not change with density; the outline is 4 px + a 1 px halo in both; the smallest pointer target is the 48 px band (spec §3); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.focus.ring`, `color.surface.canvas`, `color.surface.overlay`, `color.text.primary`, `color.text.tertiary`, `color.border.default`, `color.border.strong`, `color.surface.raised`, `opacity.muted`, `radius.sm`, `motion.duration.instant`, `motion.duration.fast`; all resolve at the base; the catalogue's `color.accent.subtle` and `motion.fast` do not exist and are **requested from E15-D13**, not bound (spec D04-A-3)
- [ ] N/A — **Data contract**: client state; a drop is one mutation of the working copy's tree within `22` `LayoutGridSpec`'s limits (depth ≤6, ≤64 nodes, ≤16 leaves); only Save writes
- [x] **Contrast and CVD** — the lit outline, the ghost outline and the hatch measured over the darkest and lightest content in three themes (spec §12: 27 gated rows, 0 FAIL); PROPOSED `pairs.mjs` rows as CMP-083's plus `color.text.primary` on `color.surface.overlay`; greyscale computed; `cvd_sim.py` on the exports pending
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — the owner's `approved` comment on #320, pending

### Table 1 — Variants × States

| Component                | Variant                                                  | State (every one is a Penpot variant and a story)                           | Penpot variant (planned)                       | Story (planned, hand-off text — E15-T02 / E15-S02 write them)                                                                 | Notes                                                                  |
| ------------------------ | -------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| CMP-083                  | horizontal · vertical (the n-ary split's k−1 separators) | rest, hover, active-drag, focused, at-minimum                               | `CMP-083 · SplitPane / Orientation=…, State=…` | `Dock/SplitPane/Horizontal`, `Vertical`, `Focused`, `AtMinimum`, `Dragging`, `NAry`                                           | spec §6; the catalogue's Horizontal, Vertical kept; four stories added |
| CMP-214                  | edge left · right · top · bottom · centre                | idle (faint), active (lit), invalid (hatched + reason), withdrawn (absent)  | `CMP-214 · DockDropZone / Zone=…, State=…`     | `Dock/DockDropZone/EdgeZones`, `CentreTabify`, `ActiveZone`, `InvalidZone`, `ReducedSet`, `KeyboardChooser`, `LargeOverSmall` | spec §3–§5; the catalogue's three kept; four stories added             |
| MoveModeBar (new)        | one line · two lines (200 %)                             | stage one, stage two, refused (second line), leaving                        | `MoveModeBar / Lines=…, Stage=…`               | `Dock/MoveModeBar/*`                                                                                                          | spec D04-D-8; filed by E15-D13                                         |
| MinimisedPanelTray (new) | compact 24 px · comfortable 32 px                        | one tab, several tabs, an order panel's tab with its env badge, tab focused | `MinimisedPanelTray / Density=…`               | `Dock/MinimisedPanelTray/*`                                                                                                   | spec §7; filed by E15-D13                                              |
| DockTabGroup (new)       | compact · comfortable                                    | two tabs, active tab, focused tab                                           | `DockTabGroup / Density=…`                     | `Dock/DockTabGroup/*`                                                                                                         | spec §4 P6; filed by E15-D13                                           |

### Table 2 — Keyboard

| Component                    | Key                                                | Action                                                                                   | Focus after                           | Global conflict? (`05` §3.2 / §3.3)                                                        |
| ---------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------ |
| CMP-083                      | `Tab` / `Shift+Tab`                                | reaches the separator after the panel it follows                                         | the separator                         | none                                                                                       |
| CMP-083                      | `←` `→` (vertical separator), `↑` `↓` (horizontal) | moves the split 2 % (PROPOSED component key)                                             | stays                                 | the chart's crosshair arrows live in the Chart context; a focused separator is not a chart |
| CMP-083                      | `Shift`+arrows                                     | moves the split 10 %                                                                     | stays                                 | `Shift+arrows` pans the chart viewport (`05` §3.1 item 7) — different focus, no conflict   |
| CMP-083                      | `Home` / `End`                                     | equal sizes / the followed panel's maximum                                               | stays                                 | `Home` / `End` jump bars on a focused chart — different focus                              |
| CMP-083                      | `Alt+Shift+arrows`                                 | PROPOSED-PENDING alias (E15-D01 OQ-16: Windows' input-language toggle; E15-D15 checks)   | —                                     | not drawn as shipped                                                                       |
| CMP-083                      | `Esc`                                              | nothing (no modal state; reserved, `05` §3.3 rule 3)                                     | stays                                 | untouched                                                                                  |
| CMP-214 (chooser, stage one) | `↑` `↓` `←` `→`                                    | target = the neighbour sharing the longest edge; "No panel further that way." at an edge | the moving panel's header (unchanged) | captured ahead of `replay.step_bar_back` / `_fwd` (E15-D02 §7 line 602)                    |
| CMP-214 (stage one)          | `Tab` / `Shift+Tab`                                | target = next / previous panel in reading order                                          | unchanged                             | captured ahead of `rules.cycle_nodes`                                                      |
| CMP-214 (stage one)          | `Enter`                                            | takes the target; stage two on the centre                                                | unchanged                             | captured ahead of `positions.open_sltp`, `global.auth.submit`                              |
| CMP-214 (stage two)          | `↑` `↓` `←` `→`                                    | chooses a side; the opposite arrow returns to the centre                                 | unchanged                             | as above                                                                                   |
| CMP-214 (stage two)          | `Backspace`                                        | back to stage one, same target                                                           | unchanged                             | a component key (the lint rejects it as a row)                                             |
| CMP-214 (either stage)       | `Enter` on a lit side                              | drops: one mutation; the mode ends                                                       | the moved panel's header              | —                                                                                          |
| CMP-214 (either stage)       | `Enter` on a hatched side                          | nothing; the reason repeats once                                                         | unchanged                             | —                                                                                          |
| CMP-214 (either stage)       | `Esc`                                              | restores the exact layout; the mode ends; never gated                                    | the moving panel's header             | reserved; captured ahead of `ticket.clear`, `chart.cancel_drawing`                         |
| CMP-216 (entry only)         | `Shift+F10`, the context-menu key                  | opens the panel menu with Move panel (PROPOSED `workspace.panel_menu`)                   | the menu                              | one meaning app-wide: the focused thing's menu                                             |

### Table 3 — Accessible name / role

| Component                | Element                   | Role                                             | Accessible name (source)                                                                          | States / properties                                                                                                                                                                   |
| ------------------------ | ------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-083                  | the separator             | `separator` (focusable)                          | "{Left panel} and {Right panel} splitter" (`aria-label`, built from the neighbours' region names) | `aria-orientation`, `aria-valuenow` (%), `aria-valuemin` / `aria-valuemax` (PROPOSED, from the minimums), `aria-describedby` → the tooltip "{Panel}: {n} px minimum" while at-minimum |
| CMP-214                  | the overlay and its bands | presentation (`aria-hidden="true"`)              | —                                                                                                 | the state is spoken by the MoveModeBar's `status` in move mode and by the dock's polite region for a pointer (the announcements of spec §10)                                          |
| CMP-214                  | the ghost                 | presentation                                     | —                                                                                                 | its label is repeated in the announcement ("Below Chart.")                                                                                                                            |
| MoveModeBar              | the bar                   | `status` (E15-D02 §8 line 610, CARRIED; D04-D-8) | its instruction text                                                                              | line one the instruction; line two the target or the reason; its live text is the step string AN-1 … AN-4, once each, the latest only under key repeat                                |
| MinimisedPanelTray       | the tray                  | `toolbar`                                        | "Minimised panels"                                                                                | one stop in the region ring; tabs as buttons "Tape · BTCUSDT", "Positions · LIVE"                                                                                                     |
| DockTabGroup             | the tab row               | `tablist` (automatic activation)                 | —                                                                                                 | tabs named kind and symbol; `aria-selected`                                                                                                                                           |
| CMP-045 (the Undo toast) | the toast                 | `status`                                         | its text                                                                                          | the action "Undo" a button; dismissible by keyboard; never steals focus                                                                                                               |

### Table 4 — Motion pair

| Component          | Property             | motion-safe                                 | motion-reduce | Duration / easing tokens                                                     |
| ------------------ | -------------------- | ------------------------------------------- | ------------- | ---------------------------------------------------------------------------- |
| CMP-083            | all five states      | instant token swaps; live resize unanimated | identical     | `motion.duration.instant`                                                    |
| CMP-214            | ghost appear / leave | `fast` fade                                 | instant       | `motion.duration.fast` → `motion.duration.instant` (E15-D14 fixes the curve) |
| CMP-214            | zone lit / hatched   | instant                                     | instant       | `motion.duration.instant`                                                    |
| CMP-214            | drop commit          | instant (one mutation)                      | identical     | —                                                                            |
| MoveModeBar        | enter / leave        | `fast` fade                                 | instant       | `motion.duration.fast`                                                       |
| MinimisedPanelTray | appear / leave       | `fast` fade                                 | instant       | `motion.duration.fast`                                                       |
| CMP-045            | enter / exit         | `fast` slide+fade                           | fade only     | `16` §7's toast recipe                                                       |

### Table 5 — Live data

| Component             | Field           | Politeness                | Cadence                        | Coalescing            | Notes                                                                                                                                                                                                      |
| --------------------- | --------------- | ------------------------- | ------------------------------ | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-083               | `aria-valuenow` | the separator's own value | once per key press or drag end | the latest value only | never per pointer pixel; a live region speaks only "Minimum size."                                                                                                                                         |
| CMP-214 / MoveModeBar | the step        | polite                    | once per discrete step         | —                     | spoken by the bar's `status` in move mode (the latest step only under key repeat, `05` §6.2) and by the dock's polite region for a pointer; never per pointer move; a hatched zone announces once on entry |
| all                   | —               | —                         | —                              | —                     | no streaming value on SCR-021                                                                                                                                                                              |

### Density

| Component          | Mode                  | Row / control height                                               | Padding tokens   | Smallest target          |
| ------------------ | --------------------- | ------------------------------------------------------------------ | ---------------- | ------------------------ |
| CMP-083            | compact               | gutter 4 px, hit band 24 px, grip 24×4                             | —                | 24 px (the band)         |
| CMP-083            | comfortable           | gutter 4 px, hit band 24 px, grip 32×4                             | —                | 24 px                    |
| CMP-214            | both                  | band 25 % of the smaller side, 48–160 px; outline 4 px + 1 px halo | —                | 48 px (the clamped band) |
| MoveModeBar        | compact / comfortable | 32 / 40 px, two lines 56 / 72                                      | `space.inset.sm` | —                        |
| MinimisedPanelTray | compact / comfortable | 24 / 32 px (`size.row.compact` / `size.row.comfortable`)           | `space.inset.sm` | 24 px (a tab)            |
| DockTabGroup       | compact / comfortable | 24 / 32 px                                                         | `space.inset.sm` | 24 px (a tab)            |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all       | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-021

- [x] Only published Tier-2 tokens; zero hard-coded hex / px in the spec other than anatomy derived from the tokens and the tool's resolved values (spec §12).
- [~] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §12); `forced-colors: active` is stated per carrier; the visual parity check runs on the boards (BLOCKED-PENPOT).
- [x] Passes the contrast matrix for every pair introduced — 27 gated rows, 0 FAIL, worst 6.30:1 (spec §12); the PROPOSED `pairs.mjs` rows named above.
- [~] CVD simulation reviewed — the greyscale twin of every ratio is computed (spec §12); `docs/design/_tools/cvd_sim.py` on every export is the boards PR's.
- [~] Every documented state has a Penpot variant and a story — named (Table 1); the variants exist once drawn; the stories are E15-T02 / E15-S02's.
- [x] Disabled states use the disabled-with-reason pattern (E09-D09 T2) for every gated action — the one statement in spec §11: no direct dock operation is gated; the one T2 control on SCR-021 is a limit-refused Move to ▸ item (E15-D02 §8.1's carried row, a state key as its second line, the CMP-019 lock); Save after a drop takes E15-D02 §8.1's legs, view-as first; drag and chooser refusals are outcomes, never T2; Pop out in the browser is an absence.
- [x] Loading / empty / error states designed — SCR-021 has none of its own; the refusals, the at-minimum stop and the compact view are its error-class states (spec §4, §6, §8).
- [x] Keyboard-interaction table completed (spec §5, §6, §10; Table 2).
- [x] Accessible-name / role table completed (spec §6, §10; Table 3).
- [x] Canvas / WebGL-adjacent: the dock never remounts a GL context; the ghost is never a canvas (spec §16).
- [x] Motion-safe / motion-reduce pair specified for every transition (Table 4; durations E15-D14's).
- [x] Hit targets ≥24 px in compact and comfortable; no essential exception.
- [ ] Accessibility role sign-off — the owner's `approved` comment, pending; E15-D15's screen-reader pass of the target model (OQ-S) and of the MoveModeBar's hidden visible lines (spec D04-D-8's gap: the instruction and `Esc: cancel` out of the accessibility tree, AN-1 naming no key).
- [x] Confirm-gate variant stated: none — no SCR-021 operation is destructive without Undo (Close is undone from the toast and the menu, E15-D02 A-22); a drop never writes.
- [x] Every heuristic / estimated value is chip-tagged — none on SCR-021.
- [x] Demo / Live context unambiguous: the env badge on every order-capable header, tray tab and compact summary line; a maximised panel keeps the TopBar and its own header's badge (spec §7).
- [x] Reuses existing `CMP-*` (CMP-083, CMP-214, CMP-215 and CMP-216 by reference, CMP-080, CMP-081, CMP-082, CMP-041, CMP-045, CMP-212, CMP-075, CMP-229, CMP-079, CMP-019, CMP-016); the three new components are named, not numbered.
- [~] Storybook stories match the Variants × States matrix — planned (Table 1); none exists (`packages/dock` does not exist yet).
- [~] Composes only published-library components — on the boards, once drawn.

## B. Accessibility acceptance criteria (`05` §10) — SCR-021

```gherkin
Feature: E15-D04 dock system — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user moves the Positions panel below the Chart, resizes the splitter between them
      to its stop, maximises and restores the Chart and undoes the move, using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation (the panel header, the
      panel menu, the move-mode chooser, the separator after each panel, the toast's Undo)
    And every action (including the drag-based docking and the splitter drag) has a documented
      non-drag keyboard equivalent (Move panel and Move to in the panel menu; arrows, Shift,
      Home and End on the separator)
    And focus is never silently moved by a background data update: it stays on the moved panel's
      header after a drop and returns there on Esc
    And a visible focus indicator meeting >=3:1 contrast is present at every step (the 2 px
      color.focus.ring; the lit zone and the grip measured >=6.30:1 over the content extremes)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the user performs the same move
    Then all labels, roles, and current values are announced correctly (the separator's
      orientation and percentage; "Move mode. Positions. Choose a panel."; "Chart, BTCUSDT 1m.";
      "Below Chart."; "Positions moved below Chart.")
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding: one polite announcement per discrete
      step, never per pointer move or per pixel
    And any canvas-rendered data involved has a working DOM-mirror and/or "View as table"
      equivalent with full data parity (the dock renders no canvas data of its own)

  Scenario: Colour-independence
    Given the feature displays the lit zone, the hatched invalid zone, the ghost, the focused
      splitter and the DEMO/LIVE badge
    When the state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone (the outline, the
      hatch pattern with its words, the ghost's outline and label, the grip and the stop mark, the
      badge's word and dot)
    And the feature passes deuteranopia/protanopia/tritanopia simulation review (the greyscale
      twin of every ratio passes; cvd_sim.py runs on the exports)

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the high-contrast theme
    Then all text meets >=4.5:1 (7:1 in high contrast) and all meaningful non-text UI elements
      meet >=3:1 over the darkest and lightest panel content, per the token contrast matrix
      (27 gated rows, 0 FAIL)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the ghost, the zones, the move-mode bar, the toast or the tray would animate
    Then the feature uses the motion-reduce variant (instant, or fade only for the toast) with no
      flashing content exceeding 3 times per second and no motion lasting >5s without a pause
      control
```
