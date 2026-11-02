# E47-D08 / 05 liquidation

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-05-liquidation.png`; sheet `05-liquidation.json` (validated); theme dark.

Board 05 of 10 (§0 L75: §6: the overlay at one start per 1 000 ms against a 10-event burst; reduce: the glyph and the size as text). Grid (28000, 0); 3280 x 1000 px; "page E47-D08 — Motion · board 05 · r1".

## Frames

- `liquidation∕burst · dark` (§H: `liquidation/burst · dark`)
- `liquidation∕reduce · dark` (§H: `liquidation/reduce · dark`)

## Validator and size

- `05-liquidation.json: 0 errors, 1 warnings, 26 sections, 72186 bytes` (exit 0)
- 26 sections, 72186 bytes

## Live checks (5)

- root 'E47-D08 / 05 liquidation' at (28000, 0): read back the name exactly after the first section call; size 3280 x 1000
- after touchTexts + relayout: the annotation column (estimated 523 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'liquidation∕burst · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'liquidation∕reduce · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-05-liquidation.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (1)

- the mark's count format "<size> BTC ×<n>" is a kit label: §6 says the burst updates "the size text and the count" without words (L249)

## Fallbacks (4)

- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn
- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- fallback: the liquidation overlay (§6; PROPOSED color.liquidation.flash, D08-A9, not a token) drawn as color.status.warning.subtle under a color.status.warning.strong 2 px outline, labelled PROPOSED
- kit choice: time axes and ms ticks are annotation (color.axis.text on a hairline), not product UI

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L75; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (33)

- color.grid.line
- color.candle.wick
- color.candle.up
- color.candle.down
- type.num.sm
- color.axis.text
- color.surface.canvas
- type.ui.body-strong
- color.text.primary
- radius.control
- color.surface.hover
- space.inset.sm
- color.surface.raised
- color.border.subtle
- border.hairline
- color.status.warning.strong
- size.icon
- space.inset.xs
- color.status.warning.subtle
- border.thick
- type.ui.caption
- color.text.secondary
- color.text.tertiary
- color.border.default
- type.num.base
- type.ui.body
- space.stack.xs
- type.ui.label
- color.surface.app
- space.inset.md
- space.inset.lg
- type.ui.heading-sm
- space.stack.sm
