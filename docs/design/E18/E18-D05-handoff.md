# E18-D05 — Hand-off (§A–§G for the footprint: SCR-030, SCR-032 and SCR-056's E18 rows)

The spec is [E18-D05.md](E18-D05.md); every §, BQ-, C-, F-, G- and OQ- id below without a prefix is the spec's. The copy deck as data is `E18-D05-copy-deck.jsonl`. Nothing here edits `14`, `15`, `16`, D02, D03, D04 or E09-D09: §C's rows are copy-ready, each applied by its named owner, and pack A-1 … A-3 by a last commit on this ticket at the owner's approval. Old text is verbatim at the base `main` `e7cc2dd2a`; D03 and D03H are read at PR #5881's head `67a2907b4`, D04H at PR #5908's head `17e6d17d9`, each if it merges as is. §G links the parents' `16` §11.4 checklists and adds a block only for a contract these screens change that no parent checklists (BQ-8).

## §A Placement

| Component | `15` heading | Screens                   | Contract and checklist                                |
| --------- | ------------ | ------------------------- | ----------------------------------------------------- |
| CMP-109   | `15`:1268    | SCR-030                   | D03 §5, §6; checklist `D03H`:55                       |
| CMP-132   | `15`:1633    | SCR-030, SCR-056 (rows)   | D03 §3, §8; checklists `D03H`:117 and `E25H`:62 (F-2) |
| CMP-182   | `15`:2378    | SCR-030                   | D03 §5; checklist `D03H`:146                          |
| CMP-228   | `15`:2969    | SCR-032 (`footprint`)     | D03 §7; checklist `D03H`:174                          |
| CMP-227   | `15`:2955    | SCR-056 (the E18 variant) | `E25H`:5; the variant §G below (D02 §7.4, `D02`:707)  |
| CMP-197   | `15`:2596    | SCR-030 (tooltip rows)    | D03 A-11 (`D03`:711); §G below                        |
| CMP-046   | `15`:540     | SCR-030 (cell drawer)     | D03 A-12 (`D03`:727); §G below                        |
| CMP-079   | `15`:895     | SCR-032, SCR-030, SCR-056 | as `15` states it; every T2 control (spec R-2)        |
| CMP-019   | `15`:238     | the same                  | as `15` states it; the `lock` glyph (spec R-2)        |
| CMP-195   | `15`:2571    | SCR-030                   | as `15` states it                                     |
| CMP-222   | `15`:2896    | SCR-042                   | as `15` states it                                     |

D03H cites the four `15` headings one line earlier, at its own older base; they are re-pinned at its merge (R6). No second CMP-132 is drawn or checklisted here (BQ-8).

## §B The contract table

`15`'s fields today are the merged text; D03's §C rows replace or extend them in D03 PR 2, and until then D03's sections are the contract. D03H §B (`D03H`:16) carries the four footprint components' table; this table adds only what these screens bind.

| Field         | The footprint components | CMP-197 rows      | CMP-046 drawer    | CMP-227 on SCR-056   | SCR-032 controls |
| ------------- | ------------------------ | ----------------- | ----------------- | -------------------- | ---------------- |
| Props         | D03H §B                  | D03 A-11          | D03 A-12          | `15` CMP-227         | spec §3          |
| States        | D03 §5.4                 | D03 §6            | D03 §6            | D02 §7.4             | D02 §6.5, §6.6   |
| A11y          | D04 §7.1–§7.5            | D03 §6 (W-3)      | D04 §7.1          | `E25H`:5             | spec R-2, §8     |
| Motion        | D04H motion-pair lines   | none              | `15` CMP-046's    | none                 | D04 §2           |
| Data contract | `24`:819; `23`:750       | the cell's fields | the cell's fields | `FootprintImbalance` | spec §3          |
| Storybook     | D03H §D                  | §D                | §D                | `15` CMP-227's       | §D               |

## §C Copy-ready rows (pack A-1 … A-3 at the owner's approval; A-4 … A-8 PROPOSED to their owners)

A-1 … A-3 land in a last commit after the owner's approval; each sits after the last pointer line of its `14` entry, found by content on that day (BQ-1). Every other row is applied by its owner; until then no merged line changes.

| A   | File and line           | Old                                                      | New                                                                                                                                                                            | Owner               |
| --- | ----------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------- |
| A-1 | `14`:790, a line after  | —                                                        | "- **Hand-off pack (E18-D05):** [E18-D05.md](../design/E18/E18-D05.md) (E18-D05; the mapping table, the copy deck, the spike evidence and the sign-off map; approved on #499)" | this ticket         |
| A-2 | `14`:852, a line after  | —                                                        | the same line                                                                                                                                                                  | this ticket         |
| A-3 | `14`:1386, a line after | —                                                        | the same line                                                                                                                                                                  | this ticket         |
| A-4 | `14`:844                | "Enter a ratio between 100 and 2000 %."                  | "Enter a ratio between 150 and 2000 %." and the range "150–2000 %" (`22`:4889)                                                                                                 | the `14` owner      |
| A-5 | `14`:848                | "parity across Chromium, Electron and Tauri/WebView2"    | "parity across Chromium and Electron" (ADR-0011); the same change at `14`:745                                                                                                  | the `14` owner      |
| A-6 | `E18J`:161              | "Reduced detail: footprint text hidden below N px cells" | W-8 and W-9 (D02 A-26); and "Enter a ratio between 150 and 2000 %." for the ticket's ratio message                                                                             | the backlog's owner |
| A-7 | `D09`:85                | "and E17-D01 §7 for the feed states)"                    | "and E17-D01 §7 for the feed states; E18-D05 §5.3 for the footprint states)"                                                                                                   | E09-D09 (#192)      |
| A-8 | `D03`:380               | "Only the owner can rebuild footprint cells."            | "Only the owner can change recording." (F-1); D02:621 for D02's next toucher                                                                                                   | the D03 lane (#497) |

D03's A-1 … A-21 (`D03`:546) and D04H's A-1 … A-8 (`D04H`:13) stay their tickets' rows, never restated here.

## §D Storybook

The lists of the four footprint components are D03H §D (`D03H`:34). These screens add, PROPOSED: CMP-197 `FootprintRows` (one, two and three rows; forming); CMP-046 `FootprintCellDetail` (a traded level, a level with no trades, the T2 buttons); CMP-227 `ImbalanceRowEstimated` (stamped "no v1 source sets it", D02 §7.4); SCR-032's source group in `OwnerOnly`, `Permission`, `Offline` and `Running`. Each story renders at compact and comfortable, in dark and light, on a deterministic BTCUSDT fixture with the clock fixed.

## §E Test hooks (PROPOSED: the parents are silent)

- **Role and name first.** Tests query by D04 §7's roles and names and the deck's `name` rows.
- **Strings byte for byte.** A rendered string equals its deck row's `text`, the sample figures replaced by the fixture's.
- **T2 on a fake clock.** `Enter` on a T2 control changes nothing and the reason is announced once.
- **No `data-testid`** unless an element has no role.

## §F References and the deck as data

**Motion:** D04 §2 and the motion-pair lines (`D04H`:9–11). **Accessibility:** D04 §7.1–§7.5 (`D04`:160–237). **Tokens and encodings:** D03 §2, §3. **The deck as data:** one header line (the pack, the slice, the base, the D03 head, the statuses `merged`, `PROPOSED` and `RULED`, the `frozen` flag, the counts), then one row per string with `id`, `text`, `screen`, `kind`, `where`, `status`, `owner`, `source`, `ref`, `consumer` and `frozen`, and `key`, `narrowed` or `live` where they apply.

## §G Handoff checklists (`16` §11.4, `16`:577)

Linked, never restated: CMP-109 (`D03H`:55), CMP-132 (`D03H`:117 and `E25H`:62, F-2), CMP-182 (`D03H`:146), CMP-228 (`D03H`:174), CMP-227 (`E25H`:5); the motion-pair lines are D04H's (`D04H`:9–11). Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`; `[ ] PENDING — <reason>` marks a line still open, with what closes it. At Done only `[x]` and N/A lines remain.

## Handoff checklist — CMP-197 ChartTooltip, footprint rows (E18-D05, #499)

- [ ] **Final Penpot link** — PENDING — D03 PR 2 (D03 board 01)
- [x] **Variants × States matrix** — one, two and three rows; forming (D03 A-11; §D)
- [x] **Keyboard table** — N/A — the tooltip is not focusable; the mirror carries the values (D04 §7.1)
- [x] **Accessible name / role table** — hidden from AT; the mirror's composition W-3 (`D03`:372)
- [x] **Live data** — none: the rows follow the crosshair, never announced (D04 §7.3)
- [x] **Motion pair** — N/A — none animated
- [x] **Density notes** — D03 §5.2
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §2.1's names land with D03 PR 2
- [x] **Data contract confirmed** — the cell's fields (`24`:819); no field invented
- [ ] **Contrast and CVD** — PENDING — D03 §2.3 with its boards
- [ ] **Design QA checklist (16 §12)** — PENDING — D03 PR 2
- [ ] **Sign-off** — PENDING — owner `approved` on #499

## Handoff checklist — CMP-046 Drawer, footprint cell detail (E18-D05, #499)

- [ ] **Final Penpot link** — PENDING — D03 PR 2 (D03 board 01)
- [x] **Variants × States matrix** — a traded level, a level with no trades, the T2 buttons (D03 A-12; §D)
- [x] **Keyboard table** — D04 §7.1–§7.2 (`D04`:160, :175): non-modal, `Esc` returns focus to the level
- [x] **Accessible name / role table** — `15` CMP-046's, titled "Cell {range} · {bar} bar" (D03 A-12)
- [x] **Live data** — the forming bar's values coalesced; announced only by D04 §7.3's rows
- [x] **Motion pair** — `15` CMP-046's, instant under reduce
- [x] **Density notes** — 320 px compact, 360 px comfortable (D03 A-12)
- [x] **Essential-exceptions log** — none
- [ ] **Tokens used** — PENDING — D03 §2.1's names land with D03 PR 2
- [x] **Data contract confirmed** — the cell's fields (`24`:819); GAP-10 for the counts (`D02`:905)
- [ ] **Contrast and CVD** — PENDING — D03 §2.3 with its boards
- [ ] **Design QA checklist (16 §12)** — PENDING — D03 PR 2
- [ ] **Sign-off** — PENDING — owner `approved` on #499

## Handoff checklist — CMP-227 EstimatedBadge, the SCR-056 variant (E18-D05, #499)

- [ ] **Final Penpot link** — PENDING — D03 PR 2 (D03 board 09)
- [x] **Variants × States matrix** — the chip before the row's status, stamped "no v1 source sets it" (D02 §7.4)
- [x] **Keyboard table** — `E25H`:12: `Tab`, `Enter` / `Space` opens SCR-058, `Esc`
- [x] **Accessible name / role table** — `E25H`:13
- [x] **Live data** — N/A — the chip binds no streaming value (`E25H`:14)
- [x] **Motion pair** — none animated (`E25H`:15)
- [x] **Density notes** — `E25H`:16
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — CMP-227's (`E25H`:18)
- [x] **Data contract confirmed** — `FootprintImbalance.estimated`, false for every v1 source (D02 §7.4)
- [ ] **Contrast and CVD** — PENDING — `E25H`:20, with E25-D05's pairs
- [ ] **Design QA checklist (16 §12)** — PENDING — D03 PR 2
- [ ] **Sign-off** — PENDING — owner `approved` on #499
