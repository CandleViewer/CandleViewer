# E47-D08 / 10 forced-reduce

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-10-forced-reduce.png`; sheet `10-forced-reduce.json` (validated); theme dark.

Board 10 of 10 (§0 L80: §10's 2 × 2 matrix for the value flash, the canvas flash and a chrome transition). Grid (28000, 4200); 1920 x 1000 px; "page E47-D08 — Motion · board 10 · r1".

## Frames

- `forced-reduce∕matrix · dark` (§H: `forced-reduce/matrix · dark`)

## Validator and size

- `10-forced-reduce.json: 0 errors, 0 warnings, 6 sections, 23763 bytes` (exit 0)
- 6 sections, 23763 bytes

## Live checks (4)

- root 'E47-D08 / 10 forced-reduce' at (28000, 4200): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 462 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'forced-reduce∕matrix · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-10-forced-reduce.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (4)

- fallback: system colours (CanvasText, Canvas, Highlight, ButtonBorder) are not tokens: under forced colours they are drawn token-bound as color.text.primary / color.surface.app / color.focus.ring / color.border.strong with the system colour's name written beside them
- fallback: the value-flash overlay's peak (opacity 0.25 of color.buy.default / color.sell.default, §3 I-5) has no opacity token: drawn as color.buy.subtle / color.sell.subtle over the cell, its mid-decay as the same tint at opacity.muted, labelled with the spec's values
- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- fallback: the liquidation overlay (§6; PROPOSED color.liquidation.flash, D08-A9, not a token) drawn as color.status.warning.subtle under a color.status.warning.strong 2 px outline, labelled PROPOSED

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L80; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (28)

- type.ui.label
- color.text.secondary
- space.inset.sm
- color.text.primary
- type.ui.caption
- color.text.tertiary
- space.stack.xs
- type.num.base
- color.sell.subtle
- color.sell.default
- color.surface.canvas
- space.stack.sm
- color.surface.raised
- color.status.warning.strong
- size.icon
- type.num.sm
- space.inset.xs
- radius.control
- color.status.warning.subtle
- border.thick
- type.ui.body-strong
- color.border.subtle
- border.hairline
- color.border.strong
- type.ui.heading-sm
- space.inset.xl
- space.stack.md
- space.inset.lg
