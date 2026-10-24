# E33-D03 — Per-component handoff checklist (`16` §11.4; the contracts SCR-069's OCO half and SCR-070 introduce or change)

Three blocks — **CMP-118 AlgoProgressCard (row variant)**, **SCR-070 composite** (CMP-049 `grid` + CMP-023 `aria-valuetext` + CMP-035 + CMP-057 row menu + CMP-055 + CMP-028 banners + CMP-044 bulk dialogs) and **SCR-069 OCO-half composite** (the leg-pair fieldset + the CMP-042 variant switch + the residual-risk note; CMP-119 unchanged) — every line of the `16` §11.4 block kept, then Tables 1–5, the Density table and the Essential-exceptions table once each with a leading `Component` column (the E36-D02 shape), then §A the `16` §12 design-QA checklist and §B the `05` §10 template for SCR-069 and SCR-070. Addressed to **E33-D04**, the epic's design-system ticket, which embeds it (BQ-3 RULED): the `15` A-rows D03-A1…A4 in `docs/design/E33/E33-D03.md` §12 carry the copy-ready text. Every number is `docs/design/_tools/e33_d03_oco_monitor_audit.py`'s; the Penpot page `E33-D03 OCO builder and algo monitor` · id `1c76881c-3ef7-8021-8008-d6aa52da18d7`: all nine boards are drawn (board script r7); still owed: the CVD simulation of the a11y audit and the DS library variants. CMP-158 (contract unchanged; the builder variant is D03-A3), CMP-100 / CMP-101 (unchanged; their T2 and validity looks are `15`'s) and CMP-079 / CMP-019 (unchanged) get this line and no block.

## Handoff checklist — CMP-118 AlgoProgressCard, row variant (E33-D03, #935)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E33-D03 OCO builder and algo monitor` · id `1c76881c-3ef7-8021-8008-d6aa52da18d7`; board 04 (specimens `SCR-070/row-*`, board `8769d983-89dd-80ab-8008-d6b2d30e4f4e`), `docs/design/E33/img/E33-D03-04-scr-070-row-kinds.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): 4 kinds (TWAP · iceberg · chase · OCO, `algoType` + `"oco"`, D03-A1) × 13 run-row kinds + 2 orphan rows (spec §6); Table 1
- [x] **Keyboard table** — one roving stop in the grid, `↑` / `↓` rows, `←` / `→` cells, `Enter` on the Actions cell opens the row menu, `Shift+F10` / Menu anywhere, `Ctrl+Delete` through the bulk dialog, `Esc` closes and never cancels (spec §10); Table 2
- [x] **Accessible name / role table** — `row` with `aria-rowindex`; the State cell glyph + text; the Progress cell CMP-023 `role="progressbar"` with `aria-valuetext` = the text (M4); each control named verb + target + effect (spec §5, §6); Table 3
- [x] **Live data** — the run record re-sent at each reconcile (D03-G2, G4); progress polite, focused row only, ≤ 1 / 5 s; countdowns `aria-live="off"` from one shared 1 s ticker; Table 5
- [x] **Motion pair** — a value flash ≤200 ms on the focused row's own change, none under reduced motion; determinate bars; nothing past 5 s without a pause control (`16` §7); the full spec is E33-D04's; Table 4
- [x] **Density notes** — compact 24 px rows, comfortable 32 px; smallest target the 24 × 24 Actions disclosure; the 300 px core (spec §5, §9); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px by padding)
- [x] **Tokens used** — `color.text.primary` / `.secondary` / `.tertiary`, `color.surface.canvas` / `.raised` / `.hover` / `.selected`, `color.status.{success,warning,danger,info}.{subtle,strong}`, `color.data-confidence.stale.{text,surface}`, `color.action.primary.default` (the bar) on `color.surface.sunken` (`color.track` MISSING — DS request 1), `color.focus.ring`, `type.ui.body`, `type.ui.caption`, `type.num.base`, `size.row.height`, `space.inset.sm`, `radius.badge`; Penpot token sets = `packages/ui/tokens` at the branch base
- [ ] **Data contract confirmed** — NO: the row binds `AlgoState` (`24` :2730–2742: `status`, `filled_qty`, `remaining_qty`, `active_child_ids`, `slices_done` / `slices_total`, `avg_fill_price`, `next_action_at`, `last_error`), `machines.algo:{id}.state` (`23` :898) and B8's `sl.*` states, which have no public wire id today (`23` :909, W9 — D03-G11); `chart_state`, `paused_by`, `halt_reason`, `last_reconciled_at`, `shortfall_qty` and the run verbs are D03-G1…G6 (spec §11); the `15` data-contract sentence is replaced by D03-A1
- [ ] **Contrast and CVD** — PENDING (CVD planned on the exports): spec §14 — the T2 label 5.62 / 5.92 / 11.21, the Paused word on `warning.subtle` 9.86 / 15.62 / 11.16, the Halted word on `danger.subtle` 12.06 / 14.64 / 13.66, the Completed word 10.21 / 15.41 / 11.56, the stale row 10.69 / 7.37 / 17.42, all PASS; every state is glyph + word + fill
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — SCR-070 composite: the algo monitor grid, header, banners and bulk dialogs (E33-D03, #935)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E33-D03 OCO builder and algo monitor` · id `1c76881c-3ef7-8021-8008-d6aa52da18d7`; frame `SCR-070/running` (board 03, `docs/design/E33/img/E33-D03-03-scr-070-anatomy.png`), the 12 panel states (board 05, `docs/design/E33/img/E33-D03-05-scr-070-panel-states.png`), the 6 bulk frames (board 06, `-06-bulk-actions.png`), the density frames (board 07, `-07-density-100-rows-and-zoom.png`)
- [ ] **Variants × States matrix** — PENDING: 2 hosts (the CMP-080 panel · the SCR-063 Algos tab) × 13 panel states (spec §7 + `running`) × 2 densities; Table 1
- [x] **Keyboard table** — Tab: header controls → filter bar → the grid (one roving stop) → footer; the dialogs open with focus on Cancel, Confirm accepts an activation ≥400 ms after open, `Esc` closes the dialog and never cancels a run, and focus returns to the trigger; `Enter` on Acknowledge moves focus to the next row, else the panel header (spec §10); Table 2
- [x] **Accessible name / role table** — `region` "Algos — Main · DEMO"; the table `role="grid"` with `aria-rowcount` (100 on the density frame) and a caption carrying the "Emulated" tag's name once; the case-1 in-panel line and the case-2 banner `role="status"` (the case-1 line silent on first render — SCR-152 already alerted); the bulk dialogs `role="alertdialog"`; the panel notices as the `aria-describedby` of every gated control (spec §5, §7, §8); Table 3
- [x] **Live data** — the header age (M1) repaints once a second from one ticker, `aria-live="off"`, the warning past 60 s announced polite once; the At-Bybit-now total polite ≤ 1 / 2 s; the resume line assertive once in the app's one post-reconnect summary; a halt one assertive summary per event; Table 5
- [x] **Motion pair** — row movement per E29-D01 D13(a)–(e): stable order, ended rows linger, the flash ≤200 ms, none under reduced motion; dialogs open with `16` §7's `normal` scale + fade, instant under reduce; Table 4
- [x] **Density notes** — rows 24 / 32 px; the header one row in both; at 200 % zoom the table reflows to cards; the 300 px dock keeps Kind · Symbol · State · At Bybit now · Actions (spec §9); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the CMP-118 set plus `color.surface.overlay` (dialogs), `color.border.default`, `color.text.on-action` on `color.action.primary.default` / `color.status.danger.default` (Confirm / Cancel all), `color.data-confidence.reconnecting.indicator` on `color.surface.canvas` (the case-2 accent; on `color.surface.raised` it measures 2.9992 in light and is rejected), `color.env.demo` (the badge), `color.status.info.subtle` (CMP-158's details line), `space.inset.sm` / `.md`, `radius.card`, `radius.control`
- [ ] **Data contract confirmed** — NO: every run verb (pause · resume · cancel · cancel_and_flatten · adopt · cancel-orphan), `GET /algos`, `POST /algos/cancel-all`, `POST /algos/pause-all`, the per-item result shape and the adopt step-up class are D03-G1, G7, G8, G10 (spec §11); shipped today: `cancelAllOrders` (`22` :5871, not a run verb), `setKillSwitch` (`22` :6504; the view-as carve-out — the exits stay enabled under view-as too, spec D03-C16), `machines.algo:{id}.state`
- [ ] **Contrast and CVD** — PENDING: spec §14 — the DEMO badge 14.35 / 15.62 / 16.25 (7:1 met), the case-2 accent on canvas 8.45 / 3.22 / 8.45, the Cancel all label on `danger.default` 5.05 / 10.31 / 4.54, the focus ring on raised 6.66 / 5.86 / 17.30, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — SCR-069 OCO-half composite: the variant switch, the leg-pair fieldset, the residual-risk note (E33-D03, #935)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E33-D03 OCO builder and algo monitor` · id `1c76881c-3ef7-8021-8008-d6aa52da18d7`; `SCR-069/editing-entry-pair` (board 01, `docs/design/E33/img/E33-D03-01-scr-069-oco-anatomy.png`) and the 14 frames + `SCR-076/oco` (board 02, `docs/design/E33/img/E33-D03-02-scr-069-states.png`)
- [ ] **Variants × States matrix** — PENDING: 3 variants (A2 entry pair · A1 entry + exit pair · B standalone exit pair; A1 and B refused on the plain TP + SL fixture, D03-Q6) × the 14 states of spec §3 × 2 densities; Table 1
- [x] **Keyboard table** — E32-D02's prefix (entry → stop; stop → the legs when there is no entry) → Leg A → Leg B → the pre-submit disclosure → Cancel → Place; the mode line and CMP-158 are read, not focused; `Esc` closes before a submit; initial focus on the first editable leg field, on the first invalid field after a failed Place, on Acknowledge in a residual-risk state (spec §10); Table 2
- [x] **Accessible name / role table** — the variant switch `tablist` / `tab` (manual activation); the fieldset "OCO legs" with each leg's read-out line in its description; Place's name restating both legs, account and environment; the residual note `role="note"`, kept until acknowledged; CMP-158 `role="note"` (spec §2, §3); Table 3
- [x] **Live data** — the leg read-outs (distance from mark) polite ≤ 1 / 2 s; nothing else streams; Table 5
- [x] **Motion pair** — none animated: the variant switch and the validation boundary are instant token swaps (`16` §7); Table 4
- [x] **Density notes** — 24 px wells and rows in compact, 32 px in comfortable; the 640 px dialog fills the viewport at 1280 × 800 / 200 % with the pre-submit block as a disclosure; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.text.primary` / `.secondary` / `.tertiary`, `color.surface.overlay` / `.raised` / `.app`, `color.border.default`, `color.status.danger.default` + `border.thick` (the 2 px boundary), `color.status.danger.strong` (glyph), `color.status.info.subtle` / `.strong` (CMP-158, the refusal's route block), `color.status.warning.subtle` / `.strong` (the residual note), `color.action.selected` (the active tab rule), `color.focus.ring`, `type.ui.body`, `type.ui.caption`, `type.ui.label`, `type.num.base`, `size.control.height`, `space.inset.sm`, `radius.control`
- [ ] **Data contract confirmed** — NO: the legs bind `24` `OcoParams` (`leg_a`, `leg_b`, `mode = reduce_other`, `reduce_only`) which `22` `AlgoSpec.oco` (`other_price`, `other_trigger`, `cancel_timeout_ms`) cannot carry — D03-CG1 (spec §12); Place keeps the validity look with "contract pending" until `22` matches; the entry-pair submit path is `placeOrder` / `createTradeGroup` with `algo.kind: oco` once the model lands
- [ ] **Contrast and CVD** — PENDING: spec §14 — the validation boundary on the overlay 3.17 / 8.24 / 3.75, the refusal words on `danger.subtle` 12.06 / 14.64 / 13.66, the residual note's words on `warning.subtle` 9.86 / 15.62 / 11.16, the Emulated tag word 8.81 / 8.98 / 14.35, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component         | Variant                      | State (every one is a Penpot variant and a story)                                                                                                                                                                  | Penpot variant (planned)               | Story (planned)      |
| ----------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------- | -------------------- |
| CMP-118 row       | TWAP · iceberg · chase · OCO | running · paused by you · waiting for Bybit · rate limit · account down · bound passed · orders need you · not visible · completed · ended short · failed · halted · double fill corrected (spec §6)               | `SCR-070/row-<kind>`                   | `Row/<Kind>/<State>` |
| CMP-118 row       | orphan                       | not linked · untracked                                                                                                                                                                                             | `SCR-070/orphan-*`                     | `Row/Orphan/*`       |
| SCR-070 composite | panel · Algos tab            | running · loading · empty · filter-empty · degraded case 1 · degraded case 2 · after reconnect · account down · halted kill switch · lockout untracked · viewer read-only · view-as · manager other user (spec §7) | `SCR-070/<state>`, `SCR-063/algos-tab` | `Monitor/<State>`    |
| SCR-070 composite | bulk                         | cancel-all confirm · cancel-all result · pause-all confirm · cancel confirm · cancel-and-flatten confirm · residual row detail (spec §8)                                                                           | `SCR-070/bulk-*`, `/cancel-*`          | `Monitor/Bulk/*`     |
| SCR-069 OCO half  | A2 · A1 · B                  | the 14 states of spec §3 + `SCR-076/oco`                                                                                                                                                                           | `SCR-069/<state>`                      | `OcoBuilder/<State>` |

### Table 2 — Keyboard

| Component       | Key                                              | Action                                                                                  | Focus after                         | Global conflict? (`05` §3.2 / §3.3)    |
| --------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------- | ----------------------------------- | -------------------------------------- |
| SCR-070 grid    | `Tab` / `Shift+Tab`                              | header controls → filter bar → the grid (one stop) → footer                             | the next stop                       | none                                   |
| SCR-070 grid    | `↑` / `↓`, `←` / `→`                             | rows (header row included), cells                                                       | the cell                            | none (roving)                          |
| SCR-070 grid    | `Enter` on the Actions cell · `Shift+F10` / Menu | opens the row menu with its disabled items present                                      | the first menu item                 | none                                   |
| SCR-070 grid    | `Ctrl+Delete`                                    | cancels the selected runs (else the focused run) through the bulk dialog (E29-D01 AM-2) | the dialog's Cancel                 | the registered blotter binding, reused |
| SCR-070 grid    | `Enter` on Acknowledge                           | clears the halted / failed / corrected row                                              | the next row, else the panel header | none                                   |
| SCR-070 grid    | `Esc`                                            | closes menus and dialogs; never cancels a run                                           | the trigger                         | the universal cancel                   |
| SCR-070 dialogs | `Enter` / `Space` on Confirm                     | accepted only ≥400 ms after open (E30-D03 D3)                                           | the panel header                    | none                                   |
| T2 controls     | `Enter` / `Space` / `Ctrl+Delete`                | nothing changes; the reason re-shown inline, announced once politely (E09-D09 §9.3)     | unchanged                           | none                                   |
| SCR-069         | `Tab`                                            | E32-D02's prefix → Leg A → Leg B → the disclosure → Cancel → Place                      | the next stop                       | none                                   |
| SCR-069         | `←` / `→` on the variant switch                  | moves between Bracket and OCO, manual activation (`Enter` / `Space` switches)           | the tab                             | none                                   |
| SCR-069         | `Esc`                                            | closes before a submit; keeps a pending result                                          | the opening control                 | the universal cancel                   |

### Table 3 — Accessible name / role

| Component         | Element                            | Role                                         | Accessible name (source)                                                                                    | States / properties                                                                            |
| ----------------- | ---------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| SCR-070           | the panel                          | `region`                                     | "Algos — Main · DEMO" (CMP-080 `title`)                                                                     | —                                                                                              |
| SCR-070           | the table                          | `grid`                                       | the caption "Algos — Emulated — run by CandleViewer, not Bybit"                                             | `aria-rowcount`, `aria-rowindex`, `aria-colindex`; sortable headers `aria-sort`                |
| CMP-118 row       | the State cell                     | `gridcell`                                   | the glyph's name + the label + the cause                                                                    | —                                                                                              |
| CMP-118 row       | the Progress cell                  | `progressbar` (CMP-023)                      | the kind + progress                                                                                         | `aria-valuenow`, `aria-valuetext` = the text                                                   |
| CMP-118 row       | the Next action cell               | text (CMP-035)                               | "next slice in 0:22"                                                                                        | `aria-live="off"`                                                                              |
| CMP-118 row       | a control                          | `button` / `menuitem`                        | verb + target + effect ("Cancel TWAP a_12 on BTCUSDT, Main — its 0.07 BTC order at Bybit is cancelled too") | T2: `aria-disabled="true"` + `aria-describedby` → the reason; never `disabled`                 |
| SCR-070           | the case-2 banner                  | `status` (CMP-028 `connection-reconnecting`) | the bold lead                                                                                               | polite, once per episode                                                                       |
| SCR-070           | the case-1 in-panel line           | `status` (CMP-028 `connection-reconnecting`) | the bold lead                                                                                               | no announcement on first render (SCR-152's `role="alert"` already fired); later updates polite |
| SCR-070           | the panel notice (viewer, view-as) | text                                         | the E09-D09 §3.1 sentence                                                                                   | the `aria-describedby` of every gated control                                                  |
| SCR-070           | the bulk dialogs                   | `alertdialog` (CMP-044)                      | the restatement sentence                                                                                    | focus on Cancel; `aria-modal`                                                                  |
| SCR-069           | the variant switch                 | `tablist` / `tab`                            | "Bracket" / "OCO"                                                                                           | `aria-selected`; manual activation                                                             |
| SCR-069           | the leg pair                       | `group` (fieldset)                           | "OCO legs"                                                                                                  | each leg's read-out line as its description                                                    |
| SCR-069           | Place                              | `button`                                     | "Place OCO: buy 0.500 BTC at 64,050.0 (stop 63,940.0) or 63,990.0 (stop 63,880.0), Main, DEMO"              | validity look: `aria-disabled`, the reason beside it; T2 for the role / view-as legs           |
| SCR-069           | the residual-risk note             | `note` (CMP-028 `warning`)                   | the note's first sentence                                                                                   | kept until Acknowledge; not a live region                                                      |
| SCR-069 / SCR-070 | CMP-158                            | `note`                                       | the `e32.sl.note.draft` sentence                                                                            | not in the Tab order                                                                           |

### Table 4 — Motion pair

| Component   | Property                                    | motion-safe                                  | motion-reduce     | Duration / easing tokens                                            |
| ----------- | ------------------------------------------- | -------------------------------------------- | ----------------- | ------------------------------------------------------------------- |
| CMP-118 row | value flash on the focused row's own change | background flash ≤200 ms decaying to neutral | no flash          | `motion.duration.fast`, `motion.easing.standard` (E33-D04 confirms) |
| CMP-118 row | the progress bar                            | determinate width change                     | the same, instant | `motion.duration.fast`                                              |
| SCR-070     | dialog open                                 | `normal` scale + fade                        | instant           | `motion.duration.normal`                                            |
| SCR-070     | skeleton rows                               | `slow` shimmer                               | static two-tone   | `motion.shimmer`                                                    |
| SCR-069     | the variant switch, the validation boundary | instant token swap                           | the same          | —                                                                   |

### Table 5 — Live data

| Component   | Field                                             | Politeness                                           | Cadence             | Coalescing              |
| ----------- | ------------------------------------------------- | ---------------------------------------------------- | ------------------- | ----------------------- |
| SCR-070     | the header age "Checked with Bybit 12 s ago"      | `aria-live="off"`; the warning past 60 s polite once | 1 s from one ticker | —                       |
| SCR-070     | the At-Bybit-now total                            | polite                                               | ≤ 1 / 2 s           | latest value            |
| CMP-118 row | progress                                          | polite, focused row only                             | ≤ 1 / 5 s           | latest value            |
| CMP-118 row | countdowns                                        | `aria-live="off"`                                    | 1 s, one ticker     | CMP-035 thresholds only |
| SCR-070     | halts, account down, failures, double fills       | assertive, once per event / account / run            | discrete            | one summary per event   |
| SCR-070     | completion, ended short, cancelled, bound reached | polite, once per run / episode                       | discrete            | —                       |
| SCR-069     | the leg read-outs                                 | polite                                               | ≤ 1 / 2 s           | latest value            |

### Density

| Component            | Mode                  | Row / control height      | Padding tokens           | Smallest target                     |
| -------------------- | --------------------- | ------------------------- | ------------------------ | ----------------------------------- |
| CMP-118 row, SCR-070 | compact (default)     | 24 px / `size.row.height` | `space.inset.sm`         | the 24 × 24 Actions disclosure      |
| CMP-118 row, SCR-070 | comfortable           | 32 px                     | `space.inset.md`         | 32 × 32                             |
| SCR-069 OCO half     | compact / comfortable | 24 / 32 px wells          | `space.inset.sm` / `.md` | the 24 × 24 nudge buttons (CMP-100) |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| —         | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-069 OCO half and SCR-070

- [x] Dark-first; light is a token swap through `themes.json` (board 09); both densities (spec §9, the Density table)
- [x] Every state in `14`'s entry has a named frame (spec §3, §6–§9; §15 reconciles the checklists)
- [x] Semantic tokens only; `color.track` MISSING recorded; no hard-coded colour
- [x] Colour never the sole encoding: glyph + word + fill on every chip; side as "▲ Buy" / "▼ Sell"; DEMO as a text badge
- [x] Contrast ≥4.5:1 text / ≥3:1 non-text in every theme (spec §14: 35 gated pairs, 0 FAIL); the DEMO badge ≥7:1
- [x] Focus visible and never obscured; one roving stop in the grid; dialogs trap and return focus
- [x] Motion-safe / motion-reduce pairs (Table 4); nothing past 5 s without a pause control
- [x] Every control's accessible name carries its target and effect; T2 controls keep role, label and focusability
- [ ] Storybook stories for the three contracts — E33-D04 / E33-S06
- [ ] Owner approval — pending

## B. Accessibility acceptance criteria (`05` §10) — SCR-069 and SCR-070

- Keyboard: every control reachable by `Tab` or the grid's arrows; the row menu by `Shift+F10`; `Esc` closes without cancelling a run; no single unmodified key is bound (spec §10).
- Screen reader: the grid announces rows and cells; progress is read as its text (`aria-valuetext`); a T2 control reads its name, "unavailable", then the reason; the residual note is a `note`, the case-2 banner a `status`, the bulk dialogs `alertdialog`s.
- Live regions: progress ≤ 1 / 5 s on the focused row; countdowns silent; one assertive summary per halt or account event; no update moves focus.
- Contrast and CVD: spec §14; the greyscale strip on board 09; `forced-colors` keeps words and glyphs.
- Zoom: 200 % reflows the grid to cards and the dialog to a scrolling body with a sticky footer; nothing is clipped.
- Timing: the only timed gate is E30-D03's 400 ms acceptance delay on Confirm; the 20 s auto-cancel is off for an algo (memo SC-9).
