# E47-D03 / 08 env-badge-themes

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-08-env-badge-themes.png`; sheet `08-env-badge-themes.json` (validated); theme dark.

Board 08 of 10 (§0 L73: §9: CMP-074 / CMP-075 LIVE and DEMO in dark, light, high contrast and the CVD-safe palette). Grid (12000, 3200); 3280 x 1880 px; "page E47-D03 themes and SCR-116 · board 08 · r1".

## Frames

- `env∕badge · dark` (§G: `env/badge · dark`)
- `env∕badge · light` (§G: `env/badge · light`)
- `env∕badge · hc` (§G: `env/badge · hc`)
- `env∕badge · cvd-safe` (§G: `env/badge · cvd-safe`)

## Validator and size

- `08-env-badge-themes.json: 0 errors, 1 warnings, 19 sections, 62912 bytes` (exit 0)
- 19 sections, 62912 bytes

## Live checks (8)

- root 'E47-D03 / 08 env-badge-themes' at (12000, 3200): read back the name exactly after the first section call; size 3280 x 1880
- after touchTexts + relayout: the annotation column (estimated 1095 px) ends inside the root (h 1880); raise the root's h to its end + 80 if not
- frame 'env∕badge · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'env∕badge · light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'env∕badge · hc': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'env∕badge · cvd-safe': read back 1280 x 800 at (1440, 960); clip on, no child spills
- theme: board 08 is mixed (§0): export each frame under the set its name ends with (dark; light; high contrast = dark + semantic-hc; cvd-safe = dark) and composite them in place into docs/design/E47/img/E47-D03-08-env-badge-themes.png; read back color.surface.raised behind each LIVE word as that set's value
- export docs/design/E47/img/E47-D03-08-env-badge-themes.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 08 is 'mixed' (§0): token binds resolve under one active set, so the md's line 3 says theme dark and a live check exports each frame under its own set and composites the PNG

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- W-3 (§13 L533, verbatim): Trading environment: Live
- W-5 (§13 L535, verbatim): Colour-blind safe (blue / orange)
- W-12 (§13 L542, verbatim): = buy / bid / up
- W-13 (§13 L543, verbatim): = sell / ask / down

## Copy gaps (0)

## Fallbacks (4)

- fallback: CMP-074's font.weight.bold has no 13 px type token: LIVE and DEMO both bind type.ui.body-strong (the word and the glyph carry the environment, §9)
- fallback: icon/env-live (filled dot in a ring) and icon/env-demo (outline dot) drawn as ellipses: neither is in the local icon set
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn
- fallback: the direction glyphs ▲ / ▼ drawn as text characters (§5's own glyphs)

## Sources (1)

- spec E47-D03.md md5 b42ea2be and hand-off E47-D03-handoff.md md5 9115b708 (§0 L73; hand-off §G L132)

## Tokens (33)

- type.ui.label
- color.text.secondary
- color.env.live
- border.hairline
- type.ui.body-strong
- color.text.primary
- space.inset.sm
- space.inset.md
- color.surface.raised
- border.thick
- radius.control
- color.env.demo
- space.stack.sm
- radius.badge
- space.inset.lg
- type.ui.caption
- space.stack.xs
- radius.card
- space.stack.lg
- type.ui.heading-sm
- space.inset.xl
- space.stack.md
- color.surface.app
- color.surface.hover
- color.border.subtle
- space.inset.xs
- color.candle.wick
- color.cvd.sell
- color.cvd.buy
- color.text.inverse
- color.border.strong
- color.surface.canvas
- color.text.tertiary
