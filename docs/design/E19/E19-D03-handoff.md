# E19-D03 — Component handoff (`16` §11.4) for CMP-110, CMP-183 and CMP-184

Ticket E19-D03 (#438); spec `docs/design/E19/E19-D03.md` (the spec). This ticket owns the three entries and rewrites them in `15` in the same PR (PROPOSED fields, the spec's D03-A1 … D03-A3). **Status:** text pass; the Penpot and PNG lines are PENDING: no board is drawn yet, and the ref frames and their PNGs come in the boards PR, which closes the ticket (page `E19-D03` in the file `E19-D03 boards`, spec §0). Penpot token sets = `packages/ui/tokens` at `7e8f8034e`. BQ list RULED (comment 6580374205). Owner approval pending (#2701). Built on E19-D02 (`docs/design/E19/E19-D02.md`, PR #5487 at `bed73afaa`), which holds here if #416's PR 1 merges as is and re-pins at its merge.

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3). `[ ] PENDING` marks a line the boards PR or a named ticket closes.

## Handoff checklist — CMP-110 ProfileBar (E19-D03, #438)

- [ ] **Final Penpot link** — PENDING (boards PR): page `E19-D03`, board 04, ref frames `CMP-110 · ProfileBar — ref frame (<state>)`; PNGs `docs/design/E19/img/E19-D03-04-cmp-110-variants.png`
- [x] **Variants × States matrix** — table 1 below; spec §4.1, §4.2
- [x] **Keyboard table** — table 2 (shared, the histogram's roving row); checked against `05` §3.2 / §3.3: no new key, no global binding overridden, `Esc` / `Ctrl+K` untouched
- [x] **Accessible name / role table** — table 3 (shared)
- [x] **Live data** — table 5 (shared); D02's R-4 unchanged
- [ ] **Motion pair** — N/A — every change here is a state flip; recompute choreography and the busy bar are E19-D05's
- [x] **Density notes** — the shared density table
- [x] **Essential-exceptions log** — merged rows under 24 px are not pointer targets; the mirror and the table reach them (D02 §11, `05` §3.4.7)
- [x] **Tokens used** — spec §2.1: `color.profile.bar`, `color.profile.poc`, `color.profile.valuearea`, `color.buy.default`, `color.sell.default`, `color.text.secondary`, `color.text.tertiary`, `color.tpo.letter` (PROPOSED), `color.focus.ring`, `color.chart.focus.ring`, `color.surface.canvas` (the halos and key swatches); patterns `pattern.hatch.estimated`, `pattern.dashed.tested`; equal to the rewritten `15` entry. Buy / sell hue (R6): `color.buy.*` / `color.sell.*`, no hue decided here; E18-D03 (#497) is open, so re-bind if #497 decides otherwise.
- [x] **Data contract confirmed** — `24` §5.1 VolumeProfile / ProfileLevel (`buy_volume`, `sell_volume`, `poc_ticks`, `hvn_ticks`, `lvn_ticks`, `naked_poc_ticks`); gaps D03-G1 … D03-G3 (spec §14.2)
- [ ] **Contrast and CVD** — measured (spec §2.2, §2.3); PENDING: the `pairs.mjs` rows and the exemption drop in E19-T04's token PR (D03-A6), the export sheets in the boards PR
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — the spec's §3, §12 and §17 stand in until the boards; E19-D06 reviews
- [ ] **Sign-off** — PENDING: the owner's `approved` on #438 or the merge of the boards PR

### Table 1 — Variants × States (CMP-110)

| Variant | State                                                                            | Penpot ref frame                               | Story name                                 | Notes                   |
| ------- | -------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------ | ----------------------- |
| volume  | default, value area, POC, HVN, LVN, naked POC anchor, estimated, merged, focused | `CMP-110 · ProfileBar — ref frame (volume)`    | Volume, POC, ValueArea, Hvn, Lvn, NakedPoc | spec §3 rows 1, 3–7, 12 |
| delta   | net buy, net sell, zero delta (tick), untraded (no mark)                         | `CMP-110 · ProfileBar — ref frame (delta)`     | Delta, ZeroDeltaVsUntraded                 | spec §4.3               |
| split   | buy and sell segments, member row                                                | `CMP-110 · ProfileBar — ref frame (split)`     | Split                                      | spec §8                 |
| tpo     | letters, blocks, single print                                                    | `CMP-110 · ProfileBar — ref frame (tpo)`       | TPO, SinglePrint                           | spec §6                 |
| any     | greyscale, high contrast, forced colours                                         | `CMP-110 · ProfileBar — ref frame (greyscale)` | Greyscale, HighContrast, ForcedColors      | spec §2.3, §2.4         |

## Handoff checklist — CMP-183 VolumeProfilePane (E19-D03, #438)

- [ ] **Final Penpot link** — PENDING (boards PR): page `E19-D03`, boards 01, 03, 06, 08, ref frames `CMP-183 · VolumeProfilePane — ref frame (<period word>)`
- [x] **Variants × States matrix** — table 1 below; spec §7, §5, §9
- [x] **Keyboard table** — table 2 (shared); the legend's reveal button and history toggle are CMP-199 stops (spec §12.3)
- [x] **Accessible name / role table** — table 3 (shared)
- [x] **Live data** — table 5 (shared)
- [ ] **Motion pair** — N/A — E19-D05 owns recompute and developing → final choreography
- [x] **Density notes** — the shared density table
- [x] **Essential-exceptions log** — as CMP-110
- [x] **Tokens used** — inherits CMP-110; the header's CMP-227 keeps its own tokens (`15` CMP-227)
- [x] **Data contract confirmed** — `24` §5.1 `ProfilePeriod.kind`, `complete`, `developing_poc`; `14` SCR-038 Data (`GET /market/profile`, WS `profile.{symbol}.{kind}`)
- [ ] **Contrast and CVD** — as CMP-110 (PENDING the token PR and the exports)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — as CMP-110
- [ ] **Sign-off** — PENDING, as CMP-110

### Table 1 — Variants × States (CMP-183)

| Variant                       | State                                                              | Penpot ref frame                                          | Story name                                                                            | Notes           |
| ----------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------------------------- | --------------- |
| any                           | high contrast, forced colours                                      | `CMP-183 · VolumeProfilePane — ref frame (contrast)`      | HighContrast, ForcedColors                                                            | spec §2.2, §2.4 |
| Session (multiples an option) | developing, final, approximated, partial                           | `CMP-183 · VolumeProfilePane — ref frame (Session)`       | Session, Multiples, Developing, Final, Approximated                                   | spec §7.1–§7.3  |
| Fixed range, Anchored         | default; Anchored "contract pending A-1"                           | `CMP-183 · VolumeProfilePane — ref frame (Fixed range)`   | FixedRange, Anchored                                                                  | spec §7.1       |
| Visible range                 | default, bucketed 5 000 rows                                       | `CMP-183 · VolumeProfilePane — ref frame (Visible range)` | Visible, Bucketed5000                                                                 | spec §7.4       |
| Composite                     | default, covered range                                             | `CMP-183 · VolumeProfilePane — ref frame (Composite)`     | Composite                                                                             | D02 §7          |
| levels                        | extended lines, naked POCs capped, tested shown, POC tooltip, VWAP | `CMP-183 · VolumeProfilePane — ref frame (levels)`        | ExtendLines, NakedPocCapped, NakedPocTested, PocTooltip, WithVwap, ValueAreaHighlight | spec §5, §9     |
| host                          | docked, overlay, table                                             | `CMP-183 · VolumeProfilePane — ref frame (host)`          | Docked, Overlay, Table                                                                | spec §10, §12   |

## Handoff checklist — CMP-184 MarketProfileTpoPane (E19-D03, #438)

- [ ] **Final Penpot link** — PENDING (boards PR): page `E19-D03`, board 07, ref frames `CMP-184 · MarketProfileTpoPane — ref frame (<form>)`
- [x] **Variants × States matrix** — table 1 below; spec §6
- [x] **Keyboard table** — table 2 (shared); a focused row reads its letters in the mirror
- [x] **Accessible name / role table** — table 3 (shared)
- [x] **Live data** — table 5 (shared)
- [ ] **Motion pair** — N/A — none animated
- [x] **Density notes** — the shared density table; letters stay 10 px at all three densities (spec §6.1)
- [x] **Essential-exceptions log** — blocks under 24 px are not pointer targets for the letter; hover shows it, the mirror and the table carry it
- [x] **Tokens used** — `color.tpo.letter`, `color.tpo.initialbalance` (both PROPOSED aliases, spec §2.1), `color.surface.raised` (the IB band)
- [x] **Data contract confirmed** — `24` §5.2 TPO (`tpo_period_min`, letters A–Z, a–z, AA …); IB and single prints have no field (D03-G3)
- [ ] **Contrast and CVD** — as CMP-110 (PENDING the token PR and the exports)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — as CMP-110
- [ ] **Sign-off** — PENDING, as CMP-110

### Table 1 — Variants × States (CMP-184)

| Variant | State                                             | Penpot ref frame                                         | Story name                                      | Notes                  |
| ------- | ------------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------- | ---------------------- |
| profile | letters that fit; letter size 12                  | `CMP-184 · MarketProfileTpoPane — ref frame (profile)`   | Profile, LetterSize12                           | spec §6.1              |
| blocks  | the 48-period day at compact; the legend note     | `CMP-184 · MarketProfileTpoPane — ref frame (blocks)`    | Blocks, LettersFullDay48, BlocksFallbackCompact | spec §6.2              |
| IB      | bar + label + band; single prints on and off      | `CMP-184 · MarketProfileTpoPane — ref frame (ib)`        | InitialBalanceShaded, SinglePrints              | spec §6.3              |
| any     | greyscale, focused, high contrast, forced colours | `CMP-184 · MarketProfileTpoPane — ref frame (greyscale)` | Greyscale, Focused, HighContrast, ForcedColors  | spec §2.3, §2.4, §12.2 |

## Shared tables (CMP-110, CMP-183, CMP-184)

### Table 2 — Keyboard

| Key                                       | Action                                                                                           | Focus after                           | Global conflict?                                          | Notes                  |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------- | --------------------------------------------------------- | ---------------------- |
| ↑ / ↓                                     | previous / next row (merged rows one stop)                                                       | the row                               | none (inside the composite grid)                          | `15`:592 (shared grid) |
| `Home` / `End`                            | first / last displayed row                                                                       | the row                               | none                                                      | —                      |
| `PageUp` / `PageDown`                     | by a page of rows                                                                                | the row                               | none                                                      | —                      |
| `Enter`                                   | reads the row detail (D02 W-34; POC adds W-1)                                                    | stays on the row                      | none                                                      | spec §9                |
| `Enter` / `Space` on W-2, W-6             | toggles reveal / tested                                                                          | stays on the button                   | none                                                      | spec §5                |
| `Esc` on a shown POC tooltip              | dismisses the tooltip                                                                            | stays on the row                      | none: `Esc` keeps its global cancel meaning, not remapped | spec §9                |
| (no key) W-2 leaves the legend when k = 0 | —                                                                                                | the legend's first item, never `body` | none                                                      | spec §5, §12.3         |
| `Tab`                                     | docked: header controls → mirror → legend → table; overlay: legend-row controls → mirror → table | the next stop                         | none                                                      | spec §12.3             |

### Table 3 — Accessible name / role

| Element               | Role                                                    | Accessible name (source)                       | States / properties                                          |
| --------------------- | ------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------ |
| histogram mirror      | the composite grid's stop                               | "Profile rows" + the row's D02 W-34 sentence   | `aria-activedescendant` on the focused row                   |
| nPOC reveal button    | `button`                                                | W-3 (visible W-2); pressed W-22 (visible W-21) | none: the label-swap pattern, no `aria-pressed`              |
| tested toggle         | `button`                                                | W-6 (constant)                                 | `aria-pressed`; pressed adds a leading CMP-019 `check` glyph |
| Levels group          | the table's first row group; the mirror's first entries | W-19                                           | each row W-4 / word, price, W-5, W-20                        |
| CMP-227 in the header | `button` (CMP-227's)                                    | "Estimated, …" (CMP-227's)                     | `aria-haspopup="dialog"`                                     |

### Table 4 — Motion

N/A — no animated property here; recompute and developing → final choreography are E19-D05's.

### Table 5 — Live data

| Field                      | Politeness | Cadence                                 | Coalesced             |
| -------------------------- | ---------- | --------------------------------------- | --------------------- |
| POC / VAH / VAL (D02 W-33) | polite     | at most 1 per 2 s per field (`05` §6.2) | the latest value only |
| developing → final         | polite     | once at close                           | —                     |
| estimated / partial appear | polite     | once when it appears                    | —                     |
| bars, rays, letters        | none       | never announced                         | —                     |

### Density

| Density     | Inset            | Header row | Canvas text                | Smallest target                                                                         |
| ----------- | ---------------- | ---------- | -------------------------- | --------------------------------------------------------------------------------------- |
| compact     | `space.inset.sm` | 24 px min  | `type.num.xs` × text scale | 24 × 24 px controls; rows via the mirror and the table (`05`:100's essential exception) |
| dense       | `space.inset.xs` | 24 px min  | `type.num.xs` × text scale | as compact                                                                              |
| comfortable | `space.inset.md` | 32 px min  | `type.num.xs` × text scale | 32 × 32 px controls                                                                     |

## Who applies what

- **E19-T04** — the token PR (`color.tpo.*`, the `pairs.mjs` rows, the stale profile exemptions), the engine encodings, the stories.
- **E19-D06** — the a11y review this hand-off must pass; the mirror words; the tritanopia sheet.
- **E19-D07** — the pack: this file plus the spec as its hi-fi input.
