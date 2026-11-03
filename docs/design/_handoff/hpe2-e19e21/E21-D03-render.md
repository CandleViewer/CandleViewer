# E21-D03 (#503): render return

- File: `E21-D03 boards` (file id withheld)
- Page: `{"name": "E21-D03", "id": "66e25a87-5f14-8014-8008-e3d2c7bd71e1"}`
- Drawn on the kit at transport `af6900a9f`, under the dark theme, one board at a time with `render_exec.py --page "E21-D03"`,
  then `common/board.sh` (post-step with hatch and dash on, `lc`, `lc3`, `lintd`). Every board was exported 1:1 under dark.
  Three boards also have a light twin, exported a second time from the same board:
  - 01, 05 and 09 under light. Before the export the probe read `canvas.fill` #f6f7f9 (`palette.light.neutral.50`) on all
    three. 09 was exported again under both themes after its last live fix (below); the probe read the same value.
  - The theme was then set back to dark. The probe on 05 and on 09 read `canvas.fill` #11151a.
- Seed: the four token sets, their sync scripts and the themes, then the repo's local icons and
  `common/local-icons-e19e21.js`. Penpot refused four `motion.duration.*` primitives ("type is invalid: Empty field");
  no sheet binds a motion token (the word appears only in two drawn sentences), so nothing on the boards depends on them.
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - `lc3.cutN` 0, and `lc.clippedN` 0;
  - every frame at its md size and position, `clip` true, `spill` 0 (23 frames in all). Penpot shows a frame named
    `SCR-051/default` as `SCR-051 / default` (its path separator); the names were compared with that spacing removed;
  - `lc.h` = `lc.want`. Every kit root height was an estimate; each root was set to the checked `want` (see the SHEET-FIX
    lines).
- Each md's Live checks hold: the root names read back exactly; every annotation column ends inside its root; the twins
  were exported as their md asks.
- Board 10's live check (each focus-order marker at its control's top-left): marker 03 sat 17 px right of the
  `CMP-006 option 200` corner and was moved 16 px left (four 4 px steps); it now sits 1 px off. Every other marker reads
  0 px off, except 08 (3 px from `CMP-009 Decay`, under one step), so it was left.
- Remaining lint findings, each checked live and kept:
  - `overlap`, on every board except 09: the CMP-043 dialog drawn over the SCR-050 panel behind it (its column headers
    and row blocks), as the sheets' fallback says (01: 9, 02: 36, 03: 27, 04: 9, 05: 27, 06: 9, 07: 18, 08: 18, 10: 9).
  - `overlap`, board markers over context: the `board marker · announcement` boxes sit 16 px over the dialog's lower edge
    (02: 3, 05: 1, 07: 2, 08: 1, 10: 2, one of them the W-37 box at 20 px); 03's `accessible name` markers over SCR-050
    row blocks (4); 09's announcement boxes over SCR-050 row blocks (4); 10's focus-order markers 01 and 02 over the edges
    of what they number (3). No text is hidden by any of them (checked in every PNG).
- Link underlines: no board on this page draws a link (`lk` found none).
- Backticks in drawn text: 02 had 3 strings, 03 had 1, 05 had 2, 07 had 3, 09 had 4 and 10 had 4, as the kit check said.
  The backticks were removed live (the words kept).
- Reloads: the tab was reloaded three times, each before a board, never mid-board: before 03 (about 1 450 shapes since the
  file opened), before 06 (about 1 750 since the last reload) and before 09 (about 1 360; 09 alone is about 700). The fonts
  were warmed after each reload. Every PNG was looked at in full at 1x, and dense regions zoomed in at 2x; no blank,
  fallback-serif or wrongly sized text was found.
- Board 05: its first report read four unmeasured texts. Re-run in front (`render_exec.py --from touch`), every text
  measured and the footer ends at 1 867, so the root is 1 947.
- Each PNG sits at the export path line 3 of its sidecar names.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | cutN | PNG                                                          | Size      | Bytes  | Gate                                                                         |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | ---- | ------------------------------------------------------------ | --------- | ------ | ---------------------------------------------------------------------------- |
| 01  | 66e25a87-5f14-8014-8008-e3d2c808d85a | 418   | 0 / 0 / 0 / 9 / 0                                          | 0    | docs/design/E21/img/E21-D03-01-anatomy-redlines.png          | 3280x1026 | 370879 | PASS E21-D03-01-anatomy-redlines.png theme=dark own=2789 other=25            |
| 01  | 66e25a87-5f14-8014-8008-e3d2c808d85a | 418   | 0 / 0 / 0 / 9 / 0                                          | 0    | docs/design/E21/img/E21-D03-01-anatomy-redlines-light.png    | 3280x1026 | 369030 | PASS E21-D03-01-anatomy-redlines-light.png theme=light own=4222 other=206    |
| 02  | 66e25a87-5f14-8014-8008-e3d45141b1fb | 1029  | 0 / 0 / 0 / 39 / 0                                         | 0    | docs/design/E21/img/E21-D03-02-tier-rebuild-500.png          | 3280x2322 | 635138 | PASS E21-D03-02-tier-rebuild-500.png theme=dark own=7138 other=65            |
| 03  | e61ff304-7846-809f-8008-e3d67b83c453 | 840   | 0 / 0 / 0 / 31 / 0                                         | 0    | docs/design/E21/img/E21-D03-03-colour-cvd-greyscale.png      | 3280x1934 | 425602 | PASS E21-D03-03-colour-cvd-greyscale.png theme=dark own=4776 other=12        |
| 04  | e61ff304-7846-809f-8008-e3d819787f73 | 254   | 0 / 0 / 0 / 9 / 0                                          | 0    | docs/design/E21/img/E21-D03-04-ladder-centring.png           | 1920x1039 | 170075 | PASS E21-D03-04-ladder-centring.png theme=dark own=1599 other=2              |
| 05  | e61ff304-7846-809f-8008-e3d8ca0ddd26 | 653   | 0 / 0 / 0 / 28 / 0                                         | 0    | docs/design/E21/img/E21-D03-05-trading-demo-live.png         | 3280x1947 | 344867 | PASS E21-D03-05-trading-demo-live.png theme=dark own=4484 other=38           |
| 05  | e61ff304-7846-809f-8008-e3d8ca0ddd26 | 653   | 0 / 0 / 0 / 28 / 0                                         | 0    | docs/design/E21/img/E21-D03-05-trading-demo-live-light.png   | 3280x1947 | 342125 | PASS E21-D03-05-trading-demo-live-light.png theme=light own=7799 other=1     |
| 06  | 763030f4-ce1e-8039-8008-e3dcaefdc7f5 | 235   | 0 / 0 / 0 / 9 / 0                                          | 0    | docs/design/E21/img/E21-D03-06-detectors.png                 | 1920x1039 | 138273 | PASS E21-D03-06-detectors.png theme=dark own=1554 other=6                    |
| 07  | 763030f4-ce1e-8039-8008-e3dd6e2f28e0 | 569   | 0 / 0 / 0 / 20 / 0                                         | 0    | docs/design/E21/img/E21-D03-07-validation-clamp.png          | 3280x1422 | 333428 | PASS E21-D03-07-validation-clamp.png theme=dark own=3590 other=43            |
| 08  | 763030f4-ce1e-8039-8008-e3def1098e66 | 560   | 0 / 0 / 0 / 19 / 0                                         | 0    | docs/design/E21/img/E21-D03-08-cost-save-t2.png              | 3280x1334 | 299808 | PASS E21-D03-08-cost-save-t2.png theme=dark own=3559 other=37                |
| 09  | 7aa87b08-b547-8059-8008-e3e06be7b826 | 699   | 0 / 0 / 0 / 4 / 0                                          | 0    | docs/design/E21/img/E21-D03-09-shed-row-restore.png          | 3280x1934 | 562230 | PASS E21-D03-09-shed-row-restore.png theme=dark own=8809 other=36            |
| 09  | 7aa87b08-b547-8059-8008-e3e06be7b826 | 699   | 0 / 0 / 0 / 4 / 0                                          | 0    | docs/design/E21/img/E21-D03-09-shed-row-restore-light.png    | 3280x1934 | 560819 | PASS E21-D03-09-shed-row-restore-light.png theme=light own=9874 other=13     |
| 10  | 7aa87b08-b547-8059-8008-e3e1c7c16c63 | 397   | 0 / 0 / 0 / 14 / 0                                         | 0    | docs/design/E21/img/E21-D03-10-keyboard-reflow.png           | 2640x1166 | 365832 | PASS E21-D03-10-keyboard-reflow.png theme=dark own=3076 other=23             |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E21-D03 01 root height 1040 -> 1026 (checked want: footer end 946 + 80)
SHEET-FIX E21-D03 02 root height 2336 -> 2322 (checked want: footer end 2242 + 80)
SHEET-FIX E21-D03 02 'group · Depth tier' raised 1 px to fit its W-4 text, which it cut by 1 px, in three frames (tier-change-pending 94 -> 95, saving 86 -> 87, rebuild-refused 86 -> 87)
SHEET-FIX E21-D03 02 'SCR-050 header' in the 'inset · D02 tier notice' frame narrowed 1280 -> 1232, the frame's width less its 24 px side padding (it ran 24 px past the frame's right edge)
SHEET-FIX E21-D03 02 backticks removed from three drawn texts, words kept: the annotation 'value-2' lines "(`23`:719)", "(`23`:731) ... (`23`:765)" and "(`24`:5615)"
SHEET-FIX E21-D03 03 root height 1952 -> 1934 (checked want: footer end 1854 + 80)
SHEET-FIX E21-D03 03 'row · scale and gamma' raised 46 -> 47 and its 'tabpanel · Colour' by 1 px (385 -> 386, 393 -> 394, 385 -> 386) in all three frames: the bottom-aligned 47 px 'group · Colour scale' put its label 1 px above the tabpanel's top edge
SHEET-FIX E21-D03 03 backticks removed from the drawn annotation 'value-2' ("(`15`:2949)"), words kept
SHEET-FIX E21-D03 04 root height 1056 -> 1039 (checked want: footer end 959 + 80)
SHEET-FIX E21-D03 05 root height 1952 -> 1947 (checked want: footer end 1867 + 80, after the re-run in front)
SHEET-FIX E21-D03 05 backticks removed from two drawn texts, words kept: the annotation 'value-4' ("(`14`:1241)") and 'value-3' ("(`14`:81)")
SHEET-FIX E21-D03 06 root height 1056 -> 1039 (checked want: footer end 959 + 80)
SHEET-FIX E21-D03 07 root height 1440 -> 1422 (checked want: footer end 1342 + 80)
SHEET-FIX E21-D03 07 'group · Depth tier' in the trail-clamped frame raised 86 -> 87 to fit its W-4 text, which it cut by 1 px
SHEET-FIX E21-D03 07 'board marker · illustrative' in the trail-clamped frame wrapped to 136 x 56 (words fixed at 120 px wide, 3 lines): auto-width at 207 px it ran 47 px past the frame's right edge and was cut to "illustrative, PROPOSED, not"
SHEET-FIX E21-D03 07 backticks removed from three drawn texts, words kept: the annotation 'value-2' lines ("(`window_seconds`, `23`:2452;" and "`11`:2044–`11`:2045") and 'value-1' ("`14`:1248", twice)
SHEET-FIX E21-D03 08 root height 1352 -> 1334 (checked want: footer end 1254 + 80)
SHEET-FIX E21-D03 09 root height 1952 -> 1934 (checked want: footer end 1854 + 80)
SHEET-FIX E21-D03 09 'message' in the depth-shed CMP-092 info row raised 53 -> 55 to fit W-24 (cut by 2 px); the row kept its 77 px by taking its bottom padding 12 -> 10, so the SCR-050 header under it does not move
SHEET-FIX E21-D03 09 backticks removed from four drawn texts, words kept: the annotation 'value-2' lines ("`11`:2060–`11`:2062" and "`11`:2063–`11`:2065") and 'value-3' lines ("(`14`:3116)" and "(`14`:3117)")
SHEET-FIX E21-D03 10 root height 1528 -> 1166 (checked want: annotation end 1086 + 80)
SHEET-FIX E21-D03 10 'focus order marker 03' moved 16 px left (282 -> 266 in its frame) onto the 'CMP-006 option 200' top-left corner
SHEET-FIX E21-D03 10 backticks removed from four drawn texts, words kept: the annotation 'value-11' ("a second `Esc`"), 'value-2' ("(`05`:99)"), 'value-5' ("`CanvasText`") and 'value-6' ("`ButtonText`")

## For the kit owner

- Kit-wide: every root came out shorter than its kit estimate (by 5 to 362 px); 10's annotation column measures 1 086, far
  under the estimate behind its 1 528 root.
- The W-4 line under the depth-tier group is 1 px taller than the group the sheets give it (02, 07); the Colour tab's
  scale-and-gamma row is 1 px shorter than its group (03); 09's info-row message is 2 px short for three lines. A 1 px
  rounding allowance in those heights would save the live fixes.
- The `board marker · announcement` boxes are placed 16 px over the dialog's lower edge on 02, 05, 07, 08 and 10. Nothing
  is hidden, but a placement 16 px lower would clear the lint.
- 07: the `illustrative` marker beside the dialog has 136 px before the frame edge; a fixed wrap width in the sheet would
  match the live fix.
- 10: focus marker 03 is placed from the radio group's start, not the checked option's corner.
- 06: the 'Highlight resting size ≥' field is drawn empty with its focus ring, as the sheet has it (an `empty` text and the
  `BTC` unit).
- Seed: four `motion.duration.*` primitives fail to import in Penpot (empty `type`); nothing in this kit binds them.
