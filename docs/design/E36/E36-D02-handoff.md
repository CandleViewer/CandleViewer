# E36-D02 — Per-component handoff checklist (`16` §11.4; the eight contracts SCR-081 / SCR-083 change)

Eight blocks (CMP-140, CMP-141, CMP-142, CMP-145, CMP-157, CMP-233, CMP-234, CMP-235 — every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table **once each with a leading `Component` column** (the E25-D05 shape, `docs/design/E25/E25-D05-handoff.md` on its branch; the fallback is per-component tables; deviation recorded in `E36-D02.md` §21 item 6), then §A the `16` §12 design-QA checklist and §B the `05` §10 template for SCR-081 and SCR-083. CMP-158 (contract unchanged; placement and sentence in `E36-D02.md` §2, PROPOSED), CMP-143 and CMP-144 (contract unchanged; the trigger list is the vocabulary's 13 and `appliesTo` gains `any` — `15` amendment rows in `E36-D02.md` §16, not contract changes) get this line and no block. Every number below is `docs/design/_tools/e36_d02_form_audit.py`'s; the Penpot page is `E36-D02 Rule form editor and templates`, BLOCKED-PENPOT until the boards are drawn.

## Handoff checklist — CMP-140 RuleConditionRow (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimens `CMP-140 · RuleConditionRow` on this ticket's own page (never the DS library file); PNG planned at `docs/design/E36/img/E36-D02-04-condition-rows-grouping.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn, BLOCKED-PENPOT): 8 value forms × 8 states (spec §5; unavailable-T2 for a session without `recording:write`); Table 1
- [x] **Keyboard table** — one roving stop per row, `←` / `→` between the row's controls, `Shift+F10` the row menu, `Esc` innermost; no view-local override of a global binding, no single unmodified key, `Esc` / `Ctrl+K` untouched (spec §12); Table 2
- [x] **Accessible name / role table** — `group` "Condition {N} of {M}", `aria-describedby` → the fragment, `aria-invalid` + the message when invalid (spec §13); Table 3
- [ ] N/A — **Live data**: no streaming value; the fragment re-renders on blur, the chip's flag is set once per metric
- [x] **Motion pair** — none animated: focus, invalid and estimated are instant token swaps (`16` §7); Table 4
- [x] **Density notes** — compact 24 px row / `space.inset.sm`, comfortable 32 px / `space.inset.md`; smallest target the 24 × 24 menu button (spec §2, §5); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px by padding)
- [x] **Tokens used** — `color.text.primary` / `.secondary` / `.tertiary`, `color.surface.canvas` / `.raised`, `color.status.danger.default` + `border.thick` (invalid), `color.status.danger.strong` (glyph), `color.status.info.subtle` + `color.status.info.default` (CMP-227), `color.focus.ring`, `type.ui.body`, `type.num.sm`, `font.family.mono`, `size.control.height`, `size.target.min`, `space.inset.sm` / `.md`, `space.field.gap`, `radius.control`; `font.mono` and `color.border.invalid` are MISSING (spec §15 request 1); Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — `GET /api/v1/rules/vocabulary` `signals[]` (`display_name`, `unit`, `description`, `estimated`, `available`, `unavailable_reason`, `recorder_action`) and `operators[]` (`id`, `arity`, `operand_types`); `Comparison` (`right2`, `set_values`, `tolerance`), `TemporalNode.sustained_for` (`24` §11.2); `recorder_action` → `POST /recording/symbols` (`recording:write`, owner-only by the ruling) — T2 for a session without it (spec §5); gaps: no `display_name` per operator (D02-G4), no row anchor in diagnostics (D02-G5)
- [ ] **Contrast and CVD** — PENDING (the PROPOSED `pairs.mjs` rows are registered by E36-S01; CVD planned on the exports): spec §15 rows 1–3, 17, 21, 27 — 15.20 / 9.33 / 5.96 text on canvas, the invalid outline 3.63 / 9.62 / 4.30, the focus ring 7.05 / 6.30 / 18.32, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-141 RuleConditionGroup (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimen `CMP-141 · RuleConditionGroup`; PNG planned at `docs/design/E36/img/E36-D02-04-condition-rows-grouping.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): modes and / or × 5 states (spec §6); Table 1
- [x] **Keyboard table** — `↑` / `↓` move into and out of a group; the root switch is a CMP-003 (arrows); "+ any-of group" is a button (spec §12); Table 2
- [x] **Accessible name / role table** — `group` "Condition group — either … or …", legend "any of" (spec §13); Table 3
- [ ] N/A — **Live data**: static structure
- [x] **Motion pair** — none animated: adding a group is an instant insert (`16` §7); Table 4
- [x] **Density notes** — rows as CMP-140; the indent `space.inset.lg` in both modes; smallest target the 24 × 24 "+ any-of group" button; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-140 plus `space.inset.lg` (indent), `color.text.tertiary` (the 2 px bracket ink, 5.96:1), `color.border.selected` (the current row); `space.rulegroup.indent` is MISSING (spec §15 request 1); Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — the form subset of `rules/ir/form.py` (`form_incompatibility_reasons`), `compile_form`'s root pass-through, `MAX_BOOLEAN_CHILDREN` 32 (`ir/models.py`); the per-subtree projection is missing (D02-G2)
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 3 and 27 — the bracket 5.96 / 6.36 / 11.87, the current-row outline 5.18 / 4.44 / 7.05, PASS; `color.border.strong` on canvas (1.91) is rejected as the ink
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-142 RuleActionRow (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimens `CMP-142 · RuleActionRow`; PNG planned at `docs/design/E36/img/E36-D02-06-action-rows.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): the six parameter forms × 6 states (no loosening control for any role — #4137; T2 (permission) for the ten non-placing `orders:write` actions and Resume new orders; spec §8); Table 1
- [x] **Keyboard table** — as CMP-140 (roving row, `Shift+F10`); the action picker is a CMP-048 combobox (without `widen_stop` — #4137); Table 2
- [x] **Accessible name / role table** — `group` "Action {N} of {M}"; `sl.note` `role="note"`, `sl.kept` `role="status"`; a stop row's fragment ends with the safety line "The stop only ever tightens." — no loosening control exists for any role: "Rules never loosen a stop." (#4137; spec §8, §13); Table 3
- [ ] N/A — **Live data**: no streaming value; `sl.kept` is a per-attempt status, not a stream
- [x] **Motion pair** — none animated (`16` §7); Table 4
- [x] **Density notes** — rows 24 / 32 px; the parameter form's fields `size.control.height`; smallest target the 24 × 24 menu button; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-140 plus `color.status.danger.strong` (destructive-class glyph), `color.status.danger.default` + `color.text.on-action` (Arm… against LIVE — the destructive class; `color.action.primary.default` on demo), `color.status.info.subtle` (`sl.note`), `color.buy.default` / `color.sell.default` (the side control's glyph + word); Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — `GET /api/v1/rules/vocabulary` `actions[]` (`display_name`, `params_schema`, `required_permissions`, `loosens_risk`, `available`, `simulate_only`, `restriction`, `notes`, `targets`); the validator's `native_stop_violation` (`validator.py` line 200); `widen_stop` is still listed but omitted by id — every save refuses a loosening with no permission set (`manager.py` line 517 → `validator.py` lines 192–194; #4137, D02-G15); `restriction` is id-bearing ("Requires {permission}." / `_SIM_TEXT`) and the vocabulary carries no display reason — for a session without `orders:write` the six `simulate_only` order actions (`place_order` included) stay pickable with the tag "simulate only" and the T2 sits on `Arm…` (`rbac.permission` "Your role can't place orders."), while the ten non-placing `orders:write` actions and `resume_new_orders` are T2 options (`rbac.permission` / `rbac.owner_only` "Only the owner can arm rules against live."), every sentence mapped client-side from E09-D09 §3, the shipped string in the details (D02-G14; spec §8); the flatten-all acknowledgement is the arm request's `acknowledge_flatten_all` (`api/rules_crud.py` line 299; `arming.py` lines 121–126), not a save field; undocumented parameter semantics (D02-G6)
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 4–6, 13, 19, 29 — card text 14.35 / 8.81 / 5.62, the destructive glyph 7.83 / 3.85 / 7.83, `sl.note` 10.74, the Arm label 5.05 / 10.31 / 4.54, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-145 RuleFormEditor (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), screens `CMP-145 · RuleFormEditor / State=…`; PNGs planned at `docs/design/E36/img/E36-D02-01-scr-081-anatomy.png`, `…-02-scr-081-states.png`, `…-03-round-trip-indicator.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): 6 states × the indicator's 4 results + "Checking…" + "since your last save" (spec §3, §4); Table 1
- [x] **Keyboard table** — the focus order header → Scope → Trigger → Conditions → Actions → Options → action bar; `Ctrl+S`, `Ctrl+Enter` (Save draft), `Alt+G` as candidates (E36-D04 reviews); `Esc` innermost (spec §12); Table 2
- [x] **Accessible name / role table** — `region` "Rule editor — {name}" described by the sentence; `fieldset` / `legend` per section; `toolbar` "Rule actions"; the Arm button, Save draft, Validate and Simulate `aria-disabled` + `aria-describedby` → the reason or the one notice (spec §13); Table 3
- [x] **Live data** — the summary re-read polite on blur / save; the error count polite on recompile; the indicator word polite on change; the vocabulary-unavailable banner assertive once; nothing per tick (spec §13); Table 5
- [x] **Motion pair** — none animated: the indicator flip, the row highlight and the state pills are instant token swaps; the `Validate` loading state locks width (`16` §7); Table 4
- [x] **Density notes** — compact 24 px fields / `space.inset.sm`, comfortable 32 px / `space.inset.md`; the action bar 48 px; smallest target 24 × 24 (the indicator chip); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.canvas` / `.raised` / `.hover`, `color.text.primary` / `.secondary` / `.tertiary` / `.on-action`, `color.action.primary.default`, `color.status.success.subtle` / `.strong`, `color.status.warning.subtle` / `.strong`, `color.status.danger.subtle` / `.strong` / `.default`, `color.status.info.subtle`, `color.focus.ring`, `elevation.chrome`, `type.ui.heading-md` / `.body` / `.caption`, `space.inset.md` / `.lg`, `space.stack.md`, `space.button.paddingX`, `radius.badge`; Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — `GET /api/v1/rules/{id}`, `PUT /api/v1/rules/{id}`, `POST /api/v1/rules/validate`, `POST /api/v1/rules/{ruleId}/compile` (`ir`, `ir_hash`, `issues[]`, `blocks_arming`, and `round_trip {match, diff[]}` only when a `counterpart_model` is sent — no four-state `result`: the indicator derives it client-side, `identical` = `match: true`, `mismatch` = `match: false` + `diff[]`, `graph_only_construct` = the compiled rule's `graph_layout.node_only_constructs` (`compiler/graph.py` lines 243–247), `unverified` = 503 / transport failure, D02-G13); an invalid rule is never stored — `createRule` / `updateRule` answer 422 `RuleIrInvalid` (`22` lines 6784, 6841; `manager._validated`), so 02-4's Save draft is T2 `rule.save.invalid` "Fix the errors to save" and 02-6's is T2 → the engine-down banner (the one node) while `updateRule` answers 503 (D02-Q12); gaps: no `summary` (D02-G1), no per-subtree projection (D02-G2), no compile timestamp (D02-G11)
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 1–2, 7–16, 21–26, 28–29 — the four indicator fills 10.21 / 9.86 / 12.06 / 12.22 with glyphs 6.69 / 7.56 / 7.83 / 7.50, all PASS; the greyscale strip (board 12) keeps the four apart by glyph + word
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-157 MetricPickerCombobox (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimen `CMP-157 · MetricPickerCombobox / State=Open`; PNG planned at `docs/design/E36/img/E36-D02-05-metric-picker.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): the seven category groups, the estimated and the unavailable option × 8 states (spec §7; option-T2 — Start recording for a session without `recording:write`); Table 1
- [x] **Keyboard table** — type to filter, `↑` / `↓`, `Enter`, `Esc`, `Home` / `End`, `→` to the chip inside an option (PROPOSED) (spec §7); Table 2
- [x] **Accessible name / role table** — `combobox` "Metric", listbox options named `display_name` · unit (+ "estimated"), category `group`s (spec §13); Table 3
- [x] **Live data** — the results count announced politely per query, debounced (CMP-048); nothing else streams; Table 5
- [x] **Motion pair** — none animated: open / close instant (`16` §7); Table 4
- [x] **Density notes** — option rows 24 / 32 px; the chip inside an option 20 px in a 24 px row (CMP-227's sm); smallest target 24 × ≥160 (an option row); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.overlay` (the popover), `elevation.popover`, `color.text.primary` / `.secondary`, `color.surface.hover` / `.selected` (the active option), `color.status.info.subtle` / `.default` (CMP-227), `color.focus.ring`, `type.ui.body` / `.caption`, `size.control.height`, `space.inset.sm`, `radius.control`; Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — `GET /api/v1/rules/vocabulary` `signals[]` (`display_name`, `description`, `unit`, `confidence`, `estimated`, `dependencies`, `requires_recording`, `available`, `unavailable_reason`, `missing_dependency`, `recorder_action`), `ETag` per permission set + symbol (`build.py` line 142); `recorder_action` is emitted whatever the session holds (`build.py` lines 74–78) — T2 for a session without `recording:write` (spec §7); no `category` / `scope` on the signal (D02-G8) — derived client-side
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 2, 19, 20, 26 — descriptions 9.33, the chip word 10.74 / 15.44 / 12.16, the chip glyph 4.64 / 3.44 / 4.64, the ring on the chip 4.98, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-233 RuleOptions (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimen `CMP-233 · RuleOptions`; PNG planned at `docs/design/E36/img/E36-D02-07-options-limits-summary.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): defaults · changed · above the default (T2 for a non-owner) · above the cap × 4 states (spec §9); Table 1
- [x] **Keyboard table** — a `fieldset` of CMP-040 fields in the natural Tab order; no composite (spec §12); Table 2
- [x] **Accessible name / role table** — `group` "Options"; each field labelled with its default in the help text; the two always-said lines as text (spec §13); Table 3
- [ ] N/A — **Live data**: static settings
- [x] **Motion pair** — none animated (`16` §7); Table 4
- [x] **Density notes** — fields 24 / 32 px; `space.inset.sm` / `.md`; smallest target 24 × 24 (the Once checkbox); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.sunken` (the block), `space.4`, `color.text.primary` / `.secondary`, `type.num.sm`, `font.family.mono`, `size.control.height`, `color.focus.ring` (`15`'s `space.4` and `color.surface.sunken` exist); Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — `RuleLimits` (`ir/models.py` lines 213–225): eleven fields with defaults 1000 ms / 60 / 500 / 10 / null / null / false / 250 ms / 5; caps 600 / 5 000 (`limits.py`); the SR-104 owner-only rule (`24` §11.7; `manager.py` lines 343–356 — T2 `rbac.owner_only` for a non-owner above the default, spec §9); the two always-said lines "No rule notional cap — your account's risk caps still apply." and "Turns itself off after 5 errors in a row — you re-arm it." (#4118)
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 1, 2, 4 — 15.20 / 9.33 / 14.35, PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-234 ValidationPanel (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimen `CMP-234 · ValidationPanel / State=WithErrors`; PNG planned at `docs/design/E36/img/E36-D02-08-validation-copy.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): valid · with errors · with warnings · form-anchored × 3 states (spec §3, §14); Table 1
- [x] **Keyboard table** — each entry a button moving focus to the offending row (the sole diagnostic navigation); `Tab` through the entries (spec §12); Table 2
- [x] **Accessible name / role table** — `log` "Validation — {n} errors, {m} warnings", entries `button` "Row 2 — Row 2 is missing a value." (spec §13); Table 3
- [x] **Live data** — the error count announced politely on every recompile (debounced 300 ms); never per keystroke; Table 5
- [x] **Motion pair** — none animated (`16` §7); Table 4
- [x] **Density notes** — entries 24 / 32 px; smallest target 24 × ≥200 (an entry); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.status.danger.default` / `.strong` / `.subtle`, `color.status.warning.default` / `.strong` / `.subtle`, `color.text.primary` / `.secondary`, `space.3`, `color.focus.ring`; `color.status.warn` and bare `color.status.danger` are MISSING (spec §15 request 1); Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — `POST /api/v1/rules/validate` issues (`code`, `message`, `path`, class — `validator.py`); form and graph report identical diagnostics (OD#11); the `anchor` row id is populated by E36-T01 from the form model (D02-G5)
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 12, 17, 18 — 12.06 / 14.64 / 13.66 and the outline 3.63 / 3.43, PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-235 EditorModeToggle (E36-D02, #873)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D02 Rule form editor and templates` (page id pinned after the first build), specimen `CMP-235 · EditorModeToggle`; PNG planned at `docs/design/E36/img/E36-D02-03-round-trip-indicator.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): form active · graph active · with a graph-only construct · dirty × 3 states (spec §4); Table 1
- [x] **Keyboard table** — CMP-003 arrows between Form and Graph; `Alt+G` a candidate (E36-D04 reviews); the unsaved-changes prompt is a CMP-044 `standard` dialog (US-RULE-006) (spec §12); Table 2
- [x] **Accessible name / role table** — `radiogroup` "Editor" with options "Form" / "Graph"; `aria-describedby` → the indicator's word (spec §13); Table 3
- [ ] N/A — **Live data**: static control
- [x] **Motion pair** — none animated (`16` §7); Table 4
- [x] **Density notes** — 24 / 32 px control; smallest target 24 × ≥48 (a segment); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-003 (`color.surface.raised` / `.selected`, `color.text.primary`, `color.focus.ring`, `radius.control`); Penpot token sets = `packages/ui/tokens` at `290d29f0ac6c57daf304ad43b372240b98c4959d`
- [x] **Data contract confirmed** — the compile's `round_trip {match, diff[]}` — no four-state `result` on the response: `graph_only_construct` comes from the compiled rule's `graph_layout.node_only_constructs` (`compile_graph`, `compiler/graph.py` lines 243–247), `unverified` from the 503 / transport outcome, derived client-side (D02-G13); `lossyWarning.constructs` = `form_incompatibility_reasons` (per construct); the switch is allowed, the card renders in place (memo C10)
- [ ] **Contrast and CVD** — PENDING: spec §15 rows 1, 4, 30 — 15.20 / 14.35 / 10.17, PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component | Variant                                                                                                  | State (every one is a Penpot variant and a story)                                                                                         | Penpot variant (planned)                          | Story (planned)                     | Notes                                   |
| --------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------- | --------------------------------------- |
| CMP-140   | number · metric ref · two values · set · predicate · changes · tolerance · sustained_for                 | default, hover, focus-visible, invalid, estimated, unavailable, unavailable-T2 (recorder action, no `recording:write`), read-only         | `CMP-140 · RuleConditionRow / Form=…, State=…`    | `RuleEngine/RuleConditionRow/*`     | spec §5; T2: CMP-079 + CMP-019 lock     |
| CMP-141   | and (rows + any-of group) · or (flat)                                                                    | default, with-group, focus-visible, at-limit (32), with-read-only-card                                                                    | `CMP-141 · RuleConditionGroup / Mode=…, State=…`  | `RuleEngine/RuleConditionGroup/*`   | spec §6                                 |
| CMP-142   | place_order · modify_stop_loss · move_to_breakeven · scale_out · flatten_all_positions · halt_new_orders | default, focus-visible, invalid, destructive, T2 (permission), read-only                                                                  | `CMP-142 · RuleActionRow / Action=…, State=…`     | `RuleEngine/RuleActionRow/*`        | spec §8; T2: CMP-079 + CMP-019 lock     |
| CMP-145   | SCR-081                                                                                                  | draft, validating, valid, invalid, armed, vocabulary-unavailable × identical, graph_only_construct, mismatch, unverified, checking, stale | `CMP-145 · RuleFormEditor / State=…, RoundTrip=…` | `RuleEngine/RuleFormEditor/*`       | spec §3, §4; T2: CMP-079 + CMP-019 lock |
| CMP-157   | seven category groups · estimated option · unavailable option                                            | closed, open, filtering, no-results, focus-visible, option-focused, option-T2 (recorder action), chip-focused                             | `CMP-157 · MetricPickerCombobox / State=…`        | `RuleEngine/MetricPickerCombobox/*` | spec §7; T2: CMP-079 + CMP-019 lock     |
| CMP-233   | defaults · changed · above the default (T2, non-owner) · above the cap                                   | default, focus-visible, invalid, T2 (non-owner, above default), read-only                                                                 | `CMP-233 · RuleOptions / Variant=…, State=…`      | `RuleEngine/RuleOptions/*`          | spec §9; T2: CMP-079 + CMP-019 lock     |
| CMP-234   | valid · with errors · with warnings · form-anchored                                                      | collapsed, open, entry-focused                                                                                                            | `CMP-234 · ValidationPanel / Variant=…, State=…`  | `RuleEngine/ValidationPanel/*`      | spec §3, §14                            |
| CMP-235   | form active · graph active · with a graph-only construct · dirty                                         | default, focus-visible, prompting (unsaved changes)                                                                                       | `CMP-235 · EditorModeToggle / Mode=…, State=…`    | `RuleEngine/EditorModeToggle/*`     | spec §4                                 |

### Table 2 — Keyboard

| Component                 | Key                                                                                     | Action                                                                                                                                       | Focus after                         | Global conflict? (`05` §3.2 / §3.3)                                                                              | Notes                              |
| ------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| CMP-140 / CMP-142         | `Tab`, `↑` / `↓`, `←` / `→`, `Shift+F10`, `Esc`                                         | roving row list; the row's controls; the row menu; cancel                                                                                    | the row / the control / the menu    | none (composite widget, `05` §3.4 item 2); `Esc` untouched                                                       | P11                                |
| CMP-141                   | `↑` / `↓` into a group; CMP-003 arrows                                                  | move; switch all of / any of                                                                                                                 | the row / the segment               | none                                                                                                             | spec §6                            |
| CMP-145                   | `Ctrl+S`, `Ctrl+Enter`, `Alt+G`                                                         | Save draft; Save draft (commit chord); switch editor                                                                                         | stays / the other editor            | not in §3.2; `Ctrl+Enter` shadows a trading-view binding in a mutually exclusive focus context (§3.3 rule 1 (3)) | candidates; E36-D04 reviews        |
| CMP-157                   | type, `↑` / `↓`, `Enter`, `Esc`, `Home` / `End`, `→`                                    | filter; move; select; close; jump; reach the chip                                                                                            | the option / the chip / the trigger | none                                                                                                             | WAI-ARIA Combobox                  |
| CMP-233                   | `Tab` through the fields                                                                | edit a limit                                                                                                                                 | the field                           | none                                                                                                             | —                                  |
| CMP-234                   | `Tab`, `Enter`                                                                          | reach an entry; move focus to the offending row                                                                                              | the row                             | none                                                                                                             | the sole diagnostic navigation     |
| CMP-235                   | arrows, `Enter`                                                                         | choose Form / Graph                                                                                                                          | the segment; then the editor        | none                                                                                                             | the prompt is a CMP-044 `standard` |
| CMP-142 / 145 / 157 / 233 | `Enter` / `Space` / `Ctrl+S` / `Ctrl+Enter` on a T2 control; `↑` / `↓` onto a T2 option | nothing staged — no dialog, no request, no state change; the reason (or the one notice's sentence) re-shown inline, announced once, politely | stays / the option                  | none                                                                                                             | E09-D09 §2.2, §9.3 (spec §12)      |

### Table 3 — Accessible name / role

| Component | Element                                                                                                    | Role                                               | Accessible name (source)                                                                                                                                             | States / properties                                                                                                                                     |
| --------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-140   | the row                                                                                                    | group                                              | "Condition {N} of {M}" (`aria-label`); described by the fragment                                                                                                     | `aria-invalid`, `aria-describedby` → message; roving `tabindex`                                                                                         |
| CMP-141   | the group                                                                                                  | group (`fieldset` / `legend`)                      | "Condition group — either {A} or {B}"; legend "any of"                                                                                                               | —                                                                                                                                                       |
| CMP-142   | the row                                                                                                    | group                                              | "Action {N} of {M}" (`aria-label`); described by the fragment                                                                                                        | a stop row's fragment ends "The stop only ever tightens."; no loosening control for any role (#4137)                                                    |
| CMP-145   | the editor · the indicator · the Arm button, Save draft, Validate, Simulate · the one notice (02-5 / 02-6) | region · status + button · button · status / alert | "Rule editor — {name}" (described by the sentence) · "Round-trip: {word}" · "Arm…" / "Save draft" / "Validate" / "Simulate" (the full label) · the notice's sentence | `aria-busy`; `aria-disabled` + `aria-describedby` → the reason or the one notice (never `disabled`); the CMP-019 lock leads the label                   |
| CMP-157   | the input · an option · the chip                                                                           | combobox · option · button                         | "Metric" · "{display_name} · {unit}[, estimated]" · "Estimated, {display name}"                                                                                      | `aria-expanded`, `aria-activedescendant`; `aria-selected`; a T2 option `aria-disabled` + `aria-describedby` → its second line; `aria-haspopup="dialog"` |
| CMP-233   | the block                                                                                                  | group                                              | "Options"                                                                                                                                                            | fields labelled with their defaults; the fire-limit fields above the default `aria-disabled` + `aria-describedby` → `rbac.owner_only` for a non-owner   |
| CMP-234   | the panel · an entry                                                                                       | log · button                                       | "Validation — {n} errors, {m} warnings" · "Row 2 — Row 2 is missing a value."                                                                                        | errors first                                                                                                                                            |
| CMP-235   | the control                                                                                                | radiogroup                                         | "Editor" — "Form" / "Graph"                                                                                                                                          | `aria-describedby` → the indicator's word                                                                                                               |

### Table 4 — Motion pair

| Component | Property                     | motion-safe                                                 | motion-reduce | Duration / easing tokens  |
| --------- | ---------------------------- | ----------------------------------------------------------- | ------------- | ------------------------- |
| all eight | none animated                | focus, invalid, estimated, state pills: instant token swaps | identical     | `motion.duration.instant` |
| CMP-145   | the `Validate` loading state | label kept, width locked, no spinner                        | identical     | `motion.duration.instant` |
| CMP-157   | open / close                 | instant                                                     | identical     | `motion.duration.instant` |

### Table 5 — Live data

| Component      | Field                                           | Politeness | Cadence                               | Coalescing           | Notes                                                                  |
| -------------- | ----------------------------------------------- | ---------- | ------------------------------------- | -------------------- | ---------------------------------------------------------------------- |
| CMP-145        | the summary (accessible description)            | polite     | on blur of a row or on save           | latest sentence only | never per keystroke (P12); ≤1 ambient per 5 s                          |
| CMP-145        | the indicator word                              | polite     | on `result` change                    | latest               | never on `checking`                                                    |
| CMP-145        | the vocabulary-unavailable banner               | assertive  | once on entry                         | —                    | a discrete event (`05` §6.2)                                           |
| CMP-234        | the error count                                 | polite     | on every recompile (debounced 300 ms) | latest count         | "2 errors, 0 warnings"                                                 |
| CMP-157        | the results count                               | polite     | per query, debounced                  | latest               | CMP-048                                                                |
| any T2 control | a T2 press (`Enter` / `Space` / a bound hotkey) | polite     | once per press                        | —                    | the reason sentence, or the one notice's (E09-D09 §9.3–§9.4; spec §13) |

### Density

| Component                 | Mode                  | Row / control height                         | Padding tokens                                  | Smallest target                 |
| ------------------------- | --------------------- | -------------------------------------------- | ----------------------------------------------- | ------------------------------- |
| CMP-140 / 141 / 142       | compact               | 24 px (`size.control.height`)                | `space.inset.sm`; group indent `space.inset.lg` | 24 × 24 px (the menu button)    |
| CMP-140 / 141 / 142       | comfortable           | 32 px                                        | `space.inset.md`; group indent `space.inset.lg` | 32 × 32 px                      |
| CMP-145                   | compact               | header 32 px; fields 24 px; action bar 48 px | `space.inset.md`; sections `space.stack.md`     | 24 × 24 px (the indicator chip) |
| CMP-145                   | comfortable           | header 40 px; fields 32 px; action bar 56 px | `space.inset.lg`; sections `space.stack.lg`     | 32 × 32 px                      |
| CMP-157 / 233 / 234 / 235 | compact / comfortable | 24 / 32 px rows and controls                 | `space.inset.sm` / `space.inset.md`             | 24 × 24 px / 32 × 32 px         |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all eight | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-081 and SCR-083

- [x] Only published Tier-2 tokens; zero hard-coded hex / px in the spec (the px are anatomy derived from the tokens; the hexes in §15 are the tool's resolution of token names).
- [~] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §15); `forced-colors: active` is stated per surface (spec §15); the visual parity check runs on the boards (BLOCKED-PENPOT).
- [x] Passes the contrast matrix for every pair introduced or touched (32 gated rows — 31 pairs plus the high-contrast stretch — 0 FAIL with the unrounded compare; 18 PROPOSED `pairs.mjs` rows named; the m5 / n5 pairs rejected and never drawn).
- [~] CVD simulation reviewed — planned on every export with `docs/design/_tools/cvd_sim.py` (BLOCKED-PENPOT); the greyscale argument is in spec §15.
- [~] Every documented State has a Penpot variant and a story — the states are named (Table 1); the variants exist once drawn; the stories are E36-S01 / S02's.
- [x] Disabled states use the disabled-with-reason pattern (E09-D09 T2) for every RBAC- or state-gated action — the one rule in spec §1, the keyed reasons in §14; Start recording, the fire limits above the default, the ten non-placing `orders:write` options, Resume new orders and the flatten-all gate included; one notice per read-only frame (02-5, 02-6); no bare disabled control.
- [x] Loading / empty / error states designed: "Checking…", the vocabulary-unavailable banner, the gallery's empty and no-results states, the invalid row.
- [x] Keyboard-interaction table completed (spec §12; Table 2) — a design table, to be matched by E36-S01's tested path.
- [x] Accessible-name / role table completed (spec §13; Table 3).
- [x] No canvas / WebGL-adjacent component: the form editor is the non-spatial alternative itself (CMP-146's mandated equivalent).
- [x] Motion-safe / motion-reduce pair specified: none animated (Table 4).
- [x] Hit targets ≥24 px in compact, ≥32 px in comfortable; no essential exception.
- [ ] Accessibility role sign-off — the owner's `approved` comment, pending.
- [x] Confirm-gate variant stated: Arm against live = CMP-044 `variant="typed"` on a CMP-001 `danger` button (CMP-145 A11y); Arm on demo = a `primary` button into SCR-085 (CMP-044 `standard` PROPOSED, E35-D02 decides); the mismatch recovery = CMP-044 `standard`; the keyboard path for all three is Table 2.
- [x] Every heuristic / estimated value is chip-tagged (CMP-227) and links to SCR-058.
- [x] Demo / Live context unambiguous: the chrome's band and the `ARMED-LIVE` word; a LIVE frame never without the red band and the text badge.
- [x] Reuses existing `CMP-*` (CMP-140 … CMP-235, CMP-001 / 003 / 009 / 011 / 026 / 028 / 040 / 043 / 044 / 048 / 050 / 054 / 065 / 079 / 105 / 227 / 239, plus CMP-016 / 019 for the T2 tooltip echo and lock); no new id requested.
- [~] Storybook stories match the Variants × States matrix — planned (Table 1); none exists yet (`apps/web/src/features/` has no rules feature).
- [~] Composes only published-library components — on the boards, once drawn.

## B. Accessibility acceptance criteria (`05` §10) — SCR-081 and SCR-083

```gherkin
Feature: E36-D02 rule form editor and templates gallery — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user authors S1 from an empty rule in SCR-081, or instantiates T1 from SCR-083,
      using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation (one roving stop per row)
    And every action (reorder, duplicate, remove) has a documented non-drag keyboard equivalent
      (the Shift+F10 row menu)
    And focus is never silently moved by the 300 ms validation, the compile or a vocabulary refresh
    And a visible focus indicator meeting >=3:1 contrast is present at every step (color.focus.ring,
      >=4.57:1 on every fill it lands on)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the user authors S1 or instantiates T1
    Then all labels, roles, and current values are announced correctly ("Condition 1 of 2",
      "Metric, Unrealised R", "Round-trip: Round-trips")
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding (the summary on blur or save only)
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity (none: the form is the non-canvas alternative)

  Scenario: Colour-independence
    Given the feature displays buy/sell, bid/ask, P&L, or status state
    When the state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone (the four indicator
      states by glyph + word; Buy/Sell by glyph + word; the destructive class by glyph + word)
    And the feature passes deuteranopia/protanopia/tritanopia simulation review (planned on the exports)

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the
      high-contrast theme
    Then all text meets >=4.5:1 (or >=3:1 for large text) and all meaningful
      non-text UI/chart elements meet >=3:1, per the token contrast matrix (spec §15: 32 gated rows PASS)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the feature would normally animate
    Then the feature uses the motion-reduce variant with no flashing content
      exceeding 3 times per second and no motion lasting >5s without a pause
      control (nothing animates: instant token swaps only)

  Scenario: T2 press
    Given a T2 control (Arm…, Save draft, Validate, Simulate, a T2 picker option or Start recording)
    When Enter, Space, Ctrl+S or Ctrl+Enter is pressed on it
    Then nothing is sent or opened (no request, no dialog, no state change)
    And the reason is re-shown inline at the point of action and announced once, politely

  Scenario: Automated gates
    Given the feature's PR is opened
    Then axe-core reports zero new serious/critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering this feature's primary
      task passes (E36-Q02)
```

Screen-reader spot test: manual spot-test deferred to E36-D04 / E36-Q03 — stated. Owner-approved exceptions: none.
