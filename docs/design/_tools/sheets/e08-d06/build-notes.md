# E08-D06 board kit: build notes (#174, SCR-103 symbol info drawer)

Kit `e08d06kit.py` (this folder). Spec, binding, every string from it: `docs/design/E08/E08-D06.md` and
`E08-D06-handoff.md` as at `BASE` (`33bb920225ec`, the merge of the E08-D06 text, read with `git show` in this
checkout; md5 pinned in `SPEC_MD5`: spec `af8763f0…`, hand-off `50667e8f…`; the kit refuses drifted bytes). Seed
data: the DATA block of the r2 board script (2026-10-23), copied to `r2/e08-d06-board.js.txt` (sha256 `298c156f…e1a7`,
pinned in `R2_SHA256`). The kit reads only its data
(fixtures, strings, per-board markers), never its drawing code. Every number is re-derived from the fixture values by
the kit's §5 formatters; `r2_consistency()` proves r2's strings equal them (rules x3, live x14, recording x4, the
tiers, the seven CMP-126 conditions). The r2 data is credited by its sha256 and date only.

## Pipeline (offline; nothing here touches Penpot)

1. Board author writes `gen/gen_<key>.py` (key `1D` … `25D`, `1L` … `17L`); a twin imports its base's
   `build(theme)` and calls it with `theme="light"`.
   `frames = [k.drawer_frame(fr, theme, dkey) | k.free_frame(fr, theme, kids) for fr in k.frames_of(key)]`,
   `ann = k.annotations(key, [k.frame_block(fr, lines=…), *map(k.marker_block, k.R2_BOARDS[n]["markers"])])`.
   Board 1 is already written as `k.board1(theme)`: the reference generator.
2. `p = k.write_sheet(key, frames, ann, illustrative=…)` → `build/NN-<slug>-<theme>.json`; kit lint
   (no inst, local icons, string wrap, explicit h, no "/" in names, every `cell · *` padded 8 px a side, no painted
   colour), the banned-string scan and `../tools/validate_sheet.py --components components.offline.json --tokens
token-sync.json` must be clean (exit 0), `notes.live_checks` non-empty, else `RuntimeError`.
3. `k.write_md(key, p)` → `build/` and this folder, `NN-<slug>-<theme>.md`; line 3 is the render script's line:
   ``File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/<§15 name>.png`; sheet
`NN-<slug>-<theme>.json` (validated); theme dark.`` (`theme light.` on the twins).
4. `k.pack_sheet(p)` → `v4/<same name>`: the packer writes the absolute raw-sheet path, its sha256 is checked, every
   packed section ≤ 9 216 B, `mkcall4.py <packed> count` = the section count; then `compactOf.file` is rewritten to
   the bare name (the sha256 stays the raw sheet's), so the committed `v4/` carries no local path.
5. Live (not this kit): per-set file `E08-D06 boards` (tokens + icons + dark, `../README.md` §2), page
   `E08-D06 SCR-103 Symbol info`; render each packed sheet, run the md's live checks, export with the theme-save cycle
   (the light twins are token-bound: the theme switches at export, nothing is painted).

Self-test: `python3 -I -B e08d06kit.py selftest` → 26 PASS (writes `build/selftest/00-selftest.{json,md,packed.json}`:
board 1 dark, validator 0 errors / 0 warnings, 19 sections, packed max 4 436 B).

## Kit API (one line each)

- Registry: `BOARDS` (42 `Board`: n, sid, w, h, twinned, content, line, theme; `.key .name .png .export .sheet`),
  `DARK`, `LIGHT`, `key_of()`, `grid_xy()`, `FRAME_PLAN` / `frames_of()` (`Frame`: fid, w, h, density, states,
  `.caption`), `frame_name()`, `STATES` (§6's 23), `ILLUSTRATIVE` {9, 14, 15, 18}.
- Cap: `PROPOSED_TEN`, `ALTERNATES`, `undrawn()`, `AUTHOR_GROUPS_CAP`, `AUTHOR_GROUPS_42`.
- Spec: `L()`, `HL()`, `cite()`, `in_spec()`; r2: `D`, `R2_BOARDS`.
- Data (§5): `minimal`, `rule_value`, `at_precision`, `change_pct`, `funding_pct`, `magnitude`, `disk`, `gap_span`,
  `hms`, `clock`; `rules(sym)`, `live_values()`, `rec_values()`, `countdown_text(cond)`, `tier_rows()`,
  `r2_consistency()`.
- Drawer: `drawer(dkey, density=, h=, focused=, bands=, above=)`, `drawer_frame()`, `drawer_header()`,
  `drawer_footer()`, `band()`, `band_r2(key)`, `item()`, `dl_row(label, value, kind=, unit=, tag=, stale=, col=)`,
  `line()`, `example()`, `sentence()`, `chip()` (CMP-239), `notice()` (CMP-028), `inline_error()` (CMP-027),
  `strip()` (CMP-078), `skeleton()` (CMP-015 / placeholder), `scrim()`, `scr152_banner()`.
- Components: `countdown(cond)` (CMP-126), `recorder_row(word, says=, record=, settings=, owner_rows=)` (CMP-177;
  `REC_WORDS` = §4.3's strings), `T2_OWNER_ONLY`, `T2_VIEW_AS`, `T3_SENTENCE` (sentence form, no lock glyph, no
  button, no aria-disabled), `tiers(state)` (§4.4), `popover(state)` (CMP-125).
- Controls: `button()`, `buttons_row()`, `close_button()`, `link()`, `ring()` (CMP-039 focus).
- Board: `free_frame()`, `frame_block()`, `marker_block()`, `annotations()`, `layout()`, `board()`, `lint()`,
  `write_sheet()`, `md_line3()`, `write_md()`, `pack_sheet()`, `board1()`, `selftest()`.
- Notes: `live()`, `derived()`, `deviate()`, `spec_gap()`, `copy_gap()`, `fallback()`.

## File, page, grid, frames

- File `E08-D06 boards`; page `E08-D06 SCR-103 Symbol info` (§15 heading); page id recorded at the PR (name + id
  only).
- Root per board: `E08-D06 / NN <§15 id>` (twin: `… · light`), r2's naming; fill `color.surface.app`, clip; slot
  x = ((n−1) mod 5) × 3000, y = floor((n−1)/5) × 2400, twins 5 rows lower (y + 12 000); positions do not depend on
  the drawn set. The root hugs its frames + ONE 400 px annotation column + 80 margins.
- Frames are §15's sizes, 1:1, in one row, 80 px gutters; a `state: <fid>` caption (caption, tertiary) 28 px above
  each; frame name `SCR-103 · <fid> · <theme> · <density>`. Boards 9, 14, 15, 18 carry an "illustrative: …" footer
  (spec L13–20 "marked so on the board"); `board()` refuses them without it.
- Drawer: 480 wide (Q7: no `size.drawer` token), `color.surface.overlay`, `elevation.dialog`, clip; sticky header
  (title heading-md, close 24 px, identity caption secondary, optional chip / notice; `space.dialog.padding`), body
  (bands in D-1's order, `space.stack.lg`), sticky footer (Open in new chart, Open DOM ladder). Columns inside the
  432 px: label 248 | value 104 (11 mono characters, end-aligned, `type.num.base`) | unit 80 (caption, tertiary);
  the CandleViewer band label 176 | value 256; the Next funding row label 136 | CMP-126 296. Rows 24 / 32 px.

## Board registry (all 42, parsed from §15; ✔ = the proposed ten, alt = alternate)

| Key | Root name                                                         | Frame       | Frames | Slot (x, y)    | PNG (`docs/design/E08/img/`)                            | Cap |
| --- | ----------------------------------------------------------------- | ----------- | ------ | -------------- | ------------------------------------------------------- | --- |
| 1D  | `E08-D06 / 01 SCR-103/populated-recorded-owner`                   | 480 × 1360  | 1      | (0, 0)         | `scr-103-populated-recorded-owner-dark.png`             | ✔   |
| 1L  | `E08-D06 / 01 SCR-103/populated-recorded-owner · light`           | 480 × 1360  | 1      | (0, 12000)     | `scr-103-populated-recorded-owner-light.png`            | ✔   |
| 2D  | `E08-D06 / 02 SCR-103/populated-not-recorded-owner`               | 480 × 1220  | 1      | (3000, 0)      | `scr-103-populated-not-recorded-owner-dark.png`         |     |
| 2L  | `E08-D06 / 02 SCR-103/populated-not-recorded-owner · light`       | 480 × 1220  | 1      | (3000, 12000)  | `scr-103-populated-not-recorded-owner-light.png`        |     |
| 3D  | `E08-D06 / 03 SCR-103/live-stale-t1-t2-owner`                     | 1000 × 1360 | 1      | (6000, 0)      | `scr-103-live-stale-t1-t2-owner-dark.png`               | ✔   |
| 3L  | `E08-D06 / 03 SCR-103/live-stale-t1-t2-owner · light`             | 1000 × 1360 | 1      | (6000, 12000)  | `scr-103-live-stale-t1-t2-owner-light.png`              |     |
| 4D  | `E08-D06 / 04 SCR-103/live-reconnecting-owner`                    | 480 × 1360  | 1      | (9000, 0)      | `scr-103-live-reconnecting-owner-dark.png`              |     |
| 4L  | `E08-D06 / 04 SCR-103/live-reconnecting-owner · light`            | 480 × 1360  | 1      | (9000, 12000)  | `scr-103-live-reconnecting-owner-light.png`             |     |
| 5D  | `E08-D06 / 05 SCR-103/live-awaiting-unavailable-owner`            | 1000 × 1360 | 1      | (12000, 0)     | `scr-103-live-awaiting-unavailable-owner-dark.png`      |     |
| 5L  | `E08-D06 / 05 SCR-103/live-awaiting-unavailable-owner · light`    | 1000 × 1360 | 1      | (12000, 12000) | `scr-103-live-awaiting-unavailable-owner-light.png`     |     |
| 6D  | `E08-D06 / 06 SCR-103/not-trading-closed-owner`                   | 480 × 1100  | 1      | (0, 2400)      | `scr-103-not-trading-closed-owner-dark.png`             | ✔   |
| 6L  | `E08-D06 / 06 SCR-103/not-trading-closed-owner · light`           | 480 × 1100  | 1      | (0, 14400)     | `scr-103-not-trading-closed-owner-light.png`            |     |
| 7D  | `E08-D06 / 07 SCR-103/not-trading-variants`                       | 1480 × 560  | 1      | (3000, 2400)   | `scr-103-not-trading-variants-dark.png`                 |     |
| 7L  | `E08-D06 / 07 SCR-103/not-trading-variants · light`               | 1480 × 560  | 1      | (3000, 14400)  | `scr-103-not-trading-variants-light.png`                |     |
| 8D  | `E08-D06 / 08 SCR-103/catalogue-refreshing-owner`                 | 480 × 1060  | 1      | (6000, 2400)   | `scr-103-catalogue-refreshing-owner-dark.png`           |     |
| 8L  | `E08-D06 / 08 SCR-103/catalogue-refreshing-owner · light`         | 480 × 1060  | 1      | (6000, 14400)  | `scr-103-catalogue-refreshing-owner-light.png`          |     |
| 9D  | `E08-D06 / 09 SCR-103/rules-changed-while-open-owner`             | 480 × 1360  | 1      | (9000, 2400)   | `scr-103-rules-changed-while-open-owner-dark.png`       |     |
| 9L  | `E08-D06 / 09 SCR-103/rules-changed-while-open-owner · light`     | 480 × 1360  | 1      | (9000, 14400)  | `scr-103-rules-changed-while-open-owner-light.png`      |     |
| 10D | `E08-D06 / 10 SCR-103/load-error-catalogue-owner`                 | 480 × 760   | 1      | (12000, 2400)  | `scr-103-load-error-catalogue-owner-dark.png`           | ✔   |
| 10L | `E08-D06 / 10 SCR-103/load-error-catalogue-owner · light`         | 480 × 760   | 1      | (12000, 14400) | `scr-103-load-error-catalogue-owner-light.png`          |     |
| 11D | `E08-D06 / 11 SCR-103/load-error-coverage-owner`                  | 480 × 1360  | 1      | (0, 4800)      | `scr-103-load-error-coverage-owner-dark.png`            |     |
| 11L | `E08-D06 / 11 SCR-103/load-error-coverage-owner · light`          | 480 × 1360  | 1      | (0, 16800)     | `scr-103-load-error-coverage-owner-light.png`           |     |
| 12D | `E08-D06 / 12 SCR-103/populated-recorded-manager`                 | 480 × 1260  | 1      | (3000, 4800)   | `scr-103-populated-recorded-manager-dark.png`           |     |
| 12L | `E08-D06 / 12 SCR-103/populated-recorded-manager · light`         | 480 × 1260  | 1      | (3000, 16800)  | `scr-103-populated-recorded-manager-light.png`          |     |
| 13D | `E08-D06 / 13 SCR-103/populated-recorded-viewer`                  | 480 × 1220  | 2      | (6000, 4800)   | `scr-103-populated-recorded-viewer-dark.png`            |     |
| 13L | `E08-D06 / 13 SCR-103/populated-recorded-viewer · light`          | 480 × 1220  | 2      | (6000, 16800)  | `scr-103-populated-recorded-viewer-light.png`           |     |
| 14D | `E08-D06 / 14 SCR-103/risk-limit-tiers`                           | 1040 × 900  | 1      | (9000, 4800)   | `scr-103-risk-limit-tiers-dark.png`                     |     |
| 14L | `E08-D06 / 14 SCR-103/risk-limit-tiers · light`                   | 1040 × 900  | 1      | (9000, 16800)  | `scr-103-risk-limit-tiers-light.png`                    |     |
| 15D | `E08-D06 / 15 CMP-126/funding-countdown-states`                   | 960 × 900   | 1      | (12000, 4800)  | `cmp-126-funding-countdown-states-dark.png`             | ✔   |
| 15L | `E08-D06 / 15 CMP-126/funding-countdown-states · light`           | 960 × 900   | 1      | (12000, 16800) | `cmp-126-funding-countdown-states-light.png`            |     |
| 16D | `E08-D06 / 16 CMP-125/symbol-info-popover-states`                 | 1100 × 700  | 1      | (0, 7200)      | `cmp-125-symbol-info-popover-states-dark.png`           | alt |
| 16L | `E08-D06 / 16 CMP-125/symbol-info-popover-states · light`         | 1100 × 700  | 1      | (0, 19200)     | `cmp-125-symbol-info-popover-states-light.png`          |     |
| 17D | `E08-D06 / 17 CMP-177/recorder-status-row-summary-states`         | 960 × 900   | 1      | (3000, 7200)   | `cmp-177-recorder-status-row-summary-states-dark.png`   |     |
| 17L | `E08-D06 / 17 CMP-177/recorder-status-row-summary-states · light` | 960 × 900   | 1      | (3000, 19200)  | `cmp-177-recorder-status-row-summary-states-light.png`  |     |
| 18D | `E08-D06 / 18 SCR-103/precision-rules-examples`                   | 1200 × 1100 | 1      | (6000, 7200)   | `scr-103-precision-rules-examples-dark.png`             | ✔   |
| 19D | `E08-D06 / 19 SCR-103/anatomy`                                    | 1000 × 1400 | 1      | (9000, 7200)   | `scr-103-anatomy-dark.png`                              | alt |
| 20D | `E08-D06 / 20 SCR-103/context-min-viewport`                       | 1280 × 800  | 2      | (12000, 7200)  | `scr-103-context-min-viewport-dark.png`                 |     |
| 21D | `E08-D06 / 21 SCR-103/keyboard-focus-order`                       | 1000 × 1400 | 1      | (0, 9600)      | `scr-103-keyboard-focus-order-dark.png`                 | ✔   |
| 22D | `E08-D06 / 22 SCR-103/lifecycle-wireflow`                         | 1600 × 900  | 1      | (3000, 9600)   | `scr-103-lifecycle-wireflow-dark.png`                   |     |
| 23D | `E08-D06 / 23 SCR-103/states-matrix`                              | 1280 × 980  | 1      | (6000, 9600)   | `scr-103-states-matrix-dark.png`                        | ✔   |
| 24D | `E08-D06 / 24 SCR-103/populated-recorded-owner-comfortable`       | 480 × 1720  | 1      | (9000, 9600)   | `scr-103-populated-recorded-owner-comfortable-dark.png` |     |
| 25D | `E08-D06 / 25 SCR-103/not-recorded-non-owner-view-as`             | 480 × 1220  | 2      | (12000, 9600)  | `scr-103-not-recorded-non-owner-view-as-dark.png`       | ✔   |

Sheet file per board: `NN-<slug>-<theme>.json` (the theme suffix keeps a twin's sheet apart from its base).

## The proposed ten under the cap (Q1, PROPOSED; the 10-30 ruling: ≤ 10 boards, twins ≤ ⅓)

1D, 1L (the redline and its contrast twin), 3D (AC 2: T1 + T2), 6D (AC 3), 10D (AC 4), 18D (AC 5), 21D (keyboard),
23D (states matrix, every §6 row incl. the two T2 rows), 25D (T2 sentence form + view-as), 15D (CMP-126). One twin
(1L) of ten. CMP-177 is covered by 1D and 25D. Alternates: 19D (anatomy, could replace 10D since 23 carries AC 4's
rows) and 16D (CMP-125).
Not drawn under this pick (32, `k.undrawn()`): 2D, 4D, 5D, 7D, 8D, 9D, 11D, 12D, 13D, 14D, 16D, 17D, 19D, 20D, 22D,
24D and the twins 2L–17L. §15's deviation and each hand-off "Final Penpot link" line name them "not drawn — the text
is binding; drawn on request". Four §6 states appear only on board 23 (Exchange feed down, Catalogue overdue, Opened
from a replay surface, Demo / live), which is in the ten.

## Author groups

- Cap (10, two authors after the ruling): **A** 1D (done: `k.board1`), 1L, 3D, 6D, 10D — drawer states;
  **B** 18D, 21D, 23D, 25D, 15D — spec boards and CMP-126.
- Full 42 (if Q1 rules 42; seven groups, `k.AUTHOR_GROUPS_42`): A 1–6; B 7–11; C 12–14, 24, 25; D 15–17, 19;
  E 18, 20–23; F twins 1L–9L; G twins 10L–17L.

## Per-board sources (r2 DATA keys; the kit's builders)

| Board    | Build from                                                                                                    |
| -------- | ------------------------------------------------------------------------------------------------------------- |
| 1, 24    | `drawer_frame(fr, theme, "d01")` (24: density comfortable, 1720 tall); `k.board1()`                           |
| 2        | `d02` (SOLUSDT: live band = placeholder rows, `ph`; Record this symbol… + link)                               |
| 3 / 5    | `free_frame` row of two `drawer("d03a"/"d03b", h=1360)` / `"d05a"/"d05b"` (skeleton; Live unavailable)        |
| 4        | `drawer("d04", above=[scr152_banner()])` + `scrim()`; the banner sits above the scrim (§6)                    |
| 6 / 7    | `d06` (LUNAUSDT Closed, delisted chip, notice) / `d07a`–`d07c` side by side in 1480 × 560                     |
| 8, 9, 11 | `d08` (503 line, coverage 422 words) / `d09` (illustrative; Changed tag) / `d11` (coverage CMP-027)           |
| 10       | `d10a`–`d10c` stacked (h=None strips) in 480 × 760                                                            |
| 12 / 13  | `d12` (Manager: T3 sentence, no owner rows) / `d12` as the Viewer + `d13A` strip (column A)                   |
| 14       | `tiers("collapsed" / "expanded" / "unavailable")` + `illustrative=`                                           |
| 15       | `countdown(cond)` for ge1h, lt1h, lt5m, elapsed, clock, unknown, suppressed + sign variants (r2 `cmp126`)     |
| 16       | `popover(state)` for default, stale, not trading, unavailable (r2 `cmp125`)                                   |
| 17       | `recorder_row(word, says=…)` per r2 `cmp177` group (Owner; Manager; T2 owner_only; T2 view_as)                |
| 18–23    | r2 `precision`, `callouts` (+ d01), `topBar` (+ d01), `keys` / `_order` (+ d01, `focused=`), `flow`, `matrix` |
| 25       | `d25` and `d25B` (two 480 × 1220 frames)                                                                      |

## Ambiguities (as the kit was cut; the rulings since are noted)

1. **Q1 cap:** RULED 2026-10-31: ≤ 10 boards plus one high-contrast twin (25 hc) as the second twin; the eleven drawn
   are 1D, 1L, 3D, 6D, 10D, 15D, 18D, 21D, 23D, 25D and 25H (`gen/gen_25H.py`).
2. **Sheet names:** the brief's `NN-<slug>.json` would collide for a board and its twin, so sheets are
   `NN-<slug>-<theme>.json`; exports keep §15's `scr-103-…-<theme>.png` / `cmp-…-<theme>.png` exactly (Q7).
3. **Root names keep §15's "/"** (`E08-D06 / 01 SCR-103/populated-recorded-owner`, r2's form; E08-D09's roots also
   carry "/"). Frame and node names never do.
4. **Countdown width:** CMP-126's `next in 01:24:13 · 08:00 UTC` (≈ 218 px) does not fit the value + unit columns
   (184 px) that §3 says it spans, so the Next funding row narrows its label to 136 px (kit choice).
5. **Tags:** "can change" sits in the 80 px unit column (§3's diagram); "Changed · was 0.01" (board 9) goes on a line
   under the value so the value column never moves (§2 D-13 gives no position).
6. **State word colour:** CMP-177's word in `color.text.secondary` (hand-off A-6) vs §3's values in
   `color.text.primary`; the kit follows A-6 for the Recording row only.
7. **CMP-078 escalated strip tone:** danger (subtle + strong, danger icon) is a kit choice; words carry the state.
8. **Tier leverage:** board 14's illustrative max leverage is 1 / margin truncated to 0.01 (r2's 71.42, 41.66); §5
   gives no rounding for tier leverage. Expanded disclosure label: §4.4 gives only "Show all 12 tiers".
9. **CMP-125 width:** 400 px, no source; **buttons:** 24 px compact / 32 comfortable (§10.3 targets).
10. **r2's numbered markers** are not drawn on the frames (they would shift the drawer's flex layout); each marker is
    an annotation block "at <part>" with its five facets, each line cited `L<n>` / `H<n>` where verbatim.
11. **Fit:** board 1's bands need about 1 185 of the 1 201 px body (tight); `d03b` (T2 strip) estimates about 20 px
    over its 1 360 px frame — the drawer clips and scrolls; the live check reads it back.
12. **"Stale 15s"** chip (r2's substitution of §6's "Stale 7s") beside the strip's "Stale 15 s": spacing differs as
    in the spec's own two forms.
13. **High contrast** is "by table" (spec line 1–2); RULED: board 25's hc twin is drawn (Q4). **CVD:** cvd_sim has
    no tritanopia output (Q5); RULED: greyscale + deuteranopia on 1D, 3D, 6D, 23D, 25D, tritanopia deferred to the
    tool's owner.
14. **Label case:** §3's anatomy writes "Size on disk (owner)" / "Retention (owner)", §4.3's table "(Owner)"; the
    kit draws §3's (r2's) form.
15. **REV** is `r3` in each annotation footer (r1 / r2 were the script's text rounds); change `k.REV` for another
    label.
16. **Penpot root names (kit reading):** §15's inner "/" in a board id is written U+2215 "∕" after the
    "E08-D06 / NN " prefix (e.g. "E08-D06 / 01 SCR-103∕populated-recorded-owner"), in the root name and wherever a
    sheet text repeats it: the renderer splits section paths on "/" and otherwise finds no root. No frame or node
    name contains "/". The PNG export names in §15 keep their own form; only Penpot names change.

## Live-check fold (2026-10-31; the drawn boards, rebuilt byte for byte)

The live check of the eleven drawn boards made three fixes in the tab (no reload, dark theme kept). They are folded
into the kit, so a rebuild reproduces the drawn boards:

1. **Header rule:** the renderer's header ran 1 px taller than the estimate (2 px on board 6), so the fixed sticky
   header hid its 1 px rule. `HEADER_LIVE_H` holds the measured header per drawer key; the sticky header is that + 1
   and the fixed body gives the px back (01 / 03 1201 → 1200, 06 sticky 179 → 181 and body 864 → 862, 21 1193 →
   1192, 25 1061 → 1060). Board 10's hugging strips measured 80 + 1 already.
2. **Board 03's T2 cut:** after (1) the "Recorder settings" line (L99) would lose about 0.5 px of its descender, so
   the T2 body is cut at the line boundary above the link row: body 1181, drawer 1341 (`gen/gen_3D.py` `T2_H`); the
   link is hidden by the scroll cut, not clipped, and shows whole in T1 (a sheet deviation).
3. **Root heights:** `MEASURED_H` = max(frame / caption bottom, annotation end) + 80 as measured: 01D 1756, 01L 1786,
   03 1520, 06 1260, 10 994, 15 1098, 18 1298, 21 1560, 23 1259, 25D 1549, 25H 1694. The exports are these sizes.
