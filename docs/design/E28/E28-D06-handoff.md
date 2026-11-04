# E28-D06 — Hand-off (§A–§G for SCR-130, SCR-131, SCR-132, SCR-133, SCR-062 and the SCR-061 preview)

The spec is [E28-D06.md](E28-D06.md); every §, C-, G6-, H-, Q- and R- id below without a prefix is the spec's. The copy deck as data is `E28-D06-copy-deck.jsonl`. Nothing here edits `14`, `15`, D02, D03, D04 or D05: §C's rows are copy-ready and applied by the closing PR after #5482 merges (R-2). §G carries the `16` §11.4 checklist of each component contract the six screens change; every D03 cite reads at the base, and every use of #5482 is PENDING at its head `3b23ab11a` (R-1).

## §A Placement

| Component | Contract in the parents   | Screens                   | Change                   |
| --------- | ------------------------- | ------------------------- | ------------------------ |
| CMP-254   | D03 §9.1 DS-A (`D03`:380) | SCR-133                   | new: SymbolMatrixCell    |
| CMP-255   | D03 §9.2 DS-B (`D03`:391) | SCR-062                   | new: ReadinessStrip      |
| CMP-256   | D03 §9.3 DS-C (`D03`:407) | SCR-061                   | new: OverrideMarker      |
| CMP-138   | D03 §9.4 DS-D (`D03`:418) | SCR-130, SCR-131, SCR-061 | `size`: chip, meter, row |
| CMP-049   | D03 §9.6 DS-F (`D03`:441) | all six                   | the reason row           |
| CMP-028   | D03 §9.7 DS-G (`D03`:449) | SCR-132, SCR-133, SCR-061 | `tone="gap"`             |
| CMP-044   | D03 §9.8 DS-H (`D03`:457) | SCR-131, SCR-132, SCR-133 | the diff entry           |
| CMP-050   | D03 §9.9 DS-I (`D03`:464) | SCR-132                   | `template` variant       |

CMP-158 is used as built (DS-E, `D03`:434) and gets no checklist; every other component of spec §3.2 is used as `15` states it.

## §B The contract table

The `15` fields are D03's §14 rows, applied by #5482 (R-1); until it merges, D03 §9 is the contract the stories build against.

| Component | Props                    | States                                       | A11y                                       | Motion    | Data contract                   |
| --------- | ------------------------ | -------------------------------------------- | ------------------------------------------ | --------- | ------------------------------- |
| CMP-254   | D03 §9.1 Props           | three × four; T2 (D03 §6.1)                  | D05 §3, §5.1, AN rows; F-02, F-03, F-07    | M-7, NA-6 | the profile's symbol lists      |
| CMP-255   | D03 §9.2 Props           | ready, not ready, unknown, disabled, loading | its text is the name; D05 F-04             | M-6, NA-5 | `readiness.ready` (`22`:21566)  |
| CMP-256   | D03 §9.3 Props           | default, with cap                            | the host field's description; D05 AN rows  | NA-9      | the served cap (E28-S05)        |
| CMP-138   | `size?`, D03 §9.4        | ok, warn, lock, stale, unknown               | `role="meter"`, `aria-valuetext`; D05 F-14 | NA-8      | `getRiskSummary` (`22`:15055)   |
| CMP-049   | the reason row, D03 §9.6 | under warn, skipped, blocked                 | the parent row's `aria-describedby`; F-13  | NA-7      | `rejection`, `warnings`         |
| CMP-028   | `tone="gap"`, D03 §9.7   | one                                          | `role="note"`, not live                    | none      | none (chrome)                   |
| CMP-044   | the diff entry, D03 §9.8 | DiffSummary, relaxing                        | a list, "relaxing" in the text             | M-2       | the read and the edited profile |
| CMP-050   | `template`, D03 §9.9     | Template, not applicable                     | radio card; D05 F-10                       | none      | none (placeholders, D02 D17)    |

## §C Copy-ready rows (applied by the closing PR after #5482 merges; R-2)

Each row adds one line to its `14` entry, after the entry's last pointer line (BQ-13 as ruled). The anchor below is that line at the base; #5482, #840 and #841 add pointer lines after it, so the closing PR finds the entry's last pointer line by content and adds the row after it.

| A   | Entry   | Anchor (`14`) | New line                                                                                                                                                                          | Owner       |
| --- | ------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| A-1 | SCR-130 | `14`:2757     | "- **Hand-off pack (E28-D06):** [E28-D06.md](../design/E28/E28-D06.md) §4.1 (approved on #842; the copy deck keyed by code, the bindings, the events and the sign-off checklist)" | this ticket |
| A-2 | SCR-131 | `14`:2789     | "- **Hand-off pack (E28-D06):** [E28-D06.md](../design/E28/E28-D06.md) §4.2 (approved on #842; the copy deck keyed by code, the bindings, the events and the sign-off checklist)" | this ticket |
| A-3 | SCR-132 | `14`:2802     | "- **Hand-off pack (E28-D06):** [E28-D06.md](../design/E28/E28-D06.md) §4.3 (approved on #842; the copy deck keyed by code, the bindings, the events and the sign-off checklist)" | this ticket |
| A-4 | SCR-133 | `14`:2814     | "- **Hand-off pack (E28-D06):** [E28-D06.md](../design/E28/E28-D06.md) §4.4 (approved on #842; the copy deck keyed by code, the bindings, the events and the sign-off checklist)" | this ticket |
| A-5 | SCR-062 | `14`:1530     | "- **Hand-off pack (E28-D06):** [E28-D06.md](../design/E28/E28-D06.md) §4.5 (approved on #842; the copy deck keyed by code, the bindings, the events and the sign-off checklist)" | this ticket |
| A-6 | SCR-061 | `14`:1515     | "- **Hand-off pack (E28-D06):** [E28-D06.md](../design/E28/E28-D06.md) §4.6 (approved on #842; the copy deck keyed by code, the bindings, the events and the sign-off checklist)" | this ticket |

Every other change the pack needs is a routed row with its owner (spec §14, §17).

## §D Storybook

The lists are D03 §9's, under `15`'s titles; the stories are built by E28-S01 … S04 (spec §12) and checked by E28-D07 against this list.

| Component | Stories                                                                                                                 | Source    |
| --------- | ----------------------------------------------------------------------------------------------------------------------- | --------- |
| CMP-254   | Allowed, Blocked, NotAllowed, ViaAllSymbols, OpenPosition, Changed, ReadOnly, Focus, Compact, Comfortable, HighContrast | `D03`:388 |
| CMP-255   | AllReady, SomeNotReady, StateUnknown, MemberDisabled, Loading, Compact, Comfortable, HighContrast                       | `D03`:404 |
| CMP-256   | Override, OverrideWithCap, Compact, Comfortable, HighContrast                                                           | `D03`:415 |
| CMP-138   | added: Chip, Meter, Row, ChipUnknown, RowNearCap                                                                        | `D03`:432 |
| CMP-049   | added: ReasonRow, ReasonRowCompact                                                                                      | `D03`:447 |
| CMP-028   | added: Gap                                                                                                              | `D03`:455 |
| CMP-044   | added: DiffSummary, DiffSummaryRelaxing                                                                                 | `D03`:462 |
| CMP-050   | added: Template, TemplateNotApplicable                                                                                  | `D03`:469 |

**Cross-cutting (PROPOSED).** Every story renders at compact and comfortable, in dark and light. A component one of D04's rows animates gets a `ReducedMotion` story that sets `data-motion="reduce"` on the root. Fixtures are deterministic: the labels `Main`, `sub_001` … `sub_004`, the US-PROF-002 figures, no `Date.now`.

## §E Test hooks (PROPOSED: the parents are silent)

- **Role and name first.** Tests query the accessibility tree by D05 §6's names and the deck's `name` rows.
- **Strings byte for byte.** A test asserts each rendered deck string equals its row's `text`, fills replaced by the fixture's; a `served` row asserts the client adds nothing around the served words.
- **One string per code.** For each of `T`'s eleven codes a test sends the served answer and asserts the deck row of spec §8.2 renders, on every screen that can receive it.
- **Announcements on a fake clock.** LR-01 at most once per 1 000 ms; LR-05 at most once per 2 000 ms across the list; nothing on mount.
- **State attributes.** `data-state` on each screen root with the D03 S-row name; `data-motion` read from the root only.
- **No `data-testid`** unless an element has no role.

## §F References

**Motion:** D04 §2–§5 by id, merged as #5618 (R-3). **Accessibility:** D05 §3–§16 by id, merged as #5619 (R-4). **Tokens and redlines:** D03 §2–§11 by state row. **The deck as data:** one header line (the pack, the version, the base, the fields, the status words, the render values, the freeze note and `T`'s eleven codes), then one row per string. A builder reads the deck, not this file, for any string.

## §G Handoff checklists (`16` §11.4)

One block per component contract the six screens change (`16` §13.3 item 8). Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`; `[ ] PENDING — <reason>` marks a line still open, with what closes it. Table 1 is §D's list for the component; tables 2 and 3 are D05 §5 and §6's rows; table 4 is spec §6; table 5 is D05 §9's live regions; each is given once, by reference.

## Handoff checklist — CMP-254 SymbolMatrixCell (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 05, 09 and 10 on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-254 list (11 stories) over D03 §9.1's three states × default, hover, focus-visible, changed and read-only
- [ ] **Keyboard table** — PENDING — D05 §5.1 (KB rows): one Tab stop, arrows, Space toggles, the cell menu by Shift+F10; open until D05 F-03 (the bulk trigger, A-05, A-06) is applied (H-1)
- [x] **Accessible name / role table** — a `gridcell` holding a checkbox named "{account}, {symbol}, {state}" (deck `e28.name.matrix_cell`; D05 §6)
- [x] **Live data** — LR-08 and LR-10: polite, at most once a second for a staged bulk change; nothing per cell
- [x] **Motion pair** — M-7 (a cut in both modes); NA-6 (no cross-fade between states)
- [ ] **Density notes** — PENDING — 32 × 32 comfortable, 24 × 24 compact (D03 §9.1); D05 F-02's `scroll-padding` (A-04) open (H-1)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §9.1's Tokens line becomes the `15` field with CMP-254's entry (R-1)
- [x] **Data contract confirmed** — `all_symbols`, `allowed_symbols`, `blocked_symbols` per account; "(pos)" from `listPositions`, served at the base (spec §9)
- [ ] **Contrast and CVD** — PENDING — P6–P9 in D03 §11.1; the renders of boards 05 and 09 come with R-1; DSR-2 registers the pairs
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-255 ReadinessStrip (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 06 and 10 on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-255 list (8 stories) over ready, not ready, unknown, disabled and loading
- [x] **Keyboard table** — no stop of its own: the strip is text inside its row; the expander is the row's (D05 F-12, A-18)
- [ ] **Accessible name / role table** — PENDING — the text "2 of 3 ready" is the name and the segments are `aria-hidden` (D03 §9.2); D05 F-04's dashed unknown outline (A-07 … A-09) open (H-1)
- [x] **Live data** — LR-05: polite, at most once per 2 s across the list; the strip itself is not a live region
- [x] **Motion pair** — M-6, a cut in both modes; NA-5 (segments never move)
- [x] **Density notes** — segments 12 × 8 px comfortable, 8 × 6 px compact (D03 §9.2); not a target
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §9.2's Tokens line becomes the `15` field with CMP-255's entry (R-1)
- [x] **Data contract confirmed** — `readiness.ready` (`22`:21566), `.total`, `.members[].ready`, `.reason`; never counted by the client
- [ ] **Contrast and CVD** — PENDING — D05 CV-05 measures the unknown segment's outline (F-04); the renders come with R-1
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-256 OverrideMarker (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 07, 09 and 10 on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-256 list (5 stories): pill, pill with the cap line
- [x] **Keyboard table** — not focusable; focus belongs to the host field (D03 §9.3); the edit gesture is E34-D02's
- [x] **Accessible name / role table** — the word "override" is text; the host field's description is "Override. Capped by profile: {n}x" (deck `e28.name.override`)
- [ ] **Live data** — N/A — a static marker
- [ ] **Motion pair** — N/A — none animated (NA-9)
- [x] **Density notes** — `space.inset.xs`, the pill at the row's height in both densities (D03 §9.3); not a target
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §9.3's Tokens line becomes the `15` field with CMP-256's entry (R-1)
- [x] **Data contract confirmed** — the served cap of the leg's profile; E28-S05 builds the override against ADR-0040 Decision 1
- [ ] **Contrast and CVD** — PENDING — P13 and P29 in D03 §11.1; the renders come with R-1
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-138 RiskCapMeter (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 01, 02, 07 and 10 (the three sizes side by side) on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-138 additions (5 stories) over `chip`, `meter`, `row` × ok, warn, lock, stale, unknown
- [x] **Keyboard table** — not focusable; read on demand as `role="meter"` inside its row or field
- [x] **Accessible name / role table** — `role="meter"` with `aria-valuetext` and the state word, the same at every size (D03 §9.4)
- [x] **Live data** — none: read on demand (LR-13); the number snaps to the served value
- [ ] **Motion pair** — N/A — none animated (NA-8)
- [ ] **Density notes** — PENDING — the three sizes of D03 §9.4; D05 F-14 moves the `row` text to `type.num.sm` (A-20)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — the appended Props field (D03 §14 A-4) lands with R-1
- [x] **Data contract confirmed** — `getRiskSummary` (`22`:15055); "unknown" and the hatched track when absent
- [ ] **Contrast and CVD** — PENDING — P16, P24, P30, P31 in D03 §11.1; the renders come with R-1
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-049 Table (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 01, 05, 06 and 07 on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-049 additions (2 stories): the reason row in both densities
- [ ] **Keyboard table** — PENDING — CMP-049's grid as shipped (one Tab stop, arrows); D05 F-13 makes the preview a grid (A-19)
- [x] **Accessible name / role table** — the reason row is its parent row's description (`aria-describedby`, D03 §9.6)
- [x] **Live data** — LR-01 for the preview's result line; none per row
- [x] **Motion pair** — none per row (NA-4, NA-7); M-11 and M-12 for the grids
- [x] **Density notes** — 32 px comfortable, 24 px compact rows (D03 §2.1); the reason row follows its record
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — the appended States field (D03 §14 A-6) lands with R-1
- [x] **Data contract confirmed** — `legs[].rejection.code`, `.message` and `warnings` (`22`:25086); D02 §10's words
- [ ] **Contrast and CVD** — PENDING — D05 F-01 (A-01, A-03 and #840's A-1, the joint stale-preview rule: the text at full opacity, decoration only muted) open (H-1)
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-028 Callout (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 04, 05, 07 and 10 on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-028 addition (`Gap`)
- [x] **Keyboard table** — not focusable: a note
- [x] **Accessible name / role table** — `role="note"`, its text the name: "Not yet served: {route} ({gap})" (deck `e28.gap.not_yet_served`)
- [ ] **Live data** — N/A — static, not live (D03 §9.7)
- [ ] **Motion pair** — N/A — none animated
- [x] **Density notes** — the callout's own padding in both densities; not a target
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — the appended Props field (D03 §14 A-7) lands with R-1
- [ ] **Data contract confirmed** — N/A — chrome; spec §0 and R-5 retire three of its uses (G-6, G-8's positions half, G-9)
- [ ] **Contrast and CVD** — PENDING — no status hue (D03 §9.7); its pair is in D03 §11.1, the renders with R-1
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-044 ConfirmDialog (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 03, 04 and 05 on the page `E28-D03 Hi-fi` (R-1); D05 F-19 (Cancel missing on board 05's confirms) open (H-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-044 additions (2 stories): the diff summary, with a relaxing entry
- [x] **Keyboard table** — focus on Cancel at open, `Esc` cancels, focus returns to the opener or D05 §4's target (F-11, A-17)
- [x] **Accessible name / role table** — `alertdialog` for a confirm; the diff a list, "relaxing" in the text (D03 §9.8)
- [x] **Live data** — none: the dialog takes focus
- [x] **Motion pair** — M-2: E05-D03 row 2a and its reduce cell; the step-up replaces the summary under the same scrim
- [x] **Density notes** — dialogs keep comfortable in both densities (D03 §3.2)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — the appended States field (D03 §14 A-8) lands with R-1
- [x] **Data contract confirmed** — the read profile against the edited one; the relaxing mark as the audit record labels it (`22`:3936)
- [ ] **Contrast and CVD** — PENDING — P13 in D03 §11.1; the renders come with R-1
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)

## Handoff checklist — CMP-050 Card (E28-D06, #842)

- [ ] **Final Penpot link** — PENDING — boards 04 and 10 on the page `E28-D03 Hi-fi` (R-1)
- [x] **Variants × States matrix** — table 1 = §D's CMP-050 additions (2 stories): template, not applicable
- [x] **Keyboard table** — a radio card in a `radiogroup`: arrows move, Space selects; the not-applicable card is reached and never checked (D05 F-10, A-16)
- [x] **Accessible name / role table** — `role="radio"`; the not-applicable reason is its description (deck `e28.template.demo_only`)
- [ ] **Live data** — N/A — static cards
- [ ] **Motion pair** — N/A — none animated
- [x] **Density notes** — cards keep comfortable inside the modal (D03 §5)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — the appended Props field (D03 §14 A-9) lands with R-1
- [ ] **Data contract confirmed** — N/A — placeholders until E28-S02 sets the values (D02 D17); no template route (G-7)
- [ ] **Contrast and CVD** — PENDING — P6 and P32 in D03 §11.1; the renders come with R-1
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards (R-1)
- [ ] **Sign-off** — PENDING — the owner's `approved` on #842 (spec §16)
