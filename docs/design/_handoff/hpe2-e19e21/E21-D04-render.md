# E21-D04 (#504): render return

- File: `E21-D04 boards` (file id withheld)
- Page: `{"name": "E21-D04", "id": "2373897a-cf76-8072-8008-e3bcb65546a3"}`
- Drawn on the kit at transport `af6900a9f`, under the dark theme, one board at a time with `render_exec.py --page "E21-D04"`,
  then `common/board.sh` (post-step with hatch and dash on, `lc`, `lc3`, `lintd`). Every board was exported 1:1 under dark
  except 09, which was exported once, under high contrast only. Three boards also have a light twin:
  - 01, 04 and 06 under light. Before the export the probe read `canvas.fill` #f6f7f9 (`palette.light.neutral.50`) on all
    three; the `color.surface.raised` fills read #edeff2 (9, 10 and 12 shapes) and every `color.text.primary` text read
    #14171a (124, 90 and 115 texts).
  - 09 under high contrast. The hc set has no canvas override (the probe still reads #11151a), so hc was confirmed on the
    text instead: all 152 `color.text.primary` texts read #f6f8fa.
  - The theme was then set back to dark. The probe on 05 read `canvas.fill` #11151a, and 01's primary texts read #e8eaed.
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - `lc3.cutN` 0, and `lc.clippedN` 0;
  - every frame at its md size and position, `clip` true, `spill` 0 (51 frames in all);
  - `lc.h` = `lc.want`. Every kit root height was an estimate; each root was set to the checked `want` (see the SHEET-FIX
    lines).
- Each md's Live checks hold: the root names read back exactly; every annotation column ends inside its root; the twins
  were exported as their md asks. Board 10's md lists its 'Token map' frame in double quotes (its name has an
  apostrophe); it reads back 880 x 384 at (80, 80), as asked.
- Remaining lint findings, each checked live and kept:
  - `overlap` 1 on 02, by design: the open row menu (CMP-041) is drawn over the rows below it, as the md's reading says.
  - `overlap` 1 on 03 and 1 on 07, by design: the pulled mark's outline sits around its own hatch.
- Link underlines: no board on this page draws a link (`lk` found none).
- Backticks in drawn text: 02 had 1 string and 10 had 3, as the kit check said. The backticks were removed live (the words
  kept); the other cite with backticks in 02's sheet is not a drawn text.
- Reloads: the tab was reloaded three times, each before a board, never mid-board: before 03 (about 965 shapes since the
  file opened), before 04 (03 alone is 1 300 nodes) and before 08 (about 1 540 since the last reload). The fonts were
  warmed after each reload. Every PNG was looked at in full and zoomed in; no blank, fallback-serif or wrongly sized text
  was found.
- Board 08: during its draw the tab was briefly suspended, and its first report read one unmeasured caption and an
  annotation column ending at 740. Re-run in front (`render_exec.py --from touch`), the caption measured and the
  annotation column ends at 950, so the root is 1 030 (not the 820 the first pass gave). Nothing else on 08 changed.
- Board 09: its first render attempt failed at the root step (the tab was suspended for about two minutes; no shape was
  made, the page held no 09 root). It was drawn again from the start once the window was back in front.
- Each PNG sits at the export path line 3 of its sidecar names; board 03's file is the `E21-D04-03-cmp-111-*.png` one.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | cutN | PNG                                                         | Size      | Bytes  | Gate                                                                    |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | ---- | ----------------------------------------------------------- | --------- | ------ | ----------------------------------------------------------------------- |
| 01  | 2373897a-cf76-8072-8008-e3bcb65d8351 | 590   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-01-cmp-108-variants.png         | 3416x1512 | 428797 | PASS E21-D04-01-cmp-108-variants.png theme=dark own=2260 other=206      |
| 01  | 2373897a-cf76-8072-8008-e3bcb65d8351 | 590   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-01-cmp-108-variants-light.png   | 3416x1512 | 429484 | PASS E21-D04-01-cmp-108-variants-light.png theme=light own=4999 other=0 |
| 02  | 2373897a-cf76-8072-8008-e3be2ea5fb23 | 375   | 0 / 0 / 0 / 1 / 0                                          | 0    | docs/design/E21/img/E21-D04-02-cmp-108-density-focus.png    | 3424x999  | 281192 | PASS E21-D04-02-cmp-108-density-focus.png theme=dark own=1360 other=54  |
| 03  | 2eaa4086-603d-80c6-8008-e3bf51a58fc5 | 1300  | 0 / 0 / 0 / 1 / 0                                          | 0    | docs/design/E21/img/E21-D04-03-cmp-111-\*.png               | 4040x1670 | 350939 | PASS (board 03 PNG) theme=dark own=6005 other=80                        |
| 04  | 92503d2a-f1de-8053-8008-e3c1c688ec04 | 335   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-04-cmp-113-sets-scale.png       | 3872x1400 | 411236 | PASS E21-D04-04-cmp-113-sets-scale.png theme=dark own=1258 other=242    |
| 04  | 92503d2a-f1de-8053-8008-e3c1c688ec04 | 335   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-04-cmp-113-sets-scale-light.png | 3872x1400 | 414061 | PASS E21-D04-04-cmp-113-sets-scale-light.png theme=light own=3319 other=402 |
| 05  | 92503d2a-f1de-8053-8008-e3c2c0f355b7 | 440   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-05-ramps-cvd.png                | 2304x958  | 241296 | PASS E21-D04-05-ramps-cvd.png theme=dark own=1236 other=47              |
| 06  | 92503d2a-f1de-8053-8008-e3c3d6d090fe | 546   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-06-cmp-230-states.png           | 3424x1195 | 396613 | PASS E21-D04-06-cmp-230-states.png theme=dark own=2045 other=273        |
| 06  | 92503d2a-f1de-8053-8008-e3c3d6d090fe | 546   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-06-cmp-230-states-light.png     | 3424x1195 | 397956 | PASS E21-D04-06-cmp-230-states-light.png theme=light own=4277 other=19  |
| 07  | 92503d2a-f1de-8053-8008-e3c525740394 | 220   | 0 / 0 / 0 / 1 / 0                                          | 0    | docs/design/E21/img/E21-D04-07-cmp-227-cmp-229-usage.png    | 2956x789  | 191809 | PASS E21-D04-07-cmp-227-cmp-229-usage.png theme=dark own=873 other=65   |
| 08  | 66e25a87-5f14-8014-8008-e3c611738ca5 | 469   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-08-cmp-228-heatmap-kind.png     | 2920x1030 | 217327 | PASS E21-D04-08-cmp-228-heatmap-kind.png theme=dark own=927 other=95    |
| 09  | 66e25a87-5f14-8014-8008-e3cad03bb620 | 615   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-09-high-contrast-forced.png     | 3584x1033 | 359996 | PASS E21-D04-09-high-contrast-forced.png theme=hc own=4256 other=0      |
| 10  | 66e25a87-5f14-8014-8008-e3c8b4d13231 | 160   | 0 / 0 / 0 / 0 / 0                                          | 0    | docs/design/E21/img/E21-D04-10-token-map-redlines.png       | 2480x597  | 200197 | PASS E21-D04-10-token-map-redlines.png theme=dark own=762 other=47      |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E21-D04 01 root height 1552 -> 1512 (checked want: annotation end 1432 + 80)
SHEET-FIX E21-D04 02 root height 1072 -> 999 (checked want: annotation end 919 + 80)
SHEET-FIX E21-D04 02 backticks removed from the drawn text 'value-2' in the Focus frame ("(`15`:454)" -> "(15:454)"), words kept
SHEET-FIX E21-D04 03 root height 1672 -> 1670 (checked want: footer end 1590 + 80)
SHEET-FIX E21-D04 04 root height 1440 -> 1400 (checked want: annotation end 1320 + 80)
SHEET-FIX E21-D04 05 root height 976 -> 958 (checked want: footer end 878 + 80)
SHEET-FIX E21-D04 06 root height 1312 -> 1195 (checked want: annotation end 1115 + 80)
SHEET-FIX E21-D04 07 root height 872 -> 789 (checked want: annotation end 709 + 80)
SHEET-FIX E21-D04 08 root height 1152 -> 1030 (checked want: annotation end 950 + 80, after the re-run in front)
SHEET-FIX E21-D04 09 root height 1176 -> 1033 (checked want: annotation end 953 + 80)
SHEET-FIX E21-D04 10 root height 656 -> 597 (checked want: annotation end 517 + 80)
SHEET-FIX E21-D04 10 backticks removed from three drawn texts, words kept: the Token map 'caption' ("`font.mono` and `color.surface.ownorder`"), the Redlines badge-gap 'words' ("(`15`:2939)") and the annotation 'value-2' ("(`26`:393)")

## For the kit owner

- Kit-wide: every root came out shorter than its kit estimate (by 2 to 143 px); the annotation columns and footers measure
  shorter live.
- 05: its annotation names three CVD exports of board 04 (`E21-D04-04-cmp-113-sets-scale-greyscale.png`,
  `-deuteranopia.png`, `-protanopia.png`). RENDER.md does not list them, so this return does not carry them; they are
  `cvd_sim.py` renders of the dark 04 PNG above, for whoever owns that step.
- 09: in the two 'Forced colours' frames the stand-in tokens keep the blue focus ring, and the CMP-113 legend keeps its
  coloured stops; only the bars are hidden. The annotation says the ring is Highlight; drawn as bound, as RENDER.md asks.
