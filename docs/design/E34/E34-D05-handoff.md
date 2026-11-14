# E34-D05 — `16` §11.4 hand-off checklists (CMP-044, CMP-123, CMP-124, CMP-229, CMP-232, LegStatusCell)

The pack is [E34-D05.md](E34-D05.md); every §, SD, MP, DG, RC and BQ id below without a prefix is the pack's. E34-D02 (`D02`), E34-D03 (`D03`) and E34-D04 (`D04`) are cited by section id only, at their pinned heads, each "if its PR merges as is" (pack R-1 … R-5). One block per component contract E34 introduces or changes (`16` §13.3 item 8): the five of D03 §5 and D02's CMP-229 usage line. The screens themselves compose published components and carry the pack's §6 instead.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`; `[ ] PENDING — <reason>` marks a line still open, with what closes it. No blank line at Done (`16` §11.4, §13.3).

## Handoff checklist — CMP-044 ConfirmDialog (E34-D05, #1043)

- [x] **Final Penpot link** — page `E34-D03 Trade-group manager hi-fi`, board D3-06 (`DS/scope-confirm`) and board D3-04 (B14 … B19); PNGs in the boards PR (pack §0)
- [x] **Variants × States matrix** — D03 §5.4: ScopeRestatement, ScopeChanged, ScopeRestatementLongIds over D03 §4.2's confirm states (SD-62 … SD-68)
- [x] **Keyboard table** — D04 §4.5: focus on Cancel at open; `Esc` cancels and returns focus to the trigger; Confirm ignores its first `confirmDelayMs`; no global binding touched
- [x] **Accessible name / role table** — `role="alertdialog"` labelled by its title; Confirm's name is its `…confirm` deck row; the leg table `th scope="row"` (D04 §3)
- [x] **Live data** — the scope is re-read on Confirm, never streamed into the open dialog; a mismatch shows `e34.shared.scope.changed` once
- [x] **Motion pair** — MO-7: the scrim over `motion.duration.normal`, the card a cut; under reduce an instant open and close
- [x] **Density notes** — the leg table's rows at `size.row.compact` and `size.row.comfortable`; buttons ≥ `size.target.min` in both
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §5.4's Tokens line enters `15` through D03's A-7 (its PR 2)
- [x] **Data contract confirmed** — `cancelTradeGroup` with the confirmed `legs` (`22`:7868); the count comes from the listed legs until DG-07 is served
- [ ] **Contrast and CVD** — PENDING — Confirm's `danger` pair is D03 §8.1 P-13, not yet a row of `tools/contrast/pairs.mjs`
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with this ticket's PR 2
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1043 (pack §17)

## Handoff checklist — CMP-123 FlattenAllButton (E34-D05, #1043)

- [ ] **Final Penpot link** — N/A — not drawn on SCR-061 or SCR-062; only its A11y line changes (D03 §5.4)
- [x] **Variants × States matrix** — unchanged in `15`; the scope grammar adds no state
- [x] **Keyboard table** — unchanged: CMP-044 composition, always keyboard-operable (never a mouse-hold-only gate)
- [x] **Accessible name / role table** — the scope restatement "Flatten all positions — {account}" (D03 §5.4); gated through CMP-079 with the CMP-019 `lock`
- [ ] **Live data** — N/A — no streamed field
- [x] **Motion pair** — MO-7 for its confirm; the button itself does not animate
- [x] **Density notes** — unchanged; ≥ `size.target.min`
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — unchanged
- [x] **Data contract confirmed** — unchanged; "Flatten" stays its word and the kill switch's, never a trade group's (pack §5)
- [ ] **Contrast and CVD** — N/A — no colour pair introduced
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with this ticket's PR 2
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1043 (pack §17)

## Handoff checklist — CMP-124 TradeGroupSummaryCard (E34-D05, #1043)

- [x] **Final Penpot link** — page `E34-D03 Trade-group manager hi-fi`, board D3-06 (`DS/cmp-124-summary`) and boards D3-01 … D3-03 (pack §0)
- [x] **Variants × States matrix** — D03 §5.1 over SD-38 … SD-53: collapsed, expanded, partial failure, unwind incomplete, unknown, divergent
- [x] **Keyboard table** — D04 §4.4: one stop for the grid; arrows by row; `Enter` on a row header opens the drawer; `Shift+F10` the row menu; `Ctrl+W` and `Ctrl+Shift+W` inert on the tab (D04 F-05)
- [x] **Accessible name / role table** — a treegrid row (level 1), `aria-expanded`; in the drawer a `region` named `e34.s062.drawer.region`; the summary `aria-live="off"`
- [x] **Live data** — `trade_groups` coalesced to 5 Hz (`14`:1523); a group word through one polite region per panel at ≤ 1 per 2 s (LR-11); a rejection one one-shot alert (LR-04)
- [x] **Motion pair** — MO-6 (expansion a cut), MO-3 and MO-4 (the summary and the banner, cuts in both modes)
- [x] **Density notes** — `size.row.compact` (24 px) and `size.row.comfortable`; the expand control ≥ `size.target.min` (D04 F-16)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §5.1 replaces `15`'s "inherits CMP-050" through D03's A-4 (its PR 2)
- [x] **Data contract confirmed** — `group` is the served `TradeGroup` (`22`:21787) from `listTradeGroups` and `trade_groups`; no client aggregate (pack rule 1); DG-07, DG-09, DG-11 stamped "not served yet"
- [ ] **Contrast and CVD** — PENDING — D03 §8.1 and §8.2 measure them; not yet rows of `tools/contrast/pairs.mjs`
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with this ticket's PR 2
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1043 (pack §17)

## Handoff checklist — CMP-229 ArmToggle (E34-D05, #1043)

- [x] **Final Penpot link** — page `E34-D02 Trade-group ticket hi-fi`, boards D2-03 and D2-04 (B16, B25; pack §0)
- [x] **Variants × States matrix** — unchanged states; the group usage line adds the pill text `e34.s061.arm.pill` (D02 §2.1)
- [x] **Keyboard table** — D04 §5 KB-04: `Ctrl+Shift+T` arms or disarms, the Ticket context's command, unchanged
- [x] **Accessible name / role table** — unchanged; the pill's text is `e34.s061.arm.pill`
- [ ] **Live data** — N/A — the arm state changes on the user's press, not by stream
- [x] **Motion pair** — unchanged in `15`; a cut
- [x] **Density notes** — unchanged
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — unchanged
- [x] **Data contract confirmed** — `createTradeGroup` answers `403` `session_not_armed` without the arm (`22`:638); the pill is an affordance (pack rule 6)
- [ ] **Contrast and CVD** — N/A — no colour pair introduced
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with this ticket's PR 2
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1043 (pack §17)

## Handoff checklist — CMP-232 LimitsChip (E34-D05, #1043)

- [x] **Final Penpot link** — page `E34-D03 Trade-group manager hi-fi`, board D3-06 (`DS/cmp-232-budget`); SCR-061's use on board D2-02 (B07)
- [x] **Variants × States matrix** — D03 §5.2, the `budget` variant: waiting, refilled, expired, disclosure open, unknown deadline
- [x] **Keyboard table** — the disclosure is a button; `Enter` / `Space` opens it, focus stays; no global binding touched
- [x] **Accessible name / role table** — the pill's text is `e34.shared.budget.wait`; the digits `aria-live="off"`
- [x] **Live data** — announced at entry, at most once per 10 s, once at the outcome (LR-09, `e34.shared.budget.announce`; D04 F-15)
- [x] **Motion pair** — MO-5: a 1 Hz text swap in both modes
- [x] **Density notes** — the binding pill's heights in both densities (D03 §5.2)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §5.2's tokens enter `15` through D03's A-5 (its PR 2)
- [ ] **Data contract confirmed** — PENDING — DG-02: no served deadline, refill or remaining budget (E34-T02 #859)
- [ ] **Contrast and CVD** — PENDING — D03 §8.1; not yet a row of `tools/contrast/pairs.mjs`
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with this ticket's PR 2
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1043 (pack §17)

## Handoff checklist — LegStatusCell (its CMP id at E34-D03's PR 2) (E34-D05, #1043)

- [x] **Final Penpot link** — page `E34-D03 Trade-group manager hi-fi`, board D3-06 (`DS/leg-status-cell`)
- [x] **Variants × States matrix** — D03 §5.3: the LS and GS rows, each to its served value in pack §4.3; the stories EveryLegState … ReducedMotion
- [x] **Keyboard table** — not focusable itself; the grid's roving focus lands on its cell (D04 §4.4); no key of its own
- [x] **Accessible name / role table** — the word is the cell's text; the glyph `aria-hidden`; "—" read as `e34.cell.ls16` (D04 F-10)
- [x] **Live data** — a status change through one polite region per panel at ≤ 1 per 2 s, latest only; a rejection is the summary's one-shot alert, never the cell's
- [x] **Motion pair** — MO-1, MO-2: cuts in both modes; no status change animates (`16`:259)
- [x] **Density notes** — the cell inset `space.inset.xs`; it fills the row height in both densities
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §5.3's Tokens line enters `15` through D03's A-6 (its PR 2)
- [x] **Data contract confirmed** — `LegStatus` (`22`:18968), `TradeGroupStatus` (`22`:18962), `native_sl_confirmed` (`22`:21754); DG-02, DG-03, DG-05, DG-06, DG-09, DG-10 stamped "not served yet"
- [ ] **Contrast and CVD** — PENDING — D03 §8.1 and §8.2; D04 §9 and §10 measure every status pair
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with this ticket's PR 2
- [ ] **Sign-off** — PENDING — the owner's `approved` on #1043 (pack §17)
