# E47-D07 (#1306): render return

- File: `E47-D07 boards` (file id withheld)
- Page: `{"name": "E47-D07 announcements", "id": "338d0e73-2a2c-805f-8008-e3630783cf14"}`
- Drawn on the kit at transport `73c6a3c37`, under the dark theme. 07 was exported under light; the rest under dark. Before the light export, 07's probe read `canvas.fill` #f6f7f9 (`palette.light.neutral.50`). The theme was set back to dark after the twin (probe on 05: `canvas.fill` #11151a).
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - `lc3.cutN` 0;
  - every frame at its md size (1280 x 800) and position, `clip` true, `spill` 0;
  - `lc.h` = `lc.want`. The kit's root heights (1000) were estimates; each root was set to the checked `want` (footer end 918 + 80 = 998). See the SHEET-FIX lines.
- Each md's Live checks hold. On 05 that includes re-centring 'CMP-044 alertdialog · auto-flatten' in its overlay, which needed a 1 px live fix (see SHEET-FIX).
- Remaining lint findings, each checked live and kept:
  - `overlap` 3 on 05, by design: the 'focus∕alertdialog · dark' scrim overlay over the TopBar, body and StatusBar placeholders it dims.
- Link underlines: no board on this page draws a link (`lk` found none).
- The tab was reloaded once, before board 06 (about 890 shapes drawn since the file was created). In 06's first export the selected nav item 'Accessibility' in 'SCR-117∕announcements-default · dark' came out blank. That frame's texts were re-set to their own characters and the board was exported again. Every other PNG was looked at in full at 1x, and zoomed where needed: no other blank, fallback-serif or wrongly sized text was found.
- No board came near 2 000 shapes (the largest, 06, has 731 nodes), so every board rendered in one pass with the driver's own touch and relayout.
- Tags that covered UI content were moved to free space at the same y: the 'Synthetic data · seed 1306 · BTCUSDT' tag in every shell frame (05, 06, 07, 09) sat on the StatusBar placeholders.
- Kept as drawn, for the kit owner:
  - Kit-wide: cite marks still carry backticks in the drawn text: `` `05`:152 `` (01), `` `05`:154 `` (02), `` `15`:531 `` and `` `05`:96 `` (05).
  - Kit-wide: the 13 px x 1.4 lines measure 19 px live against the kit's 18, so the class cards (01, 02, 04) and the part chips (10) had their last line in the bottom padding. Their 'content' stacks were grown 1-2 px (SHEET-FIX); no text was cut before or after. Kit-wide, too, the 'Synthetic data' tag is placed at x 16 in the shell frames, over the StatusBar placeholders; a sheet x of 224 would fix it.
  - 02 / 05: W-27's reply reads "Not sent. order entry is paused." on the board and in its annotation: the {reason} slot is filled lower case after the sentence's full stop.
  - 03: the polite share-wait lane draws a twelfth wait block after composite 12, though the table's 'next after' for 12 is 'flush (stream over)'.
  - 04: the cyan drop marker at 1.000 s on the polite lane crosses the 'T-30 T-31 · 2.734 s' bar label (between 'T' and '31'). It is the sheet's marker at the event's time; there is no free space on that lane at that x, so it was left.
  - 05: in 'focus∕reject-kept · dark' the tag 'focus stays in Price; the value "6400" and the caret unchanged (R-7)' (x 804-1171, y 318-334 in the frame) covers the order ticket card's bottom 6 px (the card ends at y 324). It covers no glyph of the card; moving it 8 px down would clear it.
  - 05: the dialog measures 173 px high against the kit's 172 estimate, so it cannot sit exactly centred (313.5 px); it sits 0.5 px high.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | PNG                                                   | Size     | Bytes  | Gate                                                                |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | ----------------------------------------------------- | -------- | ------ | ------------------------------------------------------------------- |
| 01  | 338d0e73-2a2c-805f-8008-e363078b841c | 181   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-01-taxonomy-map.png       | 1920x998 | 348301 | PASS E47-D07-01-taxonomy-map.png theme=dark own=3038 other=15       |
| 02  | 338d0e73-2a2c-805f-8008-e36417e46384 | 154   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-02-shell-pair-writers.png | 3280x998 | 293614 | PASS E47-D07-02-shell-pair-writers.png theme=dark own=3198 other=66 |
| 03  | 338d0e73-2a2c-805f-8008-e364f8d933a5 | 299   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-03-polite-timeline.png    | 1920x998 | 238533 | PASS E47-D07-03-polite-timeline.png theme=dark own=1955 other=36    |
| 04  | 338d0e73-2a2c-805f-8008-e36679bd4ef3 | 111   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-04-incident-timeline.png  | 1920x998 | 218103 | PASS E47-D07-04-incident-timeline.png theme=dark own=1974 other=23  |
| 05  | 338d0e73-2a2c-805f-8008-e36780fb6822 | 149   | 0 / 0 / 0 / 3 / 0                                          | docs/design/E47/img/E47-D07-05-focus-kept.png         | 3280x998 | 189966 | PASS E47-D07-05-focus-kept.png theme=dark own=1336 other=25         |
| 06  | 0645ce7f-800d-802f-8008-e369d436e37b | 731   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-06-scr117-panel.png       | 3280x998 | 363854 | PASS E47-D07-06-scr117-panel.png theme=dark own=3018 other=246      |
| 07  | 0645ce7f-800d-802f-8008-e36c612c1ea1 | 329   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-07-scr117-panel-light.png | 1920x998 | 207574 | PASS E47-D07-07-scr117-panel-light.png theme=light own=3111 other=3 |
| 08  | 0645ce7f-800d-802f-8008-e36ddfa1448c | 140   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-08-verbosity-matrix.png   | 1920x998 | 168572 | PASS E47-D07-08-verbosity-matrix.png theme=dark own=1664 other=31   |
| 09  | 0645ce7f-800d-802f-8008-e36f09ade01e | 281   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-09-transcript-preview.png | 4640x998 | 280492 | PASS E47-D07-09-transcript-preview.png theme=dark own=1908 other=89 |
| 10  | 0645ce7f-800d-802f-8008-e3702133639f | 209   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D07-10-copy-anatomy.png       | 1920x998 | 228168 | PASS E47-D07-10-copy-anatomy.png theme=dark own=2088 other=4        |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E47-D07 01 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 01 ten card 'content' stacks grown 1-2 px to their texts' measured end plus their bottom padding (57 -> 59 four times, 53 -> 54, 40 -> 41 four times, 83 -> 85): the 13 px x 1.4 lines measure 19 px live against the kit's 18, so the last line sat in the bottom padding (no text was cut: lc3.cutN 0 before and after)
SHEET-FIX E47-D07 02 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 02 five 'content' stacks grown 1 px to their texts' measured end plus their bottom padding (53 -> 54, 40 -> 41 four times), as on 01
SHEET-FIX E47-D07 03 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 04 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 04 three 'content' stacks grown 1 px to their texts' measured end plus their bottom padding (66 -> 67 twice, 53 -> 54), as on 01
SHEET-FIX E47-D07 05 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 05 'CMP-044 alertdialog · auto-flatten' re-centred in its overlay per the md's live check: it measures 440 x 173 (estimated 172), so the sheet's y 314 left it 0.5 px low; y 314 -> 313 (x 420 kept centred)
SHEET-FIX E47-D07 05 in both frames 'tag · synthetic data' moved from x 16 to x 224 at the same y (760), because it covered the StatusBar placeholders (x 16-136 and 152-208)
SHEET-FIX E47-D07 06 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 06 in both frames 'tag · synthetic data' moved from x 16 to x 224 at the same y (760), because it covered the StatusBar placeholders, as on 05
SHEET-FIX E47-D07 06 frame 'SCR-117∕announcements-default · dark' texts re-set to their own characters (geometry and token binds unchanged), because the selected nav item 'Accessibility' did not paint in the first export (the first board after a tab reload)
SHEET-FIX E47-D07 07 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 07 'tag · synthetic data' moved from x 16 to x 224 at the same y (760), because it covered the StatusBar placeholders, as on 05
SHEET-FIX E47-D07 08 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 09 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 09 in all three frames 'tag · synthetic data' moved from x 16 to x 224 at the same y (760), because it covered the StatusBar placeholders, as on 05
SHEET-FIX E47-D07 10 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D07 10 25 chip 'content' stacks grown 1-2 px to their texts' measured end plus their bottom padding (43 -> 45 thirteen times, 26 -> 27 twelve times), as on 01
