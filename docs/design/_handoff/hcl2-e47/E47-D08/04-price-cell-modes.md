# E47-D08 / 04 price-cell-modes

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-04-price-cell-modes.png`; sheet `04-price-cell-modes.json` (validated); theme dark.

Board 04 of 10 (§0 L74: I-5 safe (peak and decay), reduce (glyph and sign only) and forced colours (glyph and sign in CanvasText)). Grid (21000, 0); 4640 x 1000 px; "page E47-D08 — Motion · board 04 · r1".

## Frames

- `value-flash∕safe · dark` (§H: `value-flash/safe · dark`)
- `value-flash∕reduce · dark` (§H: `value-flash/reduce · dark`)
- `value-flash∕forced · dark` (§H: `value-flash/forced · dark`)

## Validator and size

- `04-price-cell-modes.json: 0 errors, 2 warnings, 19 sections, 71558 bytes` (exit 0)
- 19 sections, 71558 bytes

## Live checks (6)

- root 'E47-D08 / 04 price-cell-modes' at (21000, 0): read back the name exactly after the first section call; size 4640 x 1000
- after touchTexts + relayout: the annotation column (estimated 750 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'value-flash∕safe · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'value-flash∕reduce · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'value-flash∕forced · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-04-price-cell-modes.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (6)

- fallback: the value-flash overlay's peak (opacity 0.25 of color.buy.default / color.sell.default, §3 I-5) has no opacity token: drawn as color.buy.subtle / color.sell.subtle over the cell, its mid-decay as the same tint at opacity.muted, labelled with the spec's values
- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn
- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI
- kit choice: time axes and ms ticks are annotation (color.axis.text on a hairline), not product UI
- fallback: system colours (CanvasText, Canvas, Highlight, ButtonBorder) are not tokens: under forced colours they are drawn token-bound as color.text.primary / color.surface.app / color.focus.ring / color.border.strong with the system colour's name written beside them

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L74; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (33)

- type.num.base
- color.text.primary
- color.sell.subtle
- color.sell.default
- type.ui.body
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- color.buy.default
- color.surface.raised
- type.ui.caption
- color.text.secondary
- color.border.default
- space.stack.xs
- type.ui.body-strong
- radius.control
- color.surface.hover
- color.border.subtle
- border.hairline
- opacity.muted
- color.status.info.subtle
- color.axis.text
- type.ui.label
- space.stack.sm
- type.ui.heading-sm
- space.stack.md
- space.inset.lg
- color.surface.app
- space.inset.md
- type.num.sm
- radius.badge
- color.border.strong
- color.text.tertiary
