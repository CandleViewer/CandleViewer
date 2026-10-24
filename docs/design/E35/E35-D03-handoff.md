# E35-D03 — Per-component handoff checklist (`16` §11.4; the contracts SCR-086 / SCR-087 / SCR-089 change)

Three blocks (CMP-156 RuleEvaluationTimeline's **live** variant, CMP-159 RuleConflictWarning's **resolver** variant, CMP-234 ValidationPanel's **third host** — every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table once each with a leading `Component` column (the E35-D02 shape), then §A the `16` §12 design-QA checklist and §B the `05` §10 template for the four screens. **E35-D05 embeds this file by reference** (BQ-3 RULED 6381678125: an `SCR-*` ticket attaches the checklist for a contract it introduces or changes, `16` §11.4; the ticket carries no `handoff` label). Every number below is `docs/design/_tools/e35_d03_diagnostics_audit.py`'s; the Penpot page is `E35-D03 Conflicts, history and IR` · id `9374df7a-7f73-809b-8008-d6c51174c6ee`, with the nine boards drawn and exported (spec §0).

## Handoff checklist — CMP-156 RuleEvaluationTimeline, live variant (E35-D03, #938)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E35-D03 Conflicts, history and IR` · id `9374df7a-7f73-809b-8008-d6c51174c6ee` (self-hosted Penpot), frames `SCR-087/populated` … `SCR-087/viewer-role` on this ticket's own page (boards 03, 04 and 08); PNGs exported at `docs/design/E35/img/E35-D03-03-scr-087-anatomy.png`, `…-04-scr-087-states-and-reasons.png`, `…-08-scr-087-anatomy-light.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists once the boards are drawn): `variant: live` × 15 frames (spec §5) beside D02's simulation half; Table 1
- [x] **Keyboard table** — the APG grid (CMP-049 `grid: true`): one Tab stop, roving rows, `↑` / `↓` rows (the restart marker included), `←` / `→` cells, `Home` / `End`, `Ctrl+Home` / `Ctrl+End`, `PgUp` / `PgDn`; `Space` expands the row (its Copy buttons and links are cells); `Enter` on a Links cell opens the link; the pill a button that inserts rows and keeps focus; no global key (spec §10); Table 2
- [x] **Accessible name / role table** — `grid` "Fire history, newest first — {n} firings" with `columnheader`s and `aria-rowindex`; the expanded row a `row` with one spanning cell holding the nested `table` "Why it fired — {rule}, {ts}" with `<th scope="col">` / `<th scope="row">`; the marker a `row` reading CA-24; the Result cell text + glyph; the Links cell's three `link`s (a T2 link `aria-disabled` + `aria-describedby` → the one Audit notice under the caption, or the row's visually-hidden `rbac.account` node echoed by CMP-016 and rendered in the expanded row — spec §4, D03-A13); the expanded row's Copy a CMP-033 cell and its cross-reference `link` to a superseded partner; Table 3
- [x] **Live data** — the `rules` topic at 250 ms with `include_events`; new firings behind the pill (polite once per batch), rows patched in place, never per event; a failed LIVE firing assertive once then coalesced (spec §10); Table 5
- [x] **Motion pair** — the expanded row `fast` height → instant; the pill `fast` fade → instant; rows append instantly, no value flash (spec §12); Table 4
- [x] **Density notes** — rows 24 px (`size.row.compact`) / 32 px (`size.row.comfortable`); `font.family.mono` numerics (`type.num.sm`); one line per cell, the full text in the expanded row; smallest target 24 × ≥ 150 (a row); Density table
- [x] **Essential-exceptions log** — none (every target reaches 24 px)
- [x] **Tokens used** — inherits CMP-049 (`color.surface.canvas` / `.raised` / `.hover` / `.selected`, `color.border.subtle`, `color.text.primary` / `.secondary`) plus `color.status.danger.subtle` / `.strong` (the failed row), `color.status.success.strong` (the Done glyph), `color.text.tertiary` (the Skipped dash — never on a selected row), `color.status.info.subtle` / `.strong` (the pill), `color.surface.sunken` (the restart marker), `color.env.demo` / `color.env.live` (the glyphs), `color.text.link`, `color.focus.ring`, `font.family.mono`, `size.row.compact` / `.comfortable`, `motion.duration.fast` / `.instant`; `font.mono` (the `15` entry's name) is MISSING (spec D03-C9); Penpot token sets = `packages/ui/tokens` at `b8881f7f598916ef4515c695640e31c05936f564`
- [x] **Data contract confirmed** — `GET /rules/{ruleId}/runs` (`RuleRun {id, rule_id, rule_version_id, kind, status, started_at, finished_at, evaluations, fires, errors, error_message}`; `status` / `kind` / `from` / `to` params; `rules:read`, `granted_accounts`), `GET /rules/runs/{runId}/events` (`RuleEvent {id, ts, kind, payload}` — `evaluated.payload.conditions[] {path, result, left, right}`, `action_sent.payload {action, position_id, price}`, `action_result.payload {ok, latency_ms}`); the `rules` topic `events[]`; **neither route is shipped** (D03-G3); gaps: environment / trigger / actions / `trade_group_id` (D03-G4), the exchange `code` (D03-G5), `audit_id` (D03-G6), the restart event (D03-G7), the CSV export (D03-G8), `scope`'s detail (D03-G11); the account id resolves to a label + last-4, never shown raw
- [ ] **Contrast and CVD** — PENDING (the PROPOSED `pairs.mjs` rows are registered by E35-S06; CVD planned on the exports): spec §13 rows 14–40 — row text 15.20 / 16.78 / 17.21 on the canvas and 14.35 / 15.62 / 16.25 on raised, the failed row 12.06 / 14.64 / 13.66, the Done glyph 9.40 / 3.39 / 9.40 (raised) and 9.96 / 3.64 / 9.96 (canvas), the Failed glyph 9.32 / 4.11 / 9.32 and 9.87 / 4.41 / 9.87 (the Error glyph shares its token), the marker 10.69 / 7.37 / 17.42, the pill 10.74 / 15.44 / 12.16, the links 7.05 / 6.30 / 7.05 and 5.59 / 5.50 / 5.59 on the failed row's fill, the LIVE glyph on that fill 3.71 / 4.23 / 3.71, all PASS; the greyscale strip (board 08) keeps Done / Failed / Skipped apart by glyph + word
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-159 RuleConflictWarning, resolver variant (E35-D03, #938)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E35-D03 Conflicts, history and IR` · id `9374df7a-7f73-809b-8008-d6c51174c6ee` (self-hosted Penpot), frames `SCR-086/conflicts-stop-pair` … `SCR-086/view-as` (boards 01, 02 and 07); PNGs exported at `docs/design/E35/img/E35-D03-01-scr-086-anatomy-kinds.png`, `…-02-scr-086-states.png`, `…-07-scr-086-anatomy-light.png`
- [ ] **Variants × States matrix** — PENDING: `variant: banner` (E36-D03's) · `inline` (E35-D02's SCR-085 line) · `resolver` (this spec) × the ten frames of spec §3 and the four kinds; Table 1
- [x] **Keyboard table** — focus opens on the first conflict's first radio, trapped, returns to the opener ("Choose which goes first" or SCR-080's banner action); `Tab` through the radiogroups (one roving stop each; `↑` / `↓` change the selection; an arrow onto a T2 option re-shows its reason and changes nothing) → Move up / Move down → the Narrow scope disclosure → the acknowledgement box → Cancel → Apply; `Enter` on a radio never writes; `Esc` cancels; no global key (spec §10); Table 2
- [x] **Accessible name / role table** — `dialog` "Two rules, one stop — choose which goes first" described by CA-27; the `table` "Conflicts — {n}"; one `radiogroup` "Resolution for {A} and {B}" per conflict, each `radio` described by its consequence sentence; the `list` "1st {A} · 2nd {B}" with the two `button`s; the acknowledgement `checkbox`; T2 options `aria-disabled` + `aria-describedby` → the reason under the group; `role="note"` on the risk band (spec §2, §10); Table 3
- [x] **Live data** — none while open; Apply's 200 closes the dialog with one polite "Order set — {A} then {B}."; a `409` / `412` assertive once (spec §10); Table 5
- [x] **Motion pair** — the dialog `normal` scale + fade → instant; the list reorders instantly; the reason re-shown instantly (spec §12); Table 4
- [x] **Density notes** — the dialog 960 px (`size: lg`); option rows 24 px control + the consequence line; table rows 24 / 32 px; the footer 48 / 56 px; smallest target 24 × 24 (a radio, the acknowledgement box); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.surface.overlay`, `elevation.4`, `radius.control`, `color.text.primary` / `.secondary` / `.tertiary` / `.on-action` / `.link`, `color.action.primary.default` (Apply, the selected ring), `color.status.warning.subtle` / `.strong` (the conflict row), `color.surface.sunken` + `color.status.info.strong` (the risk band and its glyph), `color.status.danger.subtle` / `.strong` (the refusal line), `color.surface.raised` + `color.border.default` (the T2 look), `opacity.disabled` (the validity look), `color.focus.ring`, `type.ui.heading-md` / `.body` / `.caption` / `.label`, `size.control.height`, `size.target.min`, `space.inset.md`, `space.stack.md`, `motion.duration.normal` / `.instant`; Penpot token sets = `packages/ui/tokens` at `b8881f7f598916ef4515c695640e31c05936f564`
- [x] **Data contract confirmed** — the conflict set on `Rule` / `RuleUpdate` (E36-D03 D03-G8, PROPOSED; `kind`, `risk_controls[]` and the unnamed-partner form D03-G1); Apply → PROPOSED `PUT /rules/precedence {ordered_rule_ids[]}` (D03-G1) · `PUT /rules/{ruleId}` (a narrowed scope → a new version) · `PUT /rules/{ruleId}/mode {mode: disabled}` (the disarm); `409 conflict` / `412 version_conflict` → the refusal; `GET /auth/session/view-as`; audited `rule.conflict_resolved {choice}`, `rule.priority_changed` (`14`; absent from `24` §15.5 — D03-C8); **no detection and no write is shipped** (D03-G2; `validator.py` line 255)
- [ ] **Contrast and CVD** — PENDING: spec §13 rows 1–13 — dialog text 13.27 / 14.37 / 15.02, the consequence lines 8.14 / 8.26 / 13.27, the T2 label 5.62 / 5.92 / 11.21 and reason 8.81 / 8.98 / 14.35, the conflict row 9.86 / 15.62 / 11.16 with its glyph 7.56 / 4.11 / 7.56, the risk band 17.42 / 12.82 / 19.73 with its glyph 11.85 / 3.60 / 11.85, Apply 4.76 / 4.76 / 7.45, the refusal 12.06 / 14.64 / 13.66, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-234 ValidationPanel, the SCR-089 host and the jump-to-offender pattern (E35-D03, #938)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done (docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E35-D03 Conflicts, history and IR` · id `9374df7a-7f73-809b-8008-d6c51174c6ee` (self-hosted Penpot), the frame `SCR-089/validation-panel` and its neighbours `SCR-089/export-verified` … `SCR-089/import-results-landing` (boards 05 and 09); PNGs exported at `docs/design/E35/img/E35-D03-05-scr-088-089-deltas.png`, `…-09-scr-089-verification-light.png`
- [ ] **Variants × States matrix** — PENDING: host `editor` (E36's) · `inspector` (SCR-088's Issues segment) · `import` (this spec) × empty · errors · one focused entry; Table 1
- [x] **Keyboard table** — `↑` / `↓` or `Tab` between the entries; `Enter` on an entry moves focus to the offending pre-check row's checkbox cell; `Shift+Tab` returns; the pre-check grid's `Space` toggles an Accept row's box (a Skip row has none) (spec §10); Table 2
- [x] **Accessible name / role table** — `log` "Import problems — {n}" ordered errors first; each entry a `button` "{rule} — {reason} ({field})"; the count announced once ("3 files cannot be imported"); the pre-check `grid` with a `checkbox` cell "Import {name}" on Accept rows; the verification strip `role="note"` "Checked this file" (spec §8, §10); Table 3
- [x] **Live data** — none; the pre-check's completion announces the count once; the Import button's count a text swap announced after a 500 ms pause (spec §10); Table 5
- [x] **Motion pair** — none animated: entries appear instantly; the focus move is instant (spec §12); Table 4
- [x] **Density notes** — entries 24 / 32 px; the checkbox 24 × 24 inside a 24 px row; smallest target 24 × 24; Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.status.danger.subtle` / `.strong` (the entries), `color.status.success.strong` (Accept, the strip's checks), `color.status.info.subtle` (the strip), `color.text.primary` / `.secondary` / `.tertiary` (the checkbox border), `color.action.primary.default` (the checked box; Import), `color.text.on-action`, `opacity.disabled` (Import at 0), `color.focus.ring`, `size.row.compact` / `.comfortable`, `size.target.min`, `motion.duration.instant`; `color.status.danger` and `color.status.warn` (the `15` entry's names) do not exist (E36-D03's finding, cited); Penpot token sets = `packages/ui/tokens` at `b8881f7f598916ef4515c695640e31c05936f564`
- [x] **Data contract confirmed** — `POST /rules/validate` → `{valid, errors[] {path, code, message}}` per file (the pre-check); `POST /rules` → `Rule.mode: disabled` (`create()`, `manager.py` line 576; `disabled_reason` unset, so the landing word is E36-D03's DRAFT — D03-G12), `scope.environments: ["demo"]` (`import_rule`, lines 405–407); the returned bundle `{format: "cv-rule-bundle/1", ir}` (the strip's scan; `ACCOUNT_KEY`); gaps: the export / import operations and the dry run (E36-D03 D03-G1 / D03-G16, reused), the multi-rule bundle (D03-G2 reused)
- [ ] **Contrast and CVD** — PENDING: spec §13 rows 11–12, 21–22, 26, 31, 33 — the entries 12.06 / 14.64 / 13.66 with their glyph 7.83 / 3.85 / 7.83, the strip 10.74 / 15.44 / 12.16 with its check glyph 7.03 / 3.35 / 7.03, the Accept glyph 9.40 / 3.39 / 9.40, the checkbox border 5.62 / 5.92 / 11.21, all PASS
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component | Variant                                                                | State (every one is a Penpot variant and a story)                                                                                                                                                                                                                                                                                                         |
| --------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-156   | live (this spec) · simulation (E35-D02)                                | populated, superseded row (the partner's page), streaming (the pill), failed rows, skipped rows, error row (the Error word), engine-restart marker, filtered (+ filtered-empty), empty (both forms), loading, error, older page, reflow (200 %), view-as (no notice), viewer role (two T2 links: one notice for Audit, a hidden per-row reason for Order) |
| CMP-159   | banner (E36-D03) · inline (E35-D02) · resolver (this spec)             | conflicts-stop-pair, multiple-conflicts, risk-band, arm-anyway-acknowledged, applying, applied, refused, no-conflict, other-owners-rule (two T2 options; every partner fill "a rule you can't see"), view-as (Apply alone T2; the radios, Move up / Move down and the box stage); the four kinds as insets                                                |
| CMP-234   | editor host (E36) · inspector host (SCR-088) · import host (this spec) | empty, errors (errors first), one entry focused with its pre-check row highlighted                                                                                                                                                                                                                                                                        |

### Table 2 — Keyboard

| Component               | Key                                                                             | Action                                                                                                                                       | Focus after                                | Global conflict? (`05` §3.2 / §3.3)         | Notes                                           |
| ----------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------- | ----------------------------------------------- |
| CMP-156                 | `Tab`                                                                           | into the grid (one stop) and out to Newer / Older                                                                                            | the current row                            | none                                        | APG grid                                        |
| CMP-156                 | `↑` / `↓`, `←` / `→`, `Home` / `End`, `Ctrl+Home` / `Ctrl+End`, `PgUp` / `PgDn` | rows (the marker included); cells; first / last cell; first / last row; a viewport                                                           | the row / the cell                         | none (`05` §3.4 item 2)                     | `aria-rowindex` kept honest by the virtualiser  |
| CMP-156                 | `Space`                                                                         | expand / collapse the row                                                                                                                    | stays on the row                           | none                                        | the expanded row's controls are cells           |
| CMP-156                 | `Enter` on a Links cell                                                         | open Order / Audit / Replay; a T2 link re-shows its reason                                                                                   | the target / stays                         | none                                        | never on another cell                           |
| CMP-156                 | `Enter` on the pill                                                             | insert the new rows                                                                                                                          | stays on the pill                          | none                                        | `05` §3.4 item 3 — focus never stolen           |
| CMP-159                 | `Tab`, `↑` / `↓` on a radiogroup, `Space`, `Enter`, `Esc`                       | the radiogroups → Move up / Move down → the disclosure → the box → Cancel → Apply; select; toggle; activate a button (never a radio); cancel | the first radio first; the opener on close | none; no resolver key exists or is proposed | Move up / Move down announce "{rule}, 1st of 2" |
| CMP-234                 | `↑` / `↓`, `Tab`, `Enter`, `Shift+Tab`                                          | between the entries; move focus to the offending pre-check row; back                                                                         | the row's checkbox cell / the entry        | none                                        | errors first                                    |
| any T2 control          | `Enter` / `Space` / an arrow                                                    | nothing staged; the reason re-shown once, politely                                                                                           | stays                                      | none                                        | E09-D09 §9.3                                    |
| a validity-look control | `Enter` / `Space`                                                               | the error summary shown                                                                                                                      | stays                                      | none                                        | E30-D02 D3                                      |

### Table 3 — Accessible name / role

| Component | Element                                                                                                                         | Role                                                                           | Accessible name (source)                                                                                                                                                                                                                                                                                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-156   | the grid · a row · the expanded row · the nested table · the marker · the Result cell · a link · the pill                       | grid · row · row (one spanning cell) · table · row · gridcell · link · button  | "Fire history, newest first — {n} firings" · "{time} UTC, {version}, {trigger}, {conditions}, {action}, {result}, {environment}" · "Why it fired — {rule}, {ts}" · the `<th scope="col">` Condition · Saw · Needed · Result · CA-24 · "Done, 314 ms" / "Failed — {why}" / "Error" / "Skipped" · "Order" / "Audit" / "Replay" (+ "unavailable" and the reason when T2) · "{n} new firings" |
| CMP-159   | the dialog · the table · a radiogroup · a radio · the list · Move up / Move down · the box · the risk band · the footer buttons | dialog · table · radiogroup · radio · list · button · checkbox · note · button | "Two rules, one stop — choose which goes first" described by CA-27 · "Conflicts — {n}" · "Resolution for {A} and {B}" · "Set priority" (described by CA-28) / "Narrow scope" / "Disarm one" / CA-29 · "1st {A} · 2nd {B}" · "Move {rule} up" / "Move {rule} down" · "I understand both rules can move this stop." · "Risk controls go first" · "Cancel" / "Apply"                         |
| CMP-234   | the panel · an entry · the pre-check grid · a checkbox cell · the strip                                                         | log · button · grid · checkbox · note                                          | "Import problems — {n}" · "{rule} — {reason} ({field})" · "Import preview — {n} files · checked before import" · "Import {name}" · "Checked this file"                                                                                                                                                                                                                                    |

### Table 4 — Motion pair

| Component | Property                                            | motion-safe                             | motion-reduce                 | Duration / easing tokens              |
| --------- | --------------------------------------------------- | --------------------------------------- | ----------------------------- | ------------------------------------- |
| CMP-156   | the expanded row; the pill's arrival; a row append  | `fast` height; `fast` fade; instant     | instant; instant; identical   | `motion.duration.fast` → `.instant`   |
| CMP-159   | open / close; the list reorder; the reason re-shown | `normal` scale + fade; instant; instant | instant; identical; identical | `motion.duration.normal` → `.instant` |
| CMP-234   | entries appear; the focus move                      | instant                                 | identical                     | `motion.duration.instant`             |
| all three | state words, glyphs, counts                         | instant token swaps; no value flash     | identical                     | `motion.duration.instant`             |

### Table 5 — Live data

| Component      | Field                     | Politeness             | Cadence                                | Coalescing       | Notes                                                         |
| -------------- | ------------------------- | ---------------------- | -------------------------------------- | ---------------- | ------------------------------------------------------------- |
| CMP-156        | new firings               | polite                 | once per batch                         | the pill's count | rows insert on press only (D03-Q2 for the top-of-grid insert) |
| CMP-156        | a failed LIVE firing      | assertive, then polite | once, then "{rule}: {n} more failures" | per rule         | `05` §6.2; E35-D04 settles with `05`'s owner                  |
| CMP-156        | a filter result           | polite                 | once per change                        | —                | "Showing {n} of {m} firings, filtered by: …"                  |
| CMP-159        | Apply's outcome / refusal | polite / assertive     | once                                   | —                | "Order set — {A} then {B}." / the `409` / `412` sentence      |
| CMP-234        | the count                 | polite                 | once on completion                     | —                | "{n} files cannot be imported"                                |
| any T2 control | a T2 press                | polite                 | once per press                         | —                | E09-D09 §9.3                                                  |

### Density

| Component | Mode                  | Row / control height                                                                 | Padding tokens                            | Smallest target               |
| --------- | --------------------- | ------------------------------------------------------------------------------------ | ----------------------------------------- | ----------------------------- |
| CMP-156   | compact               | 24 px (`size.row.compact`)                                                           | `space.inset.sm`                          | 24 × ≥ 150 px (a row)         |
| CMP-156   | comfortable           | 32 px (`size.row.comfortable`)                                                       | `space.inset.md`                          | 32 × ≥ 150 px                 |
| CMP-159   | compact               | option rows 24 px control + the consequence line; table rows 24 px; the footer 48 px | `space.inset.md`; blocks `space.stack.md` | 24 × 24 px (a radio, the box) |
| CMP-159   | comfortable           | option rows 32 px + the line; table rows 32 px; the footer 56 px                     | `space.inset.md`                          | 32 × 32 px                    |
| CMP-234   | compact / comfortable | entries 24 / 32 px; the checkbox 24 × 24                                             | `space.inset.sm` / `.md`                  | 24 × 24 px                    |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all three | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — SCR-086, SCR-087 and the SCR-088 / SCR-089 deltas

- [x] Only published Tier-2 tokens; zero hard-coded hex / px in the spec (the px are anatomy derived from the tokens; the hexes in §13 are the tool's resolution of token names).
- [~] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §13); `forced-colors: active` is stated per surface (spec §10); the boards are drawn and exported (spec §0); the visual parity check on them is still owed with the a11y audit.
- [x] Passes the contrast matrix for every pair introduced or touched (40 gated rows, 0 FAIL; 17 PROPOSED `pairs.mjs` rows named; the rejected rows reported and never drawn).
- [x] CVD simulation reviewed — delivered for the three boards that carry the outcome and status colours (02, 04, 08): `docs/design/_tools/cvd_sim.py` greyscale and deuteranopia renders beside the PNGs, at the source dimensions, the greyscale true grey (R=G=B on every pixel): `docs/design/E35/img/E35-D03-02-scr-086-states-greyscale.png`, `docs/design/E35/img/E35-D03-02-scr-086-states-deuteranopia.png`, `docs/design/E35/img/E35-D03-04-scr-087-states-and-reasons-greyscale.png`, `docs/design/E35/img/E35-D03-04-scr-087-states-and-reasons-deuteranopia.png`, `docs/design/E35/img/E35-D03-08-scr-087-anatomy-light-greyscale.png`, `docs/design/E35/img/E35-D03-08-scr-087-anatomy-light-deuteranopia.png`; the other boards carry no status colour of their own; the greyscale argument is in spec §13 and board 08.
- [~] Every documented State has a Penpot variant and a story — the states are named (Table 1); the variants exist once drawn; the stories are E35-S06 / S07 / S09's.
- [x] Disabled states use the disabled-with-reason pattern (E09-D09 T2) for every RBAC- or state-gated action — the one rule in spec §1: Set priority / Disarm one on another owner's rule (every partner fill "a rule you can't see"), the Audit link without `audit:read` (one notice under the caption, many pointers), the Order link on an ungranted account (defensive; the dense-row rendering of spec §4), Apply while viewing as (one notice per frame; the radios, Move up / Move down and the box stage and stay live), the inspector's quarantined / engine-unavailable segments; form validity (Apply with nothing chosen or the box unticked; Import at 0) is `aria-disabled` with its reason and no lock (E30-D02 D3); the risk band's control, a Skip row's box and Download diff on a match are absences.
- [x] Loading / empty / error states designed: loading, empty (both forms), filtered-empty, error, refused, no-conflict, export-check-failed.
- [x] Keyboard-interaction table completed (spec §10; Table 2) — a design table, to be matched by the build's tested path.
- [x] Accessible-name / role table completed (spec §10; Table 3).
- [x] No canvas / WebGL-adjacent component: the history is a grid with its nested table; the tree is CMP-240.
- [x] Motion-safe / motion-reduce pair specified (spec §12; Table 4).
- [x] Hit targets ≥ 24 px in compact, ≥ 32 px in comfortable; no essential exception.
- [ ] Accessibility role sign-off — the owner's `approved` comment, pending; E35-D04 reviews.
- [x] Confirm-gate variant stated: Apply = one primary button (no typed word, no step-up — it writes a resolution and never arms); Disarm one → CMP-044 `standard` after Apply (CA-31); Import = one primary button; every arm stays SCR-085's with its `22` step-up on LIVE.
- [x] Every heuristic / estimated value is chip-tagged (CMP-227) — the Conditions cell and the nested table carry "(estimated)" inline when the metric is a heuristic.
- [x] Demo / Live context unambiguous: the chrome's band on every frame, the environment column's word + glyph, a LIVE firing only as a row; no LIVE arm path on any board.
- [x] Reuses existing `CMP-*` (CMP-001 / 005 / 006 / 015 / 019 / 026 / 027 / 028 / 033 / 036 / 043 / 044 / 046 / 047 / 049 / 055 / 067 / 074 / 079 / 093 / 144 / 155 / 156 / 159 / 227 / 234) and E13-D02's G-1 CMP-240; no new id requested.
- [~] Storybook stories match the Variants × States matrix — planned (Table 1); none exists yet.
- [~] Composes only published-library components — on the boards, once drawn.

## B. Accessibility acceptance criteria (`05` §10) — SCR-086, SCR-087, SCR-088, SCR-089

```gherkin
Feature: E35-D03 conflict resolver, fire history, IR inspector and import / export — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the user resolves a conflict in SCR-086, reads and expands a firing in SCR-087, reaches the
      masked account leaf in SCR-088's tree and skips a file in SCR-089 using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation (the resolver's radiogroups
      and Move up / Move down; the grid's one Tab stop with roving rows; the tree's arrow keys; the
      pre-check grid's checkbox cells and CMP-234's entries)
    And every action has a documented non-drag keyboard equivalent (Move up / Move down replace drag)
    And focus is never silently moved by the 250 ms rules frame, a new firing or a filter result
    And a visible focus indicator meeting >=3:1 contrast is present at every step (the double ring:
      color.focus.ring over a color.surface.canvas halo, >=5.39:1 on every surface it lands on)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the user reads row 1 of the fire history and expands it
    Then all labels, roles, and current values are announced correctly ("Fire history, newest first — 40
      firings", the row's cells in order, "Why it fired — ATR trail 2x, 09-03 11:20:12 UTC, table",
      "unrealised R multiple, 1.04, at least 1, true")
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding (the pill once per batch; a failed LIVE firing
      assertive once then coalesced)
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity (none: the history is a grid; the IR has its tree)

  Scenario: Colour-independence
    Given the feature displays buy/sell, bid/ask, P&L, or status state
    When the state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone (Done / Failed / Skipped
      by word + glyph; DEMO / LIVE by word + glyph; Accept / Skip by word + glyph; the T2 look by
      lock + label + reason; the verification strip by word + check glyph)
    And the feature passes deuteranopia/protanopia/tritanopia simulation review (planned on the exports)

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the
      high-contrast theme
    Then all text meets >=4.5:1 (or >=3:1 for large text) and all meaningful
      non-text UI/chart elements meet >=3:1, per the token contrast matrix (spec §13: 40 gated rows PASS)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the feature would normally animate
    Then the feature uses the motion-reduce variant with no flashing content
      exceeding 3 times per second and no motion lasting >5s without a pause
      control (the dialog opens instantly; rows append without a flash; the pill fades not at all)

  Scenario: T2 press
    Given a T2 control (Set priority or Disarm one on a rule the user may not change, the Audit link
      without audit:read, the Order link on an ungranted account, or any write while viewing as)
    When Enter, Space or an arrow lands on it
    Then nothing is sent or opened (no request, no state change)
    And the reason is re-shown inline at the point of action and announced once, politely

  Scenario: Automated gates
    Given the feature's PR is opened
    Then axe-core reports zero new serious/critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering this feature's primary
      task passes (E35-Q06)
```

Screen-reader spot test: manual spot-test deferred to E35-D04 / E35-Q06 — stated. Owner-approved exceptions: none.
