# E25-D07 — Hand-off (§A–§F for the five detector surfaces, SCR-055 … SCR-059)

The spec is [E25-D07.md](E25-D07.md); every §, C-, G-, Q- and FZ- id below without a prefix is the spec's. The copy deck as data is `E25-D07-copy-deck.jsonl`. Nothing here edits `14`, `15` or a parent: §C's rows are copy-ready, applied by this ticket's closing slice (PR 1b) after #5456 merges; #5415 has merged. The component-level hand-off of the six detector components is D05's own file, [E25-D05-handoff.md](E25-D05-handoff.md), cited and not repeated.

## §A Placement

| Screen  | Where it docks                                             | Opened from                                        | Story          |
| ------- | ---------------------------------------------------------- | -------------------------------------------------- | -------------- |
| SCR-055 | the order-flow band, its third cell (208 px at 1280 × 800) | the band layout                                    | E25-S01 (#791) |
| SCR-056 | the order-flow band, its middle cell (440 px)              | the band layout; rows locate on SCR-030            | E25-S02 (#792) |
| SCR-057 | the order-flow band, its first cell (280 px)               | the band layout                                    | E25-S03 (#793) |
| SCR-058 | a non-modal drawer, 420 px, over the band                  | any `(estimated)` chip (CMP-227)                   | E25-S04 (#794) |
| SCR-059 | a modal dialog, 760 × 560                                  | the panel menu; SCR-058's "Detector settings" link | E25-S05 (#795) |

The cell widths are D03's band board (`D03`:42); the drawer and the dialog sizes are D02's (`D02`:238, :262). E25-S06 (#796) draws the CMP-134 cards and the CMP-132 marks on SCR-030's chassis.

## §B The contract table

| Field    | SCR-055                          | SCR-056                          | SCR-057              | SCR-058                       | SCR-059                                  |
| -------- | -------------------------------- | -------------------------------- | -------------------- | ----------------------------- | ---------------------------------------- |
| Bindings | DB-1 … DB-8                      | DB-9 … DB-15                     | DB-16 … DB-20        | DB-21 … DB-23                 | DB-24 … DB-28                            |
| States   | S55-1 … S55-14                   | S56-1 … S56-13                   | S57-1 … S57-12       | S58-1 … S58-8                 | S59-1 … S59-17; AP-1 … AP-5; CF-1 … CF-3 |
| Tokens   | D03 §3                           | D03 §4                           | D03 §5               | D04 §3                        | D04 §4                                   |
| A11y     | D06 §4.1, N-1 … N-4, T-1         | N-4, N-5, N-8; T-2 … T-5, T-18   | N-4, N-6, N-7        | focus-to-section; T-14 … T-16 | N-9 … N-16; T-6 … T-13, T-17             |
| Motion   | D03 M-1 … M-5, M-10, M-12 … M-14 | D03 M-6 … M-8, M-10, M-12 … M-14 | D03 M-9 … M-14       | D04 M-1, M-3, M-5 … M-10      | D04 M-2 … M-10 (M-9 by D06 A-3)          |
| Budget   | ≤ 4 Hz, 1 ms                     | ≤ 4 Hz, 1.5 ms, 2,000 events     | ≤ 1 Hz, 1 ms         | open ≤ 150 ms                 | applied ≤ 2 s, after the 200             |
| Copy     | `detectors.tape.*`               | `detectors.imbalance.*`          | `detectors.regime.*` | `detectors.methodology.*`     | `detectors.settings.*`                   |
| Shared   | `detectors.shared.*`             | `detectors.shared.*`             | `detectors.shared.*` | none                          | `detectors.shared.*`                     |

## §C Copy-ready rows (applied by the closing PR)

| A   | File and line           | Old | New                                                                                                                                                                                                                                 | Owner                    |
| --- | ----------------------- | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| A-1 | `14`:1357, a line after | —   | "- **Hand-off pack (E25-D07):** [E25-D07.md](../design/E25/E25-D07.md) v0 (owner approval pending; the bindings DB-1 … DB-8, the deck's `detectors.tape.*` rows, the sign-off rows SO-1 … SO-6)"                                    | this ticket (`14` owner) |
| A-2 | `14`:1383, a line after | —   | "- **Hand-off pack (E25-D07):** [E25-D07.md](../design/E25/E25-D07.md) v0 (owner approval pending; the bindings DB-9 … DB-15, the deck's `detectors.imbalance.*` rows, the sign-off rows SO-7 … SO-12)"                             | this ticket (`14` owner) |
| A-3 | `14`:1408, a line after | —   | "- **Hand-off pack (E25-D07):** [E25-D07.md](../design/E25/E25-D07.md) v0 (owner approval pending; the bindings DB-16 … DB-20, the deck's `detectors.regime.*` rows, the sign-off rows SO-13 … SO-18)"                              | this ticket (`14` owner) |
| A-4 | `14`:1422, a line after | —   | "- **Hand-off pack (E25-D07):** [E25-D07.md](../design/E25/E25-D07.md) v0 (owner approval pending; the bindings DB-21 … DB-23, the frozen string FZ-1, the deck's `detectors.methodology.*` rows, the sign-off rows SO-19 … SO-22)" | this ticket (`14` owner) |
| A-5 | `14`:1436, a line after | —   | "- **Hand-off pack (E25-D07):** [E25-D07.md](../design/E25/E25-D07.md) v0 (owner approval pending; the bindings DB-24 … DB-28, the frozen strings FZ-2 … FZ-15, the sign-off rows SO-23 … SO-27)"                                   | this ticket (`14` owner) |

The lines are read at the base, with #5415's rewrite of SCR-058's and SCR-059's pointer lines merged. Each A-row inserts a line, which would shift every later anchor by one, so the closing slice applies A-1 … A-5 by content, bottom-up (A-5 first). Every other change the pack needs is a routed row with its owner (spec §8.3, §14).

## §D Storybook

The component stories are D05 §13's, 95 stories in six groups (`D05`:396–401): stories are mandated per CMP only. The per-screen composed stories below are a **recommendation** to E25-S01 … S05, not a requirement (#672 BQ-12; C-4.9):

| Screen  | Title                         | Stories                                                                                                  |
| ------- | ----------------------------- | -------------------------------------------------------------------------------------------------------- |
| SCR-055 | `Detectors/TapeSpeedPanel`    | one per S55 row, plus Compact, Comfortable, Light, HighContrast, Greyscale, ReducedMotion                |
| SCR-056 | `Detectors/ImbalancePanel`    | one per S56 row, plus ViewerReadOnly, ViewAs, Compact, Comfortable, Light, HighContrast, Greyscale       |
| SCR-057 | `Detectors/RegimePanel`       | one per S57 row (S57-1 as five), plus Compact, Comfortable, Light, HighContrast, Greyscale               |
| SCR-058 | `Detectors/MethodologyDrawer` | one per S58 row, plus each of the nine sections, Light, HighContrast, ReducedMotion                      |
| SCR-059 | `Detectors/SettingsDialog`    | one per S59 row, one per AP and CF row, plus Manager, Viewer, ViewAs, Light, HighContrast, ReducedMotion |

The fixtures are deterministic: BTCUSDT and ETHUSDT, the clock 13:58:02 UTC, D05's synthetic values (63,118.0, 0.71), no `Date.now`.

## §E Test hooks (PROPOSED: the parents are silent)

- **Role and name first.** Tests query the accessibility tree by D02's a11y trees (`D02`:341) and the deck's `name` rows.
- **Strings byte for byte.** A test asserts each rendered deck string equals its row's `text`, the sample figures replaced by the fixture's; a frozen row (§9.2) gets its own named test.
- **Announcements on a fake clock.** N-1 at most once per 5 s and once per episode under a 4 Hz oscillation; N-5 summarised at most once per 5 s; nothing on mount inside a window.
- **The apply machine.** "Applied" never before the 200; a 503 restores the last confirmed values; a timeout re-reads and sends nothing.
- **State attributes.** `data-state` on each panel with its S-row id; `data-motion` read from the root only.
- **No `data-testid`** unless an element has no role.

## §F References and the deck as data

**States and bindings:** D02 §9 and §15 (`D02`:192, :406). **Tokens:** D03 §3–§8 and D04 §3–§7 by state row. **Motion:** D03 §9, D04 §8. **Accessibility:** D06 §4–§11, at #5456's head, PENDING its merge. **Components:** D05 and its hand-off file. **The deck as data:** one header line (the pack, the version, the base, D06's request ref, the fields, the status and provenance words, the `frozen` flag), then one row per string with `key`, `text`, `screen`, `kind`, `where`, `status`, `frozen`, `owner`, `provenance`, `source`, `consumer`, and `quote`, `ruling`, or `carry` with its `request`, where needed. A builder reads the deck, not this file, for any string.
