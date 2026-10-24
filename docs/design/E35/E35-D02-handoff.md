# E35-D02 — Per-component handoff checklist (`16` §11.4; the contracts SCR-084 / SCR-085 change)

Three blocks (CMP-154 RuleSimulatePanel, CMP-156 RuleEvaluationTimeline's simulation variant, the SCR-085 composite over CMP-043 + CMP-006 + CMP-158 + CMP-159 + the footer buttons — every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table once each with a leading `Component` column (the E36-D02 shape), then §A the `16` §12 design-QA checklist and §B the `05` §10 template for both screens. **E35-D05 embeds this file by reference** (BQ-3: an `SCR-*` ticket attaches the checklist for a contract it introduces or changes, `16` §11.4; the ticket carries no `handoff` label). Every number below is `docs/design/_tools/e35_d02_sim_arming_audit.py`'s; the Penpot page is `E35-D02 Rule simulation and arming`, BLOCKED-PENPOT until the boards are drawn.

## Handoff checklist — CMP-154 RuleSimulatePanel (E35-D02, #937)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E35-D02 Rule simulation and arming` (page id pinned after the first build), frames `SCR-084/idle` … `SCR-084/no-history` on this ticket's own page; PNGs planned at `docs/design/E35/img/E35-D02-01-scr-084-anatomy.png`, `…-02-scr-084-states.png`, `…-07-scr-084-anatomy-light.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): 6 states × 3 treatments (spec §3); Table 1
- [x] **Keyboard table** — initial focus Run simulation; the drawer non-modal, `Esc` closes and returns to the opener; the table a focusable scroll region with roving rows (`↑` / `↓`, `←` / `→`, `Enter`, `Home` / `End`); no global key (spec §7); Table 2
- [x] **Accessible name / role table** — `region` "Simulation — {rule}"; `progressbar` with `aria-valuenow` only where the derivation holds; `table` "Simulated firings — {n}"; the `<ol>` text list; Run T2 `aria-disabled` + `aria-describedby` → the view-as notice (spec §7); Table 3
- [x] **Live data** — the `rules` topic at 250 ms with `include_events`; progress polite ≤ 1 per 2 s, never per `evaluated` event; complete / partial once; failed assertive once (spec §7); Table 5
- [x] **Motion pair** — the drawer `normal` slide → instant; the progress fill `fast` → instant with its text twin; everything else instant token swaps (spec §9); Table 4
- [x] **Density notes** — compact 24 px controls and rows / `space.inset.sm`, comfortable 32 px / `space.inset.md`; the drawer 480 px (360 px narrow); smallest target 24 × 24 (the close button); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px)
- [x] **Tokens used** — `color.surface.raised` / `.canvas`, `color.text.primary` / `.secondary` / `.tertiary` / `.on-action`, `color.action.primary.default`, `color.status.warning.subtle` / `.strong`, `color.status.danger.subtle` / `.strong`, `color.status.success.strong`, `color.status.info.subtle` / `.strong`, `color.border.default`, `color.focus.ring`, `elevation.chrome`, `type.ui.heading-sm` / `.body` / `.caption`, `type.num.sm`, `font.family.mono`, `size.control.height`, `size.row.height`, `size.target.min`, `space.inset.sm` / `.md`, `space.field.gap`, `space.stack.md`, `motion.duration.normal` / `.fast` / `.instant`; `color.track` and `color.action.primary` (CMP-023's names) are MISSING (spec §10 request 1); Penpot token sets = `packages/ui/tokens` at `2b25eff387d00824d2f180dc74df19b5326c5ba1`
- [x] **Data contract confirmed** — `POST /rules/{ruleId}/simulate` (`SimulateRuleRequest`; the 200 `RuleSimulationResult` — `evaluations`, `fires`, `suppressed_by_guard`, `actions[]`, `errors[]`, `duration_ms`; the 202 `{run_id, status: running}`), `GET /rules/{ruleId}/runs` (`RuleRun.status` running · ok · error · aborted · throttled), `GET /rules/runs/{runId}/events` (`evaluated.payload.conditions[]`, `action_sent`), `GET /market/data-coverage` (intervals per stream), `RuleDetail.last_simulation` + `ir_hash`, `RuleValidationResult.blocks_arming`, `RuleEngineConfig.min_simulation_fires` 5 / `min_simulation_hours` 24 (= `b09_rule_instance.py`'s defaults); gaps: no coverage / `gaps[]` (D02-G1), no progress field (D02-G2), no cancel (D02-G3), the live gate count (D02-G6), no CSV operation (D02-G12)
- [ ] **Contrast and CVD** — PENDING (the PROPOSED `pairs.mjs` rows are registered by E35-S08; CVD planned on the exports): spec §10 rows 3–7, 17–19, 20–21, 27–28, 30, 32 — drawer text 14.35 / 15.62 / 16.25, the amber line 9.86 / 15.62 / 11.16 with its glyph 7.56 / 4.11 / 7.56, the failed line 12.06 / 14.64 / 13.66, the progress fill 3.64 / 4.13 / 6.66, the ring 6.66 / 5.86 / 17.30, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-156 RuleEvaluationTimeline, simulation variant (E35-D02, #937)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E35-D02 Rule simulation and arming` (page id pinned after the first build), the timeline inside `SCR-084/completed`; PNG planned at `docs/design/E35/img/E35-D02-01-scr-084-anatomy.png`
- [ ] **Variants × States matrix** — PENDING: `variant: live | simulation` × empty · streaming · dense (virtualised) · stacked cards at 200 % (spec §2 block 9, §7); Table 1
- [x] **Keyboard table** — roving rows inside a focusable scroll region; `Enter` on a row opens "open in chart at this moment"; the text list is a plain `<ol>` in a `<details>` (spec §7); Table 2
- [x] **Accessible name / role table** — `table` "Simulated firings — {n}" with `<th scope="col">`, `aria-rowindex` in the virtualised window (CMP-049 A11y); the outcome cell text + glyph ("would have succeeded" / "blocked by {cap}"); the `<ol>` sentences (spec §2); Table 3
- [x] **Live data** — rows append as `evaluated` events arrive, patched in place; no per-row announcement (spec §7); Table 5
- [x] **Motion pair** — none animated: a row appends instantly (spec §9); Table 4
- [x] **Density notes** — rows 24 / 32 px; `font.family.mono` numerics; smallest target 24 × ≥ 120 (a row); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-049 (`color.surface.canvas` / `.raised`, `color.border.subtle`, `font.family.mono`) plus `color.text.primary` / `.secondary`, `color.status.success.strong` / `color.status.danger.strong` (the outcome glyphs), `color.focus.ring`; Penpot token sets = `packages/ui/tokens` at `2b25eff387d00824d2f180dc74df19b5326c5ba1`
- [x] **Data contract confirmed** — `RuleSimulationResult.actions[] {ts, action, params, would_have_succeeded, symbol, exchange_account_id}`; `listRuleRunEvents` `RuleEvent {id, ts, kind, payload}` — `evaluated.payload.conditions[] {path, result, left, right}`, `action_sent.payload {action, position_id, price}`; `24` §11.9 `SimulatedAction.blocked_by` / `blocked_detail`; the account id resolves to a label, never shown raw; the CA-4 form for a stop move; gaps: none of its own (the dense case is bounded by `Limit` paging)
- [ ] **Contrast and CVD** — PENDING: spec §10 rows 6–7, 27–28 — row text 15.20 / 16.78 / 17.21, captions 9.33 / 9.65 / 15.20, the outcome glyphs 9.40 / 3.39 / 9.40 and 11.00 / 4.11 / 11.00 on raised, PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — SCR-085 composite: CMP-043 + CMP-006 + CMP-158 + CMP-159 + the footer (E35-D02, #937)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E35-D02 Rule simulation and arming` (page id pinned after the first build), frames `SCR-085/review-demo` … `SCR-085/view-as`; PNGs planned at `docs/design/E35/img/E35-D02-03-scr-085-anatomy-reading-order.png`, `…-04-scr-085-gates-and-looks.png`, `…-05-scr-085-step-up-pending-outcome.png`, `…-08-scr-085-anatomy-light.png`, `…-09-looks-and-status-words-light.png`
- [ ] **Variants × States matrix** — PENDING: 13 frames + the flag-off treatment (spec §5); the LIVE option's T2 (Manager) / T2 (`rbac.env`) / absence (flag off); Table 1
- [x] **Keyboard table** — focus opens on Cancel, trapped, returns to the Arm button; `Enter` on a radio never arms; arrows move the radios and a T2 LIVE re-shows its reason; `Esc` per state; the step-up hand-off into SCR-006 and back (spec §7); Table 2
- [x] **Accessible name / role table** — `alertdialog` "Arm rule — {name}" described by the restatement; `radiogroup` "Environment"; the account rows' include boxes; the buttons' full labels "Arm on DEMO" / "Arm on LIVE…" / "Cancel" / "Disarm" / "Done"; T2 `aria-disabled` + `aria-describedby`; `role="note"` on CMP-158 (spec §4, §7); Table 3
- [x] **Live data** — the `rules` frame with `mode: armed` ends pending; one polite "Armed on DEMO"; the environment change polite once; a refusal assertive once (spec §7); Table 5
- [x] **Motion pair** — the dialog `normal` scale + fade → instant; everything else instant; pending has no spinner (spec §9); Table 4
- [x] **Density notes** — the dialog 720 px; title 48 px; option rows 44 px (24 px control + caption); account rows 24 / 32 px; the footer 48 / 56 px; smallest target 24 × 24 (a radio, an include box); Density table
- [x] **Essential-exceptions log** — none; the step-up's unextendable time is SCR-006's (E09-D06; WCAG 2.2.1 Essential, memo §9d — E35-D04 confirms)
- [x] **Tokens used** — `color.surface.overlay`, `elevation.4`, `radius.lg`, `color.text.primary` / `.secondary` / `.tertiary` / `.on-action` / `.link`, `color.action.primary.default`, `color.status.danger.default` (the destructive class), `color.env.demo` / `color.env.live` (the glyphs and 2 px borders), `color.status.info.subtle` / `.strong` / `.default` (CMP-158, CMP-227), `color.status.warning.subtle` / `.strong` (CMP-159, the amber blocked rows), `color.status.danger.subtle` / `.strong` (the refusal line), `color.status.success.strong` (the armed glyph), `color.border.default`, `color.focus.ring` + `color.surface.canvas` (the double ring), `opacity.disabled` (the validity look), `type.ui.heading-md` / `.body` / `.caption` / `.label`, `size.control.height`, `size.target.min`, `space.inset.md` / `.lg`, `space.stack.md`, `space.button.paddingX`, `radius.control` / `.pill`, `motion.duration.normal` / `.instant`; Penpot token sets = `packages/ui/tokens` at `2b25eff387d00824d2f180dc74df19b5326c5ba1`
- [x] **Data contract confirmed** — `GET /rules/{ruleId}` (`RuleDetail` — `ir.scope.environments`, `bindings`, `last_simulation`, `ir_hash`), `GET /me` (`accounts[]` labels and mode), `GET /auth/session` (`permissions`, `allowed_environments`), `GET /auth/session/view-as`; `PUT /rules/{ruleId}/mode {mode, reason?}` (`x-idempotency: required`; the shipped `acknowledge_flatten_all` — D02-G4) → 200 `Rule` / 403 / 422 with `arming.py`'s nine codes; `403 step_up_required` → `Problem` (`challenge_id`, `challenge_expires_at`, `action_class: live_enablement`, `action_summary`) → `POST /auth/step-up` → the held request re-sent once within 60 s; the `rules` topic's `RuleUpdate.mode`; gaps: the environment on the wire (D02-G5), the gate count (D02-G6), the DEMO re-arm class (D02-G7), the server-composed fills (D02-G8), the B9 state (D02-G9), the conflict shape (D02-G11)
- [ ] **Contrast and CVD** — PENDING: spec §10 rows 1–2, 5, 9–16, 20–26, 29, 31, 33 — dialog text 13.27 / 14.37 / 15.02, the T2 label 5.62 / 5.92 / 11.21 and reason 8.81 / 8.98 / 14.35, the DEMO / LIVE words 14.35 / 15.62 / 16.25 (≥ 7:1 met) with the glyphs 3.64 / 4.13 / 3.64 and 4.42 / 4.51 / 4.42, Arm on DEMO 4.76 / 4.76 / 7.45, Arm on LIVE… 5.05 / 10.31 / 4.54, the link 6.15 / 5.39 / 6.15, all PASS; the greyscale strip (board 09) keeps the status words apart by glyph + word
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component         | Variant                                                                   | State (every one is a Penpot variant and a story)                                                                                                                                                 | Penpot variant (planned)                       | Story (planned)                       | Notes                                                                        |
| ----------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------- |
| CMP-154           | the drawer (480 / 360 px)                                                 | idle, running, completed, partial, failed, no-history (owner CTA / sentence form), view-as, gate-met, stale-run                                                                                   | `SCR-084/<state>`                              | `RuleEngine/RuleSimulatePanel/*`      | spec §3; T2: CMP-079 + CMP-019 lock on Run while viewing as                  |
| CMP-156           | live · simulation                                                         | empty, streaming, dense (48 rows, virtualised), stacked cards (200 %)                                                                                                                             | `CMP-156 · RuleEvaluationTimeline / Variant=…` | `RuleEngine/RuleEvaluationTimeline/*` | spec §2 block 9                                                              |
| SCR-085 composite | review (DEMO / LIVE) · blocked · flatten-all · arm-again · disarm-confirm | review-demo, review-live, manager-live-locked, blocked, flatten-all, step-up-hand-off, returned-from-step-up, refused, pending, armed, arm-again, disarm-confirm, view-as; the flag-off treatment | `SCR-085/<state>`                              | `RuleEngine/ArmRuleDialog/*`          | spec §5; T2: CMP-079 + CMP-019 lock; validity look on the two validity cases |

### Table 2 — Keyboard

| Component               | Key                                                     | Action                                                                                   | Focus after                           | Global conflict? (`05` §3.2 / §3.3)                | Notes                                  |
| ----------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------- | -------------------------------------------------- | -------------------------------------- |
| CMP-154                 | `Tab`, `Esc`                                            | through the controls; close the drawer                                                   | the opener                            | none                                               | non-modal                              |
| CMP-156                 | `↑` / `↓`, `←` / `→`, `Enter`, `Home` / `End`           | roving rows; cells; open in chart; first / last                                          | the row / the chart                   | none (`05` §3.4 item 2)                            | a focusable scroll region              |
| SCR-085                 | `Tab`, `↑` / `↓` on the radios, `Space`, `Enter`, `Esc` | the order of spec §7; select; toggle; activate a button (never a radio); close per state | Cancel first; the Arm button on close | none; no arm or simulate key exists or is proposed | 400 ms activation guard on Arm on DEMO |
| any T2 control          | `Enter` / `Space` / an arrow                            | nothing staged; the reason re-shown once, politely                                       | stays                                 | none                                               | E09-D09 §9.3                           |
| a validity-look control | `Enter` / `Space`                                       | the error summary shown                                                                  | stays                                 | none                                               | E30-D02 D3                             |

### Table 3 — Accessible name / role

| Component | Element                                                                                 | Role                                                      | Accessible name (source)                                                                                                                                                                                     | States / properties                                                                                                                                                           |
| --------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-154   | the drawer · the progress · Run / Cancel · the table · the text list                    | region · progressbar · button · table · list              | "Simulation — {rule}" · "Simulation progress" · "Run simulation" / "Cancel" · "Simulated firings — {n}" · the `<ol>`                                                                                         | `aria-busy` while running; Run `aria-disabled` + `aria-describedby` → the view-as notice                                                                                      |
| CMP-156   | a row · the outcome cell                                                                | row · cell                                                | "{time} UTC, {trigger}, {conditions}, {action}, {outcome}"                                                                                                                                                   | `aria-rowindex`; the glyph `aria-hidden`, the word carries the state                                                                                                          |
| SCR-085   | the dialog · the radiogroup · an option · an account row · CMP-158 · the footer buttons | alertdialog · radiogroup · radio · option · note · button | "Arm rule — {name}" described by the restatement · "Environment" · "DEMO" / "LIVE" · "{label} …{last-4}, {environment}" · the CA-26 sentence · "Cancel" / "Arm on DEMO" / "Arm on LIVE…" / "Disarm" / "Done" | a T2 option `aria-disabled` + `aria-describedby` → its reason; `aria-busy` while pending; the validity-look button `aria-disabled` + `aria-describedby` → the reason under it |

### Table 4 — Motion pair

| Component | Property                                   | motion-safe                  | motion-reduce          | Duration / easing tokens                        |
| --------- | ------------------------------------------ | ---------------------------- | ---------------------- | ----------------------------------------------- |
| CMP-154   | the drawer open / close; the progress fill | `normal` slide; `fast` width | instant; the text twin | `motion.duration.normal` / `.fast` → `.instant` |
| CMP-156   | a row appends                              | instant                      | identical              | `motion.duration.instant`                       |
| SCR-085   | open / close                               | `normal` scale + fade        | instant                | `motion.duration.normal` → `.instant`           |
| all three | state words, reasons, the gate strip       | instant token swaps          | identical              | `motion.duration.instant`                       |

### Table 5 — Live data

| Component      | Field                        | Politeness                  | Cadence         | Coalescing   | Notes                       |
| -------------- | ---------------------------- | --------------------------- | --------------- | ------------ | --------------------------- |
| CMP-154        | progress                     | polite                      | ≤ 1 per 2 s     | latest count | never per `evaluated` event |
| CMP-154        | complete / partial / failed  | polite / polite / assertive | once            | —            | `05` §6.2                   |
| SCR-085        | the environment change       | polite                      | once per change | —            | —                           |
| SCR-085        | armed / disarmed             | polite                      | once            | —            | from the `rules` frame      |
| SCR-085        | a refusal or a returned drop | assertive                   | once            | —            | —                           |
| any T2 control | a T2 press                   | polite                      | once per press  | —            | E09-D09 §9.3                |

### Density

| Component         | Mode        | Row / control height                                 | Padding tokens                            | Smallest target               |
| ----------------- | ----------- | ---------------------------------------------------- | ----------------------------------------- | ----------------------------- |
| CMP-154 / CMP-156 | compact     | 24 px (`size.control.height`, `size.row.height`)     | `space.inset.sm`                          | 24 × 24 px (the close button) |
| CMP-154 / CMP-156 | comfortable | 32 px                                                | `space.inset.md`                          | 32 × 32 px                    |
| SCR-085           | compact     | title 48 px; options 44 px; rows 24 px; footer 48 px | `space.inset.md`; blocks `space.stack.md` | 24 × 24 px (a radio)          |
| SCR-085           | comfortable | title 48 px; options 52 px; rows 32 px; footer 56 px | `space.inset.lg`                          | 32 × 32 px                    |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all three | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-084 and SCR-085

- [x] Only published Tier-2 tokens; zero hard-coded hex / px in the spec (the px are anatomy derived from the tokens; the hexes in §10 are the tool's resolution of token names).
- [~] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §10); `forced-colors: active` is stated per surface (spec §7); the visual parity check runs on the boards (BLOCKED-PENPOT).
- [x] Passes the contrast matrix for every pair introduced or touched (34 gated rows, 0 FAIL; 14 PROPOSED `pairs.mjs` rows named; the rejected rows reported and never drawn).
- [~] CVD simulation reviewed — planned on every export with `docs/design/_tools/cvd_sim.py` (BLOCKED-PENPOT); the greyscale argument is in spec §10 and board 09.
- [~] Every documented State has a Penpot variant and a story — the states are named (Table 1); the variants exist once drawn; the stories are E35-S08's.
- [x] Disabled states use the disabled-with-reason pattern (E09-D09 T2) for every RBAC- or state-gated action — the one rule in spec §1: the LIVE option (a Manager, an Owner without live), the untradeable account row, every write while viewing as (one notice per frame); form validity (the flatten-all box, the empty override reason) is `aria-disabled` with its visible reason, outside the grammar (E09-D09 §9.1), drawn E30-D02 D3's way (0.45, the reason full-opacity under it, layer `validity-reason`); a deferred LIVE (flag off) and a deferred Disarm are absences — no bare disabled control, no over-conversion.
- [x] Loading / empty / error states designed: running, no-history (both forms), failed, pending, refused, returned-from-step-up.
- [x] Keyboard-interaction table completed (spec §7; Table 2) — a design table, to be matched by E35-S08's tested path.
- [x] Accessible-name / role table completed (spec §7; Table 3).
- [x] No canvas / WebGL-adjacent component: the timeline is a table with its `<ol>` text list.
- [x] Motion-safe / motion-reduce pair specified (spec §9; Table 4).
- [x] Hit targets ≥ 24 px in compact, ≥ 32 px in comfortable; no essential exception.
- [ ] Accessibility role sign-off — the owner's `approved` comment, pending; E35-D04 reviews.
- [x] Confirm-gate variant stated: Arm on DEMO = one primary button (no typed word, no step-up); Arm on LIVE… = the destructive class into SCR-006's `no-grace-live-enable` step-up (password + code + typed LIVE); Disarm = CMP-044 `standard`; the keyboard path for all three is Table 2.
- [x] Every heuristic / estimated value is chip-tagged (CMP-227) and links to SCR-058 (CA-12's "Yes" case).
- [x] Demo / Live context unambiguous: the chrome's band above the dialog, the option words with glyph + border, "Runs on LIVE." in the restatement, "Arm on LIVE…" naming the environment; a LIVE frame never without the red band.
- [x] Reuses existing `CMP-*` (CMP-043 / 006 / 036 / 023 / 026 / 027 / 028 / 040 / 046 / 047 / 049 / 079 / 093 / 105 / 154 / 156 / 158 / 159 / 227 / 044 / 019 / 016 / 074); no new id requested.
- [~] Storybook stories match the Variants × States matrix — planned (Table 1); none exists yet.
- [~] Composes only published-library components — on the boards, once drawn.

## B. Accessibility acceptance criteria (`05` §10) — SCR-084 and SCR-085

```gherkin
Feature: E35-D02 rule simulation panel and arming dialog — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user runs a simulation in SCR-084 and arms the rule on DEMO in SCR-085
      using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation (focus opens on Cancel;
      the radios move with arrows; the table's rows rove)
    And every action has a documented non-drag keyboard equivalent (none drags)
    And focus is never silently moved by the 250 ms rules frame, a progress update or the armed frame
    And a visible focus indicator meeting >=3:1 contrast is present at every step (the double ring:
      color.focus.ring over a color.surface.canvas halo, >=5.39:1 on every surface it lands on)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the user arms the rule on DEMO
    Then all labels, roles, and current values are announced correctly ("Arm rule — ATR trail 2x",
      the restatement as the description, "Environment, DEMO, radio, 1 of 2", "Arm on DEMO, button")
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding (progress <=1 per 2 s; "Armed on DEMO" once)
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity (none: the timeline is a table with its text list)

  Scenario: Colour-independence
    Given the feature displays buy/sell, bid/ask, P&L, or status state
    When the state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone (DEMO / LIVE by word +
      glyph + border; Armed / Not armed / Arming… by word + glyph; the T2 look by lock + label + reason)
    And the feature passes deuteranopia/protanopia/tritanopia simulation review (planned on the exports)

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the
      high-contrast theme
    Then all text meets >=4.5:1 (or >=3:1 for large text) and all meaningful
      non-text UI/chart elements meet >=3:1, per the token contrast matrix (spec §10: 34 gated rows PASS)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the feature would normally animate
    Then the feature uses the motion-reduce variant with no flashing content
      exceeding 3 times per second and no motion lasting >5s without a pause
      control (the dialog and drawer open instantly; pending is text)

  Scenario: T2 press
    Given a T2 control (the LIVE option for a Manager, an untradeable account row,
      or any write while the session views as another user)
    When Enter, Space or an arrow lands on it
    Then nothing is sent or opened (no request, no SCR-006, no state change)
    And the reason is re-shown inline at the point of action and announced once, politely

  Scenario: Automated gates
    Given the feature's PR is opened
    Then axe-core reports zero new serious/critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering this feature's primary
      task passes (E35-Q06)
```

Screen-reader spot test: manual spot-test deferred to E35-D04 / E35-Q06 — stated. Owner-approved exceptions: none (the step-up's time limit is SCR-006's Essential exception, E09-D06; E35-D04 confirms).
