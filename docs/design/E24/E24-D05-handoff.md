# E24-D05 — Hand-off (§A–§G for the derivatives panel, SCR-054)

The spec is [E24-D05.md](E24-D05.md); every §, C-, G- and Q- id below without a prefix is the spec's. The copy deck as data is `E24-D05-copy-deck.jsonl`. Nothing here edits `14`, `15`, D02, D03 or D04: §C's rows are copy-ready, each applied by its named owner, and pack A-1 and A-2 by a last commit on this ticket's PR 1b at the owner's approval. Old text is verbatim at the base `main` `a7d659a5be`. §G carries the `16` §11.4 checklist of each component contract SCR-054 changes.

## §A Placement

| Component | `15` heading | Screens              | Contract in the pack |
| --------- | ------------ | -------------------- | -------------------- |
| CMP-186   | `15`:2422    | SCR-054              | spec §4.1            |
| CMP-126   | `15`:1564    | SCR-054              | spec §4.2            |
| CMP-127   | `15`:1574    | SCR-054 (price pane) | spec §4.3            |
| CMP-227   | `15`:2951    | SCR-054, SCR-058     | spec §4.4            |

Every other component on SCR-054 is used as `15` states it (spec §3.2), with one exception this pack does not define: CMP-199's row-0 mode toggle and note rows (CN-7, `D03`:517), a change request to the E11-D02 D12 owner.

## §B The contract table

`15`'s fields today are the merged text; D03's rewrites (`D03`:523–540, A-1 … A-16) replace them in #661's PR 2. Until then the spec's §4 tables are the contract the stories build against.

| Field         | CMP-186                      | CMP-126                                                                               | CMP-127                                    |
| ------------- | ---------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------ |
| Props         | spec §4.1 (`D03`:488)        | spec §4.2 (`D03`:497)                                                                 | spec §4.3 (`D03`:505)                      |
| States        | spec §6; D03 A-14            | S54-19 … S54-31 and E08-D06's (spec §4.5)                                             | S54-40, the threshold, LOD shed            |
| Tokens        | `D03`:491                    | `D03`:499                                                                             | `D03`:507                                  |
| A11y          | D04 A-08 … A-21; LR-4 … LR-6 | E08-D06's table 3, the base (spec §4.5; D04 A-06's `timer` is point R-3); LR-1 … LR-3 | D04 A-02; the mirror name (`D03`:506)      |
| Motion        | M-02 … M-07                  | M-01, M-02                                                                            | M-03 (the bucket's bar, not the marker)    |
| GPU vs DOM    | `D03`:489                    | DOM                                                                                   | GPU overlay with a DOM mirror              |
| Data contract | the spec's Wire column       | the spec's Wire column                                                                | the spec's Wire column; public prints only |
| Storybook     | §D                           | §D                                                                                    | §D                                         |

## §C Copy-ready rows (pack A-1 and A-2 at the owner's approval; A-3 … A-9 PROPOSED to their owners; A-10 and A-11 pending on `15`)

Pack A-1 and A-2 land in a last commit on PR 1b after the owner's approval, so their text is written as of that day. A-1 sits after the last pointer line of `14` SCR-054, found by content (today D04's line). A-5 … A-9 apply only if the owner answers Q-1 "no" (spec §8.3); until then no merged line changes. A-10 and A-11 are the two pending rewrites of `15`'s CMP-126 entry; the amended entry arbitrates between them (spec §4.5).

| A    | File and line           | Old                                                                                         | New                                                                                                                                                                                                                                                                              | Owner                                                           |
| ---- | ----------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| A-1  | `14`:1343, a line after | —                                                                                           | "- **Hand-off pack:** [E24-D05.md](../design/E24/E24-D05.md) (E24-D05; approved on #663; the copy deck, the prop tables, the `16` §11.4 checklists, the `deriv.*` defaults and the sign-off checklist)"                                                                          | this ticket                                                     |
| A-2  | `14`:1335               | "CMP-186 OiFundingLiqPane, CMP-188 PriceAxis, CMP-199 ChartLegend, CMP-227 EstimatedBadge." | "CMP-186 OiFundingLiqPane, CMP-188 PriceAxis, CMP-199 ChartLegend, CMP-227 EstimatedBadge; and, as E24-D03 binds them, CMP-003, CMP-004, CMP-007, CMP-011, CMP-016, CMP-020, CMP-026, CMP-029, CMP-035, CMP-044, CMP-049, CMP-069, CMP-078, CMP-189, CMP-197, CMP-216, CMP-239." | this ticket (`14` owner)                                        |
| A-3  | `D03`:253               | "the notional field CMP-005 on `color.surface.app`"                                         | "the notional field CMP-007 TextInput on `color.surface.app`" (C-4: D04 A-25 gives it `textbox` with `inputmode="numeric"`, `D04`:181; CMP-008 rejected, it is a `spinbutton`)                                                                                                   | the D03 lane (#661)                                             |
| A-4  | `D03`:268               | "Cluster (×N)"                                                                              | "Cluster (prints)" (D04 F-5; deck `derivatives.table.liquidations.cluster`)                                                                                                                                                                                                      | the D03 lane (#661); `D02`:423 keeps ×N, for D02's next toucher |
| A-5  | `D03`:170               | "you pay ≈ 12.40 USDT"                                                                      | S54-26: "you pay about 12.40 USDT, predicted," (deck `derivatives.countdown.imminent.pay`)                                                                                                                                                                                       | the D03 lane (#661), after Q-1                                  |
| A-6  | `D03`:171               | "you receive ≈ 12.40 USDT"                                                                  | S54-27: "you receive about 12.40 USDT, predicted," (deck `derivatives.countdown.imminent.receive`)                                                                                                                                                                               | the D03 lane (#661), after Q-1                                  |
| A-7  | `D03`:173               | "you pay ≈ 12.40 USDT on Sub-1 · LIVE"                                                      | S54-29: each line "you pay about 12.40 USDT, predicted," and the summed form "you pay about 24.80 USDT, predicted," (deck `derivatives.countdown.imminent.live_line`, `.summed`)                                                                                                 | the D03 lane (#661), after Q-1                                  |
| A-8  | `D03`:174               | "you pay ≈ 12.40 USDT"                                                                      | S54-30: "you pay about 12.40 USDT, predicted," (deck `derivatives.countdown.imminent.under_1m`)                                                                                                                                                                                  | the D03 lane (#661), after Q-1                                  |
| A-9  | `14`:1333               | "you pay ≈ 12.40 USDT"                                                                      | "you pay about 12.40 USDT, predicted", and "you receive about 12.40 USDT, predicted" for the receiving side (C-9)                                                                                                                                                                | the `14` owner, after Q-1                                       |
| A-10 | `15`:1564               | —                                                                                           | pending: E08-D06 A-5's rewrite of the CMP-126 entry, the base contract (R-1 … R-4 settled on its lines)                                                                                                                                                                          | the E08-D06 lane (#174)                                         |
| A-11 | `15`:1564               | —                                                                                           | pending: E24-D03's `predicted: boolean` (required, no default; RULED in #661) as a PROPOSED extension of the amended entry                                                                                                                                                       | the E24-D03 lane (#661)                                         |

Every other change the pack needs is a routed row with its owner (spec §14): D03's A-1 … A-16 in #661's PR 2, and the request rows R-5 and R-6 (spec §4.1). D04's A-1 and A-2 landed with #5548.

## §D Storybook

The lists are D03 §17's (`D03`:544–546), under its titles; the stories are built by E24-S01 … S08 and checked by E24-D06 against this list.

| Component | Title                           | Stories                                                                                                                                                                                                                                                                                                                                                                                               |
| --------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-186   | `ChartEngine/OiFundingLiqPane`  | OiOnly, FundingOnly, LiquidationBars, Combined, OiDelta, QuadrantsOff, NoSample, NativeGranularity, FundingBars, FundingAnnualised, FundingPredictedNa, LiqHeatmap, LiqCascade, LiqPartialCoverage, LiqGap, ZonesEnabled, RecordedHistogram, Backfilling, RetryBand, StaleT1, StaleT2, Delayed, Collapsed, TableAlternative, Narrow360, Dense, HighContrast, Light, Greyscale, ReducedMotionIdentical |
| CMP-126   | `Trading/FundingCountdown`      | Running, UnderOneHour, Positive, Negative, Zero, NoRate, UnderFiveMinutes, ImminentPay, ImminentReceive, ImminentTwoAccounts, ImminentDemoAndLive, ImminentUnderOneMinute, Settlement, Elapsed, ClockSkew, Unknown, PredictedNa, IntervalChanged, AtCap, AnnualisedFirst, InBandState, Suppressed, Light, HighContrast, Greyscale (one list for SCR-054 and SCR-103, spec §4.5)                       |
| CMP-127   | `ChartEngine/LiquidationMarker` | LongLiquidated, ShortLiquidated, Clustered, BelowThresholdHidden, Hover, FocusVisible, Stale, LodShed, Light, HighContrast, Greyscale                                                                                                                                                                                                                                                                 |
| CMP-227   | as `15`:2962                    | Inline and Marker carry the SCR-054 bindings, `detector: "funding"` and `"liquidation_cluster"`                                                                                                                                                                                                                                                                                                       |

**Cross-cutting (PROPOSED).** Every story renders at compact and comfortable, in dark and light. A component one of D04's moments animates (CMP-186: M-02, M-03, M-05, M-06; CMP-126: M-02) gets a `ReducedMotion` story that sets `data-motion="reduce"` on the root. The fixtures are deterministic: BTCUSDT, the clock 13:42:05 UTC, the illustrative values of D02 §2, no `Date.now`.

## §E Test hooks (PROPOSED: the parents are silent)

- **Role and name first.** Tests query the accessibility tree by the roles and names of D04 §10 and the deck's `name` rows; CMP-126's by E08-D06's table 3 (spec §4.5).
- **Strings byte for byte.** A test asserts each rendered deck string equals its row's `text`, with the sample figures replaced by the fixture's.
- **Announcements on a fake clock.** LR-1 and LR-2 fire once at 300 000 and 60 000 ms and never on mount inside a window; LR-4 fires at most once per 5 000 ms at 500 prints/s.
- **State attributes.** `data-state` on each sub-pane with the §6 state name; `data-motion` read from the root only.
- **No `data-testid`** unless an element has no role.

## §F References and the deck as data

**Motion:** D04 §2 (`D04`:62–68) and §3–§8, by reference. **Accessibility:** D04 §9–§11 (`D04`:128–135, :155–185), its findings (§12) and its checklist for E24-Q04 (§13). **Tokens:** D03 §3–§11 by state row. **The deck as data:** one header line (the pack, the version, the base, the status and provenance words, `T` Scope's seven groups), then one row per string with `id` (the key), `text`, `screen`, `kind`, `where`, `status`, `owner`, `provenance`, `source`, `consumer`, and `quote`, `ruling`, `scope` or `q1` where needed. A builder reads the deck, not this file, for any string.

## §G Handoff checklists (`16` §11.4, `16`:570)

One block per component contract SCR-054 changes (`16` §13.3 item 8; `02`:56). Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`; `[ ] PENDING — <reason>` marks a line still open, with what closes it (spec D7). At Done only `[x]` lines and `[ ] N/A — <reason>` lines remain; a PENDING line holds Done (`16`:579, :744). Table 1 is §D's list for the component; tables 2 and 3 are D04 §10's rows; table 4 is spec §7; table 5 is D04 §9.2's live regions (`D04`:128–135); each is given once, by reference.

## Handoff checklist — CMP-186 OiFundingLiqPane (E24-D05, #663)

- [ ] **Final Penpot link** — PENDING — D03's boards 01–03 and 05–10 on the page `E24-D03 Derivatives panel hi-fi` (#661 PR 2); no page id or PNG until that PR pins them (spec §2)
- [x] **Variants × States matrix** — table 1 = §D's CMP-186 list (30 stories) over spec §6's 14 states and the S54 rows (spec §5)
- [x] **Keyboard table** — D04 A-08 … A-21 (`D04`:164–177): per pane the legend toggle, chevron, menu, gutters, plot cursor, action and splitter; no global binding overridden, `Esc` / `Ctrl+K` untouched
- [x] **Accessible name / role table** — D04 A-08 … A-21 and the deck's `name` rows (spec §9.7)
- [x] **Live data** — LR-4 … LR-6: one polite node per sub-pane; a cascade summary at most once per 5 000 ms; nothing per print
- [x] **Motion pair** — M-02 … M-07 with their reduced forms (spec §7)
- [x] **Density notes** — compact 24 px rows, comfortable 32 px, `dense` chart-only (`D03`:261); targets at least 24 × 24 px by padding (`D03`:302)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03's Tokens line (`D03`:491) replaces the `15` field via D03 A-12 (#661 PR 2); the heatmap ramp and the five engine aliases wait for the DS owner (D03-G1, spec §5)
- [x] **Data contract confirmed** — spec §4.1's Wire column against `22` / `23` as shipped at the base, E24-T01 (#5257) included; the gaps are G-5, D02 G1, G2 and NG-15 (spec §14)
- [ ] **Contrast and CVD** — PENDING — D03 §11.1's matrix (`D03`:310); its PROPOSED `pairs.mjs` rows are D03-G4's; the CVD run waits for the drawn boards
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards; until then D04 §13's checklist (`D04`:210–216) carries the criteria
- [ ] **Sign-off** — PENDING — the owner's `approved` on #663 (spec §16)

## Handoff checklist — CMP-126 FundingCountdown (E24-D05, #663)

- [ ] **Final Penpot link** — PENDING — D03's board 04 `funding-header-and-countdown-ladder` (#661 PR 2); E08-D06's board 15 draws the SCR-103 form (`E08H`:138)
- [x] **Variants × States matrix** — table 1 = §D's CMP-126 list, which merges E08-D06's table 1 (`E08H`:152) under spec §4.5
- [ ] **Keyboard table** — N/A — not a stop of its own: the countdown is read inside A-05's roving group (D04 A-06) and binds no key, as in E08-D06
- [x] **Accessible name / role table** — E08-D06's table 3, the base (`E08H`:169): text, `aria-live="off"`, "Next funding in 1 hour 24 minutes, at 08:00 UTC"; D04 A-06's `timer` is point R-3 for the `15` amendment (spec §4.5)
- [x] **Live data** — LR-1 … LR-3: polite once at 300 000 and 60 000 ms; the digits `off`, as E08-D06's table 5
- [x] **Motion pair** — M-01 (a cut in both modes) and M-02 (spec §7)
- [x] **Density notes** — one row, 24 / 32 px; fixed-width `hh:mm:ss`, tabular figures
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — `type.num.base`, `color.text.primary` / `.secondary`, the `color.status.warning.default` border and the `color.status.warning.strong` glyph (`D03`:499); `15`:1564's field changes with pack A-10 and A-11 (C-8)
- [x] **Data contract confirmed** — `ticker.{symbol}` live (`23`:3323–3324) and `/market/funding` history (`22`:5455–5464), spec §4.2; `charges` await D02 G11
- [ ] **Contrast and CVD** — PENDING — the warning border is decorative and the sentence carries it (P27, `D03`:499); the CVD run waits for board 04
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards; D04 §13's checklist meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #663 (spec §16)

## Handoff checklist — CMP-127 LiquidationMarker (E24-D05, #663)

- [ ] **Final Penpot link** — PENDING — D03's board 06 `liquidations-bars-feed-markers-cascade` (#661 PR 2)
- [x] **Variants × States matrix** — table 1 = §D's CMP-127 list (11 stories); S54-40, S54-42, S54-67
- [x] **Keyboard table** — D04 A-02 (`D04`:158): one roving stop, arrows between markers, `Enter` locates; `Esc` dismisses the tooltip (`D03`:506)
- [x] **Accessible name / role table** — a `button` per marker in the DOM mirror, named by the deck's `derivatives.name.marker`
- [ ] **Live data** — N/A — a marker announces nothing; the cascade summary is CMP-186's LR-4
- [ ] **Motion pair** — N/A — none animated: M-03 emphasises the bucket's bar, not the marker
- [x] **Density notes** — the marker follows the chart density; the mirror's buttons at least 24 × 24 px by padding (`D03`:302)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03's Tokens line (`D03`:507) replaces the `15` field via D03 A-8 (#661 PR 2)
- [x] **Data contract confirmed** — public prints, live `23`:3367–3372 and history `22`:20671–20688, spec §4.3; `liquidatedSide` awaits D02 G3, the threshold G4
- [ ] **Contrast and CVD** — PENDING — D03 §11.1 (`D03`:310); P13–P16 are D03-G4's PROPOSED rows
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards; D04 §13's checklist meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #663 (spec §16)

## Handoff checklist — CMP-227 EstimatedBadge (E24-D05, #663)

- [ ] **Final Penpot link** — PENDING — D03's boards 05 and 07 (#661 PR 2)
- [x] **Variants × States matrix** — table 1 = §D's CMP-227 row: `Inline` and `Marker` carry the two SCR-054 bindings
- [x] **Keyboard table** — D04 A-01 (`D04`:157): one stop per band chip in price order, `Enter` opens SCR-058; the funding chip's `Enter` opens CMP-069 inside A-05's group
- [x] **Accessible name / role table** — `button`, "Estimated, Funding rate" and "Estimated, Liquidation cluster" (`D03`:449)
- [ ] **Live data** — N/A — static chips
- [ ] **Motion pair** — N/A — none animated; M-07 is a cut
- [x] **Density notes** — as `15`'s CMP-227 entry; targets at least 24 × 24 px by padding (`D03`:302)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `15`'s CMP-227 Tokens field, unchanged; only the `detector` members are new (D03 A-16)
- [ ] **Data contract confirmed** — PENDING — `detector: "funding"` and `"liquidation_cluster"` are PROPOSED members; the `22` enum is D03-G5's owner's
- [ ] **Contrast and CVD** — PENDING — the chips sit on the funding header and the band; their pairs are in D03 §11.1 (`D03`:310), the CVD run waits for the boards
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PENDING — attached with the boards; D04 §13's checklist meanwhile
- [ ] **Sign-off** — PENDING — the owner's `approved` on #663 (spec §16)
