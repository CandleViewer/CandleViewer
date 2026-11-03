# E21-D01 / 04 pulled-vs-consumed

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-04-pulled-vs-consumed.png`; sheet `04-pulled-vs-consumed.json` (validated); theme dark.

Board 04 of eight (memo §0 L75: the two marks and the estimated carrier (§6, AD-6)). Grid (21000, 0); 1840 x 2151 px; "page E21-D01 · board 04 · r1".

## Frames

- `pulled∕consumed` (`pulled/consumed`)
- `pulled∕pulled` (`pulled/pulled`)
- `pulled∕side-by-side` (`pulled/side-by-side`)

## Validator and size

- `04-pulled-vs-consumed.json: 0 errors, 1 warnings, 16 sections, 61684 bytes` (exit 0)
- 16 sections, 370 shapes, 61684 bytes

## Live checks (6)

- root 'E21-D01 / 04 pulled-vs-consumed' at (21000, 0): read back the name exactly after the first section call; size 1840 x 2151
- after touchTexts + relayout: the annotation column (estimated 1374 px with 15 % slack) ends inside the root (h 2151); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'pulled∕consumed': read back 1200 x 648 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'pulled∕pulled': read back 1200 x 664 at (80, 864); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'pulled∕side-by-side': read back 1200 x 384 at (80, 1636); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-04-pulled-vs-consumed.png: record the board id and the PNG size

## Derivations (3)

- consumed: 70,000.30 holds 32.925 BTC; prints at that price total 32.925 BTC over 4 columns; 32.925 − 32.925 = 0.000
- time axis: 20 columns × 100 ms = 2.0 s drawn of the 60 s live trail; labels at columns 0, 9, 19
- pulled: 69,999.50 holds 40.606 BTC until −0.9 s, 0 from −0.8 s; no print at that price in the 20 columns; the mark never trades below 70,000.00

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- memo L104: "heatmap (time ->)"
- memo L58: "(estimated)"
- memo L107: "without L3 data replenishment is inferred from L2 changes only"
- memo L107: "(estimated) a level dropped without matching prints"

## Copy gaps (0)

## Fallbacks (4)

- lo-fi: resting size is drawn as five grey steps on a log scale (none, color.surface.hover, color.surface.selected, color.neutral.default, color.text.secondary), never a hue; E21-D04 #504 picks the ramp tokens and checks them with contrast_check.py and cvd_sim.py (memo §1)
- kit choice: the pulled carrier is a hollow 'dashed · ' outline with 'hatch line · ' rules inside (dashed and rotated 45 degrees by the post-step); a consumed level ends in print marks (filled circles) — the two differ by pattern, not by lightness (AD-6)
- kit choice: board markers (step numbers, reading arrows, region names, violation flags) are caption text in a 'dashed · ' outline (board markers, not product UI)
- kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that shows a recommendation carries a PROPOSED stamp)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L75)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (30)

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
- color.border.default
- color.surface.canvas
- space.stack.xs
- space.inset.xl
- radius.control
- type.num.sm
- type.ui.label
- space.inset.md
- radius.card
- radius.badge
- color.border.strong
- border.thick
- space.stack.lg
- space.stack.sm
- type.ui.heading-sm
- space.inset.lg
