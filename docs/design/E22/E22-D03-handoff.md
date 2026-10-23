# E22-D03 — Per-component handoff checklist (`16` §11.4)

One block for the component contract this ticket changes (**CMP-112 BigTradeBubble**) with the legend row it depends on (CMP-199 / CMP-037's `pair` swatch), then the four `16` §11.4 blocks — A. design QA (`16` §12), B. a11y acceptance criteria (`05` §10), C. field → element map, D. redlines and token map — in the E39-D02 / E25-D05 handoff shape. Every number is the audit tool's (`docs/design/_tools/e22_d03_bubble_hifi_audit.py` at `642114e0a945c4ba402a31ea4a81abafa798ff3e`, this PR's base, which carries E05-D02 slice 2's merged CMP-011 / CMP-020 / CMP-037); every decision is PROPOSED until the owner's `approved` (spec header). BQ-07 RULED YES (comment 6372015368 on #508): this file exists in the `16` §11.4 four-block shape.

## Handoff checklist — CMP-112 BigTradeBubble (E22-D03, #508)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E22-D03 BigTrade hi-fi` (page id pinned in the spec's §0 after the first build), specimens `CMP-112 · BigTradeBubble` on this ticket's own page (never the DS library file); PNG per state planned at `docs/design/E22/img/E22-D03-06-cmp-112-states-sheet.png` (dark) and `E22-D03-07-cmp-112-states-sheet-light.png` (light), the anatomy and laws at `E22-D03-05-cmp-112-anatomy-laws.png`, the composed overlay at `E22-D03-08-overlay-legend-tooltip-scr-030.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists only once the boards are drawn): `shape` circle / square (+ diamond available-unused, text = the label mode) × `sizeScale` sqrt / log / linear × `ageBand` fresh / aged × capped (label / outline) × clustered × 12 states (spec §4.8) × 3 themes; Table 1 below
- [x] **Keyboard table** — D02 Table 2 verbatim, nothing new: `←/→` on the chart's cursor carries "big trade"; `Enter` on a mirror node locates (`tape.print_clicked {source: bubble}`); `↑/↓` + `Space` in the legend block toggles the layer; `Esc` dismisses the tooltip; no key is gated by a role (the legend eye is a view preference; the strip's scale select keeps D02's T2 legs — spec §4.10, §7.1); Table 2
- [x] **Accessible name / role table** — one sparse `button` per big print named `"Big {side}, {notional} USDT, {price}, {time}"` (fixed by the ticket; "Big sell, 42,000 USDT, 65,410, 14:32:01"), the abbreviated notional expanded per CMP-020 ("1,200,000"); a cluster node `"Cluster of 7, 1,900,000 USDT, sell, 14:02:11, estimated"` (D02 Table 3's name plus the literal word and the CMP-020 digit expansion, PROPOSED — spec D03-C10); the legend `row` with the eye `aria-pressed` "Big trades visible" and "(estimated)" in the name while clustering is on; the tooltip `aria-hidden` (values in the mirror and the cursor region); the badge "Estimated, Trade cluster" (spec §4.9, §5); Table 3
- [x] **Live data** — nothing per print: the cursor region announces "big trade" with the bar (E06-D03 D5, last-write-wins), the whale announcements are E22-D04's policy (opt-in, ≤ 1 per 5 s); the legend row's value is the cursor bar's (≤ 1 per frame); a T2 press announces its reason once, politely (spec §7); Table 5
- [x] **Motion pair** — appear = a 0 ms flip, no pop / scale-in; band changes, badge, outline, eye and scale switch are flips; the stale dim is the pane's uniform (`normal` / instant); the tooltip fades `fast` / instant; 0 flashes (spec §9, M-1..M-12); Table 4
- [x] **Density notes** — the mark has no density axis (r is the law's px); the legend row 24 / 32 px with `space.inset.sm` / `.md`; the tooltip `space.inset.sm` / `.md`; the mirror hit area is the mark's bounds, never under 24 × 24 CSS px (padding to `size.target.min` where r < 12) (spec §2, §4.1); Density table
- [x] **Essential-exceptions log** — two logged, no target exception: (1) **the canvas mark below r 5 px** (14.1 % of the dense tape's flagged prints, D02 tool) is not shape-distinguishable — the side is carried by the tape row, the tooltip and the mirror name, and for a protan / deutan / tritan reader the mark alone is hue-only (spec §4.7; AC 3 holds for r ≥ 5 px; open under D03-Q2, r_min 5 closes it); (2) **a stale and aged mark** at 0.8 × 0.85 = 0.68 measures sell 2.75 dark / buy 2.82 light on the canvas (tool, reported) — E11-D06 D13's stale dim is a pane-wide status treatment over all data ink and the CMP-239 chip carries the state (spec §8.1). The mirror node's target is padded to 24 × 24 px; the glyph is a redundant carrier below r 10 px — not a target
- [x] **Tokens used** — `color.buy.default` / `color.sell.default` (the `.hc` values in high contrast), `color.cvd.buy` / `color.cvd.sell`, `color.text.inverse`, `type.num.xs` (the side glyph's fixed box), `color.text.primary`, `color.text.secondary`, `color.text.tertiary`, `color.surface.canvas`, `color.surface.overlay`, `color.border.default`, `color.focus.ring`, `border.focus`, `border.thick`, `radius.card`, `elevation.popover`, `space.1`, `space.inset.sm` / `.md`, `type.num.sm`, `type.num.base`, `type.ui.label`, `motion.duration.fast` / `.instant` — every one resolves at the base (tool §D); **one PROPOSED token** `opacity.bubble.aged` = 0.8 (CR-1; the literal 0.8 is a PROPOSED engine uniform until it lands); `size.bubble.scale` is retired in favour of the props `rMinPx` / `rMaxPx` (A-3) and `color.marker.*` is MISSING and not bound (spec §4.11, §8.4); the legend's `pair` swatch adds `size.icon` and `color.border.strong` (merged CMP-037, spec §5)
- [x] **Component contract deltas** — CMP-112's props change as the spec's A-1 / A-3 / A-4 copy them: `sizeScale` gains `sqrt` (the area-linear default) beside `log` / `linear`; new `rMinPx` (3) / `rMaxPx` (24) replacing `size.bubble.scale`, `ageBand: "fresh"|"aged"`, `capped: boolean`, `clusterSize?` (≥ 2 shows the badge) and `estimated?` (clusters); the legend's CMP-037 `pair` kind is A-10 (D03-C11)
- [x] **Data contract confirmed** — the engine's `BigTradeEvent` (`notional`, `side`, `price`, `capped`, `estimated`) and `TradeClusterEvent` (`cluster_size`, `total_notional`, `vwap`, `first_ts_event`, `estimated: True`) of `24` §2.10 once E22-T02 echoes them on `trades.{symbol}` (memo G1 / C18; spec D03-G6 for the cluster values on the wire); never a client-side threshold (A-5); the `(estimated)` word from `estimated: true`
- [ ] **Contrast and CVD** — PENDING for the exports (CVD renders in PR 2); the text is measured: 61 pairs × 3 themes, 40 gated rows, 0 FAIL (unrounded compare); the marks on the canvas 7.45 / 5.03 / 9.96 buy and 4.68 / 4.85 / 7.60 sell; the aged band at 0.8 5.13 / 3.48 / 6.75 and 3.39 / 3.61 / 5.26; the glyph 7.87 / 5.39 / 10.51 and 4.94 / 5.20 / 8.02; greyscale / deuteranopia hue separation 1.59 / 1.23 / 1.46 — the shape carries (spec §8.1, §8.3)
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

### Table 1 — Variants × States (CMP-112; the legend row's two states)

| Component / Screen | Variant                                    | fresh | aged (0.8) | capped label | capped outline | clustered (×N) | stale (× 0.85) | disconnected | hidden                                    | LOD-shed | hover | focus-visible   | located |
| ------------------ | ------------------------------------------ | ----- | ---------- | ------------ | -------------- | -------------- | -------------- | ------------ | ----------------------------------------- | -------- | ----- | --------------- | ------- |
| CMP-112            | `circle` (buy) · `sqrt` / `log` / `linear` | BS1   | BS2        | BS3          | BS4            | BS5            | BS6            | BS7          | BS8                                       | BS9      | BS10  | BS11            | BS12    |
| CMP-112            | `square` (sell) · the same laws            | BS1   | BS2        | BS3          | BS4            | BS5            | BS6            | BS7          | BS8                                       | BS9      | BS10  | BS11            | BS12    |
| CMP-112            | `diamond` — available, unused              | —     | —          | —            | —              | —              | —              | —            | —                                         | —        | —     | —               | —       |
| CMP-112            | `text` — the label mode                    | BS3   | BS3 + BS2  | BS3          | → BS4          | BS5 + BS3      | BS6            | BS7          | BS8                                       | BS9      | BS10  | BS11            | BS12    |
| CMP-199 row        | per law; "(estimated)" when clustering     | shown | —          | —            | —              | the word       | —              | —            | eye off (`color.text.tertiary`, "hidden") | —        | —     | the row focused | —       |

### Table 2 — Keyboard (D02 Table 2, line 257; nothing new)

| Component / Screen | Key                      | Action                                                                    | Focus after | Global conflict?     | Notes                                                                                                    |
| ------------------ | ------------------------ | ------------------------------------------------------------------------- | ----------- | -------------------- | -------------------------------------------------------------------------------------------------------- |
| SCR-030 cursor     | `←/→`                    | the cursor announcement carries "big trade" when the bar holds one        | the plot    | the chart's own keys | no new binding (E06-D03 D5)                                                                              |
| CMP-112 mirror     | `Enter`                  | locate: the crosshair to the print; `tape.print_clicked {source: bubble}` | the plot    | none                 | the "overlay handles" stop (E11-D02 D18)                                                                 |
| CMP-112 mirror     | `Esc`                    | dismiss the tooltip                                                       | the node    | reserved             | innermost cancel                                                                                         |
| CMP-199 row        | `↑/↓`, `Space` / `Enter` | reach the Big trades row; toggle the layer                                | stays       | none                 | the tape keeps its tiers when the layer is off                                                           |
| strip scale select | `↑/↓`, `Enter`           | choose `sqrt` (area-linear) / `log`; the legend text follows              | stays       | none                 | T2 while viewing as / for a Viewer (D02 S21 / S23; spec §7.1): changes nothing, re-shows the reason once |

### Table 3 — Accessible name / role

| Component / Screen | Element        | Role                | Accessible name (source)                                                                                                  | States / properties                                                                          |
| ------------------ | -------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| CMP-112            | mirror node    | `button`            | "Big {side}, {notional} USDT, {price}, {time}" — "Big sell, 42,000 USDT, 65,410, 14:32:01" (`15` 1196; ticket a11y note)  | sparse, one per big print; the abbreviated notional expanded per CMP-020 ("1,200,000")       |
| CMP-112            | cluster node   | `button`            | "Cluster of 7, 1,900,000 USDT, sell, 14:02:11, estimated" (D02 Table 3 + the PROPOSED suffix and expansion, spec D03-C10) | the literal word in the name; also the legend row's word and the badge's name                |
| CMP-112            | tooltip        | `tooltip` (CMP-197) | the CP19 string (`aria-hidden`; the values live in the mirror and the cursor region)                                      | hover and focus; flip-not-clip                                                               |
| CMP-199            | legend row     | `row`               | "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled" (+ "(estimated)" while clustering is on)             | eye `button` `aria-pressed`, stable name "Big trades visible"; hidden → "hidden" in the name |
| CMP-227            | badge (inline) | `button`            | "Estimated, Trade cluster" (E25-D05 §4.3)                                                                                 | `aria-haspopup="dialog"`; opens SCR-058 (G10)                                                |

### Table 4 — Motion pair

| Component / Screen | Property                 | motion-safe                                            | motion-reduce | Carrier                         |
| ------------------ | ------------------------ | ------------------------------------------------------ | ------------- | ------------------------------- |
| CMP-112            | appear                   | 0 ms flip                                              | identical     | the mark                        |
| CMP-112            | fresh → aged             | flip to 0.8 at the band boundary (E22-D04's value)     | identical     | the alpha step                  |
| CMP-112            | label ↔ outline; badge   | flip                                                   | identical     | the outline / the text          |
| SCR-030 pane       | stale dim                | 1.00 → 0.85 over `motion.duration.normal` / `standard` | instant       | the static × 0.85 + the chip    |
| CMP-197            | show / hide              | `motion.duration.fast` fade                            | instant       | the text                        |
| CMP-199            | eye toggle; scale switch | flip                                                   | identical     | `aria-pressed`; the legend text |
| CMP-112            | any flash                | 0 (`BUBBLE_FLASH_MAX_HZ` 3 is the cap)                 | 0             | —                               |

### Table 5 — Live data

| Component / Screen | Source                                                      | Rate                                    | Region                                  |
| ------------------ | ----------------------------------------------------------- | --------------------------------------- | --------------------------------------- |
| CMP-112 mark       | `BigTradeEvent` / `TradeClusterEvent` (engine, via E22-T02) | per flagged print; redraw ≤ 1 per frame | none (`aria-hidden` canvas)             |
| CMP-112 mirror     | the same                                                    | one node per big print                  | none; the cursor region on `←/→`        |
| CMP-199 row        | the cursor bar                                              | ≤ 1 per frame                           | none                                    |
| whale announcement | E22-D04's policy                                            | ≤ 1 per 5 s, opt-in                     | the panel's one `status` node (D02 D29) |

### Density

| Component / Screen | Compact                                             | Comfortable                     | Smallest target                                |
| ------------------ | --------------------------------------------------- | ------------------------------- | ---------------------------------------------- |
| CMP-112 mark       | r 3 → 24 px (no density axis)                       | identical                       | the mirror's hit area padded to 24 × 24 CSS px |
| CMP-199 row        | 24 px row, `space.inset.sm`                         | 32 px row, `space.inset.md`     | the eye 24 × 24                                |
| CMP-197 tooltip    | `space.inset.sm`, `type.ui.label` + `type.num.base` | `space.inset.md`, the same type | not a target                                   |

### Essential exceptions

Two, logged in the checklist above: the canvas mark below r 5 px (shape cannot carry the side there — row, tooltip and name do; AC 3 open below r 5, D03-Q2) and the stale + aged band at 0.68 (reported, the chip carries). No target exception.

## A. Design QA checklist (`16` §12) — CMP-112, CMP-199 row, SCR-053 hi-fi

- [x] Only published Tier-2 tokens; zero hard-coded hex / px beyond the anatomy px derived from the law and the tokens (spec §4.1–4.3, §8.2); the one DS change request (CR-1 `opacity.bubble.aged`) is a PROPOSED row, never bound as existing
- [ ] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §8.1: 40 gated rows, 0 FAIL); the visual parity check runs on the boards (BLOCKED-PENPOT; boards 02 / 07 light, board 09 high-contrast cells)
- [x] Passes the contrast matrix for every pair introduced or touched (61 rows; six unregistered `pairs.mjs` rows named in CR-3 — four pairs and the two composited aged rows; the rejected and reported rows carry their reasons)
- [ ] CVD simulation reviewed — the greyscale / deuteranopia values are computed (spec §8.3); the renders run on the exports in PR 2; protanopia / tritanopia rest on the shape channel, stated per pair
- [x] Every state in Table 1 has a token binding and a frame or inset (spec §4.8 ↔ §0 boards 05–08)
- [x] Reduced-motion variant for every animated property (Table 4; spec §9)
- [x] Keyboard table and accessible names complete (Tables 2–3); the T2 rule stated once and cited (spec §7.1); no control over-converted
- [x] No colour-only meaning: the side by shape + glyph + word; estimated by the word + outline; hidden by the eye + "hidden"
- [x] Copy strings verbatim from D02's deck (CP19–CP22, CP24, CP26) and the ticket's fixed `aria-label`; "(estimated)" never "Est."

## B. Accessibility acceptance criteria (`05` §10) — CMP-112, CMP-199 row

```gherkin
Feature: E22-D03 big-trade bubbles, legend row and tooltip — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the chart root has focus and the overlay is on
    When I press Tab to the overlay handles stop and focus a mirror node
    Then the CMP-197 tooltip shows the node's values and Esc dismisses it with focus kept on the node
    When I press Enter on the mirror node
    Then the crosshair jumps to that print and focus moves to the plot (D02 Table 2)

  Scenario: Screen-reader names
    Given a big sell of 1.2M USDT at 64,012.0 at 14:02:11
    Then its mirror node is a button named "Big sell, 1,200,000 USDT, 64,012.0, 14:02:11" (the CMP-020 expansion of the drawn 1.2M)
    And a cluster of 7 prints is named "Cluster of 7, 1,900,000 USDT, sell, 14:02:11, estimated"
    And while clustering is on the legend row's name contains "(estimated)"

  Scenario: Side independent of hue
    Given the buy and sell marks under greyscale or any colour-vision simulation
    Then a buy is a disc and a sell is a square of equal area, told apart from about r 5 px
    And below r 5 px the tape row, the tooltip and the mirror name carry the side (the logged exception)
    And from r 10 px the mark carries the ▲ or ▼ glyph
    And the tooltip and the mirror name carry the side word

  Scenario: Contrast
    Then every mark on the chart canvas measures at least 3:1 in dark, light and high contrast
    And an aged mark at opacity.bubble.aged measures at least 3:1 in every theme
    And the label, the badge, the legend text and the tooltip text measure at least 4.5:1

  Scenario: Reduced motion
    Given prefers-reduced-motion or the in-app override
    Then a bubble appears without a pop or scale-in and a band change is an instant step
    And nothing on the layer flashes

  Scenario: Gated writes keep E09-D09's T2 look
    Given the session views as another user
    Then the strip's scale select keeps its full label with the lock glyph and its reason
    And the legend's eye and the mirror nodes stay enabled
```

## C. Field → element map

| Contract field                                                        | Frame element                                                                 | Format / rule                                      |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `BigTradeEvent.price`, `.trade_id` (time via the source `TradeEvent`) | the mark's position                                                           | price on the pane's scale; time at the print's bar |
| `BigTradeEvent.notional`, `.threshold_abs`                            | the radius under the active law (`k = notional / T`, clamped 1–4)             | spec §4.3; T = the class's effective threshold     |
| `BigTradeEvent.side`                                                  | the shape (`circle` buy / `square` sell) and the fill token; the ▲ / ▼ glyph  | never hue alone                                    |
| `notional ≥ 4 T`                                                      | the `text` label beside the mark ("1.2M") or the cap outline                  | CMP-020 abbreviation; the mirror name expands it   |
| `BigTradeEvent.estimated` (percentile mode)                           | nothing on the mark; the strip's "(estimated)" readout (D02 §7)               | the mark's own `estimated` is the cluster's        |
| `TradeClusterEvent.vwap`, `.first_ts_event`                           | the cluster mark's position                                                   | the bar containing the first print                 |
| `TradeClusterEvent.total_notional`                                    | the cluster mark's radius                                                     | the same law                                       |
| `TradeClusterEvent.cluster_size`                                      | the "×N" badge; "Cluster of N" in the name; "N prints within…" in the tooltip | badge from N ≥ 2                                   |
| `TradeClusterEvent.estimated: True`                                   | "(estimated)" in the tooltip and the legend row; "Estimated, Trade cluster"   | the full word                                      |
| age (the engine's clock vs `ts_event`)                                | the band: fresh 1.0 / aged `opacity.bubble.aged`                              | the boundary is `BubbleOptions.ageBands` (E22-D04) |
| `sizeScale` (the strip's scale select, `PATCH /settings`)             | the law and the legend text                                                   | D02 S21 / S23 T2 legs                              |
| the legend eye                                                        | layer visible / hidden                                                        | a client view preference; `aria-pressed`           |

## D. Redlines and token map (px PROPOSED; every token resolved by the audit tool)

| Frame / element            | Anatomy (px)                                                                                                                                                                                                                                                 | Tokens (dark / light / hc values in the spec's §8.2)                                                                                                                                                                                              |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| mark, buy                  | disc r 3.0 / 10.2 / 14.1 / 19.7 / 24.0 at 1 / 1.5 / 2 / 3 / 4× (`sqrt`)                                                                                                                                                                                      | `color.buy.default`; aged × `opacity.bubble.aged` 0.8                                                                                                                                                                                             |
| mark, sell                 | square side r·√π: 5.3 / 17.7 / 42.5 at r 3 / 10 / 24                                                                                                                                                                                                         | `color.sell.default`; aged × 0.8                                                                                                                                                                                                                  |
| side glyph                 | ▲ / ▼ centred, from r ≥ 10 px; glyph box `type.num.xs` 10 px, `font.weight.bold`, fixed at every radius                                                                                                                                                      | `color.text.inverse`; `type.num.xs`                                                                                                                                                                                                               |
| cap outline                | 2 px ring centred at r + 3 (2 px canvas gap); the square grows by the same gap                                                                                                                                                                               | the mark's hue; `border.thick`                                                                                                                                                                                                                    |
| label                      | right of the mark at `space.1` 4 px; `type.num.sm` 11 px; 1 px halo                                                                                                                                                                                          | `color.text.primary`; halo `color.surface.canvas`                                                                                                                                                                                                 |
| badge                      | "×N" top-right outside the fill; `type.num.sm`; 1 px halo                                                                                                                                                                                                    | `color.text.primary`; halo `color.surface.canvas`                                                                                                                                                                                                 |
| focus ring                 | 2 px `color.focus.ring` outside a 1 px canvas halo at the mark's bounds                                                                                                                                                                                      | `color.focus.ring`, `border.focus`, `color.surface.canvas`                                                                                                                                                                                        |
| tooltip                    | 16 px right-below; `radius.card` 6; `space.inset.sm` / `.md`; labels `type.ui.label`, values `type.num.base`                                                                                                                                                 | `color.surface.overlay`, `color.border.default`, `elevation.popover`, `color.text.secondary` / `.primary`                                                                                                                                         |
| legend row                 | 24 / 32 px; one CMP-037 `pair` cell: two `size.icon` 16 px swatches (a disc + a square of equal area, side 14), each with a 1 px `color.border.strong` outline and its ▲ / ▼ `glyph` (`type.num.xs`), `space.1` gap, 36 × 16; `type.ui.label`                | `color.text.primary` (text and the visible eye); hidden `color.text.tertiary`; swatches `color.buy.default` / `color.sell.default`, outline `color.border.strong`, glyphs `color.text.inverse`; the badge `color.status.info.subtle` / `.default` |
| corner badge               | 20 px pill, `space.inset.sm`; `type.ui.caption`                                                                                                                                                                                                              | `color.neutral.subtle` + `color.border.default` 1 px (merged CMP-011 `neutral`, A-16); `color.text.secondary` (7.50 / 8.26 / 12.22)                                                                                                               |
| tape row (compact / comf.) | 24 / 32 px; cells `type.num.sm` 11 / `type.num.base` 13; 2 px left accent on tiers 1–2                                                                                                                                                                       | `color.surface.raised`; tier 2 `color.buy.subtle` / `color.sell.subtle`; glyphs and accent `color.buy.default` / `color.sell.default`                                                                                                             |
| T2 control                 | the control's own box; `lock` 12 px (`size.icon.sm`) leading the label                                                                                                                                                                                       | `color.surface.raised` + `color.border.default`; label `color.text.tertiary`; reason `color.text.secondary`                                                                                                                                       |
| invalid threshold value    | the field's own box; label and value full-opacity; the range message under the field, linked by `aria-describedby`; `aria-invalid`; focusable and editable; never `opacity.disabled` (that look is only for a control disabled by validity, none on SCR-053) | label and value `color.text.primary`; `color.status.danger.default` hairline; message `color.text.secondary`                                                                                                                                      |
