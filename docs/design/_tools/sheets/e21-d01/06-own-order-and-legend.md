# E21-D01 / 06 own-order-and-legend

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-06-own-order-and-legend.png`; sheet `06-own-order-and-legend.json` (validated); theme dark.

Board 06 of eight (memo §0 L77: the own-order column and the legend text (AD-5, AD-10)). Grid (0, 6400); 1920 x 1299 px; "page E21-D01 · board 06 · r1".

## Frames

- `own-order∕column-at-three-tiers` (`own-order/column-at-three-tiers`)
- `legend∕convention-and-anchors` (`legend/convention-and-anchors`)

## Validator and size

- `06-own-order-and-legend.json: 0 errors, 1 warnings, 34 sections, 70806 bytes` (exit 0)
- 34 sections, 430 shapes, 70806 bytes

## Live checks (5)

- root 'E21-D01 / 06 own-order-and-legend' at (0, 6400): read back the name exactly after the first section call; size 1920 x 1299
- after touchTexts + relayout: the annotation column (estimated 875 px with 15 % slack) ends inside the root (h 1299); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'own-order∕column-at-three-tiers': read back 1280 x 672 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'legend∕convention-and-anchors': read back 1280 x 280 at (80, 888); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-06-own-order-and-legend.png: record the board id and the PNG size

## Derivations (2)

- own-order column: x 200 px, width 136 px in every tier's ladder; own orders (synthetic): Buy 0.250 Limit at 69,999.70; Sell 0.120 Limit at 70,000.60
- anchors 0.4, 2, 10, 50 BTC, each ×5 the last; visible rows at the last column per step 0..4: {0: 7, 1: 7, 2: 1, 3: 2, 4: 0}

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (9)

- "Sell 0.120 Limit": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — own-order cell words: side, size and type (AD-5)
- "Buy 0.250 Limit": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — own-order cell words: side, size and type (AD-5)
- "price": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — ladder column heading
- "size": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — ladder column heading; asks above the mark, bids below
- "own orders": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — C7 (Your orders / My orders) is open
- "depth": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — header tier chip label
- "Bids sit below the mark and asks above it; a brighter cell holds more resting size.": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — the convention sentence (AD-10); the bid/ask hue is user-configurable, so the hi-fi sentence names the user's colours (E21-D04 #504)
- "scale: log, ×5 a step; BTC per level": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — the scale type and unit
- "Legend": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — legend title

## Fallbacks (5)

- lo-fi: the mark (last price) row is a color.surface.selected fill with a 2 px color.text.primary edge and the word 'mark' (board marker)
- lo-fi: bid and ask are told apart by position (asks above the mark, bids below) and by the column heading, never by a hue (the bid/ask hue is user-configurable, F-16)
- kit choice: board markers (step numbers, reading arrows, region names, violation flags) are caption text in a 'dashed · ' outline (board markers, not product UI)
- kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that shows a recommendation carries a PROPOSED stamp)
- lo-fi: resting size is drawn as five grey steps on a log scale (none, color.surface.hover, color.surface.selected, color.neutral.default, color.text.secondary), never a hue; E21-D04 #504 picks the ramp tokens and checks them with contrast_check.py and cvd_sim.py (memo §1)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L77)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (30)

- type.num.sm
- color.text.primary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.surface.canvas
- size.icon
- type.ui.caption
- color.surface.selected
- border.focus
- color.text.tertiary
- color.text.secondary
- type.ui.label
- radius.badge
- color.border.strong
- border.thick
- space.stack.xs
- space.inset.xl
- border.hairline
- radius.control
- space.inset.md
- radius.card
- color.border.default
- space.stack.lg
- type.ui.body
- color.surface.hover
- color.neutral.default
- space.inset.lg
- space.stack.sm
- type.ui.heading-sm
