# E32-D03 — Per-component handoff checklist (`16` §11.4; the contracts SCR-069's bracket half and CMP-119 introduce or change)

Two blocks — **CMP-119 BracketEditor** (all four consumers in one Variants × States table) and the **SCR-069 bracket-half composite** (CMP-043 + CMP-119 + CMP-158 + CMP-006 + the CMP-118 placing card + CMP-229 + the CMP-027 summary + the CMP-117 banner + CMP-079 / CMP-019 on the gated legs) — every line of the `16` §11.4 block kept, then Tables 1–5, the Density table and the Essential-exceptions table once each with a leading `Component` column, then §A the `16` §12 design-QA checklist and §B the `05` §10 template for SCR-069. Addressed to **E32-D07 (#927)**, which embeds it in the a11y review and handoff pack (BQ-3 RULED), and to **E32-D06 (#926)** for the DS rows: the `15` HA-rows in `docs/design/E32/E32-D03.md` §9 carry the copy-ready text. Every number is `docs/design/_tools/e32_d03_bracket_builder_audit.py`'s; the Penpot page is `E32-D03 Bracket builder` · id `62af8090-fa0a-80b4-8008-d74ac5de5491`, all ten boards drawn from board script r6. CMP-158 (contract unchanged; the ticket-variant sentence is `e32.sl.note.draft`, E32-D06's to publish), CMP-100 / CMP-101 (unchanged; their T2 and validity looks are `15`'s) and CMP-079 / CMP-019 (unchanged) get this line and no block.

## Handoff checklist — CMP-119 BracketEditor (E32-D03, #923)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E32-D03 Bracket builder` · id `62af8090-fa0a-80b4-8008-d74ac5de5491` (drawn, board script r6), specimens `CMP-119 / anatomy`, the mode matrix and the two disabled looks on board 06, the four consumer strips and the ladder rows on board 07; PNGs at `docs/design/E32/img/E32-D03-06-cmp119-anatomy-and-modes.png`, `-07-cmp119-consumers-and-ladder.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): 5 variants (ticket · existing position · bracket builder · profile default · reduce-only) × the states of spec §5.1 / §5.6 × 2 densities; Table 1
- [x] **Keyboard table** — `↑` / `↓` one tick, `Shift` ×10, `PageUp` / `PageDown` ×100 (O-6 open); `←` / `→` on a unit radiogroup; `Space` on the breakeven checkbox and the one-target / ladder radio; `Enter` commits, never places; Tab across the ladder rows (% then R per rung); on a T2 control nothing changes and the reason re-shows (spec §7); Table 2
- [x] **Accessible name / role table** — the `<fieldset>` "Protective orders"; the stop `spinbutton` "Stop-loss (required)" described by its source line and holder sentence; the unit `radiogroup`; the ladder a `table` with each rung named `bkt.ladder.row`; the risk block `aria-live="polite"`; CMP-158 `role="note"`; T2 per spec §1.3 (spec §5.1); Table 3
- [x] **Live data** — the recompute line local, polite ≤ 1 / 2 s; the server's `resolved.stop_loss_price`, `risk_usd` and `estimated_fee_usd` on blur / commit (`POST /trade-groups/preview`, debounced), a difference highlighted, never silent; nothing per keystroke over the network; Table 5
- [x] **Motion pair** — none animated: the reduce-only collapse, the boundary, the captions and the placing card forming are cuts in both modes (E30-D04 §10 :397; E32-D06 owns motion); Table 4
- [x] **Density notes** — compact 24 px rows and fields on `space.2`, comfortable 32 px on `space.3`; the source line one line in compact, the holder sentence wraps in comfortable; the ladder rows 24 / 32 px; the smallest target the 24 × 24 unit segment (spec §2.2); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px by padding)
- [x] **Tokens used** — `color.text.primary` / `.secondary` / `.tertiary` / `.on-action`, `color.surface.overlay` / `.raised` / `.app` / `.selected` / `.sunken`, `color.border.default`, `color.status.danger.default` (+ `border.thick`) / `.subtle` / `.strong`, `color.status.info.subtle` / `.strong`, `color.status.warning.subtle` / `.strong`, `color.status.success.subtle` / `.strong`, `color.action.primary.default`, `color.focus.ring`, `color.buy.default`, `color.sell.default`, `opacity.disabled`, `font.family.mono`, `type.num.sm` / `.base`, `type.ui.label` / `.caption` / `.body`, `size.row.height`, `size.control.height`, `space.1` / `.2` / `.4`, `space.inset.sm` / `.md`, `space.field.gap`, `radius.control`; every one resolves in dark / light / high-contrast (0 MISSING); Penpot token sets = `packages/ui/tokens` at the branch base
- [ ] **Data contract confirmed** — NO: the stop, the single target and `tpsl_mode` bind `PlaceOrderRequest` (`22` :18040–18042) and the ladder `algo.bracket.take_profit_levels[]` (`offset`, `pct_of_position`, ≤ 10, :17999–18012); the preview binds `ResolvedLegParams` (:18312); the stop's trigger has no field on `PlaceOrderRequest` (HG-6, "contract pending — G-23"), the refused child has no retry (HG-1), `LADDER_NOT_SPLITTABLE` and the sub-minimum merge are not in `22` / `24` (HG-2), the preview carries no liquidation estimate (HG-4); R on a target is a client-side input aid (`22` :5463–5464; HC-1); the `15` Props sentence is replaced by HA-4; the profile default binds `24` §9.2's `sl_offset_unit` ticks / percent / atr with the ATR period and multiple and the fallback % (:2379–2384)
- [x] **Contrast and CVD** — CVD renders delivered for 02 and 10 (greyscale and deuteranopia beside each export in `docs/design/E32/img/`); spec §11 — the T2 label 5.62 / 5.92 / 11.21, the T2 reason on raised 8.81 / 8.98 / 14.35, the danger boundary on the overlay 3.17 / 8.24 / 3.75, the Mono numbers in the well 16.06 / 17.99 / 18.18, the CMP-158 sentence 10.74 / 15.44 / 12.16, all PASS; the validity composite 2.59 / 1.96 / 2.58 reported, not gated
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — SCR-069 bracket-half composite: the dialog, the placing card, the gated legs (E32-D03, #923)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E32-D03 Bracket builder` · id `62af8090-fa0a-80b4-8008-d74ac5de5491` (drawn, board script r6), `SCR-069 / editing` (board 01), the 20 state frames across boards 02–05 and 09, the composite light twin (board 10); PNGs at `docs/design/E32/img/E32-D03-01-scr069-anatomy.png` … `-05-scr069-placing-and-partial.png`, `-09-e33-extension-point-and-zoom.png`, `-10-scr069-and-cmp119-light.png`
- [ ] **Variants × States matrix** — PENDING: 1 chassis × the 20 states of spec §3 (the E33 extension point among them) × 2 densities, LIVE on the arm frame only; Table 1
- [x] **Keyboard table** — initial focus the first invalid field, else the target from "Targets…", else the price; Tab Side → type → price → size → stop → unit → trigger → target / ladder → value → unit → breakeven → R → the arm pill (LIVE) → Cancel → Place; state controls after the region they act on; `Esc` closes before a submit and never cancels a sent request; focus returns to the invoker (spec §7); Table 2
- [x] **Accessible name / role table** — CMP-043 `dialog` "Bracket · BTCUSDT · Main · DEMO"; Place named with the full action (`bkt.place`); the CMP-027 summary `role="alert"` once with its heading focused; CMP-158 `role="note"`; the placing card's lines `status`; the one panel notice as the `aria-describedby` of every gated control; the T2 locks "Not available" (spec §1.3, §3, §6); Table 3
- [x] **Live data** — the preview line and the placing card's progress polite ≤ 1 / 2 s, latest value; a refusal, `accepted` / `accepted.partial` and an arm change assertive once; a merge note and a T2 re-show polite once; nothing streams from a write under view-as; Table 5
- [x] **Motion pair** — none animated: the placing card forming is a cut, the bar steps under reduced motion; dialog open per `16` §7's `normal` scale + fade, instant under reduce; Table 4
- [x] **Density notes** — rows 24 / 32 px; at 200 % on 1280 × 800 the dialog fills the viewport, the header and footer stay one sticky row each, the entry row stacks, the ladder and the risk block collapse into disclosures, the body scrolls (spec §2.2); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — the CMP-119 set plus `color.env.demo` / `.live` (the band and the badge), `color.surface.canvas`, `color.action.selected` (the selected tab), `color.data-confidence.stale.text` / `.surface` (the `· disconnected` inset), `radius.card`, `radius.badge`, `space.inset.sm` / `.md`
- [ ] **Data contract confirmed** — NO: the submit is `placeOrder` with `algo.kind: bracket` (`22` :5421, :18043), the acceptance `OrderAcceptance.trade_group` (:18455), the placing card WS `trade_groups` (`legs[].native_sl_confirmed`, `23` :3800; `legs[].error`) and `orders`; the gaps are HG-1 (the retry), HG-3 (`order.diagnostics_viewed`), HG-5 (the fee-aware breakeven offset), HG-6 (the trigger); every submit on LIVE carries `X-Arm-Token` (:14232), the retry included
- [x] **Contrast and CVD** — CVD renders delivered for 02 and 10 (greyscale and deuteranopia beside each export in `docs/design/E32/img/`); spec §11 — the dialog body 13.27 / 14.37 / 15.02, Place's label 4.76 / 4.76 / 7.45, the DEMO badge 14.35 / 15.62 / 16.25 (7:1 met), the LIVE border 4.42 / 4.51 / 4.42, the placing bar 4.41 / 3.39 / 8.08, the stale shading 10.69 / 7.37 / 17.42, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component         | Variant                                              | State (every one is a Penpot variant and a story)                                                                                                                         | Penpot variant (planned)    | Story (planned)                        |
| ----------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- | -------------------------------------- |
| CMP-119           | ticket (SCR-060)                                     | default (typed · profile · fallback) · focus · rounded-away · rounded-toward · empty stop · wrong-side stop · TP on / off · reduce-only collapsed · read-only T2          | `CMP-119 / ticket-<state>`  | `BracketEditor/Ticket/<State>`         |
| CMP-119           | existing position (SCR-064, by reference to E32-D05) | held stop (never emptied: `sl.kept`, `sl.loosen.refused`) · the ladder rungs with their class · breakeven and trail rows with the class word · read-only T2               | E32-D05's frames            | E32-D05's                              |
| CMP-119           | bracket builder (SCR-069)                            | the ticket states + ladder (3 rungs) · ladder step below minimum · ladder not splittable · breakeven on · the greyed trigger · T2 (viewer, view-as, arm, frozen, lockout) | `CMP-119 / bracket-<state>` | `BracketEditor/BracketBuilder/<State>` |
| CMP-119           | profile default (SCR-131; SCR-111 by reference)      | default (ticks · percent · ATR + the fallback %; no price, no R) · empty (validity) · read-only T2 — no holder line, no submit gate, no risk line                         | `CMP-119 / profile-<state>` | `BracketEditor/ProfileDefault/<State>` |
| CMP-119           | reduce-only                                          | collapsed (`sl.reduce_only`, `tp.reduce_only`)                                                                                                                            | `CMP-119 / reduce-only`     | `BracketEditor/ReduceOnlyCollapsed`    |
| SCR-069 composite | the bracket half                                     | the 20 states of spec §3                                                                                                                                                  | `SCR-069 / <state>`         | `BracketBuilder/<State>`               |

### Table 2 — Keyboard

| Component | Key                                                 | Action                                                                                                                          | Focus after         | Global conflict? (`05` §3.2 / §3.3) |
| --------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------------------- |
| CMP-119   | `↑` / `↓` (`Shift` ×10, `PageUp` / `PageDown` ×100) | one tick on a price or stop field; the recompute line follows                                                                   | the field           | none                                |
| CMP-119   | `←` / `→`                                           | moves the unit on a radiogroup; on a T2 radiogroup nothing changes and the reason re-shows                                      | the radio           | none                                |
| CMP-119   | `Space`                                             | toggles the breakeven checkbox; selects one target / ladder                                                                     | the control         | none                                |
| CMP-119   | `Enter`                                             | commits the field, never places                                                                                                 | the field           | none                                |
| SCR-069   | `Tab` / `Shift+Tab`                                 | Side → type → price → size → stop → unit → trigger → target / ladder → value → unit → breakeven → R → arm pill → Cancel → Place | the next stop       | none                                |
| SCR-069   | `Enter` / `Space` on Place (validity look)          | shows the error summary                                                                                                         | the summary heading | none                                |
| SCR-069   | `Enter` / `Space` / `Ctrl+Enter` on a T2 Place      | nothing changes; the reason re-shown inline, announced once politely (E09-D09 §9.3)                                             | unchanged           | none                                |
| SCR-069   | `Ctrl+Shift+T`                                      | opens E30-D02's LIVE arm dialog; while locked `arm.refused`                                                                     | the dialog          | the registered arm binding          |
| SCR-069   | `Esc`                                               | closes before a submit; never cancels a sent request                                                                            | the invoker         | the universal cancel                |

### Table 3 — Accessible name / role

| Component | Element            | Role                      | Accessible name (source)                          | States / properties                                                                                                                                    |
| --------- | ------------------ | ------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SCR-069   | the dialog         | `dialog`                  | "Bracket · BTCUSDT · Main · DEMO" (`e32.title.*`) | `aria-modal`; focus trapped and returned                                                                                                               |
| CMP-119   | the section        | `group` (fieldset)        | "Protective orders" (E30-D04 §10 :394)            | —                                                                                                                                                      |
| CMP-119   | the stop field     | `spinbutton`              | "Stop-loss (required)"                            | `aria-describedby` → the source line + the holder sentence; invalid: `aria-invalid` + the line; T2: `aria-disabled` + `readonly`, the lock in the well |
| CMP-119   | the unit switch    | `radiogroup`              | "Stop unit" / "Target unit" (CMP-003)             | T2: one lock leads the group; the profile default's units ticks / percent / ATR (spec §5.2)                                                            |
| CMP-119   | the trigger select | `combobox` (CMP-009)      | "Trigger"                                         | the validity look, `aria-disabled`, described by "contract pending — G-23"                                                                             |
| CMP-119   | the ladder         | `table`                   | "Take-profit ladder"                              | each row named `bkt.ladder.row`                                                                                                                        |
| CMP-119   | the breakeven row  | `checkbox` + `spinbutton` | "Breakeven" · "Breakeven at R"                    | the class word in the description                                                                                                                      |
| CMP-119   | the risk block     | `paragraph`               | `bkt.preview`                                     | `aria-live="polite"`, ≤ 1 / 2 s                                                                                                                        |
| SCR-069   | CMP-158            | `note`                    | `e32.sl.note.draft`                               | not in the Tab order                                                                                                                                   |
| SCR-069   | Place              | `button`                  | `bkt.place` (the full action)                     | validity look: `aria-disabled` + the reason beside it; T2: `aria-disabled` + `aria-describedby` → the reason, the lock leads the label                 |
| SCR-069   | the error summary  | `alert` (CMP-027)         | "{n} problems" + the rows                         | its heading takes focus after a press                                                                                                                  |
| SCR-069   | the placing card   | `group` (CMP-118)         | `bkt.placing`                                     | the lines `status`, polite ≤ 1 / 2 s; the bar `aria-valuetext`                                                                                         |
| SCR-069   | the panel notice   | text                      | `notice.panel_read_only` / `rbac.view_as`         | the `aria-describedby` of every gated control                                                                                                          |

### Table 4 — Motion pair

| Component | Property                                             | motion-safe                               | motion-reduce | Duration / easing tokens                  |
| --------- | ---------------------------------------------------- | ----------------------------------------- | ------------- | ----------------------------------------- |
| CMP-119   | the boundary, the captions, the reduce-only collapse | instant token swap (a cut)                | the same      | —                                         |
| SCR-069   | the placing card forming                             | a cut; the bar's width change determinate | the bar steps | `motion.duration.fast` (E32-D06 confirms) |
| SCR-069   | dialog open                                          | `normal` scale + fade                     | instant       | `motion.duration.normal`                  |

### Table 5 — Live data

| Component | Field                                                     | Politeness      | Cadence                     | Coalescing   |
| --------- | --------------------------------------------------------- | --------------- | --------------------------- | ------------ |
| CMP-119   | the recompute line                                        | polite          | ≤ 1 / 2 s                   | latest value |
| CMP-119   | the preview answer (the server's stop, risk, fees)        | polite          | on blur / commit, debounced | latest value |
| SCR-069   | the placing card's progress                               | polite          | ≤ 1 / 2 s                   | latest value |
| SCR-069   | a refusal, `accepted` / `accepted.partial`, an arm change | assertive, once | discrete                    | —            |
| SCR-069   | a merge note, `bkt.liq.beyond`, a T2 re-show              | polite, once    | discrete                    | —            |

### Density

| Component        | Mode              | Row / control height                             | Padding tokens   | Smallest target          |
| ---------------- | ----------------- | ------------------------------------------------ | ---------------- | ------------------------ |
| CMP-119, SCR-069 | compact (default) | 24 px / `size.row.height`, `size.control.height` | `space.inset.sm` | the 24 × 24 unit segment |
| CMP-119, SCR-069 | comfortable       | 32 px                                            | `space.inset.md` | 32 × 32                  |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| —         | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — CMP-119 and SCR-069's bracket half

- [x] Dark-first; light is a token swap through `themes.json` (board 10); both densities (spec §2.2, the Density table)
- [x] Every state E32-D02 names has a frame or a named inset (spec §3; §12 reconciles the checklist)
- [x] Semantic tokens only; 0 MISSING; no hard-coded colour
- [x] Colour never the sole encoding: the T2 look is a lock and a full label, the validity look a reduced-opacity word beside a full-opacity reason, the boundary a message; side as "▲ Buy" / "▼ Sell"; DEMO / LIVE as text badges
- [x] Contrast ≥ 4.5:1 text / ≥ 3:1 non-text in every theme (spec §11: 28 gated pairs, 0 FAIL); the DEMO badge ≥ 7:1
- [x] Focus visible and never obscured; dialogs trap and return focus; no push moves focus
- [x] Motion-safe / motion-reduce pairs (Table 4); nothing animated
- [x] Every control's accessible name carries its target and effect; T2 controls keep role, label and focusability
- [ ] Storybook stories for CMP-119's new states — E32-S05 / the `15` owner (HA-6)
- [ ] Owner approval — pending

## B. Accessibility acceptance criteria (`05` §10) — SCR-069

- Keyboard: every control reachable by `Tab`; the ladder rows in order; `Esc` closes without cancelling a sent request; no single unmodified key is bound (spec §7).
- Screen reader: the stop field reads its name, value, source and holder; a T2 control reads its name, "unavailable", then the reason; the validity look reads its name, "unavailable", then the reason beside it; the summary is an `alert` once; CMP-158 is a `note`.
- Live regions: the recompute line and the placing card polite ≤ 1 / 2 s; a refusal and an acceptance assertive once; no update moves focus.
- Contrast and CVD: spec §11; the greyscale strip on board 10; `forced-colors` per spec §2.2.
- Zoom: 200 % on 1280 × 800 reflows the dialog to a scrolling body with sticky header and footer rows; nothing is clipped.
- Timing: no timed gate on this screen; SCR-076's 400 ms acceptance delay applies on LIVE (E30-D03).
