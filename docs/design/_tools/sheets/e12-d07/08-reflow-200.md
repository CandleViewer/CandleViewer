# E12-D07 / 08 reflow-200

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-08-reflow-200.png`; sheet `08-reflow-200.json` (validated); theme dark.

Board 08 of ten (§0 L82: the tick set at 640 CSS px (200 %): the stacked block with close time and duration (§5)). Grid (12000, 3200); 1280 x 1253 px; footer "page E12-D07 SCR-045 data table · board 08 · r1".

## Frames

- `SCR-045∕reflow∕tick-200 · dark`
- reflow/tick-200: tick, maximised panel 640 × 400 CSS px, stacked blocks (spec §5 L208, L215; E11-D04 :214)
- Walkthrough (hand-off §E L65): at 200 % the stacked block keeps every value of the tick row
- Copy: W-10 (spec L354), W-11 (L355); theme dark; export docs/design/E12/img/E12-D07-08-reflow-200.png at 2x

## Validator and size

- `08-reflow-200.json: 0 errors, 9 warnings, 5 sections, 24816 bytes` (exit 0)
- 5 sections, 24816 bytes

## Live checks (7)

- frame 'SCR-045∕reflow∕tick-200 · dark' is drawn in CSS px (640 x 400): export the board at scale 2 and read back a 1280 x 800 frame in the PNG
- frame 'SCR-045∕reflow∕tick-200 · dark': block 02 reads '10:22:11.412 bar 5 of 5' and its `state` “—”; its stroke is 2 px color.focus.ring (inner); each block shows open, high, low, close, close time, duration, volume, delta, trades
- frame 'SCR-045∕reflow∕tick-200 · dark': no block is cut at the table's bottom edge after relayout (2 blocks, then the footer)
- root 'E12-D07 / 08 reflow-200' at (12000, 3200): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 1280 x 1253
- after touchTexts + relayout: the annotation column (estimated 1300 px) ends inside the root (h 1253); raise the root's h if not
- frame 'SCR-045∕reflow∕tick-200 · dark': read back 640 x 400 at (80, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-08-reflow-200.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size

## Spec gaps (4)

- A-2: bars 1–4 of 5 close at their open millisecond (duration 0:00.0) under §2.2 L136's rule; the focused bar 5 of 5 carries a non-zero duration; L138's example string is not drawn
- A-6: no token scales type 2×; the frame is drawn in CSS px (640 × 400) and exported at 2x
- A-8: seeded synthetic stream; tick size and qty step from the recorded instrument fixture
- A-12: buy / sell text tokens unregistered: color.buy.default / color.sell.default, the sign carries it

## Deviations (1)

- board 08's frame is 640 x 400 CSS px (the 1280 x 800 window at 200 %), exported at 2x; no token scales type by 2, so the CSS-px drawing at 2x export is the only token-bound way to show 200 %

## Copy keys (2)

- W-10 (§13 L354, verbatim)
- W-11 (§13 L355, PROPOSED, the registry's unit)

## Copy gaps (0)

## Fallbacks (1)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs

## Sources (1)

- spec E12-D07.md md5 55948c5b (§0 L82); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (27)

- color.text.secondary
- size.icon.sm
- type.num.sm
- color.text.primary
- space.inset.sm
- type.ui.caption
- space.inset.xs
- space.inset.lg
- color.surface.canvas
- space.stack.xs
- color.text.tertiary
- type.ui.label
- color.surface.raised
- color.border.default
- border.hairline
- radius.control
- color.focus.ring
- border.focus
- color.surface.selected
- size.icon
- color.env.demo
- radius.badge
- radius.card
- color.surface.app
- type.ui.heading-sm
- type.ui.body
- space.stack.sm
