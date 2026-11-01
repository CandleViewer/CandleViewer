# E08-D10 — Hand-off (`16` §11.4; SCR-151's E08 variants)

Components: **CMP-026 EmptyState** (the `backfill-in-progress` block and its throttled description; `recording-not-started` as E16-D05 left it), **CMP-023 Progress Bar** (the known-target bar), **CMP-038 InlineSpinnerText** (the unknown-target words), **CMP-011 Tag / Chip** (the `backfilling`, `gapped` and Partial chips), **CMP-001 Button** (`Retry`) and **CMP-021 Link** (the Owner's diagnostic link, `Show coverage`), plus CMP-019's glyphs. The spec is [E08-D10.md](E08-D10.md); every "§" below without a prefix is the spec's. The variants change component examples and the catalogue's analytics line, so the hand-off is due.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-026 (E08 variants)                                                                                                              | CMP-023 / CMP-038 (progress)                          | CMP-011 (chips)                                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Final Penpot link        | [x] page `E08-D10 SCR-151 empty and backfill states` (page id `cb0c3916-2579-81a4-8008-e0954a0af0d3`); boards 01–09 drawn (spec §0) | [x] the same page: boards 01, 08, 09 drawn (spec §0)  | [x] the same page: boards 01–03 drawn (spec §0)                                                                              |
| Variants × states        | [x] spec §2, §3, §4, §5                                                                                                             | [x] spec §3 (known and unknown target), §4 (frozen)   | [x] spec §3, §4, §6                                                                                                          |
| Keyboard table           | [x] spec §3–§6 "Keyboard and focus" rows; §10.1                                                                                     | [x] not focusable                                     | [x] the Partial chip: a described static stop (KB-19, spec §4); `backfilling` and `gapped`: static, not a stop (spec §4, §6) |
| Accessible name and role | [x] heading `h3`, cause as description (spec §10.1)                                                                                 | [x] "History loaded so far", value text W-3           | [x] Partial: `role="note"`, missing range in its description; the others' words in the panel's description                   |
| Live data                | [x] spec §10.2, every row with its `max_rate`                                                                                       | [x] never a live region; ≤ 1 Hz samples (T-4)         | [x] never announced                                                                                                          |
| Motion pair              | [x] cuts only (spec §7)                                                                                                             | [x] steps per sample; no loop, no spinner on throttle | [x] none                                                                                                                     |
| Density notes            | [x] compact; the 480 px block (E16-D05)                                                                                             | [x] the `progress?` slot                              | [x] the header's status slot                                                                                                 |
| Essential exceptions     | [x] none                                                                                                                            | [x] none                                              | [x] none                                                                                                                     |
| Tokens used              | [x] spec §11                                                                                                                        | [x] spec §11                                          | [x] spec §11                                                                                                                 |
| Data contract            | [ ] NO: D10-G1 (PROPOSED `backfill` fields)                                                                                         | [ ] NO: D10-G1                                        | [x] `coverage_holes`, `recording_started_at`                                                                                 |
| Contrast                 | [x] spec §11 (computed)                                                                                                             | [x] spec §11 (computed)                               | [x] spec §11 (computed)                                                                                                      |
| Storybook                | [x] §D                                                                                                                              | [x] §D                                                | [x] §D                                                                                                                       |
| Sign-off                 | [ ] owner approval pending                                                                                                          | [ ] owner approval pending                            | [ ] owner approval pending                                                                                                   |

## §B Who applies what

| A              | Target                                | Applied by                               |
| -------------- | ------------------------------------- | ---------------------------------------- |
| D10-A1, D10-A2 | `15` CMP-026, CMP-023                 | `15`'s owner, at the owner's sign-off PR |
| D10-A3         | E08-D13 §SCR-151 row, as a `v1.N` row | E08-D13 (#181)                           |
| D10-A4         | E16-D05 §5                            | E16-D05's owner                          |
| D10-A5         | E11-D04 §10, the loading band row     | E11-D04's owner (#329)                   |
| D10-A6         | `14` SCR-151 analytics                | `14`'s owner, at the owner's sign-off PR |
| D10-A7         | E08-D12 G-02                          | E08-D12 (#180), at its re-run            |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `fef3148c5` (the tool checks it); New replaces it, or follows it where the row says "insert after". 7<!--=COUNT:arows--> rows.

| A      | Target        | Field (`file`:line)             | Old                                                 | New                                                                                                              |
| ------ | ------------- | ------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| D10-A1 | `15` CMP-026  | E08-D04 example (`15`:314)      | (e.g. "Loading history — page 3 of ~9")             | (e.g. "Loaded 3 200 of about 5 000 bars"; bars, never pages or a countdown — E08-D10 §3)                         |
| D10-A2 | `15` CMP-023  | `valueText` example (`15`:282)  | e.g. "page 3 of ~9"                                 | e.g. "Loaded 3 200 of about 5 000 bars"                                                                          |
| D10-A3 | E08-D13       | SCR-151 row (D13:172)           | `backfill-throttled` has no merged source (D13-G-3) | `backfill-throttled` is E08-D10 §4 (#178); D13-G-3 answered                                                      |
| D10-A4 | E16-D05 §5    | the cited backfill (E16D5:242)  | (`aria-valuetext` "page 3 of 9")                    | (`aria-valuetext` "Loaded 3 200 of about 5 000 bars", E08-D10 §3)                                                |
| D10-A5 | E11-D04 §10   | loading older bars (D04E11:325) | a band row "Loading older bars…"                    | insert after: ; while the exchange holds the paging back, the band reads E08-D10 W-6 and the header carries W-7  |
| D10-A6 | `14` SCR-151  | analytics (`14`:3060)           | `empty_state_shown` `{surface, reason}`             | insert after: with `reason` ∈ {`nothing_created`, `no_matches`, `not_recorded`, `role_restricted`} (E08-D10 §12) |
| D10-A7 | E08-D12 §12.2 | G-02 (D12:568)                  | have no hi-fi text                                  | have hi-fi text in E08-D10 (#178) §10, which answers this column                                                 |

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component | Stories                                                                                                            |
| --------- | ------------------------------------------------------------------------------------------------------------------ |
| CMP-026   | the merged list + BackfillKnownTarget · BackfillOpenTarget · BackfillThrottled · ThrottledOwnerLink · GaveUpNoRows |
| CMP-023   | the merged list + BackfillBars · FrozenAtSample                                                                    |
| CMP-011   | the merged list + BackfillingChip · GappedChip · PartialBackTo                                                     |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

- [ ] Board 01: loaded rows stay visible and usable while older bars load; nothing covers them.
- [ ] Board 01: the progress says bars, never pages, seconds or a percentage over an unknown total.
- [ ] Board 02: the throttled line says older bars are still loading and being retried; the result is labelled partial.
- [ ] Board 02: only the Owner's frame shows the diagnostic link; the Manager's frame shows no trace of it.
- [ ] Board 03: a reconstructed window and a missing window read differently, and neither empties the panel.
- [ ] Board 04: the E08 strings replace D02's two and read as the data-not-recorded class; none says "No data".
- [ ] Board 05: a cache hit shows data with no skeleton; nothing appears before the slow-path threshold.
- [ ] Board 06: each announcing row has a rate; the progress is never announced per sample.
- [ ] Boards 08–09: the light and high-contrast twins keep every word.
- [ ] Record `approved` on #178, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer       | Builds from                             | Waits on                                       |
| -------------- | --------------------------------------- | ---------------------------------------------- |
| E16-S05 (#487) | spec §2–§13; §C's A-rows; §D            | D10-G1 through epic E08 (#35) and `22`'s owner |
| E08-D13 (#181) | spec §2, §11, §13; D10-A3               | —                                              |
| E08-D14 (#277) | spec §2.1 (the forced states), §10, §11 | the build                                      |
| E08-D12 (#180) | spec §10                                | —                                              |

## §G Dry-run needs (spec §18; one item per need, the spec pointer after the arrow)

An item marked (not found) had no pointer when the role ran; its fold is named after it.

| Role                   | Needs                                                                                                                                                                                                                                                                                                                                                                                    |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| story: E16-S05 (#487)  | the variant per coverage state → §2.1 · the full-panel and in-context slots → §3 · the value text → §3 · the throttled words and chip → §4 · the give-up control (not found) → §4 · the Owner-only link → §4 · the recorder variant → §5.1 · the gap markers → §6 · the timing constants → §7 · the event a cache hit emits (not found) → §12 · the reason enum → §12 · the tokens → §11 |
| design: E08-D13 (#181) | the variant map → §2 · the copy deck → §13 · the tokens and ratios → §11 · the throttled source → §4 · the A-rows → §C                                                                                                                                                                                                                                                                   |
| QA: E08-D14 (#277)     | the forced-state list per variant (not found) → §2.1 · the announcement rates → §10.2 · the contrast matrix → §11 · the cache-hit rule → §7 · the no-spinner rule → §4                                                                                                                                                                                                                   |
| review: E08-D12 (#180) | the ten items → §10.1 · `aria-valuetext` → §3 · the countdown's politeness → §10.2 · every `max_rate` → §10.2 · the naming rule → §10.1 · contrast in three themes → §11                                                                                                                                                                                                                 |

## §H The board plan (drawn in this PR; spec §0 as built)

The boards of spec §0; frames named `SCR-151/<variant>/<state> · <theme>`. Data: a seeded synthetic history (seed 178), not recorded, declared synthetic on every board's face; only the instrument's tick size comes from the recorded fixture. PROPOSED fields (R-7) are labelled on every frame that uses them: boards 01, 02, 05 and 08. Hosts: board 02's `throttled/in-context · dark` is SCR-053's header (BQ-6, narrowed by D10-Q3); the other in-context frames use a generic E08 history panel; SCR-045 is not drawn (D10-A5 only).

| Board | Frames                                                                                                                                                       |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 01    | `backfill/known-target · dark`, `backfill/open-target · dark`, `backfill/in-context · dark`, `backfill/cut · dark`                                           |
| 02    | `throttled/in-context · dark`, `throttled/long-wait · dark`, `throttled/gave-up · dark`, `throttled/owner-vs-manager · dark`                                 |
| 03    | `gap/gapped · dark`, `gap/hole-row · dark`, `gap/both · dark`, `gap/vs-stale · dark`                                                                         |
| 04    | `classes/e08-delta · dark` (W-10 and W-11 over D02's two strings), `classes/e08-exemplars · dark` (the E08 table; the three classes stay E16-D05 board 01's) |
| 05    | `timing/cache-hit · dark`, `timing/slow-path · dark`, `timing/definitive-empty · dark`                                                                       |
| 06    | `a11y/focus-order · dark` (the Partial chip's stop), `a11y/retry-focus · dark`, `a11y/status-rows · dark`                                                    |
| 07    | `redlines · dark`                                                                                                                                            |
| 08    | `throttled/in-context · light`, `gap/hole-row · light`, `backfill/known-target · light`                                                                      |
| 09    | `backfill/known-target · hc`, `gap/hole-row · hc`                                                                                                            |

## §I Summary for #178

1. Text-first hi-fi of SCR-151's E08 variants + hand-off + default-deny audit tool; 9<!--=COUNT:boards--> boards drawn in this PR (spec §0 as built), the light variants beyond board 08 the ruled text-only exception (BQ-2), the high-contrast variants beyond board 09 text only on the same reading (spec D10-C16 … D10-C20).
2. Backfill shows bars loaded of a target in bars, or bars and the oldest date; never pages, a countdown or a false percentage.
3. Throttled is a `backfilling` sub-case: the exchange's hold-back in plain words, a Partial chip, automatic retries, no spinner; the Owner alone gets a link to SCR-147.
4. A gap is marked in context: `gapped` when reconstructed, a separator row with its cause when missing; never merged, never emptying the panel.
5. The recorder variant and the three classes stay E16-D05's; D02's wireframe strings are superseded.
6. Cache hits show data at once; nothing appears before 600 ms; empty only on a definitive answer.
7. BQ-0 … BQ-15 RULED (comment 6552807966): twelve defaults stand; BQ-2 records the text-only exception for the light variants beyond board 08 (spec D10-C11 … D10-C15, to the next boards touch); BQ-10 reuses `no_matches`; BQ-11 keeps the merged cut, no minimum display. Owner approval pending.
