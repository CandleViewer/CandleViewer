# E12-D07 / 03 range-renko

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-03-range-renko.png`; sheet `03-range-renko.json` (validated); theme dark.

Board 03 of ten (§0 L57: `range` in ticks; `brick` as a word; a seam inside the renko rows). Grid (12000, 0); 4640 x 2587 px; footer "page E12-D07 SCR-045 data table · board 03 · r1".

## Frames

- `SCR-045∕range∕default · dark`
- `SCR-045∕renko∕default · dark`
- `SCR-045∕renko∕seam · dark`
- sources: spec §0 L57; §2.2 L111; §3.1 range L138, brick L139; §3.2 L148; §5 L179; §7.1 seam L234; §7.2 L246; §7.4 L255; §13 W-1 L323, W-10 L332, W-13 L335, W-15 L337; hand-off §H L98
- theme dark; export docs/design/E12/img/E12-D07-03-range-renko.png

## Validator and size

- `03-range-renko.json: 0 errors, 134 warnings, 70 sections, 186932 bytes` (exit 0)
- 70 sections, 186932 bytes

## Live checks (10)

- frame 1: read back every closed row's `range` cell as a whole number of ticks >= 40 and the 10:22:11.412 rows' headers as bar 1 of 3, bar 2 of 3, bar 3 of 3
- frame 2: read back the `brick` cells as the words up / down (no colour-only cue) and the high / low cells present on every row
- frame 3: read back the seam row's text exactly "Series restarted 09:15 UTC", its 2 px color.focus.ring stroke (inner), its fill color.surface.hover, and its width equal to the header row's
- each frame: read back the focused row's ring as 2 px color.focus.ring and exactly one focused row per frame
- root 'E12-D07 / 03 range-renko' at (12000, 0): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 4640 x 2587
- after touchTexts + relayout: the annotation column (estimated 2802 px) ends inside the root (h 2587); raise the root's h if not
- frame 'SCR-045∕range∕default · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕renko∕default · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕renko∕seam · dark': read back 1280 x 800 at (2800, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-03-range-renko.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size

## Spec gaps (3)

- A-3: the seam with no recording gap is the data's 11:30 builder cold start; its row keeps W-1 verbatim, so its "09:15" is a placeholder time (spec §13 gives one seam string)
- A-8: the recorded fixtures cannot build range or renko bars (1m klines, sparse prints); the rows come from a seeded synthetic stream; only tick size and qty step come from the fixture
- hand-off §H gives range/default and renko/default no focus or announcement; the frames focus the cursor bar's row as E11-D04 D2 opens the table, and announce "Data table, row k of N"

## Deviations (0)

## Copy keys (4)

- W-10 (§13 L332, verbatim)
- W-13 (§13 L335, PROPOSED, the registry's unit)
- W-15 (§13 L337, PROPOSED, the registry's unit)
- W-1 (§13 L323, verbatim)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (1)

- spec E12-D07.md md5 93418570 (§0 L57); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (32)

- color.text.secondary
- size.icon.sm
- type.num.sm
- color.text.primary
- color.sell.default
- color.surface.canvas
- color.surface.raised
- color.buy.default
- color.focus.ring
- border.focus
- type.ui.caption
- color.text.tertiary
- type.ui.label
- color.border.default
- border.hairline
- radius.control
- space.inset.sm
- space.inset.xs
- space.stack.xs
- color.surface.selected
- size.icon
- color.env.demo
- radius.badge
- radius.card
- type.ui.heading-sm
- space.inset.lg
- space.inset.md
- color.surface.hover
- color.surface.app
- color.surface.sunken
- type.ui.body
- space.stack.sm
