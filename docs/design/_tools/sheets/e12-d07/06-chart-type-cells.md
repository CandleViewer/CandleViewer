# E12-D07 / 06 chart-type-cells

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-06-chart-type-cells.png`; sheet `06-chart-type-cells.json` (validated); theme dark.

Board 06 of ten (§0 L80): baseline `vs base`, delta-volume `buy` and `sell`, equi-volume `width capped` (§4). Three 1280 × 800 windows, one chart panel each (RightRail strip, dock 1,168 CSS px), compact density, dark.

## Frames

- `SCR-045∕chart-type∕baseline · dark`
- `SCR-045∕chart-type∕delta-volume · dark`
- `SCR-045∕chart-type∕equi-volume · dark`
- `SCR-045∕chart-type∕baseline · dark`: time, Baseline, B 63,988.2, 20 rows; §4 L194, D06:163
- `SCR-045∕chart-type∕delta-volume · dark`: Vol 50 BTC, Delta-volume, 20 rows + buy, sell; §4, W-10, W-12
- `SCR-045∕chart-type∕equi-volume · dark`: time, Equi-volume, `state` 12 ch, 10:22 `width capped`; §4, §5, §6

## Validator and size

- `06-chart-type-cells.json: 0 errors, 136 warnings, 74 sections, 250183 bytes` (exit 0)
- 74 sections, 250183 bytes

## Live checks (10)

- root 'E12-D07 / 06 chart-type-cells' at (0, 3200): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 4640 x 2520
- after touchTexts + relayout: the annotation column (estimated 2772 px) ends inside the root (h 2520); raise the root's h if not
- frame 'SCR-045∕chart-type∕baseline · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕chart-type∕delta-volume · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕chart-type∕equi-volume · dark': read back 1280 x 800 at (2800, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-06-chart-type-cells.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size
- frame 1: the header row's last value cell reads 'vs base' and every 'vs base' cell is signed (+ / −)
- frame 2: read back the header words in order: time, open, high, low, close, volume, delta, buy, sell, state, close time, duration; the focused row's buy + sell equals its volume
- frame 3: the 'state' header cell is 95 px wide (12 characters) and the focused row's state reads 'width capped'; ring 2 px color.focus.ring
- every frame: no body row is cut at the table's bottom edge after relayout (whole 24 px rows)

## Spec gaps (5)

- §4's baseline cell name “above 64,100 by 132” vs D06's summary “above base 64,100 by 132” (D06:353): the cell's name takes §4's form (“above 63,988.2 by 0.6”); the below form (“below … by …”) is not written in either and is not drawn (the focused row is above B)
- B is not printed in the table (no caption clause in §7.4 names it); it is in the cell names and on the chart's base tag only
- §6's name “width capped (N × median)” leaves N to the data (ruling P-3); the frame shows the computed N: “width capped (14.5 × median)”
- CVD: E11-D04 D3 rejoins CVD at ≥ 708 CSS px but §3.1 tiers it E; the board draws §3.1's set (as board 01)
- `vs base` width: §3.1 / §5 give none; the kit reserves 9 characters (build notes A-9)

## Deviations (0)

## Copy keys (2)

- W-10 (§13 L354, verbatim)
- W-12 (§13 L356, PROPOSED, the registry's unit)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (1)

- spec E12-D07.md md5 55948c5b (§0 L80); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (32)

- color.text.secondary
- size.icon.sm
- type.num.sm
- color.text.primary
- space.inset.sm
- color.buy.default
- color.surface.canvas
- color.surface.raised
- color.sell.default
- color.focus.ring
- border.focus
- type.ui.caption
- color.text.tertiary
- type.ui.label
- color.border.default
- border.hairline
- radius.control
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
