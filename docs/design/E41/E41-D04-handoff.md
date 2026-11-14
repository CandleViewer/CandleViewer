# E41-D04 — `16` §11.4 hand-off checklists (CMP-166, CMP-167, CMP-168, CMP-169)

The spec is [E41-D04.md](E41-D04.md); every §, PT, AN, K, M, P, V, RT, RV, HC, C and BQ id below without a prefix is the spec's. E41-D02 (`D02`) and E41-D03 (`D03`) are cited by section id only, at their pinned heads, each if its PR merges as is (spec §12 R-1, R-2). One block per component contract E41 introduces or changes (`16` §13.3 item 8): CMP-166 and CMP-169 (D02 §4.1, §4.2), CMP-167 and CMP-168 (D03 §4).

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`; `[ ] PENDING — <reason>` marks a line still open, with what closes it. No blank line at Done (`16` §11.4, §13.3).

## Handoff checklist — CMP-166 JournalEntryRow (E41-D04, #1082)

- [ ] **Final Penpot link** — PENDING — D02's SCR-093 frames (D02 §0), drawn in #1018's PR 2; no page id or PNG until that PR pins them; this ticket's PR 2 adds the annotation layer (BQ-02: page `E41-D04`, one PNG per frame)
- [x] **Variants × States matrix** — D02 §4.1: Winner, Loser, WithRuleTag, WithManualTags over Reconciling, ContextUnavailable, LongText, Selected and Focused; the S93 rows of §10.5. WithRuleTag carries an auto chip with no remove control (BQ-03, ruled jointly; D02 §4.1, F-01, C-5); Divergent and Excluded are D02 §4.1's states (S93-22)
- [x] **Keyboard table** — §5.1 K93-02 … K93-07 and PT-01, PT-03, PT-04: one grid stop, roving focus by trade id; `T` and `Alt+R` view-local (CM-01, CM-02); no global binding overridden, `Esc` / `Ctrl+K` untouched (G-KEYS)
- [x] **Accessible name / role table** — PT-01, PT-03, PT-04: the grid row, its checkbox `journal.name.select_row` and its menu button `journal.name.row_menu`; the row's name is D02 §4.1's
- [ ] **Live data** — N/A — closed trades are not streamed; selection, sort and filter changes speak once through the page's one region (AN-01, AN-02, AN-05)
- [x] **Motion pair** — M-01 and M-02, cuts in both modes; M-13 for the bulk bar
- [x] **Density notes** — RT-01: `size.row.compact` (24 px) by default and `size.row.comfortable` (32 px); the select and menu cells span the row height in both
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D02 §4.1's Tokens line replaces `15`'s field through D02's A-row (`color.text.buy/sell` are not tokens, D02 C-6); RT-01, RT-02 and RT-04 here
- [ ] **Data contract confirmed** — PENDING — D02 §4.1's props (Decimal strings, `env`, `isPaper`) wait on D01's G-1 and G-2 (E41-T01 #1019)
- [ ] **Contrast and CVD** — PENDING — measured by this ticket's tool (§6.1 P-01 … P-05, P-15 … P-17, P-19, P-20, P-29 … P-31; §6.3 V-01 … V-05), not yet rows of `tools/contrast/pairs.mjs`; attached on #1082 with PR 1b
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (this ticket's PR 2); HC-01 carries the criteria meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1082 (§14)

## Handoff checklist — CMP-167 JournalEquityCurveChart (E41-D04, #1082)

- [ ] **Final Penpot link** — PENDING — D03's SCR-095 frames (D03 §0), drawn in #1081's PR 2; this ticket's PR 2 adds the annotation layer (BQ-02: page `E41-D04`, one PNG per frame)
- [x] **Variants × States matrix** — D03 §4: default, with drawdown, table view, low sample, one point, empty, loading and error, as the stories Default, WithDrawdown, TableViewToggle, LowSample, TransferMarked, OnePoint and Loading (D03's AR-10 to `15`)
- [x] **Keyboard table** — §5.3 K95-03: `Enter` or `Space` on View as table, or `Alt+T` with the chart focused, which is `05`'s own table binding, not an override; focus stays on the toggle
- [x] **Accessible name / role table** — PT-13: `role="img"` named by the summary sentence; View as table a toggle button with `aria-pressed`; the table view CMP-049 (D03 §4)
- [ ] **Live data** — N/A — the curve is re-read per cohort change, not streamed; the re-read speaks AN-06, then AN-07, once
- [x] **Motion pair** — M-06 (a cut in both modes), M-09 (the table swap, a cut) and M-10 (the skeleton, static under reduce)
- [ ] **Density notes** — PENDING — the card's heights and the toggle's target in both densities are drawn with D03's boards (#1081 PR 2)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03's AR-9 replaces `15`'s Tokens field (D03 §4); RT-11 here
- [ ] **Data contract confirmed** — PENDING — the points and the maximum drawdown come from the analytics read (E41-T03 #1021); D01's G-1 (no environment filter) is open
- [ ] **Contrast and CVD** — PENDING — measured by this ticket's tool (§6.1 P-25, P-26, P-28), not yet rows of `tools/contrast/pairs.mjs`; attached on #1082 with PR 1b
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (this ticket's PR 2); HC-03 carries the criteria meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1082 (§14)

## Handoff checklist — CMP-168 JournalStatsSummaryCard (E41-D04, #1082)

- [ ] **Final Penpot link** — PENDING — D03's SCR-095 frames (D03 §0), drawn in #1081's PR 2; this ticket's PR 2 adds the annotation layer (BQ-02: page `E41-D04`, one PNG per frame)
- [x] **Variants × States matrix** — D03 §4: Default, LowSample and Undefined; the S95 rows of §10.5 (S95-03, S95-04, S95-07)
- [x] **Keyboard table** — §5.3 K95-04: one stop per tile, its Formula link; `Enter` opens the reference drawer on its heading and `Esc` returns focus to the link
- [x] **Accessible name / role table** — AN-08: the value, then its `aria-describedby`, "n = 42" or `journal.caveat.number` or `journal.stat.undefined.1`; the tile is no landmark and no button (D03 §4); the names are §11's L rows
- [ ] **Live data** — N/A — values are re-read per cohort change, never live; AN-08 is read on demand
- [x] **Motion pair** — M-06 (a cut in both modes) and M-10 (static under reduce); numbers never tween (MR-4)
- [ ] **Density notes** — PENDING — the tile's heights in both densities and the Formula link's target are drawn with D03's boards (#1081 PR 2)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03's AR-12 replaces `15`'s Tokens field (D03 §4); RT-10 here
- [ ] **Data contract confirmed** — PENDING — the statistics and the sample size come from the analytics read (E41-T03 #1021); their names wait on E41-T05 (#1083, F-20)
- [ ] **Contrast and CVD** — PENDING — measured by this ticket's tool (§6.1 P-02, P-03, P-07, P-13, P-22), not yet rows of `tools/contrast/pairs.mjs`; attached on #1082 with PR 1b
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (this ticket's PR 2); HC-03 carries the criteria meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1082 (§14)

## Handoff checklist — CMP-169 TagEditor (E41-D04, #1082)

- [ ] **Final Penpot link** — PENDING — D02's SCR-093 popover and D03's Notes and tags frames (D02 §0, D03 §0), drawn in their PR 2s; this ticket's PR 2 adds the annotation layer (BQ-02: page `E41-D04`, one PNG per frame)
- [x] **Variants × States matrix** — D02 §4.2: Default, WithReadOnlyRuleTags, Denied and LongText; the auto chip is read-only on SCR-093 and SCR-096, and SCR-094 carries the one recorded removal of an auto tag (BQ-03, ruled jointly; D03 §2.6, F-01, C-5); S94-09 and S94-11 for Denied
- [x] **Keyboard table** — PT-08, PT-09, K93-05 and K94-06: the combobox field, `Enter` adds; `Backspace` in an empty field focuses the last removable chip; `Delete` or `Enter` on a remove button removes it, focus to the next chip, else the previous one, else the field (D02 §4.2); `Esc` untouched
- [x] **Accessible name / role table** — PT-08: combobox `journal.name.tag_field` with a listbox of suggestions; PT-09: a list of chips, each remove button `journal.name.tag_remove`; T2 controls per RV-03, RV-06
- [ ] **Live data** — N/A — static chips; an add or a removal speaks once (AN-04, AN-12)
- [ ] **Motion pair** — N/A — none animated: a chip is added and removed in one frame
- [ ] **Density notes** — PENDING — the chip and its remove target in both densities are drawn with the parents' boards (#1018, #1081 PR 2)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — RT-05 for chips and swatches; `15`'s "inherits CMP-011 Tag" holds if CMP-011's tokens are RT-05's, checked with D02's boards
- [ ] **Data contract confirmed** — PENDING — `22` lists and creates tags but has no rename, merge or delete, and SCR-094's recorded removal of an auto tag (E41-T04's suppression) has no contract yet (D01's G-3, E41-T04 #1132)
- [ ] **Contrast and CVD** — PENDING — measured by this ticket's tool (§6.1 P-12, P-15, P-18), not yet rows of `tools/contrast/pairs.mjs`; attached on #1082 with PR 1b
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (this ticket's PR 2); HC-01 and HC-02 carry the criteria meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1082 (§14)
