# E24-D05 — Hand-off (§A–§F for the derivatives panel, SCR-054)

The spec is [E24-D05.md](E24-D05.md); every §, C-, G- and Q- id below without a prefix is the spec's. The copy deck as data is `E24-D05-copy-deck.jsonl`. Nothing here edits `14`, `15`, D02, D03 or D04: §C's rows are copy-ready, each applied by its named owner, and A-1 and A-2 by this ticket's closing PR after #5464 merges. Old text is verbatim at the base `e078bf030d`.

## §A Placement

| Component | `15` heading | Screens              | Contract in the pack |
| --------- | ------------ | -------------------- | -------------------- |
| CMP-186   | `15`:2403    | SCR-054              | spec §4.1            |
| CMP-126   | `15`:1561    | SCR-054              | spec §4.2            |
| CMP-127   | `15`:1571    | SCR-054 (price pane) | spec §4.3            |
| CMP-227   | `15`:2932    | SCR-054, SCR-058     | spec §4.4            |

Every other component on SCR-054 is used as `15` states it (spec §3.2); none needs a variant this pack defines.

## §B The contract table

`15`'s fields today are the merged text; D03's rewrites (`D03`:523–540, A-1 … A-16) replace them in #661's PR 2. Until then the spec's §4 tables are the contract the stories build against.

| Field         | CMP-186                      | CMP-126                | CMP-127                                    |
| ------------- | ---------------------------- | ---------------------- | ------------------------------------------ |
| Props         | spec §4.1 (`D03`:488)        | spec §4.2 (`D03`:497)  | spec §4.3 (`D03`:505)                      |
| States        | spec §6; D03 A-14            | S54-19 … S54-31        | S54-40, the threshold, LOD shed            |
| Tokens        | `D03`:491                    | `D03`:499              | `D03`:507                                  |
| A11y          | D04 A-08 … A-21; LR-4 … LR-6 | D04 A-06; LR-1 … LR-3  | D04 A-02; the mirror name (`D03`:506)      |
| Motion        | M-02 … M-07                  | M-01, M-02             | M-03 (the bucket's bar, not the marker)    |
| GPU vs DOM    | `D03`:489                    | DOM                    | GPU overlay with a DOM mirror              |
| Data contract | the spec's Wire column       | the spec's Wire column | the spec's Wire column; public prints only |
| Storybook     | §D                           | §D                     | §D                                         |

## §C Copy-ready rows (A-1 and A-2 applied by the closing PR; A-3 and A-4 PROPOSED to their owners)

| A   | File and line           | Old                                                 | New                                                                                                                                                                                                                                 | Owner                    |
| --- | ----------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| A-1 | `14`:1337, a line after | —                                                   | "- **Hand-off pack:** [E24-D05.md](../design/E24/E24-D05.md) v0 (E24-D05; owner approval pending; the copy deck, the prop tables, the `deriv.*` defaults and the sign-off checklist)"                                               | this ticket              |
| A-2 | `14`:1330               | "CMP-199 ChartLegend, CMP-227 EstimatedBadge."      | "CMP-199 ChartLegend, CMP-227 EstimatedBadge; and, as E24-D03 binds them, CMP-003, CMP-004, CMP-007, CMP-011, CMP-016, CMP-020, CMP-026, CMP-029, CMP-035, CMP-044, CMP-049, CMP-069, CMP-078, CMP-189, CMP-197, CMP-216, CMP-239." | this ticket (`14` owner) |
| A-3 | `D03`:253               | "the notional field CMP-005 on `color.surface.app`" | "the notional field CMP-007 TextInput on `color.surface.app`" (C-4)                                                                                                                                                                 | the D03 lane (#661)      |
| A-4 | `D03`:268               | "Cluster (×N)"                                      | "Cluster (prints)" (D04 F-5; deck `derivatives.table.liquidations.cluster`)                                                                                                                                                         | the D03 lane (#661)      |

Every other change the pack needs is a routed row with its owner (spec §14): D03's A-1 … A-16 in #661's PR 2, D04's A-1 and A-2 in #662's PR 2.

## §D Storybook

The lists are D03 §17's (`D03`:544–546), under its titles; the stories are built by E24-S01 … S08 and checked by E24-D06 against this list.

| Component | Title                           | Stories                                                                                                                                                                                                                                                                                                                                                                                               |
| --------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-186   | `ChartEngine/OiFundingLiqPane`  | OiOnly, FundingOnly, LiquidationBars, Combined, OiDelta, QuadrantsOff, NoSample, NativeGranularity, FundingBars, FundingAnnualised, FundingPredictedNa, LiqHeatmap, LiqCascade, LiqPartialCoverage, LiqGap, ZonesEnabled, RecordedHistogram, Backfilling, RetryBand, StaleT1, StaleT2, Delayed, Collapsed, TableAlternative, Narrow360, Dense, HighContrast, Light, Greyscale, ReducedMotionIdentical |
| CMP-126   | `Trading/FundingCountdown`      | Running, UnderOneHour, ImminentPay, ImminentReceive, ImminentNoPosition, ImminentTwoAccounts, ImminentDemoAndLive, UnderOneMinute, Settlement, NextTimeUnknown, PredictedNa, IntervalChanged, AtCap, AnnualisedFirst, Stale, Light, HighContrast, Greyscale                                                                                                                                           |
| CMP-127   | `ChartEngine/LiquidationMarker` | LongLiquidated, ShortLiquidated, Clustered, BelowThresholdHidden, Hover, FocusVisible, Stale, LodShed, Light, HighContrast, Greyscale                                                                                                                                                                                                                                                                 |
| CMP-227   | as `15`:2943                    | Inline and Marker carry the SCR-054 bindings, `detector: "funding"` and `"liquidation_cluster"`                                                                                                                                                                                                                                                                                                       |

**Cross-cutting (PROPOSED).** Every story renders at compact and comfortable, in dark and light. A component one of D04's moments animates (CMP-186: M-02, M-03, M-05, M-06; CMP-126: M-02) gets a `ReducedMotion` story that sets `data-motion="reduce"` on the root. The fixtures are deterministic: BTCUSDT, the clock 13:42:05 UTC, the illustrative values of D02 §2, no `Date.now`.

## §E Test hooks (PROPOSED: the parents are silent)

- **Role and name first.** Tests query the accessibility tree by the roles and names of D04 §10 and the deck's `name` rows.
- **Strings byte for byte.** A test asserts each rendered deck string equals its row's `text`, with the sample figures replaced by the fixture's.
- **Announcements on a fake clock.** LR-1 and LR-2 fire once at 300 000 and 60 000 ms and never on mount inside a window; LR-4 fires at most once per 5 000 ms at 500 prints/s.
- **State attributes.** `data-state` on each sub-pane with the §6 state name; `data-motion` read from the root only.
- **No `data-testid`** unless an element has no role.

## §F References and the deck as data

**Motion:** D04 §2 (`D04`:47–53) and §3–§8, by reference. **Accessibility:** D04 §9–§11 (`D04`:113–120, :140–170), its findings (§12) and its checklist for E24-Q04 (§13). **Tokens:** D03 §3–§11 by state row. **The deck as data:** one header line (the pack, the version, the base, the D04 ref, the status and provenance words), then one row per string with `key`, `text`, `screen`, `kind`, `where`, `status`, `owner`, `provenance`, `source`, `consumer`, and `quote` or `ruling` where needed. A builder reads the deck, not this file, for any string.
