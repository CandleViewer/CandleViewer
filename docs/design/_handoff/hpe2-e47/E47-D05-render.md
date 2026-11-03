# E47-D05 (#1304): render return

- File: `E47-D05 boards` (file id withheld)
- Page: `{"name": "E47-D05 SCR-117", "id": "b96edf38-8e58-8006-8008-e2ec6704db96"}`
- Drawn under the dark theme; 02 exported under light, 03 under high contrast, the rest under dark (theme back to dark after the twins).
- Every board: `lc.count` = `lintd.shapes` + 1; `lc3.cutN` = 0; lint `unmeasured` 0 and `unbound` 0; every frame at its md size and position, `clip` true, `spill` 0.
- Remaining lint findings, each checked live and kept:
  - `overlap`: the CMP-039 focus ring drawn over the ladder row (bid, price, ask), by design. On board 09 there is also the modal scrim (`overlay`) over the frame.
  - `outside-root`:
    - board 03: the three 640 CSS px strips scroll the long page inside clipped strip boards;
    - board 06: the frames' scrolled page content, clipped by `body`.
    - Nothing outside the root is visible in the PNG.
- Root heights stay at the md sizes. In every root, the annotation column end + 80 and the footer (`footer · data`) end + 80 both fit.
  - `lc.want` reads the annotation end only: its footer lookup is `footer · data statement`, but the board's footer is named `footer · data`.
  - The footer end + 80 is 2 px under the md height on 01, 02, 03, 06, 07, 08 and 10 (a 14 px measured text against a 16 px estimate).

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | PNG                                                      | Size      | Bytes  | Gate                                                                    |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | -------------------------------------------------------- | --------- | ------ | ----------------------------------------------------------------------- |
| 01  | b96edf38-8e58-8006-8008-e2ec670b7796 | 299   | 0 / 0 / 0 / 3 / 0                                          | docs/design/E47/img/E47-D05-01-scr117-default.png        | 1920x1896 | 334997 | PASS E47-D05-01-scr117-default.png theme=dark own=3877 other=4          |
| 02  | b96edf38-8e58-8006-8008-e2ed93a03f85 | 300   | 0 / 0 / 0 / 3 / 0                                          | docs/design/E47/img/E47-D05-02-scr117-light.png          | 1920x1896 | 339374 | PASS E47-D05-02-scr117-light.png theme=light own=4991 other=30          |
| 03  | b96edf38-8e58-8006-8008-e2ee2a3aed74 | 730   | 0 / 3 / 0 / 9 / 0                                          | docs/design/E47/img/E47-D05-03-hc-zoom-200.png           | 2560x1000 | 313425 | PASS E47-D05-03-hc-zoom-200.png theme=hc own=3731 other=0               |
| 04  | d066085e-49b4-8070-8008-e2efc56320fa | 632   | 0 / 0 / 0 / 9 / 0                                          | docs/design/E47/img/E47-D05-04-system-states.png         | 4640x1296 | 501126 | PASS E47-D05-04-system-states.png theme=dark own=5289 other=54          |
| 05  | d066085e-49b4-8070-8008-e2f0af5dc104 | 610   | 0 / 0 / 0 / 6 / 0                                          | docs/design/E47/img/E47-D05-05-motion-table-tiles.png    | 4640x1008 | 400725 | PASS E47-D05-05-motion-table-tiles.png theme=dark own=5250 other=36     |
| 06  | 208ce316-0bed-8055-8008-e2f1d4ae9003 | 581   | 0 / 3 / 0 / 9 / 0                                          | docs/design/E47/img/E47-D05-06-focus-tile.png            | 4640x1000 | 321289 | PASS E47-D05-06-focus-tile.png theme=dark own=5407 other=49             |
| 07  | 208ce316-0bed-8055-8008-e2f30f911c1f | 567   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D05-07-announcement-tile.png     | 3280x1880 | 510001 | PASS E47-D05-07-announcement-tile.png theme=dark own=6044 other=60      |
| 08  | 208ce316-0bed-8055-8008-e2f443d60c64 | 308   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D05-08-keyboard-only-reveal.png  | 4640x1000 | 201317 | PASS E47-D05-08-keyboard-only-reveal.png theme=dark own=1246 other=33   |
| 09  | 69be570b-37e6-80e2-8008-e2f57eb0ff5c | 653   | 0 / 0 / 0 / 12 / 0                                         | docs/design/E47/img/E47-D05-09-modified-reset-search.png | 4640x1032 | 463067 | PASS E47-D05-09-modified-reset-search.png theme=dark own=3891 other=103 |
| 10  | 69be570b-37e6-80e2-8008-e2f6df8706b6 | 350   | 0 / 0 / 0 / 3 / 0                                          | docs/design/E47/img/E47-D05-10-keyboard-order-150.png    | 1920x2864 | 500702 | PASS E47-D05-10-keyboard-order-150.png theme=dark own=24618 other=19    |

Nodes = `lc.count`; lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E47-D05 01 link underlines 'Read the accessibility statement' / 'Change shortcuts' set to the words' measured widths (233 -> 199, 116 -> 110), per the md live check
SHEET-FIX E47-D05 01 'fold · 800 px viewport' was a 2 px filled rect (name not 'dashed · …', so the post-step skipped it): fill removed, 1 px inner dashed stroke bound to color.status.info.default, so it reads as an annotation
SHEET-FIX E47-D05 02 link underlines set to the words' measured widths (199, 110) and 'fold · 800 px viewport' made a dashed color.status.info.default stroke, as on 01
SHEET-FIX E47-D05 03 link underlines in the three strips set to the words' measured widths (199, 110)
SHEET-FIX E47-D05 04 frame 'SCR-117/following-system · dark': its texts re-set to their own characters (geometry and token binds unchanged), because the first export lacked h1 'Accessibility' (the first board after a tab reload: texts drawn before the font loaded did not paint); re-exported
SHEET-FIX E47-D05 06 frame 'tile/focus-normal · dark': texts re-set to their own characters (geometry and token binds unchanged), because the nav label 'Accessibility' and h2 'Contrast and focus' did not paint (first board after a reload); re-exported
SHEET-FIX E47-D05 08 order-line 'handle' (drag handle + W-20 hint) moved from y 404 to 420 in 'chart canvas (synthetic)', so the stop line no longer strikes through the hint text
SHEET-FIX E47-D05 08 rule-edge 'handle' moved from y 244 to 260 in 'rule graph (synthetic)', so the W-20 hint no longer overlaps Node 2's box (lint overlap 1 -> 0)
SHEET-FIX E47-D05 09 'CMP-043 Dialog' re-centred in its overlay after relayout (measured 440 x 178; y 312 -> 311), per the md live check
SHEET-FIX E47-D05 09 frame 'SCR-117/modified · dark': texts re-set to their own characters (geometry and token binds unchanged), because the nav label and h1 'Accessibility' did not paint (first board after a reload); re-exported
SHEET-FIX E47-D05 10 'text' columns of option rows keyboard_only and larger_hit_targets (and their label and description) narrowed 882 -> 874, because the two-digit 'stop 13/14 + switch' badges are 74 px wide and the texts were cut 8 px by the 960 px row (lc3.cutN 4 -> 0; descriptions still 2 lines)
SHEET-FIX E47-D05 10 link underlines set to the words' measured widths (314, 173) and 'fold · 800 px viewport' made a dashed color.status.info.default stroke, as on 01
