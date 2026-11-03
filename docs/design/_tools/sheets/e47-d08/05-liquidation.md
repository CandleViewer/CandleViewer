# E47-D08 / 05 liquidation

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-05-liquidation.png`; sheet `05-liquidation.json` (validated); theme dark.

Board 05 of 10 (§0 L75: §6: the overlay at one start per 1 000 ms against a 10-event burst; reduce: the glyph and the size as text). Grid (28000, 0); 3280 x 998 px; "page E47-D08 — Motion · board 05 · r1".

## Frames

- `liquidation∕burst · dark` (§H: `liquidation/burst · dark`)
- `liquidation∕reduce · dark` (§H: `liquidation/reduce · dark`)

## Validator and size

- `05-liquidation.json: 0 errors, 1 warnings, 26 sections, 72247 bytes` (exit 0)
- 26 sections, 72247 bytes

## Live checks (5)

- root 'E47-D08 / 05 liquidation' at (28000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is max(footer end, annotation column end) + 80 (annotation column estimated 535 px); read it back and raise it to the measured end + 80 if not
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

- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn
- fallback: the liquidation overlay (§6; PROPOSED color.liquidation.flash, D08-A9, not a token) drawn as color.status.warning.subtle under a color.status.warning.strong 2 px outline, labelled PROPOSED
- kit choice: time axes and ms ticks are annotation (color.axis.text on a hairline), not product UI

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 a935d098, hand-off docs/design/E47/E47-D08-handoff.md md5 e4e1def0 (§0 L75; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 48c711e64 (§7.1); SCR-117 strings E47-D05 at 5e4065a44

## Tokens (34)

- type.num.base
- color.text.primary
- color.buy.default
- type.ui.body
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- color.surface.raised
- type.ui.caption
- color.text.secondary
- color.border.default
- space.stack.xs
- color.grid.line
- color.candle.wick
- color.candle.up
- color.candle.down
- type.num.sm
- color.axis.text
- type.ui.body-strong
- radius.control
- color.surface.hover
- color.border.subtle
- border.hairline
- color.status.warning.strong
- size.icon
- color.status.warning.subtle
- border.thick
- color.text.tertiary
- type.ui.label
- color.surface.app
- space.inset.md
- space.inset.lg
- type.ui.heading-sm
- space.stack.sm
