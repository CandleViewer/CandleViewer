# E30-D03 — handoff checklists (SCR-076, SCR-077, SCR-158, SCR-114 and the selector; #851)

Per `docs/plan/16-design-system-brief.md` §11.4 and §13.3 item 8 (`02` §4.2): this SCR ticket changes three component contracts — **CMP-044 ConfirmDialog**, **CMP-105 AccountMultiSelect** and **CMP-232 LimitsChip** — so each gets a block below; the components it only composes (CMP-046 Drawer, CMP-068 CopyableCodeBlock, CMP-036 KeyValueRow, CMP-124 TradeGroupSummaryCard, CMP-158 SafetyInvariantNotice) get one placement line each and link their own checklists. **Deviation from the §11.4 block shape (the lane shape of E25-D05 / E36-D02):** Tables 1–5, the Density table and the Essential-exceptions table appear once each with a leading `Component` column instead of once per block. Every line is `[x]` with its evidence or `[ ] N/A — <reason>`; BLOCKED-PENPOT lines are N/A with the reason until hpe-worker-1 draws (2026-10-22). Prop names are PROPOSED (spec §10, A10–A12).

## Handoff checklist — CMP-044 ConfirmDialog (E30-D03, #851)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: BLOCKED-PENPOT (2026-10-22). Page `E30-D03 Confirmation, rejection, defaults and selector` (id pinned once created; never a URL, host, team or file id); planned PNGs `docs/design/E30/img/E30-D03-01-scr-076-anatomy.png`, `-02-scr-076-demo-live-timeout.png`, `-03-scr-076-fanout.png`, `-13-themes-densities.png`
- [ ] N/A — **Variants × States matrix**: PENDING until drawn; Table 1 lists the planned frames (spec §3: 17 `SCR-076/<state>` frames)
- [x] **Keyboard table** — Table 2 (spec §11): APG dialog keys only, Cancel focused on open, `Enter` accepted ≥400 ms after open, `Esc` cancels, focus returns to the submit; no view-local override of a global binding, `Esc` / `Ctrl+K` untouched
- [x] **Accessible name / role table** — Table 3: `role="dialog"` `aria-modal` named `confirm.name`, the restatement as `aria-describedby`, the Confirm's name restates the whole order
- [x] **Live data** — Table 5: the countdown (`aria-live="off"`, polite at 0:10 and 0:00), the preview rows (the last settled answer; nothing streams inside the dialog)
- [x] **Motion pair** — Table 4: open / close and the countdown's last five seconds are E30-D04's recipes with instant twins; the value-change highlight is an instant token swap
- [x] **Density notes** — Density table: 560 / 640 px, rows 24 / 32 px, smallest target 24 × 24 px (the close `×`)
- [x] **Essential-exceptions log** — `none`
- [x] **Tokens used** — spec §2 / §13: `color.surface.overlay`, `elevation.dialog`, `elevation.scrim`, `space.dialog.padding`, `space.row.height.{compact,comfortable}`, `color.text.{primary,secondary,tertiary,inverse}`, `color.buy.default` / `color.sell.default`, `color.env.{live,demo}`, `color.focus.ring`, `radius.badge`, `type.ui.{heading-sm,body-strong}`, `type.num.{md,base}`; none invented (CMP-043's `elevation.4` → `elevation.dialog`, A13); Penpot token sets = `packages/ui/tokens` at `081101c0d95d98b54e7166aff780d604dabf7c84`
- [x] **Data contract confirmed** — `POST /trade-groups/preview` (`TradeGroupPreview.legs[].resolved`, `estimated_margin_usd`, `estimated_risk_usd`, `totals`), `POST /orders`, `POST /trade-groups` (`atomicity`, `compensate`), `POST /settings/arm` (the `X-Arm-Token`), `GET /risk/summary`; gaps named: the auto-cancel seconds key (G6), the cancelled-reason payload (G7)
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; the tool's numbers (34 pairs × 3 themes, FAIL 0; 15 CVD rows) and the 19 PROPOSED `pairs.mjs` rows are spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#851)

## Handoff checklist — CMP-105 AccountMultiSelect (E30-D03, #851)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: BLOCKED-PENPOT (2026-10-22). Page `E30-D03 Confirmation, rejection, defaults and selector`; planned PNG `docs/design/E30/img/E30-D03-12-selector.png`
- [ ] N/A — **Variants × States matrix**: PENDING until drawn; Table 1 lists the planned frames (spec §8: 12 `SCR-061/<state>` frames)
- [x] **Keyboard table** — Table 2 (spec §11): the CMP-048 combobox keys, `Shift+F10` on a leg row, `Esc` innermost; nothing global overridden
- [x] **Accessible name / role table** — Table 3: `role="combobox"` named "Target: Group Core3, 3 accounts, 2 ready", rows `role="option"`, the leg table `role="table"`, T2 rows `aria-disabled` + `aria-describedby`
- [x] **Live data** — Table 5: the preview re-runs on each change (debounced; polite results count); the stale-wallet leg shows its age
- [x] **Motion pair** — Table 4: the disclosure open / close is E30-D04's recipe with an instant twin; row state flips are token swaps
- [x] **Density notes** — rows 24 / 32 px; smallest target 24 × 24 px (the include / exclude control)
- [x] **Essential-exceptions log** — `none`
- [x] **Tokens used** — spec §8 / §13: `color.surface.{overlay,raised,selected,hover}`, `color.text.{primary,secondary,tertiary}`, `color.env.{live,demo}`, `color.status.danger.strong`, `color.focus.ring`, `space.row.height.*` (CMP-105's `space.list.row` does not exist, A11); Penpot token sets = `packages/ui/tokens` at `081101c0d95d98b54e7166aff780d604dabf7c84`
- [x] **Data contract confirmed** — `GET /trade-group-definitions` (listed only when every member is granted, SR-E28-21; `members[].enabled`), `POST /trade-groups/preview` (`legs[].would_submit`, `rejection.code` ∈ the eight, `rejection.message`), `TradeGroupLegInput.overrides.skip`; gaps named: readiness (G3), served / unserved (G4), the skipped read-only leg vs the scope check (G5)
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#851)

## Handoff checklist — CMP-232 LimitsChip (E30-D03, #851)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: BLOCKED-PENPOT (2026-10-22). Page `E30-D03 Confirmation, rejection, defaults and selector`; planned PNG `docs/design/E30/img/E30-D03-01-scr-076-anatomy.png`
- [ ] N/A — **Variants × States matrix**: PENDING until drawn; the `results` rendering appears on every `SCR-076/<state>` confirm frame (binding / none binding)
- [x] **Keyboard table** — Table 2: the results block is static text inside the dialog (no stop of its own); the ticket's chip keeps D02 D14's disclosure
- [x] **Accessible name / role table** — Table 3: a `role="group"` named "Profile limits" of CMP-036 rows; the binding row names the limit and the authority in text
- [x] **Live data** — Table 5: none inside the dialog (the rows are the settled preview); on the ticket D02 D14's once-on-change announcement
- [x] **Motion pair** — Table 4: none animated
- [x] **Density notes** — rows 24 / 32 px; no interactive target inside the dialog
- [x] **Essential-exceptions log** — `none`
- [x] **Tokens used** — `color.status.warning.subtle` / `.strong` for the binding row (CMP-232's `color.status.warn` does not exist — D02 A-10), `color.text.{primary,secondary}` on `color.surface.overlay`; Penpot token sets = `packages/ui/tokens` at `081101c0d95d98b54e7166aff780d604dabf7c84`
- [x] **Data contract confirmed** — the account profile (`24` §9.2 caps), `GET /risk/summary` (`cap_utilisation_pct`, `lockout`), `GET /instruments/{symbol}`; the limits of spec §1.4 (max position 17,500 USDT, daily 120 of 500 USDT, lev ≤ 10x, min 0.001 BTC)
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#851)

**Placement lines (contract unchanged):** CMP-046 Drawer — SCR-077, right, `modal: false`, `role="alert"` once on open (a documented instance, A13). CMP-068 CopyableCodeBlock — the exchange record with a `<blockquote>` for the verbatim text (A13). CMP-036 KeyValueRow — the restatement rows and "What CandleViewer sent". CMP-124 TradeGroupSummaryCard — the group's aggregate on SCR-061 (E28's). CMP-158 SafetyInvariantNotice — one line in the confirm and in SCR-114's Stop fieldset (D02 D12).

### Table 1 — Variants × States (planned frames; PENDING until drawn)

| Component | Variant                  | State                                                                                                                                                                                                                                                                          | Penpot variant / frame                                      | Story name     | Notes                                     |
| --------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | -------------- | ----------------------------------------- |
| CMP-044   | standard · order-confirm | live-limit · live-limit-comfortable · demo-limit · live-market · live-conditional · countdown-10s · countdown-5s · timed-out · cancelled · confirmed · dont-ask-demo · dont-ask-live-disabled · preview-stale-refused · fanout · fanout-all-or-none · fanout-narrowed · replay | `SCR-076/<state>` (boards 01–03, 08)                        | OrderConfirm   | 17 frames; the arm dialog is D02 board 07 |
| CMP-105   | account · group          | single · list-open · group-chosen · group-expanded · leg-excluded · leg-override · would-be-rejected · narrowed · member-disabled · stale-wallet-leg · no-groups-owner · no-groups-manager                                                                                     | `SCR-061/<state>` (board 12)                                | TargetSelector | 12 frames                                 |
| CMP-232   | results                  | none binding (every default confirm) · binding (the clamp / lockout frames of SCR-061)                                                                                                                                                                                         | inside `SCR-076/live-limit` and `SCR-061/would-be-rejected` | LimitsResults  | rows, not a chip                          |

### Table 2 — Keyboard

| Component | Key                       | Action                                    | Focus after             | Global conflict?                    | Notes                                    |
| --------- | ------------------------- | ----------------------------------------- | ----------------------- | ----------------------------------- | ---------------------------------------- |
| CMP-044   | open                      | the dialog opens                          | Cancel                  | none                                | never the Confirm                        |
| CMP-044   | `Tab` / `Shift+Tab`       | Cancel → Confirm → don't-ask (DEMO) → `×` | the next stop (trapped) | none                                |                                          |
| CMP-044   | `Enter` <400 ms           | nothing                                   | unchanged               | absorbs a `Ctrl+Enter` pass-through | `confirmDelayMs` 400                     |
| CMP-044   | `Enter` ≥400 ms / `Space` | activates the focused button              | the submit control      | none                                |                                          |
| CMP-044   | `Esc`                     | cancels                                   | the submit control      | none (`Esc` is the dialog's own)    | never disabled on this instance          |
| CMP-044   | any key / pointer         | restarts the 20 s countdown               | unchanged               | none                                | `autoCancelMs` 20,000                    |
| CMP-105   | `Alt+↓` / `Enter`         | opens the list                            | the active option       | none                                | combobox pattern                         |
| CMP-105   | `↑` `↓` `Home` `End`      | moves the active option                   | `aria-activedescendant` | none                                |                                          |
| CMP-105   | `Enter` / `Esc`           | picks / closes the innermost              | the control             | none                                |                                          |
| CMP-105   | `Shift+F10` on a leg row  | Include / Exclude / Override menu         | the first item          | none                                |                                          |
| CMP-232   | —                         | static inside the dialog                  | —                       | none                                | the ticket's chip keeps D02's disclosure |

### Table 3 — Accessible name / role

| Component | Element                   | Role                     | Accessible name (source)                                                                          | States / properties                                                            |
| --------- | ------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| CMP-044   | the dialog                | dialog, `aria-modal`     | `confirm.name` "Confirm order - BTCUSDT - LIVE - Main"                                            | `aria-describedby` = the restatement; `aria-busy` on the Confirm while sending |
| CMP-044   | Confirm button            | button                   | `confirm.confirm.name` "Confirm: buy 0.250 BTCUSDT limit 64,010.0 with stop 63,900.0, LIVE, Main" | never autofocused; `aria-busy` after Confirm                                   |
| CMP-044   | don't-ask checkbox (LIVE) | checkbox                 | "Don't ask again for DEMO limit orders"                                                           | `aria-disabled` + `aria-describedby` → "LIVE orders always confirm"            |
| CMP-044   | countdown                 | text (`aria-live="off"`) | "Cancels in 20 seconds unless you act"                                                            | polite announcements at 0:10 and 0:00 only                                     |
| CMP-105   | the control               | combobox                 | "Target: Group Core3, 3 accounts, 2 ready" / "Target: Main"                                       | `aria-expanded`, `aria-activedescendant`                                       |
| CMP-105   | an account / group row    | option                   | "Core3, 3 accounts, 2 of 3 ready" / "Main, LIVE account, 10x isolated One-Way"                    | `aria-selected`; a read-only member `aria-disabled` + `aria-describedby`       |
| CMP-105   | a leg row                 | row (table)              | "sub_002, 0.110 BTC, 10x, stop 63,900.0 held by Bybit, ready"                                     | include / exclude as a checkbox; the override flag as text                     |
| CMP-232   | the results block         | group                    | "Profile limits"                                                                                  | the binding row's text names the limit and the authority                       |

### Table 4 — Motion pair

| Component | Property                    | motion-safe                         | motion-reduce | Duration / easing tokens                       |
| --------- | --------------------------- | ----------------------------------- | ------------- | ---------------------------------------------- |
| CMP-044   | open / close                | fade + 8 px rise (E30-D04's recipe) | instant       | motion.duration.normal, motion.easing.standard |
| CMP-044   | countdown last five seconds | the number only; no pulse           | identical     | none                                           |
| CMP-105   | disclosure open / close     | height tween (E30-D04's recipe)     | instant       | motion.duration.normal, motion.easing.standard |
| CMP-232   | none animated               | —                                   | —             | —                                              |

### Table 5 — Live data

| Component | Field                         | Politeness                   | Cadence                    | Coalescing         | Notes                                            |
| --------- | ----------------------------- | ---------------------------- | -------------------------- | ------------------ | ------------------------------------------------ |
| CMP-044   | countdown                     | off; polite at 0:10 and 0:00 | once per second visually   | —                  | never per second to the screen reader (05 §6.2)  |
| CMP-044   | restatement rows              | none                         | one settled preview answer | —                  | the dialog does not update while open            |
| CMP-105   | preview re-run                | polite (results count)       | debounced per draft change | latest answer only | E28-T05's route                                  |
| CMP-105   | stale-wallet leg age          | none                         | per wallet frame           | latest value       | "equity not available — wallet data is 14 s old" |
| CMP-232   | binding limit (on the ticket) | polite, once on change       | on change only             | —                  | D02 D14                                          |

### Density

| Component | Mode        | Row / control height                 | Padding tokens                       | Smallest target |
| --------- | ----------- | ------------------------------------ | ------------------------------------ | --------------- |
| CMP-044   | compact     | 24 px (space.row.height.compact)     | space.dialog.padding, space.inset.sm | 24 × 24 px      |
| CMP-044   | comfortable | 32 px (space.row.height.comfortable) | space.dialog.padding, space.inset.md | 32 × 32 px      |
| CMP-105   | compact     | 24 px                                | space.inset.sm, space.field.gap      | 24 × 24 px      |
| CMP-105   | comfortable | 32 px                                | space.inset.md, space.field.gap      | 32 × 32 px      |
| CMP-232   | compact     | 24 px                                | space.inset.sm                       | — (static)      |
| CMP-232   | comfortable | 32 px                                | space.inset.md                       | — (static)      |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all three | none      | —                    | —        | —    |

## §A — Design QA checklist (`16` §12), filled

- [x] Only published Tier-2 / Tier-3 tokens (spec §2, §13); zero hard-coded hex or px in the spec beyond the measured redlines.
- [ ] N/A — three themes × two densities verified visually: BLOCKED-PENPOT; the tool measures all three themes (spec §13), the boards show light and hc on board 13.
- [x] Contrast matrix for every pair introduced (34 × 3, FAIL 0; 19 PROPOSED `pairs.mjs` rows routed).
- [x] CVD simulation reviewed for every new colour-carrying state (15 rows; the collapses carried by word / glyph / shape).
- [ ] N/A — every State has a Penpot variant and a Storybook story: the frames are planned (Table 1), the stories are E30-S04 / S06 / S07 / T02's.
- [x] Disabled states use disabled-with-reason (CMP-079 / E09-D09 T2), never a bare disabled control.
- [x] Loading / empty / error states designed (the record loading, the two empty states, the nine rejection frames).
- [x] Keyboard table completed (Table 2; spec §11).
- [x] Accessible-name / role table completed (Table 3).
- [x] No canvas-adjacent component.
- [x] Motion-safe / motion-reduce pair specified (Table 4).
- [x] Hit targets ≥24 px compact / 32 px comfortable; no essential exception.
- [ ] N/A — accessibility role sign-off: the owner's `approved` on #851 (agent-delivery adaptations); E30-D05 reviews.
- [x] Confirm-gate variant stated (`standard`) and its keyboard-only path specified (spec §2 gates).
- [x] Every estimated value is chip-tagged and links to its methodology (`(estimated)` on margin, fee, slippage, liquidation).
- [x] Demo / Live context unambiguous wherever a trading action can fire (the band, the pill, the rule, the sentence).
- [x] Reuses existing CMP ids; no near-duplicate requested.
- [ ] N/A — Storybook stories match the matrix: the implementing tickets'.
- [ ] N/A — composes only published-library components in Penpot: BLOCKED-PENPOT.

## §B — Accessibility acceptance criteria (`05` §10), filled per screen

| Screen  | Primary task (keyboard-only, screen-reader)                        | Keyboard-only                                                                                                                         | Screen reader                                                                                                                 | Colour-independence                                         | Contrast                          | Reduced motion                      | Automated gates                                                  |
| ------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | --------------------------------- | ----------------------------------- | ---------------------------------------------------------------- |
| SCR-076 | confirm a LIVE limit order with the keyboard                       | `Ctrl+Enter` → Cancel focused → `Tab` → Confirm → `Enter` ≥400 ms; `Esc` returns focus to the submit; no focus moved by the countdown | the dialog's name, the restatement as its description, the Confirm's full name; the countdown announced at 0:10 and 0:00 only | LIVE = word + weight + dot + sentence; side = ▲ / ▼ + words | spec §13 (overlay rows ≥4.5 / ≥3) | open / close instant twin; no pulse | axe 0 serious / critical; Lighthouse ≥95; keyboard E2E — E30-S04 |
| SCR-077 | read why the order was rejected and retry with the corrected price | [Details] → the drawer heading → `Tab` to Copy, Retry, the disclosure, the link; `Esc` returns to [Details]                           | `role="alert"` once with the class line + code; the quote block announced as "Exchange message, verbatim"                     | class banner = glyph + words; the quote = rule + mono       | spec §13                          | drawer open / close instant twin    | axe 0; keyboard E2E — E30-T02                                    |
| SCR-158 | see when a held order may be replayed and replay it                | `Tab` to Replay → `Enter` → SCR-076 opens; Discard reachable                                                                          | `role="status"` ≤1 per 10 s, absolute + relative time; the held row's full-intent label read in full                          | clock glyph + words                                         | spec §13                          | the countdown changes text only     | axe 0; keyboard E2E — E30-T02                                    |
| SCR-114 | set the DEMO defaults and refuse the LIVE skip                     | segmented control → fieldsets in order → the LIVE `never when armed` option reachable, not selectable → Save                          | each fieldset's legend; units read with every number; the T2 reason via `aria-describedby`; "Saved · audited" polite          | T2 = lock glyph + reason; saved = check + words             | spec §13                          | none animated                       | axe 0; keyboard E2E — E30-S07                                    |

Screen-reader spot test: **manual spot-test deferred to E30-D05 / E30-Q05 — stated** (no screen reader was run for this spec). Exceptions: none.
