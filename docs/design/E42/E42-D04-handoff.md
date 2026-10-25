# E42-D04 — handoff checklists (SCR-135, SCR-136, SCR-145, SCR-148 and the admin motion spec; #887)

Per `docs/plan/16-design-system-brief.md` §11.4 and §13.3 item 8 (`02` §4.2): this SCR ticket changes six component
contracts (`docs/design/E42/E42-D04.md` §16, D04:739-753) — **CMP-173 AuditRow**, **CMP-174 AuditFilterBar**,
**CMP-179 FeatureFlagRow**, **CMP-095 FeatureFlagChip**, **CMP-099 PrintExportBar** and **CMP-053 Pagination** — so
each gets a block below; the components it only composes get one placement line each and link their own checklists.
**Shape:** E30-D03's (and E39-D02's): Tables 1–5, the Density table and the Essential-exceptions table appear once each
with a leading `Component` column instead of once per block. **This file decides nothing:** every row cites the spec
line that decides it. Prop and story names are Appendix A's text (D04:935-971), which lands in `15` in the boards PR;
they are PROPOSED until owner approval (D04:3-8).

**Key.** `D04:n` = a line of `docs/design/E42/E42-D04.md` at this branch; `D03` = `docs/design/E42/E42-D03.md`;
`D09` = `docs/design/E09/E09-D09.md`; `Y`, `W`, `M`, `svc/` and `tok` as D04's key (D04:10-17). `15` entries are
read at `origin/main` `43d1145e6`, where the six contracts above are still the text D04 quotes as "Old" (verbatim at
`b7154f951`). CMP-173's base is E42-D03's Appendix A text (merged as `58660d32f`), which reaches `15` with E42-D03's
boards PR (#886); until then `15`'s CMP-173 is the pre-D03 entry. **Merged contracts read, per the orchestrator's
2026-10-25 rulings for E42-D03:** CMP-044 is the entry #4414 merged (a natively disabled typed Confirm, `role?`), never
E42-D03's Appendix A rows; D04 composes no CMP-138.

## Handoff checklist — CMP-173 AuditRow (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0, D04:55-63): page `E42-D04`, its page id pinned in §0 once
      it exists (never a host, team, file id or URL); the row is drawn on boards 02 `scr135-populated`, 13
      `scr135-tamper-failed`, 67 `diff-sheet` (every value kind and the three record shapes, both forms) and 69
      `redlines`, its integrity line on 34 `scr136-after-break`; PNGs `docs/design/E42/img/E42-D04-NN-<slug>.png`;
      board 68 `component-sheet` is not drawn — the text binds (D04:74, :79)
- [ ] **Variants × States matrix** — PENDING with the boards: the 15 stories of Appendix A (D04:948), each mapped to
      its §4–§6 state in Table 1
- [x] **Keyboard table** — Table 2: the row lives in CMP-049's APG grid (one tab stop, roving `tabindex`; ↑ ↓ rows,
      ← → cells, Home / End, PgUp / PgDn); Space expands, Enter opens SCR-136; the diff row's Copy and disclosure
      buttons are cells; every acting key acts once per press and ignores `event.repeat` (D04:238, :266-269, :601);
      no key binding is added (D02 D17, D04:102)
- [x] **Accessible name / role table** — Table 3: the expander a button with `aria-expanded` and `aria-controls`; the
      expanded diff a `<dl>` per changed field with visible Before / After (Requested for a refused or intent record);
      severity and outcome words, the glyph `aria-hidden`; a selected row `aria-selected="true"` with the `check`
      glyph (D04:149, :335-340, :945)
- [x] **Live data** — Table 5: a row announces nothing; new entries come from page 1's 30 s re-read as a pill, never
      spliced, announced once by the page's polite region (D5, §12; D04:140, :594)
- [x] **Motion pair** — Table 4: expansion is a cut in both modes, heights never animate (M4, D04:631; S-5,
      D04:657); severity and outcome words flip in one frame (M9, D04:636)
- [ ] N/A — **Density notes**: D04 binds the admin rows at `size.control.comfortable` (D04:696) with a 24 px expander
      column at 1280 (D04:211) and names no compact values; board 69 `redlines` measures the drawn density (D04:74);
      Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D04:946) over D03's: `type.num.sm`, `color.text.{primary,secondary,tertiary}`,
      `color.status.danger.strong` (the octagon and the `border.thick` high rule), `color.status.warning.strong`
      (the triangle), `font.weight.semibold`; the selected row `color.surface.selected` with the `check` in
      `color.text.primary` and its meta in `color.text.secondary` (D14, D04:149, :714); none invented, stand-ins as
      §15 (D04:696-702); Penpot token sets = `packages/ui/tokens` at `b7154f95153d5357b5c50cc91c5f43000de64335`
      (unchanged at `origin/main` `43d1145e6`)
- [x] **Data contract confirmed** — `AuditEntry` (Y:20056-20136) from `GET /admin/audit` (`audit:read`, executed,
      M:22-27); `detail.before`, `detail.after`, `detail.elided` (Y:20114-20130), read with `outcome` and the record's
      shape (state, request or result, §6, D04:331-366); the Manager projection (Y:20061-20065); the redaction markers
      (svc/audit/redact.py:38-39, :147); gaps named: CG-1, CG-8, CG-29, CG-30, CG-33 (D04:861-893)
- [ ] **Contrast and CVD** — PENDING: every pair is §15's (D04:686-737), re-run by
      `docs/design/_tools/e42_d04_admin_audit.py` in this PR; registering the gated pairs in
      `tools/contrast/pairs.mjs` is a `tools/` change outside a design PR, routed as E16-D02 and E39-D02 route theirs;
      the greyscale and deuteranopia renders of the ★ boards ship with the boards (D04:61-63)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887), with the blocking security review (D04:6-8)

## Handoff checklist — CMP-174 AuditFilterBar (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D04`; the bar is drawn on board 02
      `scr135-populated` and redlined on 69; its Applied, OwnView, Invalid and RateLimited states are boards 06, 25,
      17 and 16, not drawn — the text binds (D04:69, :79)
- [ ] **Variants × States matrix** — PENDING with the boards: the six stories of Appendix A (D04:954); Table 1
- [x] **Keyboard table** — Table 2: the controls in reading order after the incident banner and before the pill
      (D04:266-267); a `422` moves focus to the first field in error (D04:252); a T2 field or picker is also
      read-only, so typing, arrows and paste change nothing, and Enter or Space re-shows its reason (D04:607, :952)
- [x] **Accessible name / role table** — Table 3: `<form role="search" aria-label="Filter the audit log">`; a visible
      label on every control; From and To say UTC; errors by `aria-describedby` (D04:952)
- [x] **Live data** — Table 5: the rows-shown count after the Environment facet, polite once, never a total (AL-6,
      D04:241, :594); a field's `422` announces nothing (D04:596)
- [x] **Motion pair** — Table 4: filter → results is a one-frame swap, `audit.slow` at 400 ms (M17, D04:644)
- [ ] N/A — **Density notes**: as CMP-173's line (D04:696); D04 names no compact values; at 200 % the bar wraps into
      a "Filters" disclosure (AL-28, D04:263)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D04:953): CMP-055's, `space.field.gap`, `color.text.secondary`,
      `color.text.tertiary`, `color.surface.raised` with a `color.border.default` hairline (a T2 control),
      `color.text.primary` with the `color.status.danger.strong` octagon (errors); Penpot token sets as CMP-173's line
- [x] **Data contract confirmed** — `queryAuditLog`'s parameters (Y:9509-9565): `from` inclusive, `to` exclusive,
      `actor_user_id`, `action` (≤ 50 codes), `subject_type`, `subject_id`, `outcome`, one `severity`, `ip` and `q`
      Owner only; Environment filters the loaded rows (D7, D04:142, :227-232); gaps named: CG-2, CG-3 (D04:862-863)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line; the T2 pairs are §15's T2 rows (D04:723-724)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887)

## Handoff checklist — CMP-179 FeatureFlagRow (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D04`; the row is drawn on board 41
      `scr145-live-blocked` (the Gated row, for the security reviewer); FF-2's populated page (board 39), FF-12's
      fail-closed page (board 49) and the rest are not drawn — the text binds (D04:71, :79)
- [ ] **Variants × States matrix** — PENDING with the boards: the 16 stories of Appendix A (D04:959); Saving, Refused
      and OutcomeUnknown render in the rung dialog with the row unchanged (D04:745, :956); Table 1
- [x] **Keyboard table** — Table 2: per row Change… → History (→ Revert); the live row Change… → Security centre →
      History; `maintenance.mode` → Maintenance → History; a T2 control keeps its stop, and Enter or Space re-shows
      its reason, polite once, and sends nothing (D04:493-494, :502, :517-518); Change… acts once per press (D04:601)
- [x] **Accessible name / role table** — Table 3: a CMP-049 table row, one table per `h2` group captioned by it, not
      an arrow grid (FF-2, D04:500); the Change button named by description, key and deployment value, never
      "on/off"; a blocked control `aria-disabled="true"`, its reason by `aria-describedby` at mount, a visible link
      (D19, D20; D04:154-155, :490-495, :957)
- [x] **Live data** — Table 5: a push from another session swaps the row in one frame, and an open dialog keeps its
      draft and meets `409` on confirm (D04:518-519); `flags.applied` polite once on the answer (FF-7, D04:505);
      `fail_closed` assertive once through the shell's region (FF-12, D04:510, :592)
- [x] **Motion pair** — Table 4: a flag's value flips in one frame on the server's answer, never animated (M9,
      D04:636; S-2, S-4, D04:653-656); "Saving…" is M14's in-flight spinner in the dialog (D04:641)
- [ ] N/A — **Density notes**: as CMP-173's line (`size.control.comfortable`, D04:958); at 200 % rows reflow to
      stacked cards (FF-15, D04:513)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D04:958): `color.surface.raised`, `color.text.{primary,secondary,tertiary}`,
      `color.border.default`, `color.status.warning.subtle` and `.strong` (fail-closed and unreadable
      notes; the "Affects …" marks as a CMP-011 Tag with the triangle), `color.status.info.subtle` and `.strong`
      ("Requires reload"), `type.num.sm` (the key), `size.control.comfortable`; CMP-004's tokens dropped with the
      toggle (D19); Penpot token sets as CMP-173's line
- [x] **Data contract confirmed** — `GET /admin/feature-flags` → `{resolution, items: FeatureFlag[]}`
      (Y:10398-10409, :20163-20210); `PUT /admin/feature-flags/{flagKey}` with `value`, `reason`,
      `expected_updated_at` (Y:10478-10480, :20211-20253); the row shows `default_value` and, when it differs, the
      caller's `value` (D19, Y:20169-20175); WS `feature_flags` carries the changed key only (W:4270-4279); gaps named:
      CG-15, CG-16, CG-19, CG-28, CG-35 (D04:875-879, :888, :895)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line; board 41 carries the ★ renders (D04:71)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887), with the blocking security review of the live row (D20, Q1;
      D04:155, :171)

## Handoff checklist — CMP-095 FeatureFlagChip (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: the chip is not drawn on SCR-145 (D04:746, :960); its variants are board 68
      `component-sheet`, not drawn — the text binds (D04:74)
- [ ] N/A — **Variants × States matrix**: one story, Default, kept (D04:746); the change is its visible text and
      tokens, not a new state
- [x] **Keyboard table** — Table 2: static text, no Tab stop of its own (D04:961)
- [x] **Accessible name / role table** — Table 3: visible text "Flag: {flagKey}", also its accessible name; never
      colour or an icon alone (D04:961)
- [ ] N/A — **Live data**: static chrome
- [x] **Motion pair** — Table 4: none animated
- [ ] N/A — **Density notes**: an inline atom with no target of its own
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.status.info.subtle` (fill), `color.status.info.strong` (glyph), `color.text.primary`
      (text) until `color.chip.dev` exists (D02 DS-4; D04:698, :962; CG-24, D04:884); Penpot token sets as CMP-173's
      line
- [ ] N/A — **Data contract confirmed**: pure chrome (`flagKey`, a registry key)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line; Tests add axe (D04:963)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887)

## Handoff checklist — CMP-099 PrintExportBar (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: the contract changes its purpose only — not used for the audit log (Q9 default
      (b), D04:179, :747, :964); SCR-135 composes CMP-001, CMP-093 and CMP-023 instead (§8, D04:420-425)
- [ ] N/A — **Variants × States matrix**: Default and Exporting are unchanged
- [ ] N/A — **Keyboard table**: unchanged
- [ ] N/A — **Accessible name / role table**: unchanged
- [ ] N/A — **Live data**: unchanged
- [ ] N/A — **Motion pair**: unchanged
- [ ] N/A — **Density notes**: unchanged
- [x] **Essential-exceptions log** — none
- [ ] N/A — **Tokens used**: unchanged (CMP-001's)
- [x] **Data contract confirmed** — the audit export it does not carry: `POST /admin/audit/export` → `202 {job_id}`
      → `GET /admin/jobs/{jobId}` → download, one signed NDJSON window (Y:9788-9920; §8, D04:418-454)
- [ ] N/A — **Contrast and CVD**: no pair introduced
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887; Q9, owner #2701)

## Handoff checklist — CMP-053 Pagination (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D04`; the cursor pager is drawn on board 02
      (page 1: Newest and Newer T2 `admin.newest`) and redlined on 69; AL-9's end (board 09) and AL-16's RateLimited
      (board 16) are not drawn — the text binds (D04:69, :237, :244, :251)
- [ ] **Variants × States matrix** — PENDING with the boards: Default, CursorMode, CursorKeyset, RateLimited
      (D04:967); Table 1
- [x] **Keyboard table** — Table 2: [Newest] [Newer] [Older] after the grid, before Run tamper check; once a press
      has loaded its page, focus moves to the page's first row; a failed or refused read keeps focus on the button and
      the cursors; after `400 invalid_cursor` Newer and Older stay enabled (D04:266-275); a T2 button keeps its stop
      and re-shows its reason (D04:607)
- [x] **Accessible name / role table** — Table 3: `nav aria-label="Pagination"`; in cursor mode no `aria-current`;
      no page number or total (D4, D04:139, :966)
- [x] **Live data** — Table 5: `audit.end` polite once at `has_more: false` (AL-9, D04:244); the count is the rows
      shown, never a total (D04:594)
- [x] **Motion pair** — Table 4: a page change is a one-frame swap; the newest page lands in one frame and the scroll
      jumps, never smoothly (M16, M17; D04:643-644)
- [ ] N/A — **Density notes**: as CMP-173's line (D04:696)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.action.*` (unchanged, `15`), plus the T2 look: `color.surface.raised`,
      `color.border.default`, `color.text.tertiary` (label and `lock`), `color.text.secondary` (reason) (§12.1,
      D04:607); Penpot token sets as CMP-173's line
- [x] **Data contract confirmed** — keyset paging: `limit=200` inside 1–500, the cursors and `has_more`
      (Y:9455-9459, :15575-15583; D4, D04:139); a malformed cursor → `400 invalid_cursor` (Y:9512-9516; AL-17,
      D04:252)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line (the T2 rows, D04:723)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887)

**Placement lines (contract unchanged here; their own checklists apply).** CMP-049 Table — SCR-135's APG grid
(`role="grid"`, one tab stop, roving `tabindex`, `aria-rowindex` when virtualised), caption `audit.caption`, Time the
only `aria-sort="descending"` header, not operable (D6; D04:141, :195, :266-268); SCR-145's one table per group,
captioned by its `h2`, not an arrow grid (D04:500). CMP-046 Drawer — SCR-136 `modal: false`, a `role="dialog"` without
`aria-modal`; focus to its `h2` in frame 0, Esc or Close back to the row, `Ctrl+\` still reaches CMP-211; 480 px over
the grid at 1280, docked at 640 px at 2560 (D1, D14; D04:136, :149, :322-325; M1, M2, D04:628-629). CMP-044
ConfirmDialog (the entry #4414 merged) on CMP-043 `size` Large — every rung and export dialog: `role="alertdialog"`
(its `role?`), described by the whole body and the marker, Cancel focused first, the confirm ignoring `event.repeat`,
`busy?` while a write is in flight (MM-3, FF-7); no typed variant, as maintenance has no server-checked token (D02 D15;
D04:101, :567-586). CMP-079 RbacGate + CMP-019 Icon `lock` (`decorative=false`, "Not available") — every T2 control
(§12.1, D04:603-608); one reason shared by a region's controls is CMP-079's `notice` form, one node each points at
(D23, AL-16, AD-7, MM-1; D04:608). CMP-028 Callout / Banner — the integrity incident (danger, non-dismissible,
`role="alert"` on the episode's first mount only, then static; §7, D11; D04:146, :383, :410-412), `flags.fail_closed`
(FF-12) and the maintenance banners in the shell-band slot, their voice the shell's one region (D26; D04:161, :592).
CMP-027 ErrorState — AL-15, FF-17 and MM-11 in its error look with the octagon and `role="status"` (D04:250, :515,
:558, :751-753). CMP-023 Progress Bar — the export line, `aria-live` off, "{n} %" polite at 25 % steps (D04:448-449).
CMP-001 Button `loading` — the busy Signed export… and a rung-2 confirm while its count loads (§8, D22; D04:157,
:420-425). CMP-033 CopyButton — "Copied" for 2 s, polite once (AD-2, D04:314). CMP-068 CopyableCodeBlock — SCR-136's raw
record, a focusable scroll region named "Raw record", withheld when §6's name rule flags the record (AD-2, AD-3;
D04:314-315). CMP-093 AuditActionTrigger — the marker lines, which rejoin a control's description only while it is
enabled (D8, §12.1; D04:143, :608). CMP-015 Skeleton (AL-1, FF-1, MM-10), CMP-026 EmptyState (AL-7), CMP-054 SearchBox
(FF-3, `flags.search`), CMP-047 DatePicker (the export window, MM-1's field), CMP-065 FormSection (MM-1) — as §4, §8,
§9 and §10 place them. CMP-138 RiskCapMeter — not composed by D04.

### Table 1 — Variants × States (stories from Appendix A; boards PENDING)

| Component | Story              | D04 state (cite)                                                              | Board (drawn ★ = one of §0's ten) | Notes                                             |
| --------- | ------------------ | ----------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------- |
| CMP-173   | Default            | AL-2 populated, page checked (D04:237)                                        | 02 ★                              | D03's story                                       |
| CMP-173   | ExpandedDiff       | AL-3 row expanded, §6's full form (D04:238, :339-340)                         | 03 (not drawn); 67 ★ sheet        | D03's story; `<dl>`, never a code block (D04:945) |
| CMP-173   | SystemActor        | AL-5 `system:maintenance` (D04:240)                                           | 05 (not drawn)                    | D03's story                                       |
| CMP-173   | Compact            | SCR-122's change summary; FF-14's history rows (D04:333-334, :512)            | 51 (not drawn)                    | D03's story; the inline form (§6)                 |
| CMP-173   | CompactDenied      | a refused record in the request shape, inline (D04:354, :512)                 | 51 (not drawn)                    | D03's story                                       |
| CMP-173   | CompactElided      | a withheld state, inline (D04:345-346, :365)                                  | —                                 | D03's story                                       |
| CMP-173   | HighSeverity       | error and critical: octagon, semibold, the `border.thick` rule (D2, D04:137)  | 02 ★, 13 ★                        | greyscale render on 02 (D04:914)                  |
| CMP-173   | ExpandedNested     | a nested path, "overrides › 9f1c…" (D04:347)                                  | 67 ★                              | lists compare as whole values                     |
| CMP-173   | ExpandedSecret     | AL-4: `secret`, `secret_named`, `credential` (D04:239, :359-361)              | 04 (not drawn); 32 ★, 67 ★        | security reviewer (D04:823)                       |
| CMP-173   | ExpandedWithheld   | `withheld` beside a served `after` (D04:345-346, :365)                        | 67 ★                              | `diff.withheld` once under Before                 |
| CMP-173   | ExpandedRequested  | the request shape: Requested, never After (D04:354)                           | 67 ★                              | `diff.head_failed`, `diff.head_intent`            |
| CMP-173   | WriteAhead         | "Started" / "Intent", never "Success" (D3, D04:138)                           | 02 ★                              | `audit.result_started`, `audit.result_intent`     |
| CMP-173   | OwnProjection      | AL-25 "My activity" (D04:260)                                                 | 25 (not drawn)                    | `rec.hidden` in the projected cells               |
| CMP-173   | DeletedActor       | `deleted-user-3f9a…`, no link, a labelled target (CG-33; D04:240)             | 05 (not drawn)                    | the grid cuts it to 4 hex and "…" (D04:678)       |
| CMP-173   | AfterBreak         | at or after `first_bad_id`, expanded row and SCR-136 only (D04:317, :944)     | 34 ★                              | never the collapsed row                           |
| CMP-174   | Default            | AL-2 (D04:237)                                                                | 02 ★                              | —                                                 |
| CMP-174   | Applied            | AL-6 filtered, the applied set as text (D04:241)                              | 06 (not drawn)                    | URL state (D04:231-232)                           |
| CMP-174   | OwnView            | AL-25: Actor fixed, IP, Search, Environment T2 `rbac.owner_only` (D04:260)    | 25 (not drawn)                    | `view: "own"`                                     |
| CMP-174   | Invalid            | AL-17 `422`: `audit.err_range`, `audit.err_ip` (D04:252)                      | 17 (not drawn)                    | focus carries it                                  |
| CMP-174   | EnvironmentFacet   | D7: "LIVE (this page only)" (D04:142, :241)                                   | 06 (not drawn)                    | no read sent; cursor kept                         |
| CMP-174   | RateLimited        | AL-16: every control T2 `admin.rate_limited` (D04:251)                        | 16 (not drawn)                    | `blockedReason`                                   |
| CMP-179   | Default            | FF-2, an ordinary row (D04:500)                                               | 39 (not drawn)                    | —                                                 |
| CMP-179   | SafetyFlag         | the safety group, "overrides ignored" (D04:471, :480)                         | 39 (not drawn)                    | rung 2 / rung 4 (§11)                             |
| CMP-179   | Gated              | FF-4 `trading.live_enabled`, T2 `admin.live_gate` + Security centre (D04:502) | 41 ★                              | security reviewer (D04:823)                       |
| CMP-179   | AffectsOrderEntry  | `trading.one_click`, `algo.*` (D18, D04:153, :482-483)                        | 39 (not drawn)                    | Q6                                                |
| CMP-179   | AffectsDesktop     | `desktop.backend_connection`, `flags.affects_desktop` (D04:482)               | 39 (not drawn)                    | `dlg.flag.desktop` in its dialog                  |
| CMP-179   | Overrides          | "+ 1 user override" (FF-2, D04:500)                                           | 39 (not drawn)                    | `flags.scope`                                     |
| CMP-179   | OwnerOverride      | "You: ON — your override" (D19, D04:154, :500)                                | 39 (not drawn)                    | `flags.your_override`                             |
| CMP-179   | YourResolved       | "You: ON — resolved for you" (D19; FF-2's inset, D04:500)                     | 39 (not drawn)                    | `flags.your_resolved`                             |
| CMP-179   | Unreadable         | FF-12 `unreadable: true`, Change kept as the repair (D04:510)                 | 49 (not drawn)                    | `flags.unreadable`                                |
| CMP-179   | FailClosed         | FF-12 `fail_closed`: `flags.fail_closed_value`, T2 `admin.flags_store` (D23)  | 49 (not drawn)                    | no "Changed … by …" line                          |
| CMP-179   | RequiresReload     | D24: a labelled target with [Reload now] on `engine.webgl_v2` (D04:159)       | 39 (not drawn)                    | CG-16                                             |
| CMP-179   | MaintenanceLink    | "→ Maintenance" in place of Change… on `maintenance.mode` (D04:474, :480)     | 39 (not drawn)                    | `changeHref`                                      |
| CMP-179   | Revert             | [Revert to OFF] after a change this session (FF-7, D04:505)                   | 44 (not drawn)                    | the write's rung (§11)                            |
| CMP-179   | Saving             | FF-7 "Saving…" in the dialog (D04:505)                                        | 44 (not drawn)                    | the row unchanged                                 |
| CMP-179   | Refused            | FF-10, FF-11 in the dialog (D04:508-509)                                      | 47, 48 (not drawn)                | the row unchanged                                 |
| CMP-179   | OutcomeUnknown     | FF-13 `flags.store_down`, `flags.checking` (D04:511)                          | 50 (not drawn)                    | never "Nothing was changed."                      |
| CMP-095   | Default            | visible "Flag: {flagKey}" (D04:961)                                           | 68 (not drawn)                    | not on SCR-145                                    |
| CMP-099   | Default, Exporting | unchanged; not used for the audit log (D04:964)                               | —                                 | —                                                 |
| CMP-053   | Default            | unchanged                                                                     | —                                 | —                                                 |
| CMP-053   | CursorMode         | unchanged (`15`)                                                              | —                                 | —                                                 |
| CMP-053   | CursorKeyset       | AL-2 page 1, AL-9 `has_more: false`: Newest, Newer, Older (D04:237, :244)     | 02 ★; 09 (not drawn)              | `admin.newest`, `admin.oldest`                    |
| CMP-053   | RateLimited        | AL-16: every button T2 `admin.rate_limited` (D04:251)                         | 16 (not drawn)                    | the pager points at AL-16's one notice            |

### Table 2 — Keyboard

| Component | Key                                     | Action                                                                                                               | Focus after                                                            | Global conflict?               | Cite                    |
| --------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------ | ----------------------- |
| CMP-173   | ↑ ↓ · ← → · Home / End · PgUp / PgDn    | the APG grid: rows, cells (the diff row's Copy and disclosure are cells); arrows may repeat                          | the row or cell                                                        | none                           | D04:238, :267-269, :601 |
| CMP-173   | Space                                   | expands or collapses the row (`aria-expanded`); once per press                                                       | stays on the row                                                       | none                           | D04:238, :269, :601     |
| CMP-173   | Enter                                   | opens SCR-136; while it is open, ↑ ↓ in the grid keep the drawer on the selected row; once per press                 | the drawer's `h2`                                                      | none                           | D14; D04:149, :269      |
| CMP-173   | Esc (in SCR-136)                        | closes the drawer                                                                                                    | the row                                                                | none (Esc is the drawer's own) | D04:323-324             |
| CMP-174   | Tab / Shift+Tab                         | the filters in reading order, between the incident banner and the pill                                               | the next control                                                       | none                           | D04:266-267             |
| CMP-174   | typing, arrows, paste on a T2 field     | change nothing (`readonly`, `aria-readonly` on a picker)                                                             | unchanged                                                              | none                           | D04:607, :952           |
| CMP-174   | Enter / Space on a T2 control           | stages and sends nothing; the reason is re-shown inline, polite once                                                 | unchanged                                                              | none                           | D04:595, :607           |
| CMP-174   | [Clear filters] (AL-7, AL-26)           | clears the set and reads page 1                                                                                      | page 1's first row, once loaded                                        | none                           | D04:242, :274-275       |
| CMP-179   | Tab / Shift+Tab                         | Change… → History (→ Revert); live row Change… → Security centre → History; `maintenance.mode` Maintenance → History | the next control                                                       | none                           | D04:502, :517-518       |
| CMP-179   | Enter / Space on Change…                | opens the rung dialog (Cancel focused); once per press                                                               | Cancel in the dialog; on close, back to Change…                        | none                           | D04:600-601             |
| CMP-179   | Enter / Space on the live row's Change… | sends nothing; `admin.live_gate` re-shown inline beside the Security centre link, polite once per press              | unchanged                                                              | none                           | FF-4; D04:494, :502     |
| CMP-053   | Enter / Space on Newest / Newer / Older | loads that page; once per press                                                                                      | the page's first row once loaded; a failed read keeps it on the button | none                           | D04:270-273             |
| CMP-053   | Enter / Space on a T2 button            | loads nothing; re-shows its reason (`admin.newest`, `admin.oldest`, `admin.rate_limited`)                            | unchanged                                                              | none                           | D04:275, :607           |
| CMP-095   | —                                       | static text, no stop                                                                                                 | —                                                                      | none                           | D04:961                 |

### Table 3 — Accessible name / role

| Component | Element              | Role                                    | Accessible name (source)                                                                | States / properties                                                                                                                                     |
| --------- | -------------------- | --------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-173   | the row              | `row` in CMP-049's `grid` (`gridcell`s) | its cells' words (time, actor, action label, target, environment, IP, severity, result) | `aria-rowindex` when virtualised; `aria-selected="true"` and the `check` glyph (`aria-hidden`) on the selected row (D14, D04:149)                       |
| CMP-173   | the expander         | `button`                                | the row it expands                                                                      | `aria-expanded`, `aria-controls` (D04:945)                                                                                                              |
| CMP-173   | the expanded diff    | `dl` per changed field, a nested `dl`   | the field path; the terms Before / After, or Requested (D04:338-340, :354)              | the status word (Added, Removed, Changed) as text, never colour or strike-through (D04:341-342); the arrow `aria-hidden`, read "changed from OFF to ON" |
| CMP-173   | severity, outcome    | text                                    | the enum's word; "Started" / "Intent" on a write-ahead record (D2, D3)                  | the octagon or triangle `aria-hidden`; high rows add the rule and the weight (D04:137-138, :945)                                                        |
| CMP-173   | a secret-kind value  | text                                    | "Secret — never recorded" and its siblings (§6, D04:359-361)                            | the `lock` glyph decorative (D04:607); nothing hashed client-side (D16)                                                                                 |
| CMP-174   | the bar              | `search` (`form`)                       | "Filter the audit log"                                                                  | errors by `aria-describedby` (D04:952)                                                                                                                  |
| CMP-174   | a T2 field or picker | its native role                         | its visible label, the `lock` ("Not available") leading it                              | `aria-disabled="true"`, `readonly` / `aria-readonly`, `aria-describedby` → the reason or the one notice (D04:607-608, :952)                             |
| CMP-179   | the row              | `row` in a CMP-049 `table`              | its cells' words                                                                        | one table per group, captioned by its `h2` (FF-2, D04:500)                                                                                              |
| CMP-179   | Change…              | `button`                                | the description, the key and the deployment value ("… deployment OFF"), never "on/off"  | blocked: `aria-disabled="true"`, never `disabled`, `aria-describedby` → the reason at mount, a visible link (D04:154-155, :492-494, :957)               |
| CMP-179   | values               | text                                    | `flags.deployment`, `flags.your_*`, `flags.fail_closed_value`                           | they change only on the server's answer (D19, D04:154)                                                                                                  |
| CMP-053   | the pager            | `navigation`                            | "Pagination"                                                                            | cursor mode: no `aria-current`; a T2 button `aria-disabled`, its `lock` leading the label, `aria-describedby` → its reason (D04:966)                    |
| CMP-095   | the chip             | text                                    | "Flag: {flagKey}" (visible)                                                             | never colour or an icon alone (D04:961)                                                                                                                 |

### Table 4 — Motion pair

| Component | Property                                    | motion-safe                                                      | motion-reduce                           | Duration / easing tokens | Cite                   |
| --------- | ------------------------------------------- | ---------------------------------------------------------------- | --------------------------------------- | ------------------------ | ---------------------- |
| CMP-173   | row expansion; the diff's disclosures       | a cut; heights never animate                                     | the same                                | none                     | M4, S-5; D04:631, :657 |
| CMP-173   | severity, outcome, the integrity line       | one frame, words first, on the server's answer                   | the same                                | none                     | M9, S-2; D04:636, :653 |
| CMP-174   | filter → results                            | a one-frame swap; `audit.slow` at 400 ms                         | the same                                | none                     | M17; D04:644           |
| CMP-179   | a flag's value; a push from another session | one frame on the answer; no colour tween, no cross-fade ON / OFF | the same                                | none                     | M9, S-4; D04:636, :656 |
| CMP-179   | "Saving…" (in the dialog)                   | CMP-001 `loading`, 800 ms period (PROPOSED), slow line at 5 s    | a static glyph with the in-flight label | none                     | M14; D04:641           |
| CMP-053   | a page change; the newest page              | one frame; the scroll jumps, never smoothly                      | the same                                | none                     | M16, M17; D04:643-644  |
| CMP-095   | —                                           | none animated                                                    | none animated                           | —                        | —                      |

### Table 5 — Live data

| Component | Field                                | Politeness                                                    | Cadence                                           | Coalescing                                                        | Cite                |
| --------- | ------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- | ------------------- |
| CMP-173   | rows                                 | none                                                          | a page read; page 1 re-read every 30 s (PROPOSED) | never spliced: the pill counts newer rows                         | D5; D04:140         |
| CMP-173   | the new-entries pill (`audit.new_n`) | polite once when it appears; `audit.new_loaded` once on press | per re-read                                       | "200+" at the cap; the viewer's own `admin.area_entered` left out | AL-8; D04:243, :594 |
| CMP-174   | the count (`audit.count`)            | polite once                                                   | per applied filter                                | the rows shown, never a total                                     | AL-6; D04:241, :594 |
| CMP-179   | a row's values                       | none (a push swaps the row in one frame)                      | on a `feature_flags` frame (≤ 2 s)                | the changed key only                                              | D04:461, :518       |
| CMP-179   | `flags.applied`                      | polite once, on the answer                                    | per write                                         | —                                                                 | FF-7; D04:505       |
| CMP-179   | `flags.count`                        | polite once the input settles                                 | never per keystroke                               | —                                                                 | FF-3; D04:501       |
| CMP-053   | `audit.end`                          | polite once                                                   | at `has_more: false`                              | —                                                                 | AL-9; D04:244       |

### Density

| Component         | Mode                | Row / control height                            | Padding tokens                                         | Smallest target                                 |
| ----------------- | ------------------- | ----------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| CMP-173, 174, 179 | comfortable (admin) | `size.control.comfortable` (D04:696, :958)      | `space.inset.{lg,xl}`, `space.stack.{sm,md}` (D04:696) | the expander cell, 24 px wide at 1280 (D04:211) |
| CMP-053           | comfortable (admin) | `size.control.comfortable`                      | —                                                      | a pager button                                  |
| all six           | compact             | not specified by D04 (open point for the owner) | —                                                      | —                                               |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all six   | none      | —                    | —        | —    |

## §A — Design QA checklist (`16` §12), filled

- [x] Only published Tier-2 / Tier-3 tokens; the missing ones take named stand-ins, never invented (§15, D04:692-702;
      CG-24, D04:884).
- [ ] Three themes × two densities verified visually — PENDING with the boards: dark draws every drawn board; light
      and high contrast are proven by §15's computed matrix and board 66's columns (deviation 4, Q14; D04:32-33,
      :80-81); compact is not specified (Density table).
- [ ] Contrast matrix for every pair introduced — PENDING: §15 (D04:704-725), re-run by
      `docs/design/_tools/e42_d04_admin_audit.py`; the `tools/contrast/pairs.mjs` registration is routed (blocks above).
- [ ] CVD simulation for every new colour-carrying state — PENDING: §15's colour-vision table (D04:727-733); the
      greyscale and deuteranopia renders of the ★ boards (D04:61-63).
- [ ] Every State has a Penpot variant and a Storybook story — PENDING: Table 1 maps every story to its state; ten
      boards are drawn and the rest bind as text (§0, D04:79); the stories are E42-S04's and E42-S05's (D04:902-903).
- [x] Disabled states use disabled-with-reason (§12.1 T2: CMP-079, the CMP-019 `lock`, `aria-disabled`, the reason in
      the DOM at mount; never `color.text.disabled` or `opacity.disabled`; D04:603-608); busy is never T2 (D22, §8;
      D04:157, :422-423).
- [x] Loading, empty and error states designed: AL-1, AL-7, AL-15, AL-26, FF-1, FF-17, MM-10, MM-11 (D04:236-261,
      :499, :515, :557-558).
- [x] Keyboard table completed (Table 2; §4, §5, §9, §10 Keys, §12).
- [x] Accessible-name / role table completed (Table 3).
- [x] No canvas-adjacent component.
- [x] Motion-safe / motion-reduce pair specified (Table 4; §13, D04:610-669).
- [ ] Hit targets — PENDING: D04 binds `size.control.comfortable` and the 24 px expander column (D04:211, :696);
      board 69 `redlines` measures them (D04:74); no essential exception.
- [ ] Accessibility role sign-off — owner `approved` on #887 (agent-delivery adaptations); E42-D06 reviews §12, §13,
      §15 and this file (D04:901).
- [x] Confirm-gate variant stated: rungs 1, 2 and 4, `standard`, no typed confirmation (D02 D15; §11, D04:579-586).
- [ ] N/A — estimated values chip-tagged: the admin screens show no estimate.
- [x] Demo / Live context unambiguous: the environment column and the ENV badge above every scrim and dialog (§11,
      D04:570-573; C-2.11, D04:821-822).
- [x] Reuses existing CMP ids; the diff is CMP-173's part, not a new CMP-240 (D15, Q10; D04:150, :180).
- [ ] Storybook stories match the matrix — PENDING: the implementing tickets' (E42-S04, E42-S05).
- [ ] Composes only published-library components in Penpot — PENDING with the boards.

## §B — Accessibility acceptance criteria (`05` §10), filled per screen

| Screen  | Primary task (keyboard-only, screen-reader)                               | Keyboard-only                                                                                                                                                      | Screen reader                                                                                                                                                        | Colour-independence                                                                                 | Contrast          | Reduced motion                                      | Automated gates                    |
| ------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------- | ---------------------------------- |
| SCR-135 | find a high-severity record, read its diff, and see whether the log holds | Signed export → export line → incident banner → filters → pill → the grid (one stop) → paging → Run tamper check; Space expands, Enter opens SCR-136 (D04:266-275) | the incident's `role="alert"` once per episode; counts, new entries and check results polite once through one page region (§12, D04:592-594); words for every status | severity and outcome as words, glyphs and the high rule (D2; D04:735-737); forced colours (D04:733) | §15 (D04:704-725) | expansion a cut; statuses one frame (M4, M9)        | axe 0 serious / critical — E42-S04 |
| SCR-136 | step through records and copy a hash                                      | heading in frame 0 → Previous → Next → Close → copies and links → Show raw record → the raw `<pre>`; Esc back to the row; `Ctrl+\` reaches CMP-211 (D04:322-325)   | the heading on focus; "Copied" polite once; a withheld raw record is a notice, not T2 (AD-3, D04:315)                                                                | the integrity line's words (AD-5); the selected row's `check` (D14)                                 | §15's drawer rows | the drawer instant under reduce (M1, M2)            | axe 0 serious / critical — E42-S04 |
| SCR-145 | change an ordinary flag, and find that live trading cannot be set here    | search → clear → per group Change… → History (→ Revert); the live row's T2 Change… re-shows its reason (D04:517-518)                                               | the dialog's description once; `flags.applied` polite once; `fail_closed` assertive once; a T2 press polite once (§12)                                               | values as ON / OFF words; notes as tags with the triangle (D04:958)                                 | §15's T2 rows     | values flip in one frame (M9); "Saving…" M14's twin | axe 0; keyboard E2E — E42-S05      |
| SCR-148 | turn maintenance on and off                                               | Turn on… → the window section's T2 fields; the rung-2 and rung-4 dialogs as §11 and §12 (D04:561, :600)                                                            | the notice assertive once on entry, polite on exit (D26, D04:161); the dialog's description once                                                                     | the status line's words; the banner's words and glyph (D04:735-737)                                 | §15's banner rows | banners at 0 ms; the scrim's twin (M5, M10, M11)    | axe 0; keyboard E2E — E42-S05      |
