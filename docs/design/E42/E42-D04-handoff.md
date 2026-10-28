# E42-D04 — handoff checklists (SCR-135, SCR-136, SCR-145, SCR-148 and the admin motion spec; #887)

Per `docs/plan/16-design-system-brief.md` §11.4 and §13.3 item 8 (`02` §4.2): this SCR ticket changes six component
contracts (`docs/design/E42/E42-D04.md` §16, D04:769-783) — **CMP-173 AuditRow**, **CMP-174 AuditFilterBar**,
**CMP-179 FeatureFlagRow**, **CMP-095 FeatureFlagChip**, **CMP-099 PrintExportBar** and **CMP-053 Pagination** — so
each gets a block below; the components it only composes get one placement line each and link their own checklists.
**Shape:** E30-D03's (and E39-D02's): Tables 1–5, the Density table and the Essential-exceptions table appear once each
with a leading `Component` column instead of once per block. **This file decides nothing:** every row cites the spec
line that decides it. Prop and story names are Appendix A's text (D04:991-1035), which lands in `15` in the boards PR;
they are PROPOSED until owner approval (D04:3-8).

**Key.** `D04:n` = a line of `docs/design/E42/E42-D04.md` at this branch; `D03` = `docs/design/E42/E42-D03.md`;
`D09` = `docs/design/E09/E09-D09.md`; `Y`, `W`, `M`, `svc/` and `tok` as D04's key (D04:10-17). `15` entries are
read at `origin/main` `43d1145e6` (unchanged at `c888406d2`, the re-base), where the six contracts above are still the text D04 quotes as "Old" (verbatim at
`b7154f951`); this branch applies Appendix A's rows but CMP-173's on `main`'s text (`cba937ef0`, re-based on `c888406d2` with no Old moved; D04 §20's C-row). CMP-173's base is E42-D03's Appendix A text (merged as `58660d32f`), which reaches `15` with E42-D03's
boards PR (#886); until then `15`'s CMP-173 is the pre-D03 entry. **Merged contracts read, per the orchestrator's
2026-10-25 rulings for E42-D03:** CMP-044 is the entry #4414 merged (a natively disabled typed Confirm, `role?`), never
E42-D03's Appendix A rows; D04 composes no CMP-138. The `origin/main` pin and every `D04:n` are refreshed at the
boards base once #886 lands (the REPIN step), when CMP-173's "Old" becomes E42-D03's text.

## Handoff checklist — CMP-173 AuditRow (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0, D04:55-69): page `E42-D04`, its page id pinned in §0 once
      it exists (never a host, team, file id or URL); the row is drawn on boards 01 `scr135-populated` (AL-2 [02],
      AL-3 [03]), 02 `scr135-tamper-failed` (AL-13 [13], its integrity line in AD-5 [34]), 03 `audit-secret` (AL-4 [04])
      and 09 `diff-sheet` (every value kind and the three record shapes, both forms); PNGs
      `docs/design/E42/img/E42-D04-NN-<slug>.png`; [68] `component-sheet` and [69] `redlines` are not drawn — the text
      binds (D04:98-104, :73-76)
- [ ] **Variants × States matrix** — PENDING with the boards: the 15 stories of Appendix A (D04:1012), each mapped to
      its §4–§6 state in Table 1
- [x] **Keyboard table** — Table 2: the row lives in CMP-049's APG grid (one tab stop, roving `tabindex`; ↑ ↓ rows,
      ← → cells, Home / End, PgUp / PgDn); Space expands, Enter opens SCR-136; the diff row's Copy and disclosure
      buttons are cells; every acting key acts once per press and ignores `event.repeat` (D04:267, :295-298, :630);
      no key binding is added (D02 D17, D04:131)
- [x] **Accessible name / role table** — Table 3: the expander a button with `aria-expanded` and `aria-controls`; the
      expanded diff a `<dl>` per changed field with visible Before / After (Requested for a refused or intent record);
      severity and outcome words, the glyph `aria-hidden`; a selected row `aria-selected="true"` with the `check`
      glyph (D04:178, :364-369, :1009)
- [x] **Live data** — Table 5: a row announces nothing; new entries come from page 1's 30 s re-read as a pill, never
      spliced, announced once by the page's polite region (D5, §12; D04:169, :623)
- [x] **Motion pair** — Table 4: expansion is a cut in both modes, heights never animate (M4, D04:660; S-5,
      D04:686); severity and outcome words flip in one frame (M9, D04:665)
- [ ] N/A — **Density notes**: D04 binds the admin rows at `size.control.comfortable` (D04:726) with a 24 px expander
      column at 1280 (D04:240) and names no compact values; [69] `redlines` is not drawn, so no board measures the
      density (D04:98-104); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D04:1010) over D03's: `type.num.sm`,
      `color.text.{primary,secondary,tertiary}`, `color.status.danger.strong` (the octagon and the `border.thick` high
      rule), `color.status.warning.strong` (the triangle), `font.weight.semibold`; the selected row
      `color.surface.selected` with the `check` in `color.text.primary` and its meta in `color.text.secondary` (D14,
      D04:178, :744); none invented, stand-ins as §15 (D04:726-732); Penpot token sets = `packages/ui/tokens` at
      `b7154f95153d5357b5c50cc91c5f43000de64335` (unchanged at `origin/main` `43d1145e6`)
- [x] **Data contract confirmed** — `AuditEntry` (Y:20056-20136) from `GET /admin/audit` (`audit:read`, executed,
      M:22-27); `detail.before`, `detail.after`, `detail.elided` (Y:20114-20130), read with `outcome` and the record's
      shape (state, request or result, §6, D04:360-395); the Manager projection (Y:20061-20065); the redaction markers
      (svc/audit/redact.py:38-39, :147); gaps named: CG-1, CG-8, CG-29, CG-30, CG-33 (D04:915-947)
- [ ] **Contrast and CVD** — PENDING: every pair is §15's (D04:715-767), re-run by
      `docs/design/_tools/e42_d04_admin_audit.py` in this PR; registering the gated pairs in
      `tools/contrast/pairs.mjs` is a `tools/` change outside a design PR, routed as E16-D02 and E39-D02 route theirs;
      the greyscale and deuteranopia renders of the ★ boards ship with the boards (D04:67-69)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887), with the blocking security review (D04:6-8)

## Handoff checklist — CMP-174 AuditFilterBar (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D04`; the bar is drawn on board 01
      `scr135-populated` (AL-2 [02]) with its focus order as the board's overlay; its Applied, OwnView, Invalid and
      RateLimited states are [06], [25], [17] and [16], not drawn — the text binds (D04:98-104, :73-76)
- [ ] **Variants × States matrix** — PENDING with the boards: the six stories of Appendix A (D04:1018); Table 1
- [x] **Keyboard table** — Table 2: the controls in reading order after the incident banner and before the pill
      (D04:295-296); a `422` moves focus to the first field in error (D04:281); a T2 field or picker is also
      read-only, so typing, arrows and paste change nothing, and Enter or Space re-shows its reason (D04:636, :1016)
- [x] **Accessible name / role table** — Table 3: `<form role="search" aria-label="Filter the audit log">`; a visible
      label on every control; From and To say UTC; errors by `aria-describedby` (D04:1016)
- [x] **Live data** — Table 5: the rows-shown count after the Environment facet, polite once, never a total (AL-6,
      D04:270, :623); a field's `422` announces nothing (D04:625)
- [x] **Motion pair** — Table 4: filter → results is a one-frame swap, `audit.slow` at 400 ms (M17, D04:673)
- [ ] N/A — **Density notes**: as CMP-173's line (D04:726); D04 names no compact values; at 200 % the bar wraps into
      a "Filters" disclosure (AL-28, D04:292)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D04:1017): CMP-055's, `space.field.gap`, `color.text.secondary`,
      `color.text.tertiary`, `color.surface.raised` with a `color.border.default` hairline (a T2 control),
      `color.text.primary` with the `color.status.danger.strong` octagon (errors); Penpot token sets as CMP-173's line
- [x] **Data contract confirmed** — `queryAuditLog`'s parameters (Y:9509-9565): `from` inclusive, `to` exclusive,
      `actor_user_id`, `action` (≤ 50 codes), `subject_type`, `subject_id`, `outcome`, one `severity`, `ip` and `q`
      Owner only; Environment filters the loaded rows (D7, D04:171, :256-261); gaps named: CG-2, CG-3 (D04:916-917)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line; the T2 pairs are §15's T2 rows (D04:753-754)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887)

## Handoff checklist — CMP-179 FeatureFlagRow (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D04`; the row is drawn on board 05
      `scr145-live-blocked`: FF-2's populated page [39] and FF-4's Gated row [41], for the security reviewer, and in
      light on board 10 (FF-16 [53]); FF-12's fail-closed page [49] and the rest are not drawn — the text binds (D04:84,
      :73-76)
- [ ] **Variants × States matrix** — PENDING with the boards: the 16 stories of Appendix A (D04:1023); Saving, Refused
      and OutcomeUnknown render in the rung dialog with the row unchanged (D04:775, :1020); Table 1
- [x] **Keyboard table** — Table 2: per row Change… → History (→ Revert); the live row Change… → Security centre →
      History; `maintenance.mode` → Maintenance → History; a T2 control keeps its stop, and Enter or Space re-shows
      its reason, polite once, and sends nothing (D04:522-523, :531, :546-547); Change… acts once per press (D04:630)
- [x] **Accessible name / role table** — Table 3: a CMP-049 table row, one table per `h2` group captioned by it, not
      an arrow grid (FF-2, D04:529); the Change button named by description, key and deployment value, never
      "on/off"; a blocked control `aria-disabled="true"`, its reason by `aria-describedby` at mount, a visible link
      (D19, D20; D04:183-184, :519-524, :1021)
- [x] **Live data** — Table 5: a push from another session swaps the row in one frame, and an open dialog keeps its
      draft and meets `409` on confirm (D04:547-548); `flags.applied` polite once on the answer (FF-7, D04:534);
      `fail_closed` assertive once through the shell's region (FF-12, D04:539, :621)
- [x] **Motion pair** — Table 4: a flag's value flips in one frame on the server's answer, never animated (M9,
      D04:665; S-2, S-4, D04:682-685); "Saving…" is M14's in-flight spinner in the dialog (D04:670)
- [ ] N/A — **Density notes**: as CMP-173's line (`size.control.comfortable`, D04:1022); at 200 % rows reflow to
      stacked cards (FF-15, D04:542)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Appendix A's Tokens row (D04:1022): `color.surface.raised`,
      `color.text.{primary,secondary,tertiary}`, `color.border.default`, `color.status.warning.subtle` and `.strong`
      (fail-closed and unreadable notes; the "Affects …" marks as a CMP-011 Tag with the triangle),
      `color.status.info.subtle` and `.strong` ("Requires reload"), `type.num.sm` (the key), `size.control.comfortable`;
      CMP-004's tokens dropped with the toggle (D19); Penpot token sets as CMP-173's line
- [x] **Data contract confirmed** — `GET /admin/feature-flags` → `{resolution, items: FeatureFlag[]}`
      (Y:10398-10409, :20163-20210); `PUT /admin/feature-flags/{flagKey}` with `value`, `reason`,
      `expected_updated_at` (Y:10478-10480, :20211-20253); the row shows `default_value` and, when it differs, the
      caller's `value` (D19, Y:20169-20175); WS `feature_flags` carries the changed key only (W:4270-4279); gaps named:
      CG-15, CG-16, CG-19, CG-28, CG-35 (D04:929-933, :942, :949)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line; board 05 has no ★ renders: board 08's flag column carries the
      greyscale and colour-vision evidence (D04:84, :87)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887), with the blocking security review of the live row (D20, Q1;
      D04:184, :200)

## Handoff checklist — CMP-095 FeatureFlagChip (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: the chip is not drawn on SCR-145 (D04:776, :1024); its variants are [68]
      `component-sheet`, not drawn — the text binds (D04:98-104)
- [ ] N/A — **Variants × States matrix**: one story, Default, kept (D04:776); the change is its visible text and
      tokens, not a new state
- [x] **Keyboard table** — Table 2: static text, no Tab stop of its own (D04:1025)
- [x] **Accessible name / role table** — Table 3: visible text "Flag: {flagKey}", also its accessible name; never
      colour or an icon alone (D04:1025)
- [ ] N/A — **Live data**: static chrome
- [x] **Motion pair** — Table 4: none animated
- [ ] N/A — **Density notes**: an inline atom with no target of its own
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.status.info.subtle` (fill), `color.status.info.strong` (glyph), `color.text.primary`
      (text) until `color.chip.dev` exists (D02 DS-4; D04:728, :1026; CG-24, D04:938); Penpot token sets as CMP-173's
      line
- [ ] N/A — **Data contract confirmed**: pure chrome (`flagKey`, a registry key)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line; Tests add axe (D04:1027)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887)

## Handoff checklist — CMP-099 PrintExportBar (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] N/A — **Final Penpot link**: the contract changes its purpose only — not used for the audit log (Q9 default
      (b), D04:208, :777, :1028); SCR-135 composes CMP-001, CMP-093 and CMP-023 instead (§8, D04:449-454)
- [ ] N/A — **Variants × States matrix**: Default and Exporting are unchanged
- [ ] N/A — **Keyboard table**: unchanged
- [ ] N/A — **Accessible name / role table**: unchanged
- [ ] N/A — **Live data**: unchanged
- [ ] N/A — **Motion pair**: unchanged
- [ ] N/A — **Density notes**: unchanged
- [x] **Essential-exceptions log** — none
- [ ] N/A — **Tokens used**: unchanged (CMP-001's)
- [x] **Data contract confirmed** — the audit export it does not carry: `POST /admin/audit/export` → `202 {job_id}`
      → `GET /admin/jobs/{jobId}` → download, one signed NDJSON window (Y:9788-9920; §8, D04:447-483)
- [ ] N/A — **Contrast and CVD**: no pair introduced
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887; Q9, owner #2701)

## Handoff checklist — CMP-053 Pagination (E42-D04, #887)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING (the boards PR, §0): page `E42-D04`; the cursor pager is drawn on board 01
      (AL-2 [02], page 1: Newest and Newer T2 `admin.newest`); AL-9's end [09], AL-16's RateLimited [16] and the
      redlines [69] are not drawn — the text binds (D04:98-104, :266, :273, :280)
- [ ] **Variants × States matrix** — PENDING with the boards: Default, CursorMode, CursorKeyset, RateLimited
      (D04:1031); Table 1
- [x] **Keyboard table** — Table 2: [Newest] [Newer] [Older] after the grid, before Run tamper check; once a press
      has loaded its page, focus moves to the page's first row; a failed or refused read keeps focus on the button and
      the cursors; after `400 invalid_cursor` Newer and Older stay enabled (D04:295-304); a T2 button keeps its stop
      and re-shows its reason (D04:636)
- [x] **Accessible name / role table** — Table 3: `nav aria-label="Pagination"`; in cursor mode no `aria-current`;
      no page number or total (D4, D04:168, :1030)
- [x] **Live data** — Table 5: `audit.end` polite once at `has_more: false` (AL-9, D04:273); the count is the rows
      shown, never a total (D04:623)
- [x] **Motion pair** — Table 4: a page change is a one-frame swap; the newest page lands in one frame and the scroll
      jumps, never smoothly (M16, M17; D04:672-673)
- [ ] N/A — **Density notes**: as CMP-173's line (D04:726)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.action.*` (unchanged, `15`), plus the T2 look: `color.surface.raised`,
      `color.border.default`, `color.text.tertiary` (label and `lock`), `color.text.secondary` (reason) (§12.1,
      D04:636); Penpot token sets as CMP-173's line
- [x] **Data contract confirmed** — keyset paging: `limit=200` inside 1–500, the cursors and `has_more`
      (Y:9455-9459, :15575-15583; D4, D04:168); a malformed cursor → `400 invalid_cursor` (Y:9512-9516; AL-17,
      D04:281)
- [ ] **Contrast and CVD** — PENDING: as CMP-173's line (the T2 rows, D04:753)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — §A and §B below
- [ ] **Sign-off** — owner approval pending (#887)

**Placement lines (contract unchanged here; their own checklists apply).** CMP-049 Table — SCR-135's APG grid
(`role="grid"`, one tab stop, roving `tabindex`, `aria-rowindex` when virtualised), caption `audit.caption`, Time the
only `aria-sort="descending"` header, not operable (D6; D04:170, :224, :295-297); SCR-145's one table per group,
captioned by its `h2`, not an arrow grid (D04:529). CMP-046 Drawer — SCR-136 `modal: false`, a `role="dialog"` without
`aria-modal`; focus to its `h2` in frame 0, Esc or Close back to the row, `Ctrl+\` still reaches CMP-211; 480 px over
the grid at 1280, docked at 640 px at 2560 (D1, D14; D04:165, :178, :351-354; M1, M2, D04:657-658). CMP-044
ConfirmDialog (the entry #4414 merged) on CMP-043 `size` Large — every rung and export dialog: `role="alertdialog"`
(its `role?`), described by the whole body and the marker, Cancel focused first, the confirm ignoring `event.repeat`,
`busy?` while a write is in flight (MM-3, FF-7); no typed variant, as maintenance has no server-checked token (D02 D15;
D04:130, :596-615). CMP-079 RbacGate + CMP-019 Icon `lock` (`decorative=false`, "Not available") — every T2 control
(§12.1, D04:632-637); one reason shared by a region's controls is CMP-079's `notice` form, one node each points at
(D23, AL-16, AD-7, MM-1; D04:637). CMP-028 Callout / Banner — the integrity incident (danger, non-dismissible,
`role="alert"` on the episode's first mount only, then static; §7, D11; D04:175, :412, :439-441), `flags.fail_closed`
(FF-12) and the maintenance banners in the shell-band slot, their voice the shell's one region (D26; D04:190, :621).
CMP-027 ErrorState — AL-15, FF-17 and MM-11 in its error look with the octagon and `role="status"` (D04:279, :544,
:587, :780-782). CMP-023 Progress Bar — the export line, `aria-live` off, "{n} %" polite at 25 % steps (D04:477-478).
CMP-001 Button `loading` — the busy Signed export… (§8; D04:449-454); a rung-2 confirm waiting on its count is
natively disabled, CMP-044's merged form (D22, R-2; D04:186). CMP-033 CopyButton — "Copied" for 2 s, polite once (AD-2, D04:343). CMP-068 CopyableCodeBlock — SCR-136's raw
record, a focusable scroll region named "Raw record", withheld when §6's name rule flags the record (AD-2, AD-3;
D04:343-344). CMP-093 AuditActionTrigger — the marker lines, which rejoin a control's description only while it is
enabled (D8, §12.1; D04:172, :637). CMP-015 Skeleton (AL-1, FF-1, MM-10), CMP-026 EmptyState (AL-7), CMP-054 SearchBox
(FF-3, `flags.search`), CMP-047 DatePicker (the export window, MM-1's field), CMP-065 FormSection (MM-1) — as §4, §8,
§9 and §10 place them. CMP-138 RiskCapMeter — not composed by D04.

### Table 1 — Variants × States (stories from Appendix A; boards PENDING)

| Component | Story              | D04 state (cite)                                                              | Board ([old id] → drawn board NN, PENDING; or not drawn) | Notes                                              |
| --------- | ------------------ | ----------------------------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| CMP-173   | Default            | AL-2 populated, page checked (D04:266)                                        | [02] → 01                                                | D03's story                                        |
| CMP-173   | ExpandedDiff       | AL-3 row expanded, §6's full form (D04:267, :368-369)                         | [03] → 01; [67] → 09                                     | D03's story; `<dl>`, never a code block (D04:1009) |
| CMP-173   | SystemActor        | AL-5 `system:maintenance` (D04:269)                                           | [05] not drawn                                           | D03's story                                        |
| CMP-173   | Compact            | SCR-122's change summary; FF-14's history rows (D04:362-363, :541)            | [51] not drawn                                           | D03's story; the inline form (§6)                  |
| CMP-173   | CompactDenied      | a refused record in the request shape, inline (D04:383, :541)                 | [51] not drawn                                           | D03's story                                        |
| CMP-173   | CompactElided      | a withheld state, inline (D04:374-375, :394)                                  | —                                                        | D03's story                                        |
| CMP-173   | HighSeverity       | error and critical: octagon, semibold, the `border.thick` rule (D2, D04:166)  | [02] → 01; [13] → 02                                     | greyscale render on 02 (D04:970)                   |
| CMP-173   | ExpandedNested     | a nested path, "overrides › 9f1c…" (D04:376)                                  | [67] → 09                                                | lists compare as whole values                      |
| CMP-173   | ExpandedSecret     | AL-4: `secret`, `secret_named`, `credential` (D04:268, :388-390)              | [04] → 03; [32] → 03; [67] → 09                          | security reviewer (D04:853)                        |
| CMP-173   | ExpandedWithheld   | `withheld` beside a served `after` (D04:374-375, :394)                        | [67] → 09                                                | `diff.withheld` once under Before                  |
| CMP-173   | ExpandedRequested  | the request shape: Requested, never After (D04:383)                           | [67] → 09                                                | `diff.head_failed`, `diff.head_intent`             |
| CMP-173   | WriteAhead         | "Started" / "Intent", never "Success" (D3, D04:167)                           | [02] → 01                                                | `audit.result_started`, `audit.result_intent`      |
| CMP-173   | OwnProjection      | AL-25 "My activity" (D04:289)                                                 | [25] not drawn                                           | `rec.hidden` in the projected cells                |
| CMP-173   | DeletedActor       | `deleted-user-3f9a…`, no link, a labelled target (CG-33; D04:269)             | [05] not drawn                                           | the grid cuts it to 4 hex and "…" (D04:707)        |
| CMP-173   | AfterBreak         | at or after `first_bad_id`, expanded row and SCR-136 only (D04:346, :1008)    | [34] → 02                                                | never the collapsed row                            |
| CMP-174   | Default            | AL-2 (D04:266)                                                                | [02] → 01                                                | —                                                  |
| CMP-174   | Applied            | AL-6 filtered, the applied set as text (D04:270)                              | [06] not drawn                                           | URL state (D04:260-261)                            |
| CMP-174   | OwnView            | AL-25: Actor fixed, IP, Search, Environment T2 `rbac.owner_only` (D04:289)    | [25] not drawn                                           | `view: "own"`                                      |
| CMP-174   | Invalid            | AL-17 `422`: `audit.err_range`, `audit.err_ip` (D04:281)                      | [17] not drawn                                           | focus carries it                                   |
| CMP-174   | EnvironmentFacet   | D7: "LIVE (this page only)" (D04:171, :270)                                   | [06] not drawn                                           | no read sent; cursor kept                          |
| CMP-174   | RateLimited        | AL-16: every control T2 `admin.rate_limited` (D04:280)                        | [16] not drawn                                           | `blockedReason`                                    |
| CMP-179   | Default            | FF-2, an ordinary row (D04:529)                                               | [39] → 05                                                | —                                                  |
| CMP-179   | SafetyFlag         | the safety group, "overrides ignored" (D04:500, :509)                         | [39] → 05                                                | rung 2 / rung 4 (§11)                              |
| CMP-179   | Gated              | FF-4 `trading.live_enabled`, T2 `admin.live_gate` + Security centre (D04:531) | [41] → 05                                                | security reviewer (D04:853)                        |
| CMP-179   | AffectsOrderEntry  | `trading.one_click`, `algo.*` (D18, D04:182, :511-512)                        | [39] → 05                                                | Q6                                                 |
| CMP-179   | AffectsDesktop     | `desktop.backend_connection`, `flags.affects_desktop` (D04:511)               | [39] → 05                                                | `dlg.flag.desktop` in its dialog                   |
| CMP-179   | Overrides          | "+ 1 user override" (FF-2, D04:529)                                           | [39] → 05                                                | `flags.scope`                                      |
| CMP-179   | OwnerOverride      | "You: ON — your override" (D19, D04:183, :529)                                | [39] → 05                                                | `flags.your_override`                              |
| CMP-179   | YourResolved       | "You: ON — resolved for you" (D19; FF-2's inset, D04:529)                     | [39] → 05                                                | `flags.your_resolved`                              |
| CMP-179   | Unreadable         | FF-12 `unreadable: true`, Change kept as the repair (D04:539)                 | [49] not drawn                                           | `flags.unreadable`                                 |
| CMP-179   | FailClosed         | FF-12 `fail_closed`: `flags.fail_closed_value`, T2 `admin.flags_store` (D23)  | [49] not drawn                                           | no "Changed … by …" line                           |
| CMP-179   | RequiresReload     | D24: a labelled target with [Reload now] on `engine.webgl_v2` (D04:188)       | [39] → 05                                                | CG-16                                              |
| CMP-179   | MaintenanceLink    | "→ Maintenance" in place of Change… on `maintenance.mode` (D04:503, :509)     | [39] → 05                                                | `changeHref`                                       |
| CMP-179   | Revert             | [Revert to OFF] after a change this session (FF-7, D04:534)                   | [44] not drawn                                           | the write's rung (§11)                             |
| CMP-179   | Saving             | FF-7 "Saving…" in the dialog (D04:534)                                        | [44] not drawn                                           | the row unchanged                                  |
| CMP-179   | Refused            | FF-10, FF-11 in the dialog (D04:537-538)                                      | [47] not drawn; [48] not drawn                           | the row unchanged                                  |
| CMP-179   | OutcomeUnknown     | FF-13 `flags.store_down`, `flags.checking` (D04:540)                          | [50] not drawn                                           | never "Nothing was changed."                       |
| CMP-095   | Default            | visible "Flag: {flagKey}" (D04:1025)                                          | [68] not drawn                                           | not on SCR-145                                     |
| CMP-099   | Default, Exporting | unchanged; not used for the audit log (D04:1028)                              | —                                                        | —                                                  |
| CMP-053   | Default            | unchanged                                                                     | —                                                        | —                                                  |
| CMP-053   | CursorMode         | unchanged (`15`)                                                              | —                                                        | —                                                  |
| CMP-053   | CursorKeyset       | AL-2 page 1, AL-9 `has_more: false`: Newest, Newer, Older (D04:266, :273)     | [02] → 01; [09] not drawn                                | `admin.newest`, `admin.oldest`                     |
| CMP-053   | RateLimited        | AL-16: every button T2 `admin.rate_limited` (D04:280)                         | [16] not drawn                                           | the pager points at AL-16's one notice             |

### Table 2 — Keyboard

| Component | Key                                     | Action                                                                                                               | Focus after                                                            | Global conflict?               | Cite                    |
| --------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------ | ----------------------- |
| CMP-173   | ↑ ↓ · ← → · Home / End · PgUp / PgDn    | the APG grid: rows, cells (the diff row's Copy and disclosure are cells); arrows may repeat                          | the row or cell                                                        | none                           | D04:267, :296-298, :630 |
| CMP-173   | Space                                   | expands or collapses the row (`aria-expanded`); once per press                                                       | stays on the row                                                       | none                           | D04:267, :298, :630     |
| CMP-173   | Enter                                   | opens SCR-136; while it is open, ↑ ↓ in the grid keep the drawer on the selected row; once per press                 | the drawer's `h2`                                                      | none                           | D14; D04:178, :298      |
| CMP-173   | Esc (in SCR-136)                        | closes the drawer                                                                                                    | the row                                                                | none (Esc is the drawer's own) | D04:352-353             |
| CMP-174   | Tab / Shift+Tab                         | the filters in reading order, between the incident banner and the pill                                               | the next control                                                       | none                           | D04:295-296             |
| CMP-174   | typing, arrows, paste on a T2 field     | change nothing (`readonly`, `aria-readonly` on a picker)                                                             | unchanged                                                              | none                           | D04:636, :1016          |
| CMP-174   | Enter / Space on a T2 control           | stages and sends nothing; the reason is re-shown inline, polite once                                                 | unchanged                                                              | none                           | D04:624, :636           |
| CMP-174   | [Clear filters] (AL-7, AL-26)           | clears the set and reads page 1                                                                                      | page 1's first row, once loaded                                        | none                           | D04:271, :303-304       |
| CMP-179   | Tab / Shift+Tab                         | Change… → History (→ Revert); live row Change… → Security centre → History; `maintenance.mode` Maintenance → History | the next control                                                       | none                           | D04:531, :546-547       |
| CMP-179   | Enter / Space on Change…                | opens the rung dialog (Cancel focused); once per press                                                               | Cancel in the dialog; on close, back to Change…                        | none                           | D04:629-630             |
| CMP-179   | Enter / Space on the live row's Change… | sends nothing; `admin.live_gate` re-shown inline beside the Security centre link, polite once per press              | unchanged                                                              | none                           | FF-4; D04:523, :531     |
| CMP-053   | Enter / Space on Newest / Newer / Older | loads that page; once per press                                                                                      | the page's first row once loaded; a failed read keeps it on the button | none                           | D04:299-302             |
| CMP-053   | Enter / Space on a T2 button            | loads nothing; re-shows its reason (`admin.newest`, `admin.oldest`, `admin.rate_limited`)                            | unchanged                                                              | none                           | D04:304, :636           |
| CMP-095   | —                                       | static text, no stop                                                                                                 | —                                                                      | none                           | D04:1025                |

### Table 3 — Accessible name / role

| Component | Element              | Role                                    | Accessible name (source)                                                                | States / properties                                                                                                                                     |
| --------- | -------------------- | --------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-173   | the row              | `row` in CMP-049's `grid` (`gridcell`s) | its cells' words (time, actor, action label, target, environment, IP, severity, result) | `aria-rowindex` when virtualised; `aria-selected="true"` and the `check` glyph (`aria-hidden`) on the selected row (D14, D04:178)                       |
| CMP-173   | the expander         | `button`                                | the row it expands                                                                      | `aria-expanded`, `aria-controls` (D04:1009)                                                                                                             |
| CMP-173   | the expanded diff    | `dl` per changed field, a nested `dl`   | the field path; the terms Before / After, or Requested (D04:367-369, :383)              | the status word (Added, Removed, Changed) as text, never colour or strike-through (D04:370-371); the arrow `aria-hidden`, read "changed from OFF to ON" |
| CMP-173   | severity, outcome    | text                                    | the enum's word; "Started" / "Intent" on a write-ahead record (D2, D3)                  | the octagon or triangle `aria-hidden`; high rows add the rule and the weight (D04:166-167, :1009)                                                       |
| CMP-173   | a secret-kind value  | text                                    | "Secret — never recorded" and its siblings (§6, D04:388-390)                            | the `lock` glyph decorative (D04:636); nothing hashed client-side (D16)                                                                                 |
| CMP-174   | the bar              | `search` (`form`)                       | "Filter the audit log"                                                                  | errors by `aria-describedby` (D04:1016)                                                                                                                 |
| CMP-174   | a T2 field or picker | its native role                         | its visible label, the `lock` ("Not available") leading it                              | `aria-disabled="true"`, `readonly` / `aria-readonly`, `aria-describedby` → the reason or the one notice (D04:636-637, :1016)                            |
| CMP-179   | the row              | `row` in a CMP-049 `table`              | its cells' words                                                                        | one table per group, captioned by its `h2` (FF-2, D04:529)                                                                                              |
| CMP-179   | Change…              | `button`                                | the description, the key and the deployment value ("… deployment OFF"), never "on/off"  | blocked: `aria-disabled="true"`, never `disabled`, `aria-describedby` → the reason at mount, a visible link (D04:183-184, :521-523, :1021)              |
| CMP-179   | values               | text                                    | `flags.deployment`, `flags.your_*`, `flags.fail_closed_value`                           | they change only on the server's answer (D19, D04:183)                                                                                                  |
| CMP-053   | the pager            | `navigation`                            | "Pagination"                                                                            | cursor mode: no `aria-current`; a T2 button `aria-disabled`, its `lock` leading the label, `aria-describedby` → its reason (D04:1030)                   |
| CMP-095   | the chip             | text                                    | "Flag: {flagKey}" (visible)                                                             | never colour or an icon alone (D04:1025)                                                                                                                |

### Table 4 — Motion pair

| Component | Property                                    | motion-safe                                                      | motion-reduce                           | Duration / easing tokens | Cite                   |
| --------- | ------------------------------------------- | ---------------------------------------------------------------- | --------------------------------------- | ------------------------ | ---------------------- |
| CMP-173   | row expansion; the diff's disclosures       | a cut; heights never animate                                     | the same                                | none                     | M4, S-5; D04:660, :686 |
| CMP-173   | severity, outcome, the integrity line       | one frame, words first, on the server's answer                   | the same                                | none                     | M9, S-2; D04:665, :682 |
| CMP-174   | filter → results                            | a one-frame swap; `audit.slow` at 400 ms                         | the same                                | none                     | M17; D04:673           |
| CMP-179   | a flag's value; a push from another session | one frame on the answer; no colour tween, no cross-fade ON / OFF | the same                                | none                     | M9, S-4; D04:665, :685 |
| CMP-179   | "Saving…" (in the dialog)                   | CMP-001 `loading`, 800 ms period (PROPOSED), slow line at 5 s    | a static glyph with the in-flight label | none                     | M14; D04:670           |
| CMP-053   | a page change; the newest page              | one frame; the scroll jumps, never smoothly                      | the same                                | none                     | M16, M17; D04:672-673  |
| CMP-095   | —                                           | none animated                                                    | none animated                           | —                        | —                      |

### Table 5 — Live data

| Component | Field                                | Politeness                                                    | Cadence                                           | Coalescing                                                        | Cite                |
| --------- | ------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- | ------------------- |
| CMP-173   | rows                                 | none                                                          | a page read; page 1 re-read every 30 s (PROPOSED) | never spliced: the pill counts newer rows                         | D5; D04:169         |
| CMP-173   | the new-entries pill (`audit.new_n`) | polite once when it appears; `audit.new_loaded` once on press | per re-read                                       | "200+" at the cap; the viewer's own `admin.area_entered` left out | AL-8; D04:272, :623 |
| CMP-174   | the count (`audit.count`)            | polite once                                                   | per applied filter                                | the rows shown, never a total                                     | AL-6; D04:270, :623 |
| CMP-179   | a row's values                       | none (a push swaps the row in one frame)                      | on a `feature_flags` frame (≤ 2 s)                | the changed key only                                              | D04:490, :547       |
| CMP-179   | `flags.applied`                      | polite once, on the answer                                    | per write                                         | —                                                                 | FF-7; D04:534       |
| CMP-179   | `flags.count`                        | polite once the input settles                                 | never per keystroke                               | —                                                                 | FF-3; D04:530       |
| CMP-053   | `audit.end`                          | polite once                                                   | at `has_more: false`                              | —                                                                 | AL-9; D04:273       |

### Density

| Component         | Mode                | Row / control height                            | Padding tokens                                         | Smallest target                                 |
| ----------------- | ------------------- | ----------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| CMP-173, 174, 179 | comfortable (admin) | `size.control.comfortable` (D04:726, :1022)     | `space.inset.{lg,xl}`, `space.stack.{sm,md}` (D04:726) | the expander cell, 24 px wide at 1280 (D04:240) |
| CMP-053           | comfortable (admin) | `size.control.comfortable`                      | —                                                      | a pager button                                  |
| all six           | compact             | not specified by D04 (open point for the owner) | —                                                      | —                                               |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all six   | none      | —                    | —        | —    |

## §A — Design QA checklist (`16` §12), filled

- [x] Only published Tier-2 / Tier-3 tokens; the missing ones take named stand-ins, never invented (§15, D04:721-732;
      CG-24, D04:938).
- [ ] Three themes × two densities verified visually — PENDING with the boards: dark draws every drawn board; light
      draws board 10 (AL-29, FF-16, MM-9), and light and high contrast are proven by §15's computed matrix and board
      08's columns (deviation 4, Q14; D04:32-33,
      :109-110); compact is not specified (Density table).
- [ ] Contrast matrix for every pair introduced — PENDING: §15 (D04:734-755), re-run by
      `docs/design/_tools/e42_d04_admin_audit.py`; the `tools/contrast/pairs.mjs` registration is routed (blocks above).
- [ ] CVD simulation for every new colour-carrying state — PENDING: §15's colour-vision table (D04:757-763); the
      greyscale and deuteranopia renders of the ★ boards (D04:67-69).
- [ ] Every State has a Penpot variant and a Storybook story — PENDING: Table 1 maps every story to its state; ten
      boards (PENDING) draw 38 frames and the rest bind as text (§0, D04:73-76); the stories are E42-S04's and E42-S05's
      (D04:956-957).
- [x] Disabled states use disabled-with-reason (§12.1 T2: CMP-079, the CMP-019 `lock`, `aria-disabled`, the reason in
      the DOM at mount; never `color.text.disabled` or `opacity.disabled`; D04:632-637); busy is never T2 (§8;
      D04:451-452), nor a confirm waiting on its count, natively disabled (D22, R-2; D04:186).
- [x] Loading, empty and error states designed: AL-1, AL-7, AL-15, AL-26, FF-1, FF-17, MM-10, MM-11 (D04:265-290,
      :528, :544, :586-587).
- [x] Keyboard table completed (Table 2; §4, §5, §9, §10 Keys, §12).
- [x] Accessible-name / role table completed (Table 3).
- [x] No canvas-adjacent component.
- [x] Motion-safe / motion-reduce pair specified (Table 4; §13, D04:639-698).
- [ ] Hit targets — PENDING: D04 binds `size.control.comfortable` and the 24 px expander column (D04:240, :726);
      [69] `redlines` is not drawn — the text binds (D04:98-104); no essential exception.
- [ ] Accessibility role sign-off — owner `approved` on #887 (agent-delivery adaptations); E42-D06 reviews §12, §13,
      §15 and this file (D04:955).
- [x] Confirm-gate variant stated: rungs 1, 2 and 4, `standard`, no typed confirmation (D02 D15; §11, D04:608-615).
- [ ] N/A — estimated values chip-tagged: the admin screens show no estimate.
- [x] Demo / Live context unambiguous: the environment column and the ENV badge above every scrim and dialog (§11,
      D04:599-602; C-2.11, D04:851-852).
- [x] Reuses existing CMP ids; the diff is CMP-173's part, not a new CMP-240 (D15, Q10; D04:179, :209).
- [ ] Storybook stories match the matrix — PENDING: the implementing tickets' (E42-S04, E42-S05).
- [ ] Composes only published-library components in Penpot — PENDING with the boards.

## §B — Accessibility acceptance criteria (`05` §10), filled per screen

| Screen  | Primary task (keyboard-only, screen-reader)                               | Keyboard-only                                                                                                                                                      | Screen reader                                                                                                                                                        | Colour-independence                                                                                 | Contrast          | Reduced motion                                      | Automated gates                    |
| ------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------- | ---------------------------------- |
| SCR-135 | find a high-severity record, read its diff, and see whether the log holds | Signed export → export line → incident banner → filters → pill → the grid (one stop) → paging → Run tamper check; Space expands, Enter opens SCR-136 (D04:295-304) | the incident's `role="alert"` once per episode; counts, new entries and check results polite once through one page region (§12, D04:621-623); words for every status | severity and outcome as words, glyphs and the high rule (D2; D04:765-767); forced colours (D04:763) | §15 (D04:734-755) | expansion a cut; statuses one frame (M4, M9)        | axe 0 serious / critical — E42-S04 |
| SCR-136 | step through records and copy a hash                                      | heading in frame 0 → Previous → Next → Close → copies and links → Show raw record → the raw `<pre>`; Esc back to the row; `Ctrl+\` reaches CMP-211 (D04:351-354)   | the heading on focus; "Copied" polite once; a withheld raw record is a notice, not T2 (AD-3, D04:344)                                                                | the integrity line's words (AD-5); the selected row's `check` (D14)                                 | §15's drawer rows | the drawer instant under reduce (M1, M2)            | axe 0 serious / critical — E42-S04 |
| SCR-145 | change an ordinary flag, and find that live trading cannot be set here    | search → clear → per group Change… → History (→ Revert); the live row's T2 Change… re-shows its reason (D04:546-547)                                               | the dialog's description once; `flags.applied` polite once; `fail_closed` assertive once; a T2 press polite once (§12)                                               | values as ON / OFF words; notes as tags with the triangle (D04:1022)                                | §15's T2 rows     | values flip in one frame (M9); "Saving…" M14's twin | axe 0; keyboard E2E — E42-S05      |
| SCR-148 | turn maintenance on and off                                               | Turn on… → the window section's T2 fields; the rung-2 and rung-4 dialogs as §11 and §12 (D04:590, :629)                                                            | the notice assertive once on entry, polite on exit (D26, D04:190); the dialog's description once                                                                     | the status line's words; the banner's words and glyph (D04:765-767)                                 | §15's banner rows | banners at 0 ms; the scrim's twin (M5, M10, M11)    | axe 0; keyboard E2E — E42-S05      |
