# E36-D03 — Per-component handoff checklist (`16` §11.4; the two contracts SCR-080 changes, and the rule band's motion pairs)

Two full blocks (CMP-155 RuleListRow, CMP-159 RuleConflictWarning — every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table **once each with a leading `Component` column** (E36-D02's shape at its pushed head `be4b2a25a178c41c952469dc0299f87875401434`, itself E25-D05's; the fallback is per-component tables; deviation recorded in `E36-D03.md` §19 item 6), then §A the `16` §12 design-QA checklist and §B the `05` §10 template for SCR-080, SCR-088 and SCR-089. **Division of labour with E36-D02:** CMP-140 / 141 / 142 / 145 / 157 / 233 / 234 / 235 have their blocks in `E36-D02-handoff.md`; their Motion pair lines point at **Table 4 here**, which carries every motion row of `E36-D03.md` §10 (rows 1–14). CMP-143, CMP-144 and CMP-158 are content-only `15` edits with the contract unchanged (`E36-D03.md` §9): one line each, no block. Every number below is `docs/design/_tools/e36_d03_screens_audit.py`'s; the Penpot page is `E36-D03 Rules list, IR inspector and import export`, BLOCKED-PENPOT until the boards are drawn. **Safety lines carried by both blocks:** no screen of this ticket offers a loosening or stop-clearing control (#4137); a stop-management rule's hover sentence ends "The stop only ever tightens."; a loosening in a stored IR or a bundle is drawn refused with "Not available — rules never loosen a stop."; the OFF word's reason line reads "5 errors in a row — re-arm"; the engine-down banner and the bulk-disarm dialog say "Native stops are unaffected."; the export note says "no account ids, no keys, no armed state".

## Handoff checklist — CMP-155 RuleListRow (E36-D03, #874)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D03 Rules list, IR inspector and import export` (page id pinned after the first build), specimens `CMP-155 · RuleListRow / State=…` on this ticket's own page (never the DS library file); PNGs planned at `docs/design/E36/img/E36-D03-01-scr-080-anatomy.png`, `…-02-scr-080-status-words.png`, `…-11-themes-densities-greyscale.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn, BLOCKED-PENPOT): the nine status words × compact / comfortable × dark / light / high-contrast, plus the estimated, selected, focus-visible and 200 %-stacked states (spec §3, §4, §12); Table 1
- [x] **Keyboard table** — one roving stop per row, `↑` / `↓` between rows, `←` / `→` between a row's cells and controls, `Enter` opens the rule, `Space` toggles the selection, `Shift+F10` the row menu, `Esc` innermost; `Ctrl+A` and `Del` not bound (candidates to E36-D04 / E49); no view-local override of a global binding, no single unmodified key for a destructive action, `Esc` / `Ctrl+K` untouched (spec §13); Table 2
- [x] **Accessible name / role table** — `row` "BE after 1R, armed on demo, last fired 13:42:10 UTC" (PROPOSED) described by the full sentence; the state cell's word + reason line as text; the chip "Estimated, in stop-hunt zone"; the menu "Actions for BE after 1R" with gated items `aria-disabled` + `aria-describedby` (spec §14); Table 3
- [x] **Live data** — the `rules` topic's `mode`, `last_run_status`, `fire_count_24h`, `next_eligible_fire_at_ms` at 250 ms, patched in place, no focus move; a state flip announced once, politely, within ≤1 ambient announcement per 5 s; a rule fire assertive once by the notification path, never repeated by the row (`05` §6.2; spec §3, §14); Table 5
- [x] **Motion pair** — Table 4 rows 8 (the state flip: a single token swap, instant in both modes) and 9 (the bulk bar's appearance, `fast` · `decelerate` → instant); nothing else animates on the row
- [x] **Density notes** — compact 24 px row / `space.inset.sm`, comfortable 32 px / `space.inset.md`; the pills 20 px in compact, 24 px in comfortable; smallest target the 24 × 24 row-menu button and the 24 × 24 selection checkbox (spec §2, §4); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px by padding)
- [x] **Tokens used** — `color.text.primary` / `.secondary` / `.tertiary`, `color.surface.canvas` / `.raised` / `.selected` / `.overlay`, `color.status.success.strong` / `color.status.info.strong` / `color.status.warning.strong` / `color.status.danger.strong` (the state glyphs), `color.env.demo` / `color.env.live` (the pill border), `color.status.info.subtle` + `color.status.info.default` (CMP-227), `color.border.selected` (the current row), `color.focus.ring`, `type.ui.body-strong`, `type.ui.body`, `type.ui.caption`, `type.num.sm`, `font.family.mono`, `size.row.height`, `size.target.min`, `space.inset.sm` / `.md`, `radius.badge`, `border.thick`; `font.mono` (CMP-049's name) is MISSING (spec §12 request 1); Penpot token sets = `packages/ui/tokens` at `3c643309dd24eedd82ce8fcd9ffa79cbd2e81095`
- [x] **Data contract confirmed** — `GET /api/v1/rules` (`22` `Rule`: `id`, `name`, `mode`, `scope`, `editor`, `tags`, `active_version_id`, `version`, `bindings`, `last_run_at`, `last_run_status`, `fire_count_24h`, `created_by`, …), WS `rules` (`23` §15.6 `RuleUpdate`: `mode`, `active_version_id`, `version`, `last_run_status`, `fire_count_24h`, `next_eligible_fire_at_ms`, `updated_at_ms`; events `evaluated | suppressed | action_sent | action_result | error | started | finished`), `PUT /api/v1/rules/{ruleId}/mode` (Arm → SCR-085, Disarm; `x-idempotency: required`), `DELETE /api/v1/rules/{ruleId}` (409 while armed); gaps: no `environments` (D03-G4), no `estimated` (D03-G5), no author name (D03-G6), no B9 state or disarm reason (D03-G7), no conflict shape (D03-G8), no `summary` (D03-G13)
- [ ] **Contrast and CVD** — PENDING (the PROPOSED `pairs.mjs` rows are registered by E36-S01; CVD planned on the exports): spec §12 rows 1–12, 19–21, 26–27, 34 — the words 14.35 / 15.62 / 16.25 on raised, the glyphs 9.40 / 9.76 / 11.00 / 9.32 dark (≥3.39 light), the pill borders 3.64 / 4.42, the chip word 10.74, the focus ring 7.05 / 6.66, all PASS; the nine words told apart in greyscale by glyph + text
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-159 RuleConflictWarning (E36-D03, #874)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E36-D03 Rules list, IR inspector and import export` (page id pinned after the first build), specimen `CMP-159 · RuleConflictWarning / State=OnList`; PNG planned at `docs/design/E36/img/E36-D03-03-scr-080-banners-bulk.png`
- [ ] **Variants × States matrix** — PENDING (BLOCKED-PENPOT): single conflict · multiple conflicts · on the list × default, focus-visible (the action), three themes (spec §3); Table 1
- [x] **Keyboard table** — the banner is not a stop; its one action **Set priority** (→ SCR-086) is a button in the Tab order before the table; `Esc` untouched (spec §13); Table 2
- [x] **Accessible name / role table** — `status` with the text "2 rules target the same position — resolve precedence" + the second line naming the two rules; the action's name "Set priority" (spec §14); Table 3
- [x] **Live data** — arrives with the rule state (no stream of its own); one polite announcement on arrival, never repeated while it stays; Table 5
- [x] **Motion pair** — none animated: the banner appears as an instant insert; the rows beneath keep their position (spec §10); Table 4 ("none animated")
- [x] **Density notes** — 32 px in compact / 40 px in comfortable (`space.inset.sm` / `.md`); smallest target the 24 × 24 action button; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — inherits CMP-028 `tone="warning"`: `color.status.warning.subtle` (fill), `color.status.warning.strong` (glyph), `color.text.primary` (the text), `color.text.secondary` (the second line — never `color.text.tertiary` on amber, m5), `color.focus.ring` (the action), `type.ui.body`, `radius.card`, `space.inset.sm` / `.md`; Penpot token sets = `packages/ui/tokens` at `3c643309dd24eedd82ce8fcd9ffa79cbd2e81095`
- [x] **Data contract confirmed** — no conflict shape on `Rule` or `RuleUpdate` (D03-G8); `14` SCR-086 detects conflicts server-side at arm time and on save and audits `rule.conflict_detected {ruleIds, scope, kind}`; the banner's names resolve from those ids client-side until a shape ships; the resolution lives on SCR-086 (E35)
- [ ] **Contrast and CVD** — PENDING: spec §12 rows 13–15, 29 — 9.86 / 15.62 / 11.16 text, 6.05 / 8.98 / 9.86 second line, 7.56 / 4.11 / 7.56 glyph, 4.57 / 5.86 / 11.88 focus ring, all PASS; the m5 pair (3.86) is rejected and never drawn
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending

**CMP-143 RuleTriggerPicker, CMP-144 RuleScopeSelector, CMP-158 SafetyInvariantNotice:** content-only `15` edits (the vocabulary's 13 triggers; `appliesTo` gains `any` and the environments segment; D02's placement line and sentence); contract unchanged; no block (CMP-158's placement is `E36-D02-handoff.md`'s line).

### Table 1 — Variants × States

| Component | Variant                                                                               | State (every one is a Penpot variant and a story)                                                | Penpot variant (planned)                     | Story (planned)                                                                                                             | Notes      |
| --------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------- |
| CMP-155   | DRAFT · SIMULATING · ARMED-DEMO · ARMED-LIVE · DISARMED · PAUSED · OFF · DONE · ERROR | default, hover, focus-visible, selected, estimated (the chip), with a reason line, 200 %-stacked | `CMP-155 · RuleListRow / State=…, Density=…` | `RuleEngine/RuleListRow/*` (Draft, Simulating, ArmedDemo, ArmedLive, Disarmed, PausedDegraded, Off, Done, Error, Estimated) | spec §2–§3 |
| CMP-159   | single conflict · multiple conflicts · on the list                                    | default, focus-visible (the action)                                                              | `CMP-159 · RuleConflictWarning / Variant=…`  | `RuleEngine/RuleConflictWarning/*` (SingleConflict, MultipleConflicts, OnList)                                              | spec §3    |

### Table 2 — Keyboard

| Component | Key                                                               | Action                                                                                               | Focus after                                        | Global conflict? (`05` §3.2 / §3.3)                                                                                                               | Notes                            |
| --------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| CMP-155   | `Tab`, `↑` / `↓`, `←` / `→`, `Enter`, `Space`, `Shift+F10`, `Esc` | roving row list; the row's cells and controls; open the rule; toggle selection; the row menu; cancel | the row / the cell / SCR-081 / the first menu item | none (composite widget, `05` §3.4 item 2); `Enter` shadows `rules.inspect_node` only in the SCR-082 context (mutually exclusive); `Esc` untouched | P11                              |
| CMP-155   | `Ctrl+A`, `Del`                                                   | not bound (the header checkbox selects all; Delete is a menu item with a confirm)                    | —                                                  | `rules.select_all` / `rules.delete` are the graph context's; `05` §3.3 rule 1 (2)                                                                 | candidates; E36-D04 / E49 review |
| CMP-159   | `Tab`, `Enter` / `Space`                                          | reach and activate **Set priority** (→ SCR-086)                                                      | SCR-086's dialog; on close, the button             | none                                                                                                                                              | spec §13                         |

### Table 3 — Accessible name / role

| Component | Element                                                                      | Role                                               | Accessible name (source)                                                                                                                                                                                                       | States / properties                                                                                                    |
| --------- | ---------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| CMP-155   | the row · the state cell · the chip · the menu button · the environment pill | `row` · `cell` · `button` · `button` (menu) · text | "BE after 1R, armed on demo, last fired 13:42:10 UTC" (`aria-label`, PROPOSED; described by the full sentence) · the word + reason line as text · "Estimated, in stop-hunt zone" · "Actions for BE after 1R" · "DEMO" / "LIVE" | roving `tabindex`, `aria-selected`, `aria-current`; gated menu items `aria-disabled` + `aria-describedby` → the reason |
| CMP-159   | the banner · its action                                                      | `status` · `button`                                | "2 rules target the same position — resolve precedence" + the two names · "Set priority"                                                                                                                                       | one polite announcement on arrival                                                                                     |

### Table 4 — Motion pair (every row of `E36-D03.md` §10; D02's blocks point here)

| Component / screen                                | Property                                             | motion-safe                                                                                                 | motion-reduce                 | Duration / easing tokens                                                          |
| ------------------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------- |
| CMP-140 (row 1, add)                              | opacity + 8 px slide-in                              | the `16` §7 panel-mount recipe; the new row's name and focus carry the information                          | instant                       | `motion.duration.fast`, `motion.easing.decelerate`                                |
| CMP-140 (row 2, remove)                           | opacity + height collapse                            | the announcement "Condition 2 removed; 3 conditions" and focus on the next row                              | instant                       | `motion.duration.fast`, `motion.easing.accelerate`                                |
| CMP-140 (row 3, reorder)                          | translateY swap                                      | the announcement "Condition 2 of 4 moved up" and the renumbered names                                       | instant                       | `motion.duration.fast`, `motion.easing.standard`                                  |
| CMP-141 (row 4, expand / collapse)                | height + chevron rotation                            | `aria-expanded` and the chevron's end state                                                                 | instant (the chevron flips)   | `motion.duration.fast`, `motion.easing.standard`                                  |
| CMP-234 (row 5, error-count change)               | the count pill's text crossfade; no background flash | the count text and the `role="log"` announcement (the 300 ms debounce would flash 3.33 / s, so none exists) | instant                       | `motion.duration.fast`, `motion.easing.standard`                                  |
| CMP-145 `roundTrip` (row 6, indicator transition) | crossfade of glyph + word + fill                     | the word, the glyph and one polite announcement                                                             | instant swap                  | `motion.duration.fast`, `motion.easing.standard`                                  |
| CMP-046 (row 7, drawer open / close)              | translateX slide                                     | focus moves into the drawer; the heading is announced                                                       | instant                       | `motion.duration.normal`, `motion.easing.decelerate` / `motion.easing.accelerate` |
| CMP-155 (row 8, state flip)                       | none — a single token swap                           | the word + glyph; announced once, politely                                                                  | same                          | `motion.duration.instant`                                                         |
| CMP-243 (row 9, bulk-bar appear)                  | opacity + 8 px slide                                 | the toolbar's "3 selected" text                                                                             | instant                       | `motion.duration.fast`, `motion.easing.decelerate`                                |
| CMP-044 / CMP-043 (row 10, dialog open)           | scale + fade                                         | the focus trap and the dialog heading                                                                       | instant                       | `motion.duration.normal`, `motion.easing.decelerate`                              |
| CMP-033 (row 11, "Copied")                        | the transient label swap                             | the polite announcement "Copied"                                                                            | instant                       | `motion.duration.fast`, `motion.easing.standard`                                  |
| SCR-089 (row 12, import progress)                 | a determinate per-file list filling                  | rows append as results stream; "7 of 100 checked" at ≤1 per 5 s                                             | same (none animated)          | `motion.duration.instant`                                                         |
| SCR-080 (row 13, loading skeleton)                | the `slow` looping shimmer                           | "Loading…" carries it; the loop stops on data or at 5 s                                                     | static two-tone fill, no loop | `motion.duration.slow`, `motion.easing.standard`                                  |
| SCR-080 (row 14, value flash on the fires cell)   | none — a count is not a price tick                   | the number; a fire is announced assertively once                                                            | same                          | `motion.duration.instant`                                                         |

### Table 5 — Live data

| Component | Field                    | Politeness                 | Cadence                           | Coalescing                                | Notes                                                                     |
| --------- | ------------------------ | -------------------------- | --------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------- |
| CMP-155   | the state word           | polite                     | once per flip, ≤1 ambient per 5 s | the `rules` topic at 250 ms; latest value | "BE after 1R: armed on demo"                                              |
| CMP-155   | last fired / fires today | none (`aria-live="off"`)   | patched in place per update       | 250 ms                                    | the full sentence only on hover / focus                                   |
| CMP-155   | a rule fire              | assertive, once            | per fire                          | —                                         | by the notification path (E40-D02), never repeated by the row (`05` §6.2) |
| CMP-159   | the banner               | polite                     | once on arrival                   | —                                         | never repeated while it stays                                             |
| SCR-080   | the engine-down banner   | assertive (`role="alert"`) | once on entry                     | —                                         | persistent; `aria-live` off thereafter                                    |
| SCR-089   | import progress          | polite                     | ≤1 per 5 s                        | the latest count                          | "20 of 100 checked"                                                       |

### Density

| Component         | Mode                  | Row / control height                                | Padding tokens                                              | Smallest target                                |
| ----------------- | --------------------- | --------------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------- |
| CMP-155           | compact               | 24 px (`size.row.height`); pills 20 px              | `space.inset.sm`                                            | 24 × 24 px (the row-menu button, the checkbox) |
| CMP-155           | comfortable           | 32 px; pills 24 px                                  | `space.inset.md`                                            | 32 × 32 px                                     |
| CMP-159           | compact / comfortable | 32 / 40 px banner                                   | `space.inset.sm` / `space.inset.md`                         | 24 × 24 px (the action button)                 |
| SCR-088 / SCR-089 | compact / comfortable | 24 / 32 px controls; the drawer 480 px (360 narrow) | `space.inset.sm` / `space.inset.md`; `space.dialog.padding` | 24 × 24 px (Copy, segment, Copy path)          |

### Essential exceptions

| Component        | Exception | Compensating control | Reviewer | Date |
| ---------------- | --------- | -------------------- | -------- | ---- |
| CMP-155, CMP-159 | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-080, SCR-088 and SCR-089

- [x] Only published Tier-2 tokens; zero hard-coded hex / px in the spec (the px are anatomy derived from the tokens; the hexes in §12 are the tool's resolution of token names; `space.rulegroup.indent` is PROPOSED, not bound).
- [~] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §12); the visual parity check runs on board 11 (BLOCKED-PENPOT).
- [x] Passes the contrast matrix for every pair introduced or touched (37 gated rows, 0 FAIL with the unrounded compare; 17 PROPOSED `pairs.mjs` rows named; the m5 / n5 pairs rejected and never drawn).
- [~] CVD simulation reviewed — planned on every export with `docs/design/_tools/cvd_sim.py` (BLOCKED-PENPOT); the greyscale argument is in spec §12.
- [~] Every documented State has a Penpot variant and a story — the states are named (Table 1); the variants exist once drawn; the stories are E36-S01 / S02 / S03's.
- [x] Disabled states use the disabled-with-reason pattern (E09-D09 T2) for every gated menu item and segment; no bare disabled control.
- [x] Loading / empty / error states designed: the skeleton, the empty and filtered-empty states, the engine-down banner, the compile-failure, quarantined and engine-unavailable inspector states, the import skip rows.
- [x] Keyboard-interaction table completed (spec §13; Table 2) — a design table, to be matched by E36-S02's tested path.
- [x] Accessible-name / role table completed (spec §14; Table 3).
- [x] No canvas / WebGL surface: the table, the `<pre>` and the tree are the non-canvas alternatives themselves.
- [x] Motion-safe / motion-reduce pair specified for every animated property (Table 4, fourteen rows; `16` §12's motion box).
- [x] Hit targets ≥24 px in compact, ≥32 px in comfortable; no essential exception.
- [ ] Accessibility role sign-off — the owner's `approved` comment, pending.
- [x] Confirm-gate variant stated: bulk disarm and Delete = CMP-044 `standard` on a CMP-001 `danger` button; Arm = SCR-085 (E35-D02's dialog); the keyboard path is Table 2.
- [x] Every heuristic / estimated value is chip-tagged (CMP-227 on the list row) and links to SCR-058.
- [x] Demo / Live context unambiguous: the chrome's band, the environment pill and the `ARMED-LIVE` word; a LIVE frame never without the red band and the text badge.
- [x] Reuses existing `CMP-*` (CMP-001 / 002 / 003 / 010 / 015 / 016 / 026 / 028 / 033 / 036 / 041 / 043 / 044 / 046 / 049 / 054 / 055 / 067 / 068 / 105 / 155 / 159 / 227 / 234 / 240 / 243); no new id requested (CMP-240 / 243 are E13-D02's proposals).
- [~] Storybook stories match the Variants × States matrix — planned (Table 1); none exists yet (`apps/web/src/features/` has no rules feature).
- [~] Composes only published-library components — on the boards, once drawn.

## B. Accessibility acceptance criteria (`05` §10) — SCR-080, SCR-088 and SCR-089

```gherkin
Feature: E36-D03 rules list, IR inspector and import / export — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user finds why a rule stopped and re-arms it (SCR-080), proves the two editors agree
      (SCR-088), or imports a bundle and reads why a rule was skipped (SCR-089), using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation (one roving stop per row)
    And every action (including any drag-based interaction) has a documented
      non-drag keyboard equivalent (the Shift+F10 row menu; the native file input)
    And focus is never silently moved by a background data update (the 250 ms rules update patches in place)
    And a visible focus indicator meeting >=3:1 contrast is present at every step (color.focus.ring,
      >=4.57:1 on every fill it lands on)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the user performs the three primary tasks
    Then all labels, roles, and current values are announced correctly ("BE after 1R, armed on demo,
      last fired 13:42:10 UTC"; "OFF — 5 errors in a row, re-arm"; "Skip — The bundle references an
      account you cannot access.")
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding (a state flip once; a fire once, assertively)
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity (none: the table, the pre and the tree are the alternatives)

  Scenario: Colour-independence
    Given the feature displays buy/sell, bid/ask, P&L, or status state
    When the state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone (nine words by glyph + text;
      DEMO / LIVE by word + glyph shape; Accept / Skip by word + glyph)
    And the feature passes deuteranopia/protanopia/tritanopia simulation review (planned on the exports)

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the
      high-contrast theme
    Then all text meets >=4.5:1 (or >=3:1 for large text) and all meaningful
      non-text UI/chart elements meet >=3:1, per the token contrast matrix (spec §12: 37 gated rows PASS)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the feature would normally animate
    Then the feature uses the motion-reduce variant with no flashing content
      exceeding 3 times per second and no motion lasting >5s without a pause
      control (Table 4: every row has a reduce variant; the shimmer stops on data or at 5 s)

  Scenario: Automated gates
    Given the feature's PR is opened
    Then axe-core reports zero new serious/critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering this feature's primary
      task passes (E36-Q03)
```

Screen-reader spot test: manual spot-test deferred to E36-D04 / E36-Q03 — stated. Owner-approved exceptions: none.
