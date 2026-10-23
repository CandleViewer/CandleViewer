# E30-D03 — handoff checklists (SCR-076, SCR-077, SCR-158, SCR-114 and the selector; #851)

Per `docs/plan/16-design-system-brief.md` §11.4 and §13.3 item 8 (`02` §4.2): this SCR ticket changes three component contracts — **CMP-044 ConfirmDialog**, **CMP-105 AccountMultiSelect** and **CMP-232 LimitsChip** — so each gets a block below; the components it only composes (CMP-046 Drawer, CMP-068 CopyableCodeBlock, CMP-036 KeyValueRow, CMP-124 TradeGroupSummaryCard, CMP-158 SafetyInvariantNotice) get one placement line each and link their own checklists. **Deviation from the §11.4 block shape (the lane shape of E25-D05 / E36-D02):** Tables 1–5, the Density table and the Essential-exceptions table appear once each with a leading `Component` column instead of once per block. Every line is `[x]` with its evidence or `[ ] N/A — <reason>`; BLOCKED-PENPOT lines are N/A with the reason until hpe-worker-1 draws (2026-10-22). Prop names are PROPOSED (spec §10, A10–A12).

## Handoff checklist — CMP-044 ConfirmDialog (E30-D03, #851)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: BLOCKED-PENPOT (2026-10-22). Page `E30-D03 Confirmation, rejection, defaults and selector` (id pinned once created; never a URL, host, team or file id); planned PNGs `docs/design/E30/img/E30-D03-01-scr-076-anatomy.png`, `-02-scr-076-demo-live-timeout.png`, `-03-scr-076-fanout.png`, `-13-themes-densities.png`
- [ ] N/A — **Variants × States matrix**: PENDING until drawn; Table 1 lists the planned frames (spec §3: 18 `SCR-076/<state>` frames)
- [x] **Keyboard table** — Table 2 (spec §11): APG dialog keys only, Cancel focused on open, every activation of Confirm — `Enter`, `Space`, pointer — accepted ≥400 ms after open (`confirmDelayMs`), `Esc` cancels, focus returns to the submit; the LIVE don't-ask box is a Tab stop (T2, E09-D09 §2.2) and a press on it re-shows its reason once; no view-local override of a global binding, `Esc` / `Ctrl+K` untouched
- [x] **Accessible name / role table** — Table 3: `role="dialog"` `aria-modal` named `confirm.name`, the environment sentence + the full-intent line as `aria-describedby` (the rows navigable as CMP-036 dt / dd), the Confirm's name restates the whole order
- [x] **Live data** — Table 5: the countdown (`aria-live="off"`, polite at 0:10 and 0:00), the preview rows (the last settled answer; nothing streams inside the dialog); the replay and send-now confirms open on a fresh preview (SCR-158 → `SCR-076/replay` / `SCR-076/fanout-send-now`)
- [x] **Motion pair** — Table 4: open / close and the countdown's last five seconds are E30-D04's recipes with instant twins; the value-change highlight is an instant token swap
- [x] **Density notes** — Density table: 560 / 640 px, rows 24 / 32 px, smallest target 24 × 24 px (the close `×`)
- [x] **Essential-exceptions log** — `none`
- [x] **Tokens used** — spec §2 / §13: `color.surface.overlay`, `elevation.dialog`, `elevation.scrim`, `space.dialog.padding`, `space.row.height.{compact,comfortable}`, `color.text.{primary,secondary,tertiary,inverse}`, `color.buy.default` / `color.sell.default`, `color.env.{live,demo}`, `color.focus.ring`, `radius.badge`, `type.ui.{heading-sm,body-strong}`, `type.num.{md,base}`; none invented (CMP-043's `elevation.4` → `elevation.dialog`, A13); Penpot token sets = `packages/ui/tokens` at `99da22f17c100bd626d45db3792de6d468f0d8c3`
- [x] **Data contract confirmed** — `POST /trade-groups/preview` (`TradeGroupPreview.legs[].resolved`, `estimated_margin_usd`, `estimated_risk_usd`, `totals`; re-run for Replay and for "Send 2 of 4 legs now — BUY BTCUSDT limit 64,010.0…", the held leg `overrides.skip: true`), `POST /orders`, `POST /trade-groups` (`atomicity`, `compensate`), `POST /settings/arm` (the `X-Arm-Token`), `GET /risk/summary`; gaps named: the auto-cancel seconds key (G6), the cancelled-reason payload (G7)
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; the tool's numbers (34 pairs × 3 themes, FAIL 0; 15 CVD rows) and the 18 PROPOSED `pairs.mjs` rows are spec §13
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
- [x] **Tokens used** — spec §8 / §13: `color.surface.{overlay,raised,selected,hover}`, `color.text.{primary,secondary,tertiary}`, `color.env.{live,demo}`, `color.status.danger.strong`, `color.focus.ring`, `space.row.height.*` (CMP-105's `space.list.row` does not exist, A11); Penpot token sets = `packages/ui/tokens` at `99da22f17c100bd626d45db3792de6d468f0d8c3`
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
- [x] **Tokens used** — `color.status.warning.subtle` / `.strong` for the binding row (CMP-232's `color.status.warn` does not exist — D02 A-10), `color.text.{primary,secondary}` on `color.surface.overlay`; Penpot token sets = `packages/ui/tokens` at `99da22f17c100bd626d45db3792de6d468f0d8c3`
- [x] **Data contract confirmed** — the account profile (`24` §9.2 caps), `GET /risk/summary` (`cap_utilisation_pct`, `lockout`), `GET /instruments/{symbol}`; the limits of spec §1.4 (max position 17,500 USDT, daily 120 of 500 USDT, lev ≤ 10x, min 0.001 BTC)
- [ ] N/A — **Contrast and CVD**: PENDING on the exports; spec §13
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] N/A — **Sign-off**: owner approval pending (#851)

**Placement lines (contract unchanged):** CMP-046 Drawer — SCR-077, right, `modal: false`, `role="dialog"` named `drawer.name` throughout; the CMP-027 class banner inside it is the `role="alert"` that fires once on open (A13; Table 3). CMP-068 CopyableCodeBlock — the exchange record with a `<blockquote>` for the verbatim text (A13). CMP-036 KeyValueRow — the restatement rows and "What CandleViewer sent". CMP-124 TradeGroupSummaryCard — the group's aggregate on SCR-061 (E28's). CMP-158 SafetyInvariantNotice — one line in the confirm and in SCR-114's Stop fieldset (D02 D12). CMP-079 RbacGate + CMP-019 Icon `lock` (`decorative=false`, name "Not available") — the LIVE don't-ask box (CMP-044) and the read-only member row with its include checkbox (CMP-105), E09-D09 §2.2 / §8: the raised fill with the hairline, the lock leading the full label, the reason linked by `aria-describedby`.

### Table 1 — Variants × States (planned frames; PENDING until drawn)

| Component | Variant                  | State                                                                                                                                                                                                                                                                                            | Penpot variant / frame                                      | Story name     | Notes                                     |
| --------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | -------------- | ----------------------------------------- |
| CMP-044   | standard · order-confirm | live-limit · live-limit-comfortable · demo-limit · live-market · live-conditional · countdown-10s · countdown-5s · timed-out · cancelled · confirmed · dont-ask-demo · dont-ask-live-disabled · preview-stale-refused · fanout · fanout-all-or-none · fanout-narrowed · replay · fanout-send-now | `SCR-076/<state>` (boards 01–03, 08)                        | OrderConfirm   | 18 frames; the arm dialog is D02 board 07 |
| CMP-105   | account · group          | single · list-open · group-chosen · group-expanded · leg-excluded · leg-override · would-be-rejected · narrowed · member-disabled · stale-wallet-leg · no-groups-owner · no-groups-manager                                                                                                       | `SCR-061/<state>` (board 12)                                | TargetSelector | 12 frames                                 |
| CMP-232   | results                  | none binding (every default confirm) · binding (the clamp / lockout frames of SCR-061)                                                                                                                                                                                                           | inside `SCR-076/live-limit` and `SCR-061/would-be-rejected` | LimitsResults  | rows, not a chip                          |

### Table 2 — Keyboard

| Component | Key                                                                | Action                                                                                                                                                                             | Focus after                           | Global conflict?                                       | Notes                                |
| --------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------ | ------------------------------------ |
| CMP-044   | open · `Tab` / `Shift+Tab`                                         | the dialog opens with focus on Cancel, never the Confirm; then Cancel → Confirm → `×` → don't-ask (DEMO: live; LIVE: T2, `aria-disabled`, still a Tab stop) — the DOM order, 2.4.3 | Cancel, then the next stop (trapped)  | none                                                   |                                      |
| CMP-044   | `Enter` / `Space` / pointer on Confirm                             | <400 ms after open: nothing; ≥400 ms: activates                                                                                                                                    | unchanged, then the submit control    | absorbs a `Ctrl+Enter` pass-through and a double-click | `confirmDelayMs` 400 gates all three |
| CMP-044   | `Esc`                                                              | cancels                                                                                                                                                                            | the submit control                    | none (`Esc` is the dialog's own)                       | never disabled on this instance      |
| CMP-044   | any key / pointer                                                  | restarts the 20 s countdown                                                                                                                                                        | unchanged                             | none                                                   | `autoCancelMs` 20,000                |
| CMP-044   | `Enter` / `Space` / pointer on the LIVE don't-ask box (T2)         | nothing is staged — no toggle, no request; the reason \"LIVE orders always confirm.\" is re-shown inline and announced once, politely (E09-D09 §9.3; E17-D01 D13)                  | unchanged                             | none                                                   | `aria-disabled`, never `disabled`    |
| CMP-044   | Save current as… (the templates dialog)                            | the same dialog keys: focus to the name field, `Esc` cancels                                                                                                                       | the name field; `Esc` → the button    | none                                                   | spec §9, §11                         |
| CMP-105   | `Alt+↓` / `Enter`                                                  | opens the list                                                                                                                                                                     | the active option                     | none                                                   | combobox pattern                     |
| CMP-105   | `↑` `↓` `Home` `End` · `Enter` / `Esc`                             | moves the active option · picks / closes the innermost                                                                                                                             | `aria-activedescendant` · the control | none                                                   |                                      |
| CMP-105   | `Shift+F10` on a leg row                                           | Include / Exclude / Override menu                                                                                                                                                  | the first item                        | none                                                   |                                      |
| CMP-105   | `Enter` / `Space` / pointer on the read-only member's include (T2) | nothing is staged — no toggle, no preview re-run; `rbac.account_read_only` is re-shown inline and announced once, politely (E09-D09 §9.3)                                          | unchanged                             | none                                                   | `aria-disabled`, still a Tab stop    |
| CMP-105   | `Shift+F10` on the read-only member's row                          | the leg menu with Include present and `aria-disabled`, its second line `rbac.account_read_only` (E09-D09 §9.3)                                                                     | the first item                        | none                                                   |                                      |

### Table 3 — Accessible name / role

| Component | Element                     | Role                     | Accessible name (source)                                                                          | States / properties                                                                                                                                                        |
| --------- | --------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-044   | the dialog                  | dialog, `aria-modal`     | `confirm.name` "Confirm order - BTCUSDT - LIVE - Main"                                            | `aria-describedby` = the env sentence + the full-intent line; `aria-busy` on the Confirm while sending                                                                     |
| CMP-044   | Confirm button              | button                   | `confirm.confirm.name` "Confirm: buy 0.250 BTCUSDT limit 64,010.0 with stop 63,900.0, LIVE, Main" | never autofocused; `aria-busy` after Confirm                                                                                                                               |
| CMP-044   | don't-ask checkbox (LIVE)   | checkbox                 | "Don't ask again for DEMO limit orders"                                                           | `aria-disabled` + `aria-describedby` → "LIVE orders always confirm." (T2, E09-D09 §2.2: the lock glyph "Not available" leading the label; a Tab stop)                      |
| CMP-044   | countdown                   | text (`aria-live="off"`) | "Cancels in 20 seconds unless you act"                                                            | polite announcements at 0:10 and 0:00 only                                                                                                                                 |
| CMP-046   | the drawer (placement line) | dialog (non-modal)       | `drawer.name` "Order rejected - BTCUSDT - LIVE - Main"                                            | focus to the heading on open, back to [Details] on close; the CMP-027 class banner inside is the `role="alert"`, fired once                                                |
| CMP-105   | the control                 | combobox                 | "Target: Group Core3, 3 accounts, 2 ready" / "Target: Main"                                       | `aria-expanded`, `aria-activedescendant`                                                                                                                                   |
| CMP-105   | an account / group row      | option                   | "Core3, 3 accounts, 2 of 3 ready" / "Main, LIVE account, 10x isolated One-Way"                    | `aria-selected`; a read-only member `aria-disabled` + `aria-describedby` (T2, E09-D09 §2.2: the lock leading the account; its include checkbox `aria-disabled`, focusable) |
| CMP-105   | a leg row                   | row (table)              | "sub_002, 0.110 BTC, 10x, stop 63,900.0 held by Bybit (exchange), ready"                          | include / exclude as a checkbox; the override flag as text                                                                                                                 |
| CMP-232   | the results block           | group                    | "Profile limits"                                                                                  | the binding row's text names the limit and the authority                                                                                                                   |

### Table 4 — Motion pair

| Component | Property                                        | motion-safe                                                    | motion-reduce      | Duration / easing tokens                             |
| --------- | ----------------------------------------------- | -------------------------------------------------------------- | ------------------ | ---------------------------------------------------- |
| CMP-044   | open / close; the countdown's last five seconds | fade + 8 px rise (E30-D04's recipe); the number only, no pulse | instant; identical | motion.duration.normal, motion.easing.standard; none |
| CMP-105   | disclosure open / close                         | height tween (E30-D04's recipe)                                | instant            | motion.duration.normal, motion.easing.standard       |

### Table 5 — Live data

| Component | Field                                                                              | Politeness                                                          | Cadence                                      | Coalescing                 | Notes                                                                                                           |
| --------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------- | -------------------------- | --------------------------------------------------------------------------------------------------------------- |
| CMP-044   | countdown                                                                          | off; polite at 0:10 and 0:00                                        | once per second visually                     | —                          | never per second to the screen reader (05 §6.2)                                                                 |
| CMP-044   | restatement rows                                                                   | none                                                                | one settled preview answer                   | —                          | the dialog does not update while open                                                                           |
| CMP-044   | replay / send-now preview (SCR-158 → `SCR-076/replay` / `SCR-076/fanout-send-now`) | polite ("Preview updating…" on the pressed button, then the dialog) | one fresh preview per press                  | latest answer only         | the dialog opens on the fresh settled answer, never the held numbers; a refusal lands on the held or banner row |
| CMP-105   | preview re-run; the stale-wallet leg age                                           | polite (results count); none                                        | debounced per draft change; per wallet frame | latest answer / value only | E28-T05's route; "equity not available — wallet data is 14 s old"                                               |
| CMP-232   | binding limit (on the ticket)                                                      | polite, once on change                                              | on change only                               | —                          | D02 D14                                                                                                         |

### Density

| Component | Mode                  | Row / control height                                                    | Padding tokens                                        | Smallest target         |
| --------- | --------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------- |
| CMP-044   | compact / comfortable | 24 px (space.row.height.compact) / 32 px (space.row.height.comfortable) | space.dialog.padding, space.inset.sm / space.inset.md | 24 × 24 px / 32 × 32 px |
| CMP-105   | compact / comfortable | 24 px / 32 px                                                           | space.inset.sm / space.inset.md, space.field.gap      | 24 × 24 px / 32 × 32 px |
| CMP-232   | compact / comfortable | 24 px / 32 px                                                           | space.inset.sm / space.inset.md                       | — (static)              |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all three | none      | —                    | —        | —    |

## §A — Design QA checklist (`16` §12), filled

- [x] Only published Tier-2 / Tier-3 tokens (spec §2, §13); zero hard-coded hex or px in the spec beyond the measured redlines.
- [ ] N/A — three themes × two densities verified visually: BLOCKED-PENPOT; the tool measures all three themes (spec §13); board 13 shows every screen, the selector and the template list in light and hc.
- [x] Contrast matrix for every pair introduced (34 × 3, FAIL 0; 18 PROPOSED `pairs.mjs` rows routed).
- [x] CVD simulation reviewed for every new colour-carrying state (15 rows; the collapses carried by word / glyph / shape).
- [ ] N/A — every State has a Penpot variant and a Storybook story: the frames are planned (Table 1), the stories are E30-S04 / S06 / S07 / T02's.
- [x] Disabled states use disabled-with-reason (CMP-079 / CMP-019 `lock` / E09-D09 §2.2 T2: the raised fill with the hairline, the lock leading the full label, no opacity), never a bare disabled control; the one form-validity disable (Save while a default is above its ceiling, E09-D09 §9.1) names its reason in its label.
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

| Screen  | Primary task (keyboard-only, screen-reader)                        | Keyboard-only                                                                                                                                                                                                                          | Screen reader                                                                                                                                                              | Colour-independence                                         | Contrast                          | Reduced motion                      | Automated gates                                                  |
| ------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | --------------------------------- | ----------------------------------- | ---------------------------------------------------------------- |
| SCR-076 | confirm a LIVE limit order with the keyboard                       | `Ctrl+Enter` → Cancel focused → `Tab` → Confirm → `Enter` ≥400 ms after open (`Space` and a click wait the same 400 ms); `Esc` returns focus to the submit; the LIVE don't-ask box is a Tab stop (T2); no focus moved by the countdown | the dialog's name, the env sentence + the full-intent line as its description (the rows navigable), the Confirm's full name; the countdown announced at 0:10 and 0:00 only | LIVE = word + weight + dot + sentence; side = ▲ / ▼ + words | spec §13 (overlay rows ≥4.5 / ≥3) | open / close instant twin; no pulse | axe 0 serious / critical; Lighthouse ≥95; keyboard E2E — E30-S04 |
| SCR-077 | read why the order was rejected and retry with the corrected price | [Details] → the drawer heading → `Tab` to Copy, Retry, the disclosure, the link; `Esc` returns to [Details]                                                                                                                            | the drawer `role="dialog"`; the class banner `role="alert"` once with the class line + code; the quote block announced as "Exchange message, verbatim"                     | class banner = glyph + words; the quote = rule + mono       | spec §13                          | drawer open / close instant twin    | axe 0; keyboard E2E — E30-T02                                    |
| SCR-158 | see when a held order may be replayed and replay it                | `Tab` to Replay → `Enter` → the preview re-runs (Replay `aria-busy`) → SCR-076 opens on the fresh answer; Discard reachable; "Send 2 of 4 legs now — BUY BTCUSDT limit 64,010.0…" on the fan-out banner follows the same path          | `role="status"` ≤1 per 10 s, absolute + relative time; the held row's full-intent label read in full                                                                       | clock glyph + words                                         | spec §13                          | the countdown changes text only     | axe 0; keyboard E2E — E30-T02                                    |
| SCR-114 | set the DEMO defaults and refuse the LIVE skip                     | segmented control → fieldsets in order → the LIVE `never when armed` option reachable, not selectable (a press re-shows the reason once) → the template list → Save                                                                    | each fieldset's legend; units read with every number; the T2 reason via `aria-describedby`; "Saved · audited" polite                                                       | T2 = lock glyph + reason; saved = check + words             | spec §13                          | none animated                       | axe 0; keyboard E2E — E30-S07                                    |

Screen-reader spot test: **manual spot-test deferred to E30-D05 / E30-Q05 — stated** (no screen reader was run for this spec). Exceptions: none.
