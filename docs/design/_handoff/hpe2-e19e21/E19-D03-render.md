# E19-D03 (#438): render return

- File: `E19-D03 boards` (file id withheld)
- Page: `{"name": "E19-D03", "id": "7aa87b08-b547-8059-8008-e3e9b2e83f3c"}`
- Drawn on the kit at transport `af6900a9f`, under the dark theme, one board at a time with `render_exec.py --page "E19-D03"`,
  then `common/board.sh` (post-step with hatch and dash on, `lc`, `lc3`, `lintd`). Boards 06 and 08 (over 2 000 shapes)
  were drawn one section per call through `mkcall4.py`, the selection cleared after each call, then touched and relaid out
  one top-level child per call, then `render_exec.py --from report`. Boards 01, 03, 04, 06, 07, 08 and 10 were exported
  1:1 under dark. Boards 02, 05 and 09 are light boards: each was exported once, under light only.
  - Light: before the export the probe read `canvas.fill` #f6f7f9 (`palette.light.neutral.50`) on all three; the
    `color.surface.raised` fills read #edeff2 (02: 4, 05: 14, 09: 13 shapes), every `color.text.primary` text read #14171a
    (35, 98 and 215 texts), and every `color.tpo.letter` fill read #3a4148 (`palette.light.neutral.700`, the
    `E19-D03 local · light` value; 1, 2 and 3 shapes). No light board binds `color.tpo.initialbalance` as a fill.
  - The theme was then set back to dark. The probe on 05 read `canvas.fill` #11151a, its `color.tpo.letter` fills #b1bac4
    (`E19-D03 local · dark`), and 01's primary texts read #e8eaed.
- Seed: the four token sets, their sync scripts, a top-up from `penpot_token_sets.py --emit-js` at this branch's base
  (it added 18 `semantic-dark`, 1 `semantic-light` and 1 `semantic-hc` rows, all `color.chart.*`, which no sheet binds),
  the themes, then `local-tokens.js` (6 rows added; each local set active in its own theme only), the repo's local icons,
  `common/local-icons-e19e21.js` and `theme-dark.js`. Penpot refused the four `motion.duration.*` primitives ("type is
  invalid: Empty field"); no sheet binds a motion token.
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `text-overflow`, `outside-root`, `unmeasured` and `unbound` all 0;
  - `lc3.cutN` 0. `lc.clippedN` is 0 on every board but 09, where its 9 are the settings dialog's scrolling form column
    (`lc3`: 3 texts scrolled away, 6 at the scroll edge), as drawn;
  - every frame at its md size and position, `clip` true, `spill` 0 (50 frames in all), except 01's two insets, raised
    728 -> 736 (see the SHEET-FIX lines). Penpot shows a frame named `SCR-038∕x` as `SCR-038 / x`; the names were compared
    with that spacing removed;
  - `lc.h` = `lc.want`. Every kit root height was an estimate; each root was set to the checked `want` (footer end + 80 on
    every board; see the SHEET-FIX lines).
- Each md's Live checks hold: the root names read back exactly; every annotation column ends inside its root; 01's
  text-scale inset holds every wrapped header and legend row (no cut text after the fixes below); the local sets exist
  and bind as described above.
- Legend keys (kit-wide): every CMP-199 legend drew its key rows 12 px tall around 14 px words, and its HVN / LVN glyphs
  (12 px line box) in 8 px clipped swatches, so each legend cut 6 texts by 1 to 2 px. On every board the key rows were
  raised to their words' 14 px and each glyph was fixed to its swatch's 12 x 8 box with its content centred, so it paints
  where the sheet drew it (`type.num.xs` stays bound). 01's text-scale inset instead widened its two glyph swatches to fit
  their 18 px glyphs. One line per board below.
- Remaining lint findings (`overlap`), each checked live and kept:
  - the chart's stacked layer groups (`group 02` over `group 01`, and so on) in every SCR-030 price pane, CMP-183 plot and
    CMP-183 overlay plot: by construction;
  - the last-price label over the price axis's 73,000.0 tick label (1 per docked frame): the label covers the tick, as a
    price axis draws it;
  - 06: the LVN glyphs at the ends of the hatched (estimated) rows overlap the hatch rows next to them by 2 x 2 or 2 x 3 px;
  - 09: the CMP-043 dialog over the price pane and the docked panel behind it (3 frames x 2).
  No text is hidden by any of them (checked in every PNG).
- Link underlines: no board on this page draws a link (`lk` found none).
- Backticks in drawn text: 06 had 6 strings, 07 had 1, 08 had 1 and 10 had 1, as the kit check said. The backticks were
  removed live (the words kept).
- Reloads: the tab was reloaded seven times, each before a board, never mid-board: before 03 (about 1 340 shapes since the
  file opened), before 05 (about 1 950 since the last reload), before 06 and before 08 (the kit's big boards; 07 alone is
  1 563), before 07 (06 alone is 3 352), before 09 (08 alone is 2 183) and before 10 (09 alone is 1 508). The fonts were warmed
  after each reload. Every PNG was looked at in full, and dense regions at 1x and zoomed in; no blank, fallback-serif or
  wrongly sized text was found after the fixes below.
- Each PNG sits at the export path line 3 of its sidecar names.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | cutN | PNG                                                  | Size      | Bytes  | Gate                                                                  |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | ---- | ---------------------------------------------------- | --------- | ------ | --------------------------------------------------------------------- |
| 01  | 7aa87b08-b547-8059-8008-e3e9b2f15be4 | 1080  | 0 / 0 / 0 / 6 / 0                                          | 0    | docs/design/E19/img/E19-D03-01-docked-redlines.png   | 3280x1878 | 502001 | PASS E19-D03-01-docked-redlines.png theme=dark own=5437 other=133     |
| 02  | 7aa87b08-b547-8059-8008-e3eca8d99a1c | 262   | 0 / 0 / 0 / 2 / 0                                          | 0    | docs/design/E19/img/E19-D03-02-docked-light.png      | 1920x998  | 169380 | PASS E19-D03-02-docked-light.png theme=light own=2858 other=44        |
| 03  | 826104a1-5c69-80b1-8008-e3ed7f0ffb49 | 1203  | 0 / 0 / 0 / 14 / 0                                         | 0    | docs/design/E19/img/E19-D03-03-overlay-densities.png | 3280x1878 | 322440 | PASS E19-D03-03-overlay-densities.png theme=dark own=1218 other=77    |
| 04  | 826104a1-5c69-80b1-8008-e3eeffd5f020 | 746   | 0 / 0 / 0 / 2 / 0                                          | 0    | docs/design/E19/img/E19-D03-04-cmp-110-variants.png  | 2880x2118 | 498903 | PASS E19-D03-04-cmp-110-variants.png theme=dark own=8444 other=195    |
| 05  | 6cc78319-f2b2-802a-8008-e3f0a8bd15bf | 610   | 0 / 0 / 0 / 4 / 0                                          | 0    | docs/design/E19/img/E19-D03-05-greyscale-cvd.png     | 3280x1878 | 331244 | PASS E19-D03-05-greyscale-cvd.png theme=light own=5691 other=342      |
| 06  | 4a22c7f8-b893-80ef-8008-e3f333a72dc5 | 3352  | 0 / 0 / 0 / 163 / 0                                        | 0    | docs/design/E19/img/E19-D03-06-cmp-183-periods.png   | 3280x3398 | 608160 | PASS E19-D03-06-cmp-183-periods.png theme=dark own=2589 other=287     |
| 07  | 0d70393e-b25b-8076-8008-e3f9b8d5137d | 1563  | 0 / 0 / 0 / 15 / 0                                         | 0    | docs/design/E19/img/E19-D03-07-cmp-184-tpo.png       | 3280x2518 | 476098 | PASS E19-D03-07-cmp-184-tpo.png theme=dark own=2517 other=149         |
| 08  | cba5b149-042a-8015-8008-e3fccf4d43f1 | 2183  | 0 / 0 / 0 / 48 / 0                                         | 0    | docs/design/E19/img/E19-D03-08-rays-npoc-tooltip.png | 3280x2758 | 525813 | PASS E19-D03-08-rays-npoc-tooltip.png theme=dark own=1808 other=71    |
| 09  | a437eabe-b887-80db-8008-e403ee49b958 | 1508  | 0 / 0 / 0 / 12 / 0                                         | 0    | docs/design/E19/img/E19-D03-09-settings.png          | 3280x1878 | 432269 | PASS E19-D03-09-settings.png theme=light own=2965 other=1             |
| 10  | 307e836f-d138-801c-8008-e4073f2338c4 | 1538  | 0 / 0 / 0 / 13 / 0                                         | 0    | docs/design/E19/img/E19-D03-10-table-focus-states.png | 3280x2758 | 584273 | PASS E19-D03-10-table-focus-states.png theme=dark own=3274 other=116 |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

Dark exports of boards 05 and 09 (kit reading R-K1), taken 1:1 under the dark theme (probe `canvas.fill` #11151a before export); the theme was left on dark:

- `docs/design/E19/img/E19-D03-05-greyscale-cvd-dark.png`: 3280x1878, 332179 bytes, PASS E19-D03-05-greyscale-cvd-dark.png theme=dark own=1502 other=97
- `docs/design/E19/img/E19-D03-09-settings-dark.png`: 3280x1878, 434426 bytes, PASS E19-D03-09-settings-dark.png theme=dark own=2329 other=199

SHEET-FIX E19-D03 01 root height 1896 -> 1878 (checked want: footer end 1798 + 80)
SHEET-FIX E19-D03 01 legend keys in the four docked legends (compact, dense, comfortable, degraded): 16 key rows raised 12 -> 14 to fit their 14 px words, and the 8 HVN / LVN glyphs fixed to their 12 x 8 swatch with content centred (their 12 px line box ran 2 px past the swatch's top and bottom); in the text-scale-200 inset the HVN and LVN swatches widened 12 -> 24 (the 18 px glyph ran 9 px past the right edge) and their glyphs centred in them
SHEET-FIX E19-D03 01 frames 'SCR-038∕degraded-dark' and 'SCR-038∕text-scale-200-dark' raised 728 -> 736 (one 8 px step): each holds a 736 px docked panel that spilled 8 px past the frame's bottom
SHEET-FIX E19-D03 02 root height 1016 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E19-D03 02 legend keys: 4 key rows raised 12 -> 14 and the 2 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 03 root height 1896 -> 1878 (checked want: footer end 1798 + 80)
SHEET-FIX E19-D03 03 legend keys: 4 key rows raised 12 -> 14 and the 2 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 04 root height 2136 -> 2118 (checked want: footer end 2038 + 80)
SHEET-FIX E19-D03 04 legend keys: 4 key rows raised 12 -> 14 and the 2 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 05 root height 1896 -> 1878 (checked want: footer end 1798 + 80)
SHEET-FIX E19-D03 05 legend keys in both greyscale frames: 8 key rows raised 12 -> 14 and the 4 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 06 root height 3416 -> 3398 (checked want: footer end 3318 + 80)
SHEET-FIX E19-D03 06 legend keys in the five docked frames: 20 key rows raised 12 -> 14 and the 10 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 06 'level VAH · line 1' and 'line 2' in the edge-5000-rows frame moved up 6 px (325 -> 319, 337 -> 331 in the frame): the POC rail (y 344 to 346, 9 ticks under VAH) ran through the drawn '73,195.2'
SHEET-FIX E19-D03 06 backticks removed from six drawn texts, words kept: the five period lines' annotation 'value-2' ("`24` kind ..." -> "24 kind ...") and the edge-5000-rows 'value-2' ("(<= 5 000, `14`:1013) ... (`26`:238)")
SHEET-FIX E19-D03 07 root height 2536 -> 2518 (checked want: footer end 2438 + 80)
SHEET-FIX E19-D03 07 legend keys in the three docked frames: 12 key rows raised 12 -> 14 and the 6 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 07 backticks removed from the drawn 'line 03' ("`24` has no IB or single-print fields ..."), words kept
SHEET-FIX E19-D03 08 root height 2776 -> 2758 (checked want: footer end 2678 + 80)
SHEET-FIX E19-D03 08 legend keys in the three docked frames: 12 key rows raised 12 -> 14 and the 6 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 08 edge-va-spans-view frame: 19 candle wicks and bodies that ran over the time-axis words (y 759) cut at y 754, and 'wick 007' / 'body 007' (wholly below that line) removed; the sheet drew them past the pane's time axis, 11 of them past the root's bottom (lint outside-root 11)
SHEET-FIX E19-D03 08 edge-va-spans-view frame: the in-plot VAL level label ('level VAL · line 1', 'line 2', 'leader') removed: VAL is below the view and is drawn as the 'VAL pin' (as VAH is), whose backing hid line 2 and left a stray 'VAL' word above it
SHEET-FIX E19-D03 08 edge-va-spans-view frame: 'VAH pin mark' and 'VAL pin mark' moved 1216 -> 1178 (2 px left of their pin backing): at 1216 each crossed its pin's price words
SHEET-FIX E19-D03 08 backticks removed from the drawn annotation 'value-2' ("(`24` gives no tie flag, D03-G2)"), words kept
SHEET-FIX E19-D03 09 root height 1896 -> 1878 (checked want: footer end 1798 + 80)
SHEET-FIX E19-D03 09 legend keys in the three docked frames: 12 key rows raised 12 -> 14 and the 6 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 10 root height 2776 -> 2758 (checked want: footer end 2678 + 80)
SHEET-FIX E19-D03 10 legend keys in the five docked frames: 20 key rows raised 12 -> 14 and the 10 HVN / LVN glyphs fixed to their 12 x 8 swatch, as on 01
SHEET-FIX E19-D03 10 table-dark frame: the table's 'header row' and its five th cells raised 24 -> 32 (one 8 px step): 'th · pct' wraps "% of POC" to two lines (29 px) in its 40 px column and was cut 2.5 px top and bottom; the rows below moved down 8 px inside the table's fixed 583 px, 'load more rows' now ending at its bottom edge
SHEET-FIX E19-D03 10 backticks removed from the drawn 'line 01' ("(`15`:464)"), words kept

## For the kit owner

- Kit-wide: every root came out 18 px shorter than its kit estimate (footers end shorter live). The CMP-199 legend key
  sizes (12 px rows around 14 px words; 12 px glyph line boxes in 8 px swatches) cut text on every board; a regenerated
  kit can carry the 14 px rows and fitted glyph boxes above.
- 05 and 09: their md's kit reading R-K1 asks for a second export under dark (`E19-D03-05-greyscale-cvd-dark.png`,
  `E19-D03-09-settings-dark.png`), and their annotations name those files. RENDER.md said light only; the kit owner
  confirmed both are needed, and they are now carried (the dark-exports list above).
- 05: its md also asks for Rec. 601 greyscale crops of the 'greyscale-dark' and 'greyscale-light' frames. RENDER.md does
  not list them, so this return does not carry them; they are `cvd_sim.py` runs on the PNGs, for whoever owns that step.
  Its `SCR-038∕cvd-sheet` frame leaves its lower part empty, as the sheet draws it.
- 08: the edge-va-spans-view frame's sheet draws both a level label and an edge pin for VAL (VAL below the view) and puts
  both pin marks on the pins' words; see the SHEET-FIX lines. 06's edge-5000-rows frame puts VAH 9 ticks above POC, and
  the label collision step moved the POC label but not VAH clear of the POC rail.
- 10: '% of POC' does not fit on one line in the 56 px 'th · pct' column (40 px inside its padding), so it wraps.
