# E47-D03 / 01 scr116-default

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-01-scr116-default.png`; sheet `01-scr116-default.json` (validated); theme dark.

Board 01 of 10 (§0 L66: V-1: every control of §8.1, the accent presets with names and the check glyph, the PreviewTile (a footprint cell, a ladder row, a positions row)). Grid (0, 0); 3280 x 1039 px; "page E47-D03 themes and SCR-116 · board 01 · r1".

## Frames

- `SCR-116∕default · dark` (§G: `SCR-116/default · dark`)
- `SCR-116∕preview-tile · dark` (§G: `SCR-116/preview-tile · dark`)

## Validator and size

- `01-scr116-default.json: 0 errors, 1 warnings, 16 sections, 63957 bytes` (exit 0)
- 16 sections, 63957 bytes

## Live checks (6)

- swatch 'Purple' (dark): rebind its fill from color.node.logic to palette.purple.400 (§8.2's primitive, BQ-8); read back that the check glyph stays color.text.inverse
- root 'E47-D03 / 01 scr116-default' at (0, 0): read back the name exactly after the first section call; size 3280 x 1039
- after touchTexts + relayout: the annotation column (estimated 968 px) ends inside the root (h 1039); raise the root's h to its end + 80 if not
- frame 'SCR-116∕default · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-116∕preview-tile · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D03-01-scr116-default.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 01 frame 2 (SCR-116/preview-tile): §G names the frame, §0 asks for the presets with names and the check glyph and the PreviewTile: drawn as a specimen window (the tile at size, each preset in its chosen state with §8.2 / §3.6 figures), not a second screen state

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- W-20 (§13 L550, PROPOSED): Sample data
- W-19 (§13 L549, PROPOSED): Preview: dark theme, Blue accent, default chart palette, compact
- W-18 (§13 L548, PROPOSED): Reset appearance
- W-4 (§13 L534, verbatim): Default (green / red)
- W-5 (§13 L535, verbatim): Colour-blind safe (blue / orange)
- W-22 (§13 L552, PROPOSED): Match system theme
- W-9 (§13 L539, PROPOSED): Accent: Blue · Cyan · Amber · Purple
- W-6 (§13 L536, verbatim): Invert buy/sell colours
- W-11 (§13 L541, PROPOSED): Text size: 100 % · 112 % · 125 % · 150 %
- W-10 (§13 L540, PROPOSED): Grid lines: Off · Subtle · Strong

## Copy gaps (9)

- "Price": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Bid": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Ask": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Delta": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Symbol": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Size": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Entry": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "PnL": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Appearance": the current settings entry and the h1, from §0 L62 (the shipped AppearanceScreen) and §8.4 L462; §13 has no title string

## Fallbacks (3)

- fallback: border.control (D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind its values directly, border.hairline in dark and light, border.thick in high contrast
- fallback: where no semantic alias resolves to a preset's §8.2 primitive in the board's theme, the swatch binds the same-hue stand-in and the live drawer rebinds it to the primitive (the validator refuses primitive colour binds)
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn

## Sources (1)

- spec E47-D03.md md5 ea4ad258 and hand-off E47-D03-handoff.md md5 da47f763 (§0 L66; hand-off §G L125)

## Tokens (47)

- type.ui.heading-md
- color.text.primary
- type.num.base
- space.inset.sm
- space.inset.xs
- radius.control
- color.footprint.bid
- color.footprint.ask
- color.surface.raised
- type.ui.body
- type.ui.caption
- color.text.secondary
- space.stack.md
- space.inset.lg
- color.surface.canvas
- radius.card
- color.border.subtle
- border.hairline
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- color.border.strong
- space.inset.md
- color.surface.selected
- color.surface.sunken
- color.focus.ring
- border.focus
- radius.badge
- type.ui.heading-sm
- space.stack.sm
- color.text.inverse
- size.icon
- color.text.link
- color.border.selected
- border.thick
- color.status.info.strong
- color.status.warning.strong
- color.node.logic
- color.action.primary.default
- space.stack.lg
- space.inset.xl
- color.surface.app
- color.surface.hover
- space.stack.xs
- type.num.sm
- type.ui.label
- color.text.tertiary
