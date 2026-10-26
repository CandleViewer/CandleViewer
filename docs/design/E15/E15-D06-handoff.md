# E15-D06 — Per-component handoff checklist (`16` §11.4; the contracts SCR-023 / SCR-043 change)

Three blocks (CMP-218 SyncMenu, CMP-082 PanelHeader's sync badge, CMP-188 PriceAxis's link states — every line of the `16` §11.4 block kept), a reuse note for CMP-190 (E11-D02 owns it; no block), then Tables 1–5, the Density table and the Essential-exceptions table once each with a leading `Component` column, then §A the `16` §12 design-QA checklist and §B the `05` §10 template for SCR-023 (and the SCR-043 link item only). Spec: `docs/design/E15/E15-D06.md` (E15-D06, #360), which names 45 named frames on ten PENDING boards. Every number comes from `docs/design/_tools/e15_d06_sync_audit.py --json`. Penpot: page `E15-D06 Sync groups`, by name (its id pinned here once drawn); never a host, team, file id or link. No local path, user name or notes folder appears here.

## Handoff checklist — CMP-218 SyncMenu (E15-D06, #360)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (boards PR): page `E15-D06 Sync groups` (page id pinned after the first build), frames `SCR-023/popover-1920`, `SCR-023/popover-1280`, `SCR-023/popover-no-sync`, `SCR-023/modal-200pct`, `SCR-023/popover-text-scale-125`, `SCR-023/conflict-interval`, `SCR-023/drawings-cross-symbol`, `SCR-023/account-env-refused`, `SCR-023/light-conflict`; PNGs planned at `docs/design/E15/img/E15-D06-02-scr-023-popover-dark.png`, `-03-scr-023-modal-200pct.png`, `-04-conflicts-partial-apply.png`, `-10-light-composite.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): variants popover / modal × states Unsynced / GroupA / AllAxesOn / PartialAxes / Conflict / ScaleLinkRefused (the Storybook list the ticket asks for, named exactly; spec §5, §6, §7.4); Table 1
- [x] **Keyboard table** — initial focus on the current group's radio; `Tab` radio → switches in reading order → the account row (`aria-disabled`, focusable) → each scale select → ×; arrows move and select the radio (live apply); `Space` / `Enter` toggle a switch; `Esc` closes and returns focus to the trigger, never gated; the modal at 200 % traps focus (`05` §3.4 item 4); no global binding overridden, `Esc` / `Ctrl+K` untouched (spec §9.1–§9.2); Table 2
- [x] **Accessible name / role table** — `dialog` "Sync — Chart · BTCUSDT 1m"; `radiogroup` "Group" with `radio` A / B / C / No sync; `switch` per axis with `aria-describedby` → its consequence line (and the conflict notice while it applies); the account `switch` `aria-disabled="true"` → its note, no key, no lock (an absence); the members line static text; the notice `role="status"` (spec §10.1); Table 3
- [x] **Live data** — none streams: the members list and the consequence counts are computed on open and never subscribe; the conflict notice re-computes on open and on an interval change; announcements once per event (spec §10.2, §15); Table 5
- [x] **Motion pair** — none animated beyond the popover's open: motion-safe / motion-reduce = "none / instant" (`16` §7; the motion owner is E15-D14, out of scope); Table 4
- [x] **Density notes** — compact: title 24, column switch rows 60 (switch 24 + a two-line consequence), the full-width Drawings and account rows 44, selects 28, padding `space.inset.md` 16, height 437; comfortable: 32 / 72 / 54 / 36, height 525; columns 196 px (a 160 px label box), full width 408 (372) — every label single-line at 13 px (the tool's fit gate); the smallest target the 24 × 24 switch knob area and ×; the modal at 200 %: between the TopBar and the StatusBar (272), 608 × 240, header 32, footer 40, single-line rows 44, body 461 scrolling in 168 — the TopBar, the banner band and the StatusBar never scrimmed (E15-D02 D-7, spec C-17); the text scale 125 % 591 (popover), 150 % 716 (modal) (spec §5.1, §5.3); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px in compact)
- [x] **Tokens used** — `color.surface.overlay`, `color.border.default`, `elevation.popover`, `radius.card`, `space.inset.md` / `.sm` / `.xs`, `type.ui.body`, `type.ui.caption`, `color.text.primary` / `.secondary` / `.tertiary`, `color.action.primary.default` (on track), `color.status.warning.subtle` + `color.status.warning.strong` (the conflict notice), `color.focus.ring`, `size.control.height`; PROPOSED `color.sync.a` / `.b` / `.c` (aliased to `color.status.info.strong` / `color.status.warning.strong` / `color.node.logic`, E15-D13) on the radio's letter tiles; `color.text.disabled` and `opacity.disabled` never used; Penpot token sets = `packages/ui/tokens` at `28ae3f1dbb824e77acaf71f31d32a00c7cce81ee`
- [x] **Data contract confirmed** — `22` `PaneConfig.sync_group` `[A, B, C, null]`; layout flags `crosshair_sync` (true), `symbol_sync` (false), `level_sync` (false); `PaneScaleMode` `[auto, linked, manual, log]`, `scale_mode` default `auto`; gaps G-1–G-7 (per-group axis set, interval / time range / drawings flags, the account axis, `percent`, the link target, the threshold) — "storage pending" on every un-stored switch; E15-T03's bus payload allow-list (`symbol`, `interval`, `timeRange`, `crosshair`, `priceLevel`; no account)
- [ ] **Contrast and CVD** — PENDING until the boards PR (the pairs are PROPOSED `tools/contrast/pairs.mjs` rows for E15-S04): spec §12 — popover text 13.27 / 14.37 / 15.02, consequence line 8.14 / 8.26 / 13.27, conflict glyph 10.17 / 3.78 / 10.17, on-track 3.36 / 3.80 / 6.15, off-track 5.20 / 5.44 / 10.36, focus ring on the overlay 6.15 / 5.39 / 15.99, all PASS; CVD rows in spec §12
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-082 PanelHeader, the sync badge (E15-D06, #360)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E15-D06 Sync groups`, frames `CMP-082/badge-none-compact`, `CMP-082/badge-a-compact`, `CMP-082/badge-b-compact`, `CMP-082/badge-c-compact`, `CMP-082/badge-a-comfortable`, `CMP-082/badge-narrow-steps`, `CMP-082/badge-forced-colors`, `CMP-082/badge-greyscale`, `CMP-082/chart-toolbar-badge`, `CMP-082/conflict-header`, `SCR-023/light-badges`; PNGs planned at `docs/design/E15/img/E15-D06-01-badge-anatomy-densities.png`, `-04-conflicts-partial-apply.png`, `-10-light-composite.png`
- [ ] **Variants × States matrix** — PENDING: states none / A / B / C × compact / comfortable × full words / count / tile + glyph (narrow) × conflict glyph on / off; `forced-colors` and greyscale (spec §4); Table 1
- [x] **Keyboard table** — one Tab stop in the header's `toolbar` (arrows between actions); `Enter` / `Space` opens Sync group ▸; nothing collapses the tile or the glyph at any width (E15-D02 D-3); Table 2
- [x] **Accessible name / role table** — `button` "Sync group A" / "No sync", `aria-describedby` → the axes in words, `aria-haspopup="menu"`; the region description carries group, axes, environment, conflict and provenance (spec §8.4, §10.1); Table 3
- [x] **Live data** — none: the badge re-renders only on a membership or axis change, never on a tick (spec §15); Table 5
- [x] **Motion pair** — none animated (an instant token swap on hover / focus); Table 4
- [x] **Density notes** — compact: badge 20 in the 24 px row, tile 16, glyph 12 (`size.icon.sm`), gap 4, pad 6, text 11, widths 233 / 90 / 56 / 76 / 44; comfortable: 24 in 32, tile 18, glyph 16 (`size.icon.md`), pad 8, text 12, widths 259 / 104 / 67 / 89 / 54 (spec §4.1); the smallest target the 44 × 20 narrow badge in compact (the header row gives 24 px of height); Density table
- [x] **Essential-exceptions log** — compact: the badge is 20 px tall inside a 24 px row — the row is the hit area (≥ 24 px), so no exception is logged; `none`
- [x] **Tokens used** — `color.surface.raised` (the chip's own fill), `color.border.default` (hairline), `color.border.strong` (hover), `color.text.primary` (letter), `color.text.secondary` (glyph, words), `type.ui.caption`, `radius.badge`, `size.icon.sm` / `.md`, `space.inset.xs`, `color.focus.ring`, `color.status.warning.strong` (the conflict glyph); PROPOSED `color.sync.a` / `.b` / `.c` as the tile edges; PROPOSED CMP-019 registry names `link` / `unlink`; `space.panelheader.*` does not exist (E15-D02 §12): 24 / 32 px rows; Penpot token sets = `packages/ui/tokens` at `28ae3f1dbb824e77acaf71f31d32a00c7cce81ee`
- [x] **Data contract confirmed** — `PaneConfig.sync_group` and the layout flags above; the axes shown are the group's switch set intersected with the panel kind's reach (E15-D02 D-24); pure chrome otherwise
- [ ] **Contrast and CVD** — PENDING until the boards PR: spec §12 — tile edges on the header A 9.76 / 4.38 / 9.76, B 11.00 / 4.11 / 11.00, C 4.09 / 5.21 / 4.09; letter 14.35 / 15.62 / 16.25 on the chip; words and glyph 8.81 / 8.98 / 14.35; focus ring 6.66 / 5.86 / 17.30, all PASS; CVD: the hues stay apart under the three deficiencies (ΔE ≥ 49.5 dark, ≥ 31.2 light) and collapse in greyscale (8.0 / 1.7) — the letter carries by design
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-188 PriceAxis, the link states (PROPOSED; E11 owner) (E15-D06, #360)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E15-D06 Sync groups`, frames `SCR-043/axis-linked`, `SCR-043/axis-independent`, `SCR-043/axis-linked-locked`, `SCR-043/menu-link-checked`, `SCR-043/menu-link-unchecked`, `SCR-043/link-no-group`, `SCR-043/linked-zoom-before`, `SCR-043/linked-zoom-after`, `SCR-043/link-refused`, `SCR-043/percent-result`, `SCR-043/link-refused-btc-eth`, `SCR-043/light-link-no-group`, `SCR-043/light-link-refused`; PNGs planned at `docs/design/E15/img/E15-D06-05-scale-link-axis-menu.png`, `-06-scale-link-refusal.png`, `-10-light-composite.png`
- [ ] **Variants × States matrix** — PENDING: states linked / independent / linked + locked (PROPOSED CMP-188 states, spec A-3) and the SCR-043 item checked / unchecked / T2 in no group (the one T2, spec §10.3) × dark / light / high-contrast; Table 1
- [x] **Keyboard table** — CMP-188's keys unchanged (`↑` `↓`, `Shift+↑` `↓`, `PageUp` `PageDown`, `Home`, `Shift+F10`, `Esc`); in the menu `Space` toggles the link item and keeps the menu open, `Enter` toggles and closes; the T2 item is arrow-reachable, `Enter` / `Space` change nothing and re-show the reason once, politely; the refusal `alertdialog` focuses Use percentage scale, `Esc` = Cancel, focus returns to the asker (spec §9); Table 2
- [x] **Accessible name / role table** — the `group` surrogate "Price axis, 63,900 to 64,300, linear, auto, linked to group A" (PROPOSED clause); `menuitemcheckbox` "Link scale to group A" with `aria-checked`, in no group `aria-disabled="true"` + `aria-describedby` → "Join a sync group to link its scale." (`scale.link.no_group`, PROPOSED key, owner E11-D03); `alertdialog` "Can't link these price scales" (spec §10.1); Table 3
- [x] **Live data** — the axis text changes on a link change only (polite once: "Price scale linked to group A." / "Independent scale."); the linked zoom is the engine's `sync` message ≤ 1 / frame, no live region (spec §7.6, §10.2); Table 5
- [x] **Motion pair** — none animated (the axis text swaps; the dialog opens instantly under reduced motion, CMP-043's pair otherwise); Table 4
- [x] **Density notes** — the axis text at `type.ui.caption` beside the mode tag at every axis density; the menu rows `size.control.height` 24 / 32 (E11-D03 §3.1); the dialog CMP-043 `sm` `alertdialog` (not CMP-044, spec C-16); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.text.tertiary` (the axis text and the T2 label and lock glyph), `color.text.secondary` (the T2 reason), `color.surface.overlay` + `color.border.default` (the menu and the dialog), `color.text.primary`, `color.action.primary.default` + `color.text.on-action` (the primary action), `color.focus.ring`, `type.ui.caption`, `elevation.popover`, `radius.card`; never `color.text.disabled` or `opacity.disabled` on the T2 item; Penpot token sets = `packages/ui/tokens` at `28ae3f1dbb824e77acaf71f31d32a00c7cce81ee`
- [x] **Data contract confirmed** — `scale_mode` (`PaneScaleMode`, no `percent`: G-5), no link target (G-6), the threshold constant unhomed (G-7); E15-S05's bus payload `priceLevel` / scale range; `26` has no linked-price-scale primitive (G-9)
- [ ] **Contrast and CVD** — PENDING until the boards PR: spec §12 — axis text 5.96 / 6.36 / 11.87 (CMP-188's own, reproduced), T2 label and lock 5.20 / 5.44 / 10.36, T2 reason 8.14 / 8.26 / 13.27, dialog text 13.27 / 14.37 / 15.02, primary action label 4.76 / 4.76 / 7.45, all PASS; no colour carries the link state (text only)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

**CMP-190 Crosshair — reuse note (E11-D02 owns it; no block).** The remote crosshair is E11-D02 D9's, unchanged: 1 px dashed `color.crosshair` at `opacity.muted`, a neutral time pill, at the engine's three densities (5.12 / 4.17 / 5.12:1 blended over the canvas). The one addition is PROPOSED to E11 (spec A-9): a 1 px `color.surface.canvas` halo when the background is a footprint cell (the dash alone 1.06–1.76:1; with the halo 4.41–9.87). The synced timestamp and price reach the DOM mirror and the axis pills through a PROPOSED `source` field (spec A-8); no React header readout exists.

### Table 1 — Variants × States

| Component | Variant                  | State (every one is a Penpot variant and a story)                                                                                             | Penpot variant (planned)                                                                               | Story (planned)                                                      | Notes                                                                  |
| --------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| CMP-218   | popover                  | Unsynced (no group) · GroupA (AD-4 defaults) · AllAxesOn · PartialAxes · Conflict (interval mismatch) · ScaleLinkRefused (the dialog over it) | `SCR-023/popover-no-sync`, `SCR-023/popover-1280`, `SCR-023/conflict-interval`, `SCR-043/link-refused` | Unsynced, GroupA, AllAxesOn, PartialAxes, Conflict, ScaleLinkRefused | CMP-017 host (spec C-16); the account row is an absence in every state |
| CMP-218   | modal                    | the same six at 200 % (one column, sticky footer, scrolling body; between the TopBar and the StatusBar, never over them)                      | `SCR-023/modal-200pct`                                                                                 | Modal200                                                             | `aria-modal`, focus trap                                               |
| CMP-082   | badge, compact           | none · A · B · C; words / count / tile + glyph; conflict glyph on                                                                             | `CMP-082/badge-*-compact`, `CMP-082/badge-narrow-steps`, `CMP-082/conflict-header`                     | NoSync, WithSyncBadge, NarrowHeader, ConflictGlyph                   | the tile and the glyph never collapse                                  |
| CMP-082   | badge, comfortable       | A (the pair the tool gates)                                                                                                                   | `CMP-082/badge-a-comfortable`                                                                          | WithSyncBadge (comfortable)                                          | —                                                                      |
| CMP-082   | forced-colors, greyscale | the hue dropped / Rec. 601                                                                                                                    | `CMP-082/badge-forced-colors`, `CMP-082/badge-greyscale`                                               | —                                                                    | the letter carries                                                     |
| CMP-188   | axis                     | linked · independent · linked + locked (PROPOSED)                                                                                             | `SCR-043/axis-*`                                                                                       | LinkedToGroup, Independent                                           | E11 owner                                                              |
| CMP-041   | SCR-043 link item        | checked · unchecked · T2 in no group                                                                                                          | `SCR-043/menu-link-*`, `SCR-043/link-no-group`                                                         | Checkable, DisabledWithReason (CMP-041's existing stories)           | the one T2; `disabledReason` path                                      |

### Table 2 — Keyboard

| Component | Key                               | Action                                                                               | Focus after         | Global conflict? (`05` §3.2 / §3.3)                          | Notes                              |
| --------- | --------------------------------- | ------------------------------------------------------------------------------------ | ------------------- | ------------------------------------------------------------ | ---------------------------------- |
| CMP-218   | `Tab` / `Shift+Tab`               | radio → switches → account row → scale selects → ×                                   | the next stop       | none                                                         | the account row is focusable       |
| CMP-218   | `←` `→` `↑` `↓`                   | move and select the group (live apply)                                               | the chosen radio    | none                                                         | —                                  |
| CMP-218   | `Space` / `Enter`                 | toggle a switch                                                                      | the switch          | none                                                         | AN-6                               |
| CMP-218   | `Esc`                             | close; never gated                                                                   | the trigger         | none (`Esc` untouched as the innermost cancel)               | —                                  |
| CMP-082   | `Enter` / `Space`                 | open Sync group ▸                                                                    | the first menu item | none                                                         | —                                  |
| CMP-082   | `Shift+F10`                       | the panel menu (Sync group ▸ inside)                                                 | the first menu item | a component key, not a keymap row                            | E15-D02 §7's lint note             |
| CMP-188   | `Shift+F10`                       | SCR-043                                                                              | the first menu item | none                                                         | —                                  |
| CMP-041   | `Space` / `Enter`                 | toggle "Link scale to group A" (keep open / close); T2: nothing, the reason re-shown | the item / the axis | none                                                         | AN-9 / AN-10 / AN-11               |
| CMP-043   | `Enter` / `Esc`                   | accept percent / cancel                                                              | the asker           | none                                                         | AN-12 / AN-13                      |
| —         | `Ctrl+Shift+1..3`, `Ctrl+Shift+0` | join A / B / C, unsync                                                               | —                   | **conflict**: `05` §3.2 `Ctrl+Shift+1` = Toggle 1-click; H-3 | PROPOSED-PENDING via CMP-022; OQ-9 |

### Table 3 — Accessible name / role

| Component | Element         | Role                   | Accessible name (source)                             | States / properties                                                          |
| --------- | --------------- | ---------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| CMP-218   | the popover     | `dialog`               | "Sync — Chart · BTCUSDT 1m"                          | `aria-modal` at 200 % only                                                   |
| CMP-218   | group radio     | `radiogroup` / `radio` | "Group"; "A", "B", "C", "No sync"                    | `aria-checked`                                                               |
| CMP-218   | axis switch     | `switch`               | the label                                            | `aria-checked`; `aria-describedby` → consequence (+ conflict)                |
| CMP-218   | account switch  | `switch`               | "Account and trade group"                            | `aria-disabled="true"`; `aria-describedby` → the note; no lock, no key       |
| CMP-218   | conflict notice | `status`               | the sentence                                         | polite once                                                                  |
| CMP-218   | scale select    | `combobox`             | "Price scale, Chart · BTCUSDT 1m"                    | options Independent scale / Linked to group A                                |
| CMP-082   | badge           | `button`               | "Sync group A" / "No sync"                           | `aria-describedby` → the axes; `aria-haspopup="menu"`                        |
| CMP-082   | panel region    | `region`               | "Chart, BTCUSDT 15m"                                 | description: group, axes, environment, conflict, provenance                  |
| CMP-188   | axis surrogate  | `group`                | "Price axis, …, linked to group A" (PROPOSED clause) | —                                                                            |
| CMP-041   | link item       | `menuitemcheckbox`     | "Link scale to group A"                              | `aria-checked`; T2: `aria-disabled="true"` + `aria-describedby` → the reason |
| CMP-043   | refusal         | `alertdialog`          | "Can't link these price scales"                      | initial focus on the primary                                                 |

### Table 4 — Motion pair

| Component | Property               | motion-safe                              | motion-reduce | Duration / easing tokens           |
| --------- | ---------------------- | ---------------------------------------- | ------------- | ---------------------------------- |
| CMP-218   | popover open           | CMP-017's pair (E15-D14 owns the timing) | instant       | `motion.duration.fast` (CMP-017's) |
| CMP-082   | badge hover / focus    | none (token swap)                        | none          | —                                  |
| CMP-188   | axis text, linked zoom | none (engine redraw within one frame)    | none          | —                                  |
| CMP-043   | refusal open           | CMP-043's pair                           | instant       | CMP-043's                          |

### Table 5 — Live data

| Component | Field                            | Politeness | Cadence                           | Coalescing   | Notes                                               |
| --------- | -------------------------------- | ---------- | --------------------------------- | ------------ | --------------------------------------------------- |
| CMP-218   | members list, consequence counts | none       | computed on open                  | n/a          | never a live region                                 |
| CMP-218   | conflict notice                  | polite     | once when it first arises         | n/a          | AN-5                                                |
| CMP-082   | badge                            | none       | on membership / axis change       | n/a          | announcements AN-1, AN-2, AN-7 come from the change |
| CMP-188   | axis link text                   | polite     | once per link change              | n/a          | AN-9 / AN-10                                        |
| CMP-190   | synced crosshair (reuse)         | none       | the mirror's cadence (E06-D03 D5) | latest value | never per tick                                      |

### Density

| Component | Mode        | Row / control height                                           | Padding tokens                        | Smallest target               |
| --------- | ----------- | -------------------------------------------------------------- | ------------------------------------- | ----------------------------- |
| CMP-218   | compact     | title 24, column rows 60, full rows 44, selects 28; height 437 | `space.inset.md` 16; `space.inset.xs` | 24 × 24 (the switch, ×)       |
| CMP-218   | comfortable | 32 / 72 / 54 / 36; height 525                                  | `space.inset.md`                      | 32 × 32                       |
| CMP-082   | compact     | badge 20 in the 24 px row; tile 16; glyph 12; min width 44     | pad 6, gap 4                          | the 24 px row (hit area) × 44 |
| CMP-082   | comfortable | badge 24 in 32; tile 18; glyph 16; min width 54                | pad 8, gap 4                          | 32 × 54                       |
| CMP-188   | all         | the axis text at `type.ui.caption`; menu rows 24 / 32          | `space.inset.sm`                      | the menu item (24 × 280 min)  |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| —         | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-023 and the SCR-043 link item

- [x] Tier-2 / Tier-3 tokens only; the three `color.sync.*` are PROPOSED and aliased, never hard-coded (spec §12)
- [ ] Verified in three themes × two densities — PENDING (boards)
- [x] Contrast-matrix: 81 gated pairs, 0 FAIL (tool §3); PROPOSED `pairs.mjs` rows for E15-S04
- [x] CVD simulation reviewed: three deficiencies + greyscale (tool §4)
- [ ] Every state a Penpot variant and a story — PENDING (boards); the lists in Table 1
- [x] Disabled states: the one T2 (CMP-041 `disabledReason`; CMP-079 on the Save leg); the account row an absence, never a bare disabled control and never a lock
- [x] Loading / empty / error: no loading state exists (the list is computed on open); "No sync" is the designed empty reading; the refusal is the designed error
- [x] Keyboard-interaction table (spec §9.1–§9.3; Table 2)
- [x] Accessible-name / role table (spec §10.1; Table 3)
- [x] Canvas-adjacent strategy: the synced crosshair through the DOM mirror and the axis pills (spec §7.6, A-8)
- [x] Motion pair: none / instant (Table 4)
- [x] Hit targets ≥ 24 px compact (the header row is the badge's hit area); none logged
- [ ] Accessibility role sign-off — E15-D15
- [x] Trading-specific safety: the propagated symbol change disarms every armed panel (server request, assertive) and no sync write re-arms; the environment never changes through sync (spec §6.3, §8.3)
- [x] Estimated values: none here

## B. Accessibility acceptance criteria (`05` §10) — SCR-023 (+ the SCR-043 link item)

```gherkin
Feature: SCR-023 sync groups and the per-panel scale link — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user joins a panel to group A, toggles Interval sync, links its price scale and leaves the group
    Then every control involved is reachable via Tab or arrow-key navigation (the badge, the radio, the six switches, the scale select, the SCR-043 item)
    And every pointer action has a documented keyboard path (spec §9.3; none is pointer-only)
    And focus is never moved by a propagated symbol change, a disarm or a conflict
    And a visible 2 px focus ring meeting ≥ 3:1 is present at every step (6.66 / 5.86 / 17.30 on the header)

  Scenario: Screen-reader operation
    Given the user is using NVDA or VoiceOver with the keyboard
    When the user opens SCR-023 from a badge named "Sync group A"
    Then the dialog is named "Sync — Chart · BTCUSDT 1m" and focus lands on the current group's radio
    And each switch is announced with its label, its state and its consequence line
    And the account switch is announced as unavailable with its note, with no lock and no reason key
    And joining is announced politely once with its consequence ("… shared with 2 panels.")

  Scenario: Conflict and refusal
    Given two members of group A on different intervals with crosshair sync on
    Then "Chart 15m has a different interval: crosshair sync aligns by timestamp." is in the popover, on the affected header and in that panel's description, and never only a toast
    When the user links BTCUSDT's scale to a group holding SOLUSDT
    Then an alertdialog names both symbols and both magnitudes, announces assertively once, focuses "Use percentage scale", and Esc cancels with focus returned

  Scenario: The one T2 and the exits
    Given a panel in no group
    Then "Link scale to group A" keeps its role and full label, is aria-disabled, arrow-reachable, carries the lock glyph and "Join a sync group to link its scale." as its second line
    And Enter or Space changes nothing and re-shows the reason with one polite announcement
    And leaving a group, unlinking a scale, × and Esc are never gated in any session

  Scenario: Colour independence and zoom
    Given the three group badges and the synced crosshair
    Then every badge carries its letter and glyph, and reads under protanopia, deuteranopia, tritanopia, greyscale and forced-colors
    And at 200 % the popover becomes a modal with one column, a sticky footer and a scrolling body, nothing clipped
    And the modal sits between the TopBar and the StatusBar, so the ENV badge, the Safety cluster, the banner band and the StatusBar stay visible and unscrimmed
```
