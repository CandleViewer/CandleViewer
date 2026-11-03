# E47-D08 / 03 region-arbiter

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-03-region-arbiter.png`; sheet `03-region-arbiter.json` (validated); theme dark.

Board 03 of 10 (§0 L73: §4.3: one 341 × 256 px rectangle over a ladder, a liquidation mark and a watchlist cell; who wins each window). Grid (14000, 0); 3280 x 998 px; "page E47-D08 — Motion · board 03 · r1". Twin export: theme light; export `docs/design/E47/img/E47-D08-03-region-arbiter-light.png` (the same sheet; frame `region∕arbiter · light` is the evidence).

## Frames

- `region∕arbiter · dark` (§H: `region/arbiter · dark`)
- `region∕arbiter · light` (§H: `region/arbiter · light`)

## Validator and size

- `03-region-arbiter.json: 0 errors, 1 warnings, 78 sections, 100631 bytes` (exit 0)
- 78 sections, 100631 bytes

## Live checks (6)

- root 'E47-D08 / 03 region-arbiter' at (14000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is max(footer end, annotation column end) + 80 (annotation column estimated 678 px); read it back and raise it to the measured end + 80 if not
- frame 'region∕arbiter · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'region∕arbiter · light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-03-region-arbiter.png under the dark set; record the board id and the PNG size in §0
- twin: activate the light token set, read back one bound fill (color.surface.canvas) as its light value, export the board again to docs/design/E47/img/E47-D08-03-region-arbiter-light.png (frame 'region∕arbiter · light' is the evidence there, the dark frame in the first export), then restore the dark set

## Ambiguities (1)

- A-1: §0 L73 plans a dark and a light frame on one board while the token set is file-wide: read as one token-bound board exported twice (dark, then light to docs/design/E47/img/E47-D08-03-region-arbiter-light.png); the export name adds the theme word to §0 L67's NN-<slug> pattern

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (5)

- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- fallback: the liquidation overlay (§6; PROPOSED color.liquidation.flash, D08-A9, not a token) drawn as color.status.warning.subtle under a color.status.warning.strong 2 px outline, labelled PROPOSED
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn
- fallback: the value-flash overlay's peak (opacity 0.25 of color.buy.default / color.sell.default, §3 I-5) has no opacity token: drawn as color.buy.subtle / color.sell.subtle over the cell, its mid-decay as the same tint at opacity.muted, labelled with the spec's values
- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 a935d098, hand-off docs/design/E47/E47-D08-handoff.md md5 e4e1def0 (§0 L73; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 48c711e64 (§7.1); SCR-117 strings E47-D05 at 5e4065a44

## Tokens (39)

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
- color.status.warning.strong
- size.icon
- type.num.sm
- radius.control
- color.status.warning.subtle
- border.thick
- color.sell.default
- type.ui.body-strong
- color.surface.hover
- color.border.subtle
- border.hairline
- color.sell.subtle
- color.grid.line
- color.candle.wick
- color.candle.up
- color.candle.down
- color.axis.text
- color.status.info.default
- color.text.inverse
- type.ui.label
- radius.badge
- color.surface.app
- space.inset.md
- space.inset.lg
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
