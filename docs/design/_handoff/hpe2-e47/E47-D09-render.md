# E47-D09 (#1308): render return

- File: `E47-D09 boards` (file id withheld)
- Page: `{"name": "E47-D09", "id": "eb5b7915-c07e-8076-8008-e2fe03d7842f"}`
- Drawn under the dark theme. 02 and 06 were exported under light and 10 under high contrast; the rest under dark. The theme was set back to dark after the twins (probe on 05: `canvas.fill` #11151a).
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - every frame at its md size (1280 x 800) and position, `clip` true, `spill` 0;
  - `lc.h` = `lc.want`. Footers are named `footer · synthetic`, and `lc.want` (the fixed template, 6471b0ce8) read them.
- `lc3.cutN` is 0 on every board except 04 (see below).
- Root heights: the kit's estimates were replaced by the checked `want` (footer end + 80; on 03 the annotation column end + 80). See the SHEET-FIX lines.
- Remaining lint findings, each checked live and kept:
  - `overlap`, all by design:
    - the chart layer stack (grid, candles, trading layer, price axis), the focused panel's frame over its header and body, and the CMP-039 ring and the `pending` tag over their line (01, 02, 03);
    - the rule canvas stack (grid, edges, nodes, restore-point origin) on 04;
    - the modal `overlay` over TopBar, body and StatusBar (05, 06, 07, 10);
    - the polite-region outline around the CMP-020 toast (09).
  - `outside-root` on 07: in `cheatsheet / remapped`, `body · scrolls/columns` runs 567 px below the root. The sheet scrolls the shortcut list by 426 px inside the clipped 520 px body, so nothing outside the root is visible in the PNG. The Auth group's heading sits just above the visible top as a result; that is the sheet's own scroll offset.
  - `lc3.cutN` 5 on 04, kept, not fixed. These are node texts clipped by the rule canvas that the sheet scrolls:
    - `position_side == long` in `node / view-follows` ("view scrolled 5 cells right");
    - `modify_stop` (name and kind) at the 640 CSS px edge of both 200 % strips.
    - The clipping is the state the frame shows. Moving the nodes would change it, so it needs a kit decision if cutN must be 0.
- Live checks "modal: re-centre", not applied vertically:
  - On 05, 06 and 10 the sheet places every CMP-059 palette at (320, 64): top-anchored and horizontally centred, which reads back as dx 0.
  - On 07 the sheet places every CMP-094 overlay at (48, 56). The md reading says it is "drawn 880 px wide at the frame's left", and centring it would push it under the callout column at x 1046.
  - Placement kept as drawn. CMP-044 on 01 and 02 was re-centred (SHEET-FIX).

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | PNG                                                 | Size      | Bytes  | Gate                                                                 |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | --------------------------------------------------- | --------- | ------ | -------------------------------------------------------------------- |
| 01  | eb5b7915-c07e-8076-8008-e2fe03e016f9 | 1891  | 0 / 0 / 0 / 52 / 0                                         | docs/design/E47/img/E47-D09-01-order-line.png       | 4640x1878 | 570656 | PASS E47-D09-01-order-line.png theme=dark own=5485 other=75          |
| 02  | 5603c55a-77d8-80eb-8008-e301ad379aed | 1891  | 0 / 0 / 0 / 52 / 0                                         | docs/design/E47/img/E47-D09-02-order-line-light.png | 4640x1878 | 563641 | PASS E47-D09-02-order-line-light.png theme=light own=13353 other=209 |
| 03  | ad3670ef-c3af-8008-8008-e304bfc26f74 | 1072  | 0 / 0 / 0 / 33 / 0                                         | docs/design/E47/img/E47-D09-03-anchors.png          | 4640x1008 | 328038 | PASS E47-D09-03-anchors.png theme=dark own=3996 other=20             |
| 04  | ad3670ef-c3af-8008-8008-e306aaca60c7 | 1189  | 0 / 0 / 0 / 21 / 0                                         | docs/design/E47/img/E47-D09-04-node-move.png        | 4640x1878 | 493858 | PASS E47-D09-04-node-move.png theme=dark own=8532 other=55           |
| 05  | a2bdcdba-deb8-8087-8008-e3096bffd9c4 | 707   | 0 / 0 / 0 / 12 / 0                                         | docs/design/E47/img/E47-D09-05-palette.png          | 3280x1878 | 497803 | PASS E47-D09-05-palette.png theme=dark own=2369 other=96             |
| 06  | a2bdcdba-deb8-8087-8008-e30b20876007 | 707   | 0 / 0 / 0 / 12 / 0                                         | docs/design/E47/img/E47-D09-06-palette-light.png    | 3280x1878 | 494070 | PASS E47-D09-06-palette-light.png theme=light own=3196 other=12      |
| 07  | 6ad595be-ac9f-809e-8008-e30cb4a88bb1 | 1203  | 0 / 1 / 0 / 12 / 0                                         | docs/design/E47/img/E47-D09-07-cheatsheet.png       | 3280x1878 | 492504 | PASS E47-D09-07-cheatsheet.png theme=dark own=4331 other=86          |
| 08  | 58de1ceb-1860-803f-8008-e30fa9ec357f | 1278  | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D09-08-hotkey-editor.png    | 4640x1878 | 652816 | PASS E47-D09-08-hotkey-editor.png theme=dark own=8548 other=81       |
| 09  | 58de1ceb-1860-803f-8008-e31306d8cbac | 262   | 0 / 0 / 0 / 1 / 0                                          | docs/design/E47/img/E47-D09-09-inert.png            | 3280x998  | 240905 | PASS E47-D09-09-inert.png theme=dark own=3401 other=28               |
| 10  | 516c334d-ac02-80a1-8008-e3146290e5eb | 707   | 0 / 0 / 0 / 12 / 0                                         | docs/design/E47/img/E47-D09-10-palette-hc.png       | 3280x1878 | 493738 | PASS E47-D09-10-palette-hc.png theme=hc own=2378 other=0             |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E47-D09 01 root height 1880 -> 1878 (checked want: footer end 1798 + 80; the 1880 was the kit's estimate)
SHEET-FIX E47-D09 01 bottom price-axis label 'axis 67,415.00' clamped inside its 412 px 'price axis' board in all five frames (y 405 -> 400): it ran 5 px past the axis and was cut by it (lint text-overflow 5 -> 0, lc3.cutN 5 -> 0), as an engine clamps an edge label
SHEET-FIX E47-D09 01 'CMP-044 confirm · amend' re-centred in its overlay after relayout (measured 480 x 183; y 310 -> 309), per the md live check
SHEET-FIX E47-D09 01 frame 'order-line∕selected · dark': its texts re-set to their own characters (geometry and token binds unchanged), because the axis texts read 17 px tall against 12 px in the other frames (the first board after a tab reload: the font had not loaded)
SHEET-FIX E47-D09 02 root height 1880 -> 1878, axis label 'axis 67,415.00' clamped (y 405 -> 400) in all five frames and 'CMP-044 confirm · amend' re-centred (y 310 -> 309), as on 01; frame 'order-line∕selected · light' texts re-set to their own characters (first board after a reload)
SHEET-FIX E47-D09 03 root height 1048 -> 1008 (checked want: annotation column end 928 + 80); axis label 'axis 67,415.00' clamped (y 405 -> 400) in all three frames, as on 01; frame 'drawing∕anchor-nudge · dark' texts re-set to their own characters (first board after a reload)
SHEET-FIX E47-D09 04 root height 1880 -> 1878 (checked want)
SHEET-FIX E47-D09 04 'tag · fold' in 'node∕move-mode-200 · dark' moved from x 16 to x 440 (y kept), because the tag covered the 'position_side == long' node text in strip 1
SHEET-FIX E47-D09 05 root height 1880 -> 1878 (checked want); frame 'palette∕unbound · dark' texts re-set to their own characters (first board after a reload)
SHEET-FIX E47-D09 05 'tag · the session' in 'palette∕t2 · dark' moved from x 980 to x 620 (y kept), into the empty TopBar gap, because it covered the FLATTEN ALL and FREEZE buttons
SHEET-FIX E47-D09 06 root height 1880 -> 1878 (checked want); 'tag · the session' in 'palette∕t2 · light' moved x 980 -> 620, as on 05
SHEET-FIX E47-D09 07 root height 1880 -> 1878 (checked want); frame 'cheatsheet∕search-name · dark' texts re-set to their own characters (first board after a reload)
SHEET-FIX E47-D09 08 root height 1880 -> 1878 (checked want); frame 'hotkeys∕conflict-at-capture · dark' texts re-set to their own characters (first board after a reload)
SHEET-FIX E47-D09 09 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D09 09 strip-1 tag 'toast 88 px: text on 2 lines' -> 'toast 71 px: text on 1 line', and the annotation 'W-6 on 2 lines … the toast 12 px taller' -> 'W-6 on 1 line … the toast 29 px taller': the measured toasts are 71 px (1 line, 13 px text) at text 100 % and 100 px (2 lines) at 150 %
SHEET-FIX E47-D09 10 root height 1880 -> 1878 (checked want); 'tag · the session' in 'palette∕t2 · hc' moved x 980 -> 620, as on 05; frame 'palette∕unbound · hc' texts re-set to their own characters (first board after a reload)
