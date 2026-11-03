# E21-D01 / 03 placement-and-axes

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-03-placement-and-axes.png`; sheet `03-placement-and-axes.json` (validated); theme dark.

Board 03 of eight (memo §0 L74: beside vs behind; one locked price axis (§6, AD-1, AD-2)). Grid (14000, 0); 1760 x 2364 px; "page E21-D01 · board 03 · r1".

## Frames

- `placement∕beside` (`placement/beside`)
- `placement∕behind` (`placement/behind`)
- `axis∕locked-zoom` (`axis/locked-zoom`)

## Validator and size

- `03-placement-and-axes.json: 0 errors, 1 warnings, 42 sections, 105598 bytes` (exit 0)
- 42 sections, 658 shapes, 105598 bytes

## Live checks (6)

- root 'E21-D01 / 03 placement-and-axes' at (14000, 0): read back the name exactly after the first section call; size 1760 x 2364
- after touchTexts + relayout: the annotation column (estimated 1338 px with 15 % slack) ends inside the root (h 2364); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'placement∕beside': read back 1120 x 760 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'placement∕behind': read back 1120 x 496 at (80, 976); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'axis∕locked-zoom': read back 1120 x 640 at (80, 1580); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-03-placement-and-axes.png: record the board id and the PNG size

## Derivations (3)

- time axis: 20 columns × 100 ms = 2.0 s drawn of the 60 s live trail; labels at columns 0, 9, 19
- beside: 20 columns × 17 rows from 70,000.80 down to 69,999.20, one tick (0.10) a row in both regions; the read-across row is the bid wall at 69,999.80 (17.615 BTC, still resting at the last column)
- zoom: 5-tick rows sum the ticks of each row in both regions (69,996.00–70,004.40); after + one tick a row; the heatmap and the ladder use the same step in both

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- memo L104: "heatmap (time ->)"
- memo L113: "trail [60s v]"
- memo L57: "Trail length"
- memo L106: "+/- = price zoom"

## Copy gaps (5)

- "Sell 0.120 Limit": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — own-order cell words: side, size and type (AD-5)
- "Buy 0.250 Limit": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — own-order cell words: side, size and type (AD-5)
- "price": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — ladder column heading
- "size": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — ladder column heading; asks above the mark, bids below
- "own orders": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — C7 (Your orders / My orders) is open

## Fallbacks (6)

- lo-fi: resting size is drawn as five grey steps on a log scale (none, color.surface.hover, color.surface.selected, color.neutral.default, color.text.secondary), never a hue; E21-D04 #504 picks the ramp tokens and checks them with contrast_check.py and cvd_sim.py (memo §1)
- kit choice: the pulled carrier is a hollow 'dashed · ' outline with 'hatch line · ' rules inside (dashed and rotated 45 degrees by the post-step); a consumed level ends in print marks (filled circles) — the two differ by pattern, not by lightness (AD-6)
- lo-fi: the mark (last price) row is a color.surface.selected fill with a 2 px color.text.primary edge and the word 'mark' (board marker)
- lo-fi: bid and ask are told apart by position (asks above the mark, bids below) and by the column heading, never by a hue (the bid/ask hue is user-configurable, F-16)
- kit choice: board markers (step numbers, reading arrows, region names, violation flags) are caption text in a 'dashed · ' outline (board markers, not product UI)
- kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that shows a recommendation carries a PROPOSED stamp)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L74)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (32)

- type.ui.caption
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.surface.hover
- color.neutral.default
- color.surface.selected
- color.text.secondary
- color.text.primary
- border.hairline
- color.surface.app
- color.surface.sunken
- color.axis.text
- type.num.sm
- color.surface.canvas
- size.icon
- border.focus
- type.ui.label
- radius.badge
- color.border.strong
- border.thick
- radius.control
- space.inset.md
- space.stack.xs
- radius.card
- color.border.default
- space.stack.lg
- space.inset.xl
- space.stack.sm
- type.ui.heading-sm
- space.inset.lg
