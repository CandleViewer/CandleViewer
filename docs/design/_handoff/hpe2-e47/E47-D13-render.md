# E47-D13 (#1311): render return

- File: `E47-D13 boards` (file id withheld)
- Page: `{"name": "E47-D13 — Conformance statement", "id": "516c334d-ac02-80a1-8008-e3192595e5dd"}`
- Drawn under the dark theme. 02 and 10 were exported under light and 04 under high contrast; the rest under dark. The theme was set back to dark after the twins (probe on 05: `canvas.fill` #11151a). The high-contrast set has no canvas override, so 04's theme was confirmed on a `color.text.primary` text instead: fill #f6f8fa (`palette.neutral.1000`, the hc value; dark is #e8eaed).
- Board 01 was redrawn on the corrected kit at transport `73c6a3c37` (the full §7.7 line in the first `statement∕redlines · dark` annotation, which the first run drew cut mid-word). The old board 01 was removed first and only the new one is on the page; the row and the 01 SHEET-FIX lines below are the redraw's.
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - `lc3.cutN` 0;
  - every frame at its md size (1280 x 800) and position, `clip` true, `spill` 0;
  - `lc.h` = `lc.want`. The kit's root heights were estimates; each root was set to the checked `want` (footer end + 80, or the annotation column end + 80 on 01, 04 and 09). See the SHEET-FIX lines.
- Remaining lint findings, each checked live and kept:
  - `outside-root`, all by design: the full SCR-119 statement page sits inside each clipped frame, band (01, 10) or strip (09) scrolled to the part the frame shows, so its far end runs past the root. Nothing outside a frame is visible in the PNGs.
  - `overlap` 2 on 08: the 'outline · inset · the entry' annotation over its 'stop 1' marker, in both frames (the marker sits on the outline's edge).
- Link underlines: the kit drew them at estimated widths (206, 235 and 170 px). Every underline, and every CMP-039 ring nest around a focused link, now takes the label's measured width (187, 194 and 143 px). See the SHEET-FIX lines.
- Text that did not paint after a tab reload: boards 06 and 10 were the first boards after the two reloads. In each, the selected nav item 'Help & about' came out blank in the first export. That frame's texts were re-set to their own characters and the board was exported again. Every other PNG was looked at in full; no other blank or wrongly sized text was found.
- Tags that covered UI content were moved to free space at the same y on 04 and 07. On 09 there was no free space at that y, so the viewport tag moved 30 px up (SHEET-FIX).
- Kept as drawn, for the kit owner:
  - 09 `reflow∕320 · dark`: the four strip labels ('CSS y 0-800' and the rest) sit at the strip bottoms over the strips' last, clipped lines. No strip has free space at that y.
  - 09 `reflow∕200 · dark`: the 'viewport edge' rule at CSS y 400 crosses the first row of the limitations table. That is the sheet's marker; only its tag was moved.
  - 06: the three column tags sit in the gaps between table rows. They touch the row fills but no glyphs.
  - 10 `keyboard∕tab-order · light`: the tag '2: the SettingsLayout nav items, in order' runs 17 px past the nav's right edge into the main column. It covers nothing.
  - Kit-wide: the 13 px × 1.4 lines measure 19 px live against the kit's 18, and the link labels measure narrower than the kit's estimates. That produced the 1-5 px section, pair, list and template cuts and the wide underlines fixed live here.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | PNG                                                       | Size      | Bytes  | Gate                                                                     |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | --------------------------------------------------------- | --------- | ------ | ------------------------------------------------------------------------ |
| 01  | 338d0e73-2a2c-805f-8008-e360054eb07b | 336   | 0 / 5 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-01-statement-anatomy.png      | 3280x1179 | 531955 | PASS E47-D13-01-statement-anatomy.png theme=dark own=7886 other=43       |
| 02  | 516c334d-ac02-80a1-8008-e31abd12de35 | 165   | 0 / 1 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-02-statement-top.png          | 1920x998  | 310727 | PASS E47-D13-02-statement-top.png theme=light own=4790 other=118         |
| 03  | 516c334d-ac02-80a1-8008-e31bca31018c | 405   | 0 / 3 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-03-stale-notice.png           | 4640x998  | 497439 | PASS E47-D13-03-stale-notice.png theme=dark own=11990 other=52           |
| 04  | 516c334d-ac02-80a1-8008-e31cb2bcafa3 | 298   | 0 / 2 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-04-known-limitations.png      | 3280x1001 | 545237 | PASS E47-D13-04-known-limitations.png theme=hc own=8478 other=0          |
| 05  | 516c334d-ac02-80a1-8008-e31dbb7df11e | 217   | 0 / 1 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-05-alternatives.png           | 1920x998  | 252820 | PASS E47-D13-05-alternatives.png theme=dark own=2712 other=14            |
| 06  | b05a02a6-14d5-8093-8008-e31ed4a1869b | 237   | 0 / 1 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-06-criteria-table.png         | 1920x998  | 238419 | PASS E47-D13-06-criteria-table.png theme=dark own=2626 other=20          |
| 07  | b05a02a6-14d5-8093-8008-e31fd9a2cb2e | 573   | 0 / 3 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-07-feedback-copy.png          | 4640x998  | 348235 | PASS E47-D13-07-feedback-copy.png theme=dark own=6920 other=17           |
| 08  | b05a02a6-14d5-8093-8008-e321a086dbc3 | 219   | 0 / 0 / 0 / 2 / 0                                          | docs/design/E47/img/E47-D13-08-entry-insets.png           | 3280x998  | 216949 | PASS E47-D13-08-entry-insets.png theme=dark own=2123 other=24            |
| 09  | b05a02a6-14d5-8093-8008-e322b9ececee | 477   | 0 / 7 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-09-reflow-200.png             | 4640x1029 | 904002 | PASS E47-D13-09-reflow-200.png theme=dark own=34062 other=82             |
| 10  | f530cfa4-3f66-80e0-8008-e3251a6f176e | 310   | 0 / 7 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D13-10-keyboard-reading-order.png | 3280x998  | 358308 | PASS E47-D13-10-keyboard-reading-order.png theme=light own=6507 other=59 |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E47-D13 01 root height 1304 -> 1179 (checked want: annotation column end 1099 + 80; the 1304 was the corrected kit's estimate)
SHEET-FIX E47-D13 01 the three 'cut N · … px not shown' strip labels set to the strip's 12 px height (fixed; 11 px type, was 14 px auto-height, 1 px past the strip top and bottom; lint text-overflow 3 -> 0, lc3.cutN 3 -> 0)
SHEET-FIX E47-D13 01 'link · SCR-013' underline 206 -> 187 px, the label's measured width (it ran 19 px past ')')
SHEET-FIX E47-D13 02 root height 1000 -> 998 (checked want: footer end 918 + 80); section boards '2 · target + scope' 41 -> 42 and '4 · supported' 50 -> 51 grown to their texts (the last text ran 1 px past its clipping section)
SHEET-FIX E47-D13 03 root height 1000 -> 998 (checked want: footer end 918 + 80); section boards '2 · target + scope' 41 -> 42 and '4 · supported' 50 -> 51 grown to their texts in all three frames, as on 02
SHEET-FIX E47-D13 04 root height 1056 -> 1001 (checked want: annotation column end 921 + 80)
SHEET-FIX E47-D13 04 in 'limitations∕table · hc' the three header tags moved right at the same y (x 359 -> 446, 679 -> 728, 919 -> 966), because 'tag · the words first, the criterion number after (R-7)' covered the h2 'Known limitations'
SHEET-FIX E47-D13 05 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D13 05 link underlines set to their labels' measured widths: 'link · SCR-013' 206 -> 187 px, 'link · SCR-117' 235 -> 194 px; the CMP-039 ring nest around the focused SCR-013 link re-fitted to the 187 px link (outer 218 -> 199, ring 216 -> 197, halo 212 -> 193; offsets 6 / 5 / 3 px kept)
SHEET-FIX E47-D13 06 root height 1000 -> 998 (checked want: footer end 918 + 80); frame 'criteria∕table · dark' texts re-set to their own characters (geometry and token binds unchanged), because the selected nav item 'Help & about' did not paint in the first export (the first board after a tab reload)
SHEET-FIX E47-D13 07 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D13 07 in all three frames 'template · W-14' 87 -> 89 (its three lines and 12 px padding measure 89) and section '8 · report a problem' grown to its content (169 -> 172; 170 -> 175 on 'failed', where 'actions' 40 -> 42 to hold the two-line polite region): the section clipped the CMP-039 ring's bottom under the copy button and cut W-18 'Select the template above and copy it by hand.' (lc3.cutN 1 -> 0)
SHEET-FIX E47-D13 07 in all three frames 'tag · W-14 (§11 L297): three lines, nothing personal' (x 974) and 'tag · CMP-033 · W-13 (§11 L296) · focus stays on it' (x 980) moved to x 1024 at the same y, because they covered the template box's right edge
SHEET-FIX E47-D13 08 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D13 08 link underlines set to their labels' measured widths ('link · statement' 170 -> 143 px in both frames, 'link · SCR-013' 206 -> 187 px); the CMP-039 ring nests around the two focused statement links re-fitted to the 143 px link (outer 182 -> 155, ring 180 -> 153, halo 176 -> 149); the 'outline · inset · the entry' annotations re-fitted to the entry they mark, 8 px each side as drawn on the left (SCR-117 460 -> 379 px, SCR-119 220 -> 171 px)
SHEET-FIX E47-D13 09 root height 1048 -> 1029 (checked want: annotation column end 949 + 80)
SHEET-FIX E47-D13 09 boards 1 px shorter than their texts grown to the texts' measured end: '2 · target + scope' 41 -> 42, '4 · supported' 50 -> 51 and the stacked 'pair · …' label/value boards in the 320 frame (37 -> 38, 55 -> 56, 73 -> 74; 15 + 4 + 19 px measure 38), which cut the value's last line by 1 px (lc3.cutN 30 -> 2)
SHEET-FIX E47-D13 09 in 'reflow∕320 · dark' 'alternative 4' 86 -> 87, its 'list' 366 -> 371 and section '6 · alternatives' 398 -> 403, grown to their content: the list cut the last kbd chip 'Ctrl+Shift+H' by 3 px and 'alternative 4' cut the SCR-116 line by 1 px (lc3.cutN 2 -> 0)
SHEET-FIX E47-D13 09 link underlines set to their labels' measured widths ('link · SCR-013' 206 -> 187 px, 'link · SCR-117' 235 -> 194 px, both frames that show them)
SHEET-FIX E47-D13 09 in 'reflow∕200 · dark' 'tag · viewport' moved from y 404 to y 374 (x kept), just above the viewport edge in the empty band under the table header, because below the edge it covered the first row's text in two columns; the strip has no free space at y 404
SHEET-FIX E47-D13 10 root height 1072 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D13 10 'template · W-14' 87 -> 89 (both frames), '2 · target + scope' 41 -> 42, '4 · supported' 50 -> 51 grown to their texts, and the five 'cut N · … px not shown' strip labels set to the strip's 12 px height, as on 01 and 02 (lc3.cutN 7 -> 0)
SHEET-FIX E47-D13 10 link underlines set to their labels' measured widths ('link · SCR-013' 206 -> 187 px, 'link · SCR-117' 235 -> 194 px)
SHEET-FIX E47-D13 10 frame 'keyboard∕tab-order · light' texts re-set to their own characters (geometry and token binds unchanged), because the nav item 'Help & about' did not paint in the first export (the first board after a tab reload)
