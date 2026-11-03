# E47-D08 (#1307): render return

- File: `E47-D08 boards` (file id withheld)
- Page: `{"name": "E47-D08 — Motion", "id": "0645ce7f-800d-802f-8008-e37351f8d750"}`
- Drawn on the kit at transport `73c6a3c37`, under the dark theme. Every board was exported under dark. Two boards also have a twin export:
  - 03 under light. Before it, 03's probe read `canvas.fill` #f6f7f9 (`palette.light.neutral.50`), and all 83 `color.text.primary` texts read #14171a.
  - 09 under high contrast. The hc set has no canvas override (the probe still reads #11151a), so hc was confirmed on the text instead: all 100 `color.text.primary` texts read #f6f8fa (`palette.neutral.1000`).
  - The theme was then set back to dark. The probe on 05 read `canvas.fill` #11151a, and 03's primary texts read #e8eaed.
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - `lc3.cutN` 0, and `lc.clippedN` 0;
  - every frame at its md size (1280 x 800) and position, `clip` true, `spill` 0;
  - `lc.h` = `lc.want`. The kit's root heights (1000) were estimates; each root was set to the checked `want` (footer end 918 + 80 = 998). See the SHEET-FIX lines.
- Each md's Live checks hold:
  - On 01 the tallest map column ends at 747 of 800 px in 'inventory/full · dark'. No cell had to move.
  - Every annotation column ends inside its root.
  - The 03 and 09 twins were exported as their md asks.
- Remaining lint findings, each checked live and kept:
  - `overlap` 36 on 02, by design: the timeline lanes ('lane n · requests / starts / helds / admitteds / refuseds') span the full axis over the 'windows' shading and their lane labels' boxes, and the sum lane stacks its three source rows. No glyph is covered.
  - `overlap` 2 on 03: marker 'stop 1' sits on the top-right corner of the 'I-24 liquidation mark'. It covers the mark's border, not its words.
  - `overlap` 1 on 07, by design: the 'replay frame · 4 px' outline over the replay chart panel.
- Link underlines: no board on this page draws a link (`lk` found none).
- Reloads: the tab was reloaded four times:
  - before 04 (about 1 600 shapes drawn since the file opened);
  - before 06 (about 985 since then, as the brief asks for the big board);
  - before 07 (06 alone is 1 852 nodes);
  - once during the light twin, when the tab stayed suspended.
- Fonts after a reload: in the first preview of 06 and of 07 (each the first board after a reload), the top price-axis label of the first frame painted in a fallback serif. Those frames' texts were re-set to their own characters before the final export (SHEET-FIX). Every PNG was looked at in full at 1x, and zoomed where needed. No other blank, fallback-serif or wrongly sized text was found.
- Board 06 (1 852 nodes) was drawn in steps:
  - its root and section 0 through `render_exec.py`;
  - sections 1-139 one call each, with the selection cleared after each section;
  - touch and relayout one top-level child per call (8 children; the longest took 1.5 s);
  - then `render_exec.py --from report`.
- Light twin (03): the first light export failed the gate (`own=574 other=5902`). The tab had been suspended through the 90 s wait. The texts' fills read the light value, but the export still painted them in the dark text colour. None of these changed the export (same crc each time): a reload, re-setting the texts, or zooming the board into view. Switching dark -> light again, with the window held in front for the whole 90 s wait, did: PASS `own=4058 other=76`. The hc switch was done the same way and passed first time.
- Kept as drawn, for the kit owner:
  - Kit-wide: the 13 px x 1.4 lines measure 19 px live against the kit's 18. On 01, 93 of the 123 map cells had their last line in the bottom padding; their columns and maps had to grow too (SHEET-FIX). Kit-wide, too, the watchlist grid (03, 04) is 100 px for 105 px of content (header row 24 + gap 4 + rule 1 + gap 4 + three 24 px rows), so row 3 was cut.
  - 03: the FR-2 region outline is placed at its sheet geometry:
    - its top edge runs through watchlist row 1 ('64,999.95', '▼ −0.01');
    - its left edge runs through 'Bid size' and 'DOM · BTCUSDT';
    - its tag 'FR-2 region · 341 × 256 px' covers the ladder prices 64,999.94 and 64,999.93.

    There is no free space for the tag at that y (NavRail gap 96 px, ladder-chart gap 41 px, candles in the chart), so it was left.

  - 05: in 'liquidation/reduce · dark' the mark '⚠ 7.36 BTC ×10' (no overlay under reduce) sits over the green candle bodies at its sheet position, and '×10' crosses one body. It is legible but low in contrast there.
  - 07: in 'pause/tape · dark' the Pause button's 'CMP-039 ring · normal' (74 x 36 at y −4) sits inside the tape panel's 28 px 'tools' and 'header' boards, which clip it. Only the ring's two sides show; its top and bottom 4 px are cut. A taller header, or the ring placed outside the clipping header, would show it whole.
  - 09: the hc twin differs from the dark frame only in the primary text colour (#f6f8fa against #e8eaed): `semantic-hc` overrides 15 tokens, none of them a surface.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | PNG                                                            | Size     | Bytes  | Gate                                                                      |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | -------------------------------------------------------------- | -------- | ------ | ------------------------------------------------------------------------- |
| 01  | 0645ce7f-800d-802f-8008-e3735201a92c | 427   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-01-inventory-map.png               | 4640x998 | 888741 | PASS E47-D08-01-inventory-map.png theme=dark own=2667 other=199           |
| 02  | 0645ce7f-800d-802f-8008-e374a40a9229 | 516   | 0 / 0 / 0 / 36 / 0                                         | docs/design/E47/img/E47-D08-02-budget-timeline.png             | 3280x998 | 235800 | PASS E47-D08-02-budget-timeline.png theme=dark own=3530 other=17          |
| 03  | 0645ce7f-800d-802f-8008-e375d69d6fc3 | 653   | 0 / 0 / 0 / 2 / 0                                          | docs/design/E47/img/E47-D08-03-region-arbiter.png              | 3280x998 | 243846 | PASS E47-D08-03-region-arbiter.png theme=dark own=2974 other=25           |
| 03  | 0645ce7f-800d-802f-8008-e375d69d6fc3 | 653   | 0 / 0 / 0 / 2 / 0                                          | docs/design/E47/img/E47-D08-03-region-arbiter-light.png        | 3280x998 | 242937 | PASS E47-D08-03-region-arbiter-light.png theme=light own=4058 other=76    |
| 04  | f16f8c84-73d9-80f0-8008-e379da1c4250 | 479   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-04-price-cell-modes.png            | 4640x998 | 289028 | PASS E47-D08-04-price-cell-modes.png theme=dark own=4356 other=51         |
| 05  | f16f8c84-73d9-80f0-8008-e37b1ac82989 | 506   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-05-liquidation.png                 | 3280x998 | 202643 | PASS E47-D08-05-liquidation.png theme=dark own=2642 other=57              |
| 06  | 1448e46e-576f-807b-8008-e37cfb9e815e | 1852  | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-06-heatmap-tiers.png               | 4640x998 | 211387 | PASS E47-D08-06-heatmap-tiers.png theme=dark own=3701 other=38            |
| 07  | f69b3c53-e81f-80e4-8008-e382a1b3c3aa | 615   | 0 / 0 / 0 / 1 / 0                                          | docs/design/E47/img/E47-D08-07-pause-controls.png              | 4640x998 | 309457 | PASS E47-D08-07-pause-controls.png theme=dark own=2568 other=26           |
| 08  | f69b3c53-e81f-80e4-8008-e38758b566cc | 92    | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-08-override-vs-os.png              | 1920x998 | 164596 | PASS E47-D08-08-override-vs-os.png theme=dark own=1993 other=17           |
| 09  | f69b3c53-e81f-80e4-8008-e387ee63a6e1 | 576   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-09-safety-static.png               | 3280x998 | 252493 | PASS E47-D08-09-safety-static.png theme=dark own=4313 other=19            |
| 09  | f69b3c53-e81f-80e4-8008-e387ee63a6e1 | 576   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-09-safety-static-high-contrast.png | 3280x998 | 249035 | PASS E47-D08-09-safety-static-high-contrast.png theme=hc own=4313 other=0 |
| 10  | f69b3c53-e81f-80e4-8008-e389f0e04697 | 141   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D08-10-forced-reduce.png               | 1920x998 | 167121 | PASS E47-D08-10-forced-reduce.png theme=dark own=1401 other=21            |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E47-D08 01 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 01 93 map 'cell · I-n' boards grown 1 px to their texts' measured end plus their bottom padding (35 -> 36, 48 -> 49, 61 -> 62, 74 -> 75): the 13 px x 1.4 lines measure 19 px live against the kit's 18, so each cell's last line sat in its bottom padding
SHEET-FIX E47-D08 01 the twelve map 'column n' stacks grown 4-12 px and the three 'map' boards 4-9 px (672 -> 676, 490 -> 498, 555 -> 564) to the grown cells, so no column's last cell is clipped; the tallest column now ends at 747 of 800 px in 'inventory/full · dark' (live check: inside the frame, no cell moved)
SHEET-FIX E47-D08 02 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 03 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 03 in both frames 'CMP-049 grid · watchlist' grown 100 -> 105 and its 'CMP-080 panel · watchlist' 128 -> 133: the grid's header row, rule, two 4 px gaps and three 24 px rows need 105 px, so row 3 (SOLUSDT 181.92 ▼ −0.01) was cut 1-2.5 px by both clipping ancestors (lc3.cutN 8 -> 0); the panel now ends 3 px above the DOM ladder panel
SHEET-FIX E47-D08 03 during the light twin every text of the board was re-set twice (its characters plus a space, then its own characters; geometry, words and binds unchanged), trying to make the export repaint the text colour; the export only changed after the theme was switched again with the window in front (see the light-twin note)
SHEET-FIX E47-D08 04 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 04 in all three frames 'CMP-049 grid · watchlist' grown 100 -> 105 and its 'CMP-080 panel · watchlist' 128 -> 133, as on 03 (lc3.cutN 12 -> 0); the workspace column moves the content below it down 5 px
SHEET-FIX E47-D08 05 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 06 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 06 frame 'heatmap/full · dark' texts re-set to their own characters (geometry and token binds unchanged), because its top price-axis label '65,000.07' painted in a fallback serif in the first preview export (the first board after a tab reload)
SHEET-FIX E47-D08 07 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 07 frame 'pause/replay · dark' texts re-set to their own characters (geometry and token binds unchanged), because its top price-axis label '65,000.22' painted in a fallback serif in the first preview export (the first board after a tab reload)
SHEET-FIX E47-D08 08 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 09 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D08 09 in both frames 'chart tools' grown 40 -> 42 and the 'plot' below it trimmed 164 -> 162 (its content ends at 135, so 'tools + plot' keeps 204): 'arm toggle + reason' measures 42 px (24 + 4 + 14) and sat at y -1 in the 40 px row, so the reason 'Your role can't place orders.' was cut 1 px (lc clippedN 2 -> 0)
SHEET-FIX E47-D08 10 root height 1000 -> 998 (checked want: footer end 918 + 80)
